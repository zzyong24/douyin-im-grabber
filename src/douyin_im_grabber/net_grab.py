#!/usr/bin/env python3
"""
Douyin group chat export via Chrome CDP Network interception.

The browser is allowed to do the authenticated IM loading. This tool clicks the
target group, scrolls the message list, captures protobuf responses, parses
messages, deduplicates by server_id, and writes JSON + Markdown.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import websocket

CHROME_CDP_URL = "http://localhost:9222"
GROUPS_DIR = Path(
    os.environ.get("GROUPS_DIR", Path(__file__).resolve().parent.parent.parent / "groups")
)
GROUPS_DIR.mkdir(parents=True, exist_ok=True)

MESSAGE_ENDPOINTS = (
    "get_by_conversation",
    "get_user_message",
    "get_by_id",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="通过 Chrome CDP Network 拦截导出抖音群聊记录"
    )
    parser.add_argument("group_pos", nargs="?", help="群名；兼容旧用法")
    parser.add_argument("--group", help="群名")
    parser.add_argument("--max-rounds", type=int, default=120, help="最大滚动轮数")
    parser.add_argument("--idle-rounds", type=int, default=10, help="连续无新增后停止")
    parser.add_argument("--wheel-events", type=int, default=24, help="每轮滚轮事件数")
    parser.add_argument("--delta-y", type=int, default=-1200, help="滚轮 deltaY")
    parser.add_argument("--round-wait", type=float, default=2.5, help="每轮等待网络响应秒数")
    parser.add_argument("--no-md", action="store_true", help="只输出 JSON")
    parser.add_argument("--quiet", action="store_true", help="减少进度输出")
    args = parser.parse_args(argv)
    args.group = args.group or args.group_pos
    if not args.group:
        parser.error("必须提供群名，例如: --group 财富自由团")
    return args


def parse_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return result, pos
        shift += 7
        if shift > 70:
            break
    return result, pos


def extract_field(data: bytes, target_field: int) -> bytes | None:
    pos = 0
    while pos < len(data):
        tag, pos = parse_varint(data, pos)
        fn = tag >> 3
        wt = tag & 7
        if wt == 0:
            _, pos = parse_varint(data, pos)
        elif wt == 2:
            length, pos = parse_varint(data, pos)
            value = data[pos : pos + length]
            pos += length
            if fn == target_field:
                return value
        elif wt == 1:
            pos += 8
        elif wt == 5:
            pos += 4
        else:
            break
    return None


def iter_fields(data: bytes):
    pos = 0
    while pos < len(data):
        tag, pos = parse_varint(data, pos)
        fn = tag >> 3
        wt = tag & 7
        if wt == 0:
            value, pos = parse_varint(data, pos)
            yield fn, wt, value
        elif wt == 2:
            length, pos = parse_varint(data, pos)
            value = data[pos : pos + length]
            pos += length
            yield fn, wt, value
        elif wt == 1:
            yield fn, wt, data[pos : pos + 8]
            pos += 8
        elif wt == 5:
            yield fn, wt, data[pos : pos + 4]
            pos += 4
        else:
            return


def decode_string(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def parse_metadata(data: bytes) -> tuple[str | None, str | None]:
    key = None
    value = None
    for fn, wt, raw in iter_fields(data):
        if wt == 2 and fn == 1:
            key = decode_string(raw)
        elif wt == 2 and fn == 2:
            value = decode_string(raw)
    return key, value


def apply_metadata(msg: dict[str, Any], data: bytes) -> None:
    key, value = parse_metadata(data)
    if not key or value is None:
        return

    metadata = msg.setdefault("metadata", {})
    metadata[key] = value
    if key in {
        "s:server_message_create_time",
        "server_message_create_time",
        "im_client_send_msg_time",
        "im_sdk_client_send_msg_time",
        "old_client_message_id",
    }:
        try:
            ms = int(value)
        except ValueError:
            return
        if 1_000_000_000_000 <= ms <= 9_999_999_999_999:
            msg.setdefault("created_at_ms", ms)


def normalize_message_time(msg: dict[str, Any]) -> None:
    if msg.get("created_at_ms"):
        return
    raw = msg.get("created_at_us")
    if raw is None:
        return
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return
    msg["created_at_ms"] = value // 1000 if value > 10_000_000_000_000 else value


def parse_conversation_message(data: bytes) -> dict[str, Any]:
    msg: dict[str, Any] = {}
    for fn, wt, raw in iter_fields(data):
        if wt == 0:
            value = int(raw)
            if fn == 2:
                msg["direction"] = value
            elif fn == 3:
                msg["server_id"] = str(value)
            elif fn == 4:
                msg["created_at_us"] = str(value)
            elif fn == 5:
                msg["order"] = str(value)
            elif fn == 6:
                msg["type_code"] = value
            elif fn == 7:
                msg["sender_uid"] = str(value)
            elif fn == 10:
                msg["created_at_ms"] = value
        elif wt == 2:
            if fn == 1:
                msg["conv_id"] = decode_string(raw)
            elif fn == 8:
                msg["text"] = decode_string(raw)
            elif fn == 9:
                apply_metadata(msg, raw)
            elif fn == 14:
                msg["sender_uid_short"] = decode_string(raw)
    normalize_message_time(msg)
    return msg


def parse_get_by_conversation_body(data: bytes) -> list[dict[str, Any]]:
    f6 = extract_field(data, 6)
    if not f6:
        return []
    f301 = extract_field(f6, 301)
    if not f301:
        return []

    messages = []
    for fn, wt, raw in iter_fields(f301):
        if wt == 2 and fn == 1:
            msg = parse_conversation_message(raw)
            if msg.get("server_id") and msg["server_id"] != "0":
                messages.append(msg)
    return messages


def parse_user_message(data: bytes) -> dict[str, Any]:
    msg: dict[str, Any] = {}
    for fn, wt, raw in iter_fields(data):
        if wt == 0:
            value = int(raw)
            if fn == 2:
                msg["direction"] = value
            elif fn == 3:
                msg["server_id"] = str(value)
            elif fn == 4:
                msg["type"] = value
            elif fn == 5:
                msg["sender_uid"] = str(value)
            elif fn == 6:
                msg["type_code"] = value
            elif fn == 7:
                msg["created_at_us"] = str(value)
            elif fn == 10:
                msg["created_at_ms"] = value
            elif fn == 17:
                msg["is_from_me"] = bool(value)
        elif wt == 2:
            if fn == 1:
                msg["conv_id"] = decode_string(raw)
            elif fn == 8:
                msg["text"] = decode_string(raw)
            elif fn == 9:
                apply_metadata(msg, raw)
            elif fn == 14:
                msg["sender_uid_short"] = decode_string(raw)
    normalize_message_time(msg)
    return msg


def parse_proto_body(data: bytes) -> list[dict[str, Any]]:
    """Parse get_user_message response body."""
    f6 = extract_field(data, 6)
    if not f6:
        return []
    f2048 = extract_field(f6, 2048)
    if not f2048:
        return []

    messages = []
    for fn, wt, raw in iter_fields(f2048):
        if wt != 2 or fn != 2:
            continue
        for inner_fn, inner_wt, inner_raw in iter_fields(raw):
            if inner_wt == 2 and inner_fn == 1:
                msg = parse_user_message(inner_raw)
                if msg.get("server_id") and msg["server_id"] != "0":
                    messages.append(msg)
    return messages


def parse_get_by_id_body(data: bytes) -> list[dict[str, Any]]:
    f6 = extract_field(data, 6)
    f211 = extract_field(f6 or b"", 211)
    f1 = extract_field(f211 or b"", 1)
    msg_data = extract_field(f1 or b"", 2)
    if not msg_data:
        return []
    msg = parse_conversation_message(msg_data)
    return [msg] if msg.get("server_id") and msg["server_id"] != "0" else []


def parse_messages_from_response(url: str, body: bytes) -> list[dict[str, Any]]:
    if "get_by_conversation" in url:
        return parse_get_by_conversation_body(body)
    if "get_user_message" in url:
        return parse_proto_body(body)
    if "get_by_id" in url:
        return parse_get_by_id_body(body)
    return []


def is_message_url(url: str) -> bool:
    return "imapi.douyin.com" in url and any(ep in url for ep in MESSAGE_ENDPOINTS)


def get_chat_tab() -> dict[str, Any]:
    try:
        tabs = requests.get(f"{CHROME_CDP_URL}/json/list", timeout=5).json()
    except Exception as exc:
        raise RuntimeError(
            f"无法连接 Chrome CDP ({CHROME_CDP_URL}): {exc}\n"
            "请确认 Chrome 用 --remote-debugging-port=9222 启动"
        ) from exc
    target = next(
        (t for t in tabs if t.get("url", "").startswith("https://www.douyin.com/chat")),
        None,
    )
    if not target:
        raise RuntimeError("找不到 douyin.com/chat tab，请先打开 https://www.douyin.com/chat?isPopup=1")
    return target


class Cdp:
    def __init__(self, web_socket_url: str):
        self.ws = websocket.create_connection(web_socket_url, timeout=30)
        self.next_id = 0
        self.pending_responses: list[tuple[str, str]] = []
        self.request_urls: dict[str, str] = {}
        self.seen_response_ids: set[str] = set()
        self.stats = Counter()

    def close(self) -> None:
        self.ws.close()

    def send(self, method: str, params: dict[str, Any] | None = None) -> int:
        self.next_id += 1
        self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params or {}}))
        return self.next_id

    def handle_event(self, msg: dict[str, Any]) -> None:
        method = msg.get("method")
        if method == "Network.requestWillBeSent":
            params = msg.get("params", {})
            request = params.get("request", {})
            url = request.get("url", "")
            if is_message_url(url):
                request_id = params.get("requestId")
                self.request_urls[request_id] = url
                self.stats[f"request:{endpoint_name(url)}"] += 1
        elif method == "Network.responseReceived":
            params = msg.get("params", {})
            response = params.get("response", {})
            url = response.get("url", "") or self.request_urls.get(params.get("requestId"), "")
            request_id = params.get("requestId")
            if request_id and is_message_url(url) and request_id not in self.seen_response_ids:
                self.seen_response_ids.add(request_id)
                self.pending_responses.append((request_id, url))
                self.stats[f"response:{endpoint_name(url)}"] += 1

    def recv_until_id(self, wanted_id: int, timeout: float = 5.0) -> dict[str, Any] | None:
        end = time.time() + timeout
        while time.time() < end:
            self.ws.settimeout(max(0.1, end - time.time()))
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                return None
            if msg.get("id") == wanted_id:
                return msg
            if msg.get("method"):
                self.handle_event(msg)
        return None

    def eval_js(self, expression: str, timeout: float = 5.0) -> Any:
        msg_id = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        )
        resp = self.recv_until_id(msg_id, timeout=timeout)
        if not resp:
            return None
        result = resp.get("result", {}).get("result", {})
        return result.get("value")

    def drain(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self.ws.settimeout(max(0.1, min(0.5, end - time.time())))
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                continue
            if msg.get("method"):
                self.handle_event(msg)

    def get_response_body(self, request_id: str) -> bytes | None:
        msg_id = self.send("Network.getResponseBody", {"requestId": request_id})
        resp = self.recv_until_id(msg_id, timeout=5.0)
        if not resp or "result" not in resp:
            self.stats["body_error"] += 1
            return None
        result = resp["result"]
        body = result.get("body", "")
        if result.get("base64Encoded"):
            return base64.b64decode(body)
        return body.encode("latin1", errors="replace")


def endpoint_name(url: str) -> str:
    for endpoint in MESSAGE_ENDPOINTS:
        if endpoint in url:
            return endpoint
    return "other"


def click_group(cdp: Cdp, group_name: str) -> dict[str, Any]:
    expr = f"""
    (function(){{
      const groupName = {json.dumps(group_name)};
      const titles = [...document.querySelectorAll('.conversationConversationItemtitle')];
      const title = titles.find(el => (el.textContent || '').trim().includes(groupName));
      const item = title?.closest('.conversationConversationItemwrapper') || title;
      if (item) {{
        item.scrollIntoView({{block: 'center'}});
        item.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true, cancelable: true, view: window}}));
        item.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true, cancelable: true, view: window}}));
        item.click();
        return JSON.stringify({{method: 'dom', name: title.textContent.trim()}});
      }}

      const cs = window.conversationStore;
      if (!cs || !cs.conversationMap) return JSON.stringify({{error: 'no_store'}});
      for (const [cid, info] of cs.conversationMap) {{
        const name = info?.coreInfo?.name || info?.coreInfo?.conversationShortName || info?.name || '';
        if (name.includes(groupName)) {{
          if (cs.setCurConversation) cs.setCurConversation(cid);
          return JSON.stringify({{method: 'store', name, cid}});
        }}
      }}
      return JSON.stringify({{error: 'not_found'}});
    }})()
    """
    raw = cdp.eval_js(expr, timeout=8.0)
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"error": "bad_result", "raw": raw}


def wait_for_message_list(cdp: Cdp, timeout: float = 12.0) -> dict[str, Any]:
    end = time.time() + timeout
    while time.time() < end:
        info = get_message_list_info(cdp)
        if info.get("ok"):
            return info
        time.sleep(0.5)
    raise RuntimeError("切群后没有找到消息列表，请确认目标群能在页面右侧打开")


def get_message_list_info(cdp: Cdp) -> dict[str, Any]:
    raw = cdp.eval_js(
        """
        (function(){
          const el = document.querySelector('.messageMessageListlist')
            || document.querySelector('[class*=messageMessageListlist]')
            || document.querySelector('[class*=MessageList]');
          if (!el) return JSON.stringify({ok: false});
          const r = el.getBoundingClientRect();
          return JSON.stringify({
            ok: true,
            x: r.x + r.width / 2,
            y: r.y + r.height / 2,
            width: r.width,
            height: r.height,
            scrollTop: el.scrollTop,
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight,
            preview: (el.textContent || '').slice(0, 80)
          });
        })()
        """,
        timeout=5.0,
    )
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "raw": raw}


def dispatch_wheel(cdp: Cdp, x: float, y: float, delta_y: int, count: int) -> None:
    for _ in range(count):
        cdp.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": delta_y},
        )
        time.sleep(0.05)


def add_messages(
    all_messages: dict[str, dict[str, Any]],
    messages: list[dict[str, Any]],
    conv_id: str | None,
) -> int:
    added = 0
    for msg in messages:
        sid = msg.get("server_id")
        if not sid or sid == "0":
            continue
        msg_conv_id = msg.get("conv_id")
        if conv_id and msg_conv_id and str(msg_conv_id) != str(conv_id):
            continue
        normalize_message_time(msg)
        if sid not in all_messages:
            all_messages[sid] = msg
            added += 1
        else:
            all_messages[sid].update({k: v for k, v in msg.items() if v not in (None, "", {})})
    return added


def fetch_pending_messages(
    cdp: Cdp,
    all_messages: dict[str, dict[str, Any]],
    conv_id: str | None,
) -> int:
    added = 0
    while cdp.pending_responses:
        request_id, url = cdp.pending_responses.pop(0)
        body = cdp.get_response_body(request_id)
        if not body:
            continue
        try:
            messages = parse_messages_from_response(url, body)
        except Exception as exc:
            cdp.stats[f"parse_error:{endpoint_name(url)}"] += 1
            if not cdp.stats.get("last_parse_error"):
                cdp.stats["last_parse_error"] = str(exc)
            continue
        cdp.stats[f"parsed:{endpoint_name(url)}"] += len(messages)
        added += add_messages(all_messages, messages, conv_id)
    return added


def get_user_map(cdp: Cdp) -> dict[str, str]:
    raw = cdp.eval_js(
        """
        (function(){
          const cs = window.conversationStore;
          if (!cs) return '{}';
          const convId = cs.curConversationId;
          const map = cs.participantMapWithConversationId;
          if (!map || !convId) return '{}';
          const arr = map.get(convId);
          if (!arr) return '{}';
          const out = {};
          for (const p of arr) {
            const [uid, info] = p;
            out[uid] = info.alias || info.nickname || uid;
          }
          return JSON.stringify(out);
        })()
        """,
        timeout=5.0,
    )
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def get_current_conv_id(cdp: Cdp) -> str | None:
    value = cdp.eval_js("window.conversationStore?.curConversationId || ''", timeout=5.0)
    return str(value) if value else None


def sort_key(msg: dict[str, Any]) -> tuple[int, int]:
    try:
        created_at = int(msg.get("created_at_ms") or 0)
    except (TypeError, ValueError):
        created_at = 0
    try:
        sid = int(msg.get("server_id") or 0)
    except (TypeError, ValueError):
        sid = 0
    return created_at, sid


def parse_text_payload(msg: dict[str, Any]) -> dict[str, Any] | None:
    text = str(msg.get("text") or "").strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def is_text_message(msg: dict[str, Any]) -> bool:
    if msg.get("type_code") != 7:
        return False
    return bool(display_text(msg))


def display_text(msg: dict[str, Any]) -> str:
    text = str(msg.get("text") or "").strip()
    if not text:
        return ""

    payload = parse_text_payload(msg)
    if msg.get("type_code") == 7:
        if not payload:
            return text
        value = payload.get("text") or payload.get("msgHint") or payload.get("content_name")
        return str(value).strip() if value else text

    if not payload:
        return f"[非文本 type={msg.get('type_code', '?')}] {text[:120]}"

    if payload.get("display_name"):
        return f"[表情] {payload['display_name']}"
    if payload.get("resource_url") or payload.get("aweType") == 2702:
        return "[图片]"
    if payload.get("content_name"):
        return f"[卡片] {payload['content_name']}"
    if payload.get("text"):
        return f"[非文本] {payload['text']}"
    return f"[非文本 type={msg.get('type_code', '?')}]"


def write_outputs(
    group_name: str,
    conv_id: str | None,
    messages: list[dict[str, Any]],
    user_map: dict[str, str],
    stats: Counter,
    output_md: bool,
    started_at: float,
) -> tuple[Path, Path | None]:
    group_dir = GROUPS_DIR / group_name
    group_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = group_dir / f"{group_name}_{ts}.json"
    md_path = group_dir / f"{group_name}_{ts}.md"

    text_count = sum(1 for msg in messages if is_text_message(msg))
    data = {
        "group_name": group_name,
        "conv_id": conv_id,
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(time.time() - started_at, 1),
        "total_messages": len(messages),
        "text_messages": text_count,
        "non_text_messages": len(messages) - text_count,
        "member_count": len(user_map),
        "user_map": user_map,
        "stats": dict(stats),
        "messages": messages,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if not output_md:
        return json_path, None

    senders = Counter(str(msg.get("sender_uid") or "?") for msg in messages)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 抖音群聊『{group_name}』聊天记录\n\n")
        f.write("## 基础信息\n\n")
        f.write(f"- 群名: {group_name}\n")
        f.write(f"- 会话 ID: `{conv_id or '?'}`\n")
        f.write(f"- 群成员: {len(user_map)}\n")
        f.write(f"- 抓取时间: {data['fetch_time']}\n")
        f.write(f"- 抓取耗时: {data['elapsed_seconds']} 秒\n")
        f.write(f"- 消息总数: {len(messages)}\n")
        f.write(f"- 文本消息: {text_count}\n")
        f.write(f"- 非文本消息: {len(messages) - text_count}\n\n")
        f.write("## 发消息 Top 20\n\n")
        f.write("| 排名 | 消息数 | 发送人 |\n")
        f.write("|---|---:|---|\n")
        for idx, (uid, count) in enumerate(senders.most_common(20), 1):
            f.write(f"| {idx} | {count} | {user_map.get(uid, uid)} |\n")
        f.write("\n## 消息记录\n\n")
        for msg in messages:
            text = display_text(msg)
            if not text:
                continue
            ms = int(msg.get("created_at_ms") or 0)
            time_str = datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if ms else "?"
            uid = str(msg.get("sender_uid") or "?")
            sender = user_map.get(uid, msg.get("sender_uid_short") or uid)
            f.write(f"- **{time_str}** `{sender}`: {text}\n")

    return json_path, md_path


def grab_group_via_network(
    group_name: str,
    max_rounds: int = 120,
    idle_rounds: int = 10,
    wheel_events: int = 24,
    delta_y: int = -1200,
    round_wait: float = 2.5,
    output_md: bool = True,
    quiet: bool = False,
) -> dict[str, Any]:
    started_at = time.time()
    target = get_chat_tab()
    cdp = Cdp(target["webSocketDebuggerUrl"])
    all_messages: dict[str, dict[str, Any]] = {}

    try:
        cdp.send("Page.bringToFront")
        cdp.send("Network.enable")

        click_result = click_group(cdp, group_name)
        if click_result.get("error"):
            raise RuntimeError(f"找不到群: {group_name} ({click_result['error']})")
        if not quiet:
            print(f"click: {click_result}")

        info = wait_for_message_list(cdp)
        conv_id = get_current_conv_id(cdp)
        if not quiet:
            print(f"conv_id: {conv_id}")
            print(
                "message_list:",
                f"scrollTop={info.get('scrollTop')}",
                f"scrollHeight={info.get('scrollHeight')}",
            )

        idle = 0
        for round_i in range(1, max_rounds + 1):
            info = get_message_list_info(cdp)
            if not info.get("ok"):
                raise RuntimeError("消息列表消失，抓取中止")
            dispatch_wheel(cdp, info["x"], info["y"], delta_y, wheel_events)
            cdp.drain(round_wait)
            added = fetch_pending_messages(cdp, all_messages, conv_id)
            idle = idle + 1 if added == 0 else 0

            if not quiet:
                after = get_message_list_info(cdp)
                print(
                    f"round {round_i}: +{added}, total={len(all_messages)}, "
                    f"idle={idle}/{idle_rounds}, scrollTop={after.get('scrollTop')}, "
                    f"scrollHeight={after.get('scrollHeight')}"
                )
            if idle >= idle_rounds:
                cdp.stats["stop_reason"] = "idle"
                break
        else:
            cdp.stats["stop_reason"] = "max_rounds"

        # Drain once more in case the final wheel burst is still returning bodies.
        cdp.drain(round_wait)
        fetch_pending_messages(cdp, all_messages, conv_id)
        user_map = get_user_map(cdp)
    finally:
        cdp.close()

    messages = sorted(all_messages.values(), key=sort_key)
    json_path, md_path = write_outputs(
        group_name,
        conv_id if "conv_id" in locals() else None,
        messages,
        user_map if "user_map" in locals() else {},
        cdp.stats,
        output_md,
        started_at,
    )

    result = {
        "group_name": group_name,
        "conv_id": conv_id if "conv_id" in locals() else None,
        "total_messages": len(messages),
        "json_path": str(json_path),
        "md_path": str(md_path) if md_path else None,
        "elapsed_seconds": round(time.time() - started_at, 1),
        "stats": dict(cdp.stats),
    }
    if not quiet:
        print(f"JSON: {json_path}")
        if md_path:
            print(f"MD: {md_path}")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = grab_group_via_network(
        args.group,
        max_rounds=args.max_rounds,
        idle_rounds=args.idle_rounds,
        wheel_events=args.wheel_events,
        delta_y=args.delta_y,
        round_wait=args.round_wait,
        output_md=not args.no_md,
        quiet=args.quiet,
    )
    if args.quiet:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
