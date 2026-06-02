#!/usr/bin/env python3
"""
douyin-im-grabber · 一键抓取抖音群聊全量消息

用法:
    # 全量首次（带 group-name 自动匹配）
    python3 grab.py --group "财富自由团" --mode full

    # 增量续跑（接着上次）
    python3 grab.py --group "财富自由团" --mode incremental

    # 指定 conv_id（跳过匹配）
    python3 grab.py --conv-id 7566658350746845732 --mode full

    # 只蒸馏（不抓数据，用已有 JSON 生成 MD）
    python3 grab.py --group "财富自由团" --distill-only

输出（默认）:
    ./groups/<群名>/<群名>_<时间戳>.json
    ./groups/<群名>/<群名>_<时间戳>.md

可通过环境变量 GROUPS_DIR 覆盖输出目录。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

import requests
import websocket

# ============== 路径配置 ==============
GROUPS_DIR = Path(os.environ.get("GROUPS_DIR", Path(__file__).resolve().parent.parent.parent / "groups"))
GROUPS_DIR.mkdir(parents=True, exist_ok=True)

CHROME_CDP_URL = "http://localhost:9222"
IMAPI_URL = "https://imapi.douyin.com/v1/message/get_by_conversation"
PAGE_SIZE = 50
DEFAULT_MAX_PAGES = 500
SLEEP_BETWEEN_PAGES = 0.3  # 限流防护

# ============== Protobuf 编解码 ==============

def encode_varint(value: int) -> bytes:
    bs = []
    v = value
    while True:
        b = v & 0x7F
        v >>= 7
        if v > 0:
            b |= 0x80
        bs.append(b)
        if v == 0:
            break
    return bytes(bs)


def encode_tag(fn: int, wt: int) -> bytes:
    return encode_varint((fn << 3) | wt)


def encode_string(fn: int, s: str) -> bytes:
    data = s.encode("utf-8")
    return encode_tag(fn, 2) + encode_varint(len(data)) + data


def encode_varint_field(fn: int, v: int) -> bytes:
    return encode_tag(fn, 0) + encode_varint(v)


def encode_bytes(fn: int, data: bytes) -> bytes:
    return encode_tag(fn, 2) + encode_varint(len(data)) + data


def build_browser_fingerprint() -> bytes:
    """构建浏览器指纹（field 15 repeated）"""
    pairs = [
        ("session_aid", "6383"),
        ("session_did", "0"),
        ("app_name", "douyin_pcr"),
        ("priority_region", "cn"),
        ("user_agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"),
        ("cookie_enabled", "true"),
        ("browser_language", "en-US"),
        ("browser_platform", "MacIntel"),
        ("browser_name", "Mozilla"),
        ("browser_version", "5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"),
        ("browser_online", "true"),
        ("screen_width", "1728"),
        ("screen_height", "1117"),
        ("referer", ""),
        ("timezone_name", "Asia/Shanghai"),
        ("deviceId", "0"),
        ("is-retry", "0"),
    ]
    result = b""
    for key, val in pairs:
        kv = encode_string(1, key) + encode_string(2, val)
        result += encode_bytes(15, kv)
    return result


def build_request(conv_id: str, cursor: int, timestamp: int, page: int) -> bytes:
    """构造 get_by_conversation 请求体"""
    inner = b"".join([
        encode_string(1, conv_id),
        encode_varint_field(2, 1),
        encode_varint_field(3, cursor),
        encode_varint_field(4, 1),
        encode_varint_field(5, timestamp),
        encode_varint_field(6, PAGE_SIZE),
    ])
    method_id = 10356 + page
    return b"".join([
        encode_varint_field(1, 301),
        encode_varint_field(2, method_id),
        encode_string(3, "0.1.6"),
        encode_string(4, ""),
        encode_varint_field(5, 3),
        encode_varint_field(6, 0),
        encode_string(7, "fef1a80:p/lzg/store"),
        encode_bytes(8, encode_bytes(301, inner)),
        encode_string(9, "0"),
        encode_string(11, "douyin_pc"),
        encode_string(14, "360000"),
        build_browser_fingerprint(),
        encode_varint_field(18, 1),
        encode_string(21, "douyin_web"),
        encode_string(22, "web_sdk"),
    ])


def parse_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
        if shift > 63:
            break
    return result, pos


def extract_field(data: bytes, target_field: int) -> Optional[bytes]:
    """从 protobuf 中提取指定 field 的 bytes 值"""
    pos = 0
    while pos < len(data):
        tag, pos = parse_varint(data, pos)
        fn = tag >> 3
        wt = tag & 7
        if wt == 0:
            _, pos = parse_varint(data, pos)
        elif wt == 2:
            length, pos = parse_varint(data, pos)
            if fn == target_field:
                return data[pos:pos+length]
            pos += length
        elif wt == 1:
            pos += 8
        elif wt == 5:
            pos += 4
        else:
            break
    return None


def parse_response(data: bytes) -> dict:
    """解析响应：返回 {msgs, has_more, next_ts}"""
    f6 = extract_field(data, 6)
    if not f6:
        return {"msgs": [], "has_more": 0, "next_ts": None}
    f301 = extract_field(f6, 301)
    if not f301:
        return {"msgs": [], "has_more": 0, "next_ts": None}

    msgs = []
    next_ts = None
    has_more = 0
    pos = 0
    while pos < len(f301):
        tag, pos = parse_varint(f301, pos)
        fn = tag >> 3
        wt = tag & 7
        if wt == 0:
            v, pos = parse_varint(f301, pos)
            if fn == 2:
                next_ts = str(v)
            elif fn == 3:
                has_more = v
        elif wt == 2:
            length, pos = parse_varint(f301, pos)
            if fn == 1:
                msgs.append(_parse_message(f301[pos:pos+length]))
            pos += length
        elif wt == 1:
            pos += 8
        elif wt == 5:
            pos += 4
        else:
            break
    return {"msgs": msgs, "has_more": has_more, "next_ts": next_ts}


def _parse_message(data: bytes) -> dict:
    """单条消息解析"""
    msg = {}
    pos = 0
    while pos < len(data):
        tag, pos = parse_varint(data, pos)
        fn = tag >> 3
        wt = tag & 7
        if wt == 0:
            v, pos = parse_varint(data, pos)
            if fn == 3:
                msg["server_id"] = str(v)
            elif fn == 4:
                msg["created_at_us"] = str(v)
            elif fn == 5:
                msg["order"] = str(v)
            elif fn == 7:
                msg["sender_uid"] = str(v)
            elif fn == 6:
                msg["type_code"] = v
        elif wt == 2:
            length, pos = parse_varint(data, pos)
            sl = data[pos:pos+length]
            if fn == 1:
                msg["conv_id"] = sl.decode("utf-8", errors="replace")
            elif fn == 8:
                msg["text"] = sl.decode("utf-8", errors="replace")
            pos += length
        elif wt == 1:
            pos += 8
        elif wt == 5:
            pos += 4
        else:
            break
    return msg


# ============== CDP 拿 cookie ==============

def get_cookies_via_cdp() -> list[dict]:
    """通过 Chrome DevTools Protocol 拿所有 douyin.com cookies"""
    try:
        tabs_resp = requests.get(f"{CHROME_CDP_URL}/json/list", timeout=5)
        tabs = tabs_resp.json()
    except Exception as e:
        raise RuntimeError(
            f"无法连接 Chrome CDP ({CHROME_CDP_URL}): {e}\n"
            "请确认 Chrome 用 --remote-debugging-port=9222 启动"
        )

    # 找抖音聊天 tab
    target = None
    for tab in tabs:
        if "douyin.com/chat" in tab.get("url", ""):
            target = tab
            break
    if not target:
        # 兜底：找任意 douyin.com tab
        for tab in tabs:
            if "douyin.com" in tab.get("url", ""):
                target = tab
                break
    if not target:
        raise RuntimeError("找不到 douyin.com 的 tab，请先打开抖音聊天页面")

    ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=10)
    ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == 1:
            cookies = resp["result"]["cookies"]
            ws.close()
            return [c for c in cookies if "douyin.com" in c.get("domain", "") and c.get("name")]

    raise RuntimeError("CDP 返回异常")


def get_user_map_via_cdp() -> dict[str, str]:
    """从 conversationStore 拿 UID → 名字 映射"""
    tabs_resp = requests.get(f"{CHROME_CDP_URL}/json/list", timeout=5)
    tabs = tabs_resp.json()
    target = next((t for t in tabs if "douyin.com/chat" in t.get("url", "")), None)
    if not target:
        return {}

    ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=10)
    expr = """
    (function(){
        const out = {};
        const cs = window.conversationStore;
        const convId = window.conversationStore?.curConversationId;
        if (cs && convId) {
            const map = cs.participantMapWithConversationId;
            if (map) {
                const arr = map.get(convId);
                if (arr) {
                    for (const p of arr) {
                        const [uid, info] = p;
                        out[uid] = info.alias || info.nickname || uid;
                    }
                }
            }
        }
        return JSON.stringify(out);
    })()
    """
    ws.send(json.dumps({
        "id": 1, "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True}
    }))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == 1:
            try:
                return json.loads(resp["result"]["result"]["value"])
            except:
                return {}
            finally:
                ws.close()
    return {}


# ============== 群名匹配 ==============

def get_conversation_map() -> dict[str, str]:
    """从 conversationStore 拿群名 → conv_id 映射"""
    tabs_resp = requests.get(f"{CHROME_CDP_URL}/json/list", timeout=5)
    tabs = tabs_resp.json()
    target = next((t for t in tabs if "douyin.com/chat" in t.get("url", "")), None)
    if not target:
        return {}

    ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=10)
    expr = """
    (function(){
        const out = {};
        const cs = window.conversationStore;
        if (cs) {
            // 遍历 conversationMap
            if (cs.conversationMap) {
                for (const [convId, info] of cs.conversationMap) {
                    if (info && info.coreInfo) {
                        out[convId] = info.coreInfo.name || info.coreInfo.conversationShortName || convId;
                    } else if (info && info.name) {
                        out[convId] = info.name;
                    }
                }
            }
        }
        return JSON.stringify(out);
    })()
    """
    ws.send(json.dumps({
        "id": 1, "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True}
    }))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == 1:
            try:
                return json.loads(resp["result"]["result"]["value"])
            except:
                return {}
            finally:
                ws.close()
    return {}


def match_group_by_name(group_name: str) -> Optional[str]:
    """根据群名匹配 conv_id"""
    conv_map = get_conversation_map()
    if not conv_map:
        return None

    # 精确匹配
    for conv_id, name in conv_map.items():
        if name == group_name:
            return conv_id

    # 模糊匹配（包含）
    for conv_id, name in conv_map.items():
        if group_name in name or name in group_name:
            return conv_id

    return None


# ============== 抓取 ==============

def grab_messages(conv_id: str, cookies: list[dict],
                  cursor: int, timestamp: int,
                  max_pages: int = DEFAULT_MAX_PAGES,
                  on_page: Optional[Callable] = None) -> list[dict]:
    """分页抓取群消息"""
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    headers = {
        "accept": "application/x-protobuf",
        "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "content-type": "application/x-protobuf",
        "cookie": cookie_str,
        "origin": "https://www.douyin.com",
        "referer": "https://www.douyin.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    }

    all_msgs = []
    page = 0
    while page < max_pages:
        page += 1
        body = build_request(conv_id, cursor=cursor, timestamp=timestamp, page=page)
        try:
            resp = requests.post(IMAPI_URL, data=body, headers=headers, timeout=15)
        except Exception as e:
            print(f"  [page {page}] ❌ 网络错误: {e}")
            time.sleep(2)
            continue

        if resp.status_code != 200:
            print(f"  [page {page}] ❌ HTTP {resp.status_code}")
            break

        result = parse_response(resp.content)
        msgs = result["msgs"]
        if not msgs:
            break

        all_msgs.extend(msgs)
        if on_page:
            on_page(page, len(all_msgs), result["has_more"], result["next_ts"])

        if not result["has_more"]:
            break

        if result["next_ts"]:
            timestamp = int(result["next_ts"])
        time.sleep(SLEEP_BETWEEN_PAGES)

    return all_msgs


# ============== 增量状态 ==============

def load_existing(group_name: str) -> tuple[list[dict], dict]:
    """加载群里已有数据"""
    group_dir = GROUPS_DIR / group_name
    if not group_dir.exists():
        return [], {}

    # 找最新的 json
    jsons = sorted(group_dir.glob(f"{group_name}_*.json"), reverse=True)
    if not jsons:
        return [], {}

    latest = jsons[0]
    with open(latest) as f:
        d = json.load(f)

    msgs = d.get("messages", [])
    # 找最新一条的 created_at_us 作为增量起点
    if msgs:
        msgs.sort(key=lambda m: int(m.get("created_at_us", 0)))
    return msgs, d


# ============== 蒸馏 ==============

def distill_to_md(data: dict, group_name: str, user_map: dict[str, str],
                  out_path: Path) -> None:
    """生成人读 MD（仿照昨天格式）"""
    msgs = data.get("messages", [])
    text_msgs = [m for m in msgs if m.get("type_code") == 7 and m.get("text")]
    text_msgs.sort(key=lambda m: int(m.get("created_at_us", 0)))

    senders = Counter(m.get("sender_uid") for m in text_msgs)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# 抖音群聊『{group_name}』聊天记录（蒸馏版）\n\n")
        f.write(f"> 通过 `douyin-im-grabber` skill 抓取，原始数据保留为 JSON。\n\n")
        f.write(f"## 📊 基础信息\n\n")
        f.write(f"- **群名**: {group_name}\n")
        f.write(f"- **群成员**: {data.get('member_count', '?')}\n")
        f.write(f"- **会话 ID**: `{data.get('conv_id', '?')}`\n")
        f.write(f"- **抓取时间**: {data.get('fetch_time', '?')}\n")
        f.write(f"- **消息总数**: **{len(msgs)}** 条\n")
        f.write(f"  - 纯文本 (type=7): {len(text_msgs)} 条\n")
        f.write(f"  - 非文本 (图片/系统/表情): {len(msgs) - len(text_msgs)} 条\n\n")

        f.write(f"## 🏆 发消息 Top 20\n\n")
        f.write(f"| 排名 | 消息数 | 发送人 |\n")
        f.write(f"|---|---:|---|\n")
        for i, (uid, cnt) in enumerate(senders.most_common(20), 1):
            name = user_map.get(uid, uid)
            f.write(f"| {i} | {cnt} | {name} |\n")
        f.write(f"\n")

        f.write(f"## 📝 消息记录（按时间正序）\n\n")
        f.write(f"> **注**：抖音群聊 API 返回的 `created_at_us` 时间戳精度有限，\n")
        f.write(f"> 消息按 server_id 排序，**内容/发送人/类型准确**。\n\n")
        f.write(f"---\n\n")

        # 按 1000 条分批
        BATCH = 1000
        for i, p in enumerate(text_msgs):
            batch_idx = i // BATCH
            if i % BATCH == 0:
                if i > 0:
                    f.write(f"\n")
                f.write(f"\n## 📦 第 {batch_idx+1} 批（消息 #{i+1} - #{min(i+BATCH, len(text_msgs))}）\n\n")
            us = int(p.get("created_at_us", 0))
            dt = datetime.fromtimestamp(us / 1_000_000)
            time_str = dt.strftime("%H:%M:%S")
            sender = p.get("sender_uid", "?")
            name = user_map.get(sender, sender)
            text = p.get("text", "").strip()
            if not text:
                continue
            f.write(f"- **{time_str}** `{name}`: {text}\n")

    print(f"✅ MD: {out_path}")


# ============== 主流程 ==============

def main():
    parser = argparse.ArgumentParser(description="抖音群聊全量抓取")
    parser.add_argument("--group", help="群名（自动匹配 conv_id）")
    parser.add_argument("--conv-id", help="直接指定 conv_id（跳过匹配）")
    parser.add_argument("--mode", choices=["full", "incremental"], default="full",
                        help="full=全量, incremental=增量续跑")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    parser.add_argument("--distill-only", action="store_true",
                        help="只蒸馏（不抓数据，用已有 JSON）")
    parser.add_argument("--no-distill", action="store_true",
                        help="不生成 MD（只输出 JSON）")
    args = parser.parse_args()

    print("=" * 60)
    print("▶ 抖音群聊抓取器 · douyin-im-grabber")
    print("=" * 60)

    # 1) 解析 conv_id
    conv_id = args.conv_id
    group_name = args.group

    if not conv_id and group_name:
        print(f"🔍 在抖音聊天列表里查找群: {group_name}")
        conv_id = match_group_by_name(group_name)
        if not conv_id:
            print(f"❌ 找不到群: {group_name}")
            print("提示：先在 Chrome 打开抖音群聊页面，并切到该群（确保在 conversationStore 中）")
            sys.exit(1)
        print(f"✅ 匹配到 conv_id: {conv_id}")

    if not conv_id and not group_name:
        print("❌ 必须指定 --group 或 --conv-id")
        sys.exit(1)

    if not group_name:
        group_name = f"group_{conv_id}"

    # 2) 准备目录
    group_dir = GROUPS_DIR / group_name
    group_dir.mkdir(parents=True, exist_ok=True)

    # 3) 拿 cookies
    print("🔑 拿 douyin.com cookies...")
    cookies = get_cookies_via_cdp()
    print(f"   ✅ {len(cookies)} 个 cookies")

    # 4) 增量模式：找已有数据
    existing_msgs = []
    initial_cursor = conv_id  # 全量首次用 conv_id 作 cursor
    initial_timestamp = 1672502566070000  # 默认 HAR 提取值

    if args.mode == "incremental":
        existing_msgs, existing_data = load_existing(group_name)
        if existing_msgs:
            print(f"📂 增量续跑：已有 {len(existing_msgs)} 条")
            # 增量模式：cursor 仍固定 conv_id，timestamp 从最新 next_ts 推
            # 简化：直接复用全量首次的 cursor/timestamp，重新从最旧翻
            print(f"   重置 cursor/timestamp，从头全量拉，去重合并")
        else:
            print(f"📂 未找到已有数据，切换为全量模式")

    # 5) 蒸馏模式：跳过抓取
    if args.distill_only:
        existing_msgs, existing_data = load_existing(group_name)
        if not existing_msgs:
            print("❌ 找不到已有数据，无法蒸馏")
            sys.exit(1)
        user_map = get_user_map_via_cdp()
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_path = group_dir / f"{group_name}_distilled_{ts_str}.md"
        distill_to_md({
            "messages": existing_msgs,
            "conv_id": conv_id,
            "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, group_name, user_map, md_path)
        return

    # 6) 抓取
    print(f"\n▶ 开始抓取: conv_id={conv_id}, mode={args.mode}")
    print(f"   cursor={initial_cursor}, timestamp={initial_timestamp}")

    all_new = []
    t0 = time.time()

    def on_page(p, total, has_more, next_ts):
        print(f"  [page {p}] 累计 {total} 条, has_more={has_more}, next_ts={next_ts}")

    all_new = grab_messages(
        conv_id, cookies,
        cursor=int(initial_cursor),
        timestamp=int(initial_timestamp),
        max_pages=args.max_pages,
        on_page=on_page
    )

    elapsed = round(time.time() - t0, 1)
    print(f"\n✅ 抓取完成: {len(all_new)} 条新消息，耗时 {elapsed}s")

    # 7) 合并（去重 by server_id）
    if existing_msgs:
        existing_sids = {m.get("server_id") for m in existing_msgs}
        merged = list(existing_msgs)
        added = 0
        for m in all_new:
            if m.get("server_id") not in existing_sids:
                merged.append(m)
                existing_sids.add(m["server_id"])
                added += 1
        merged.sort(key=lambda x: int(x.get("created_at_us", 0)))
        print(f"   合并后: {len(merged)} 条 (新增 {added} 条)")
    else:
        merged = sorted(all_new, key=lambda x: int(x.get("created_at_us", 0)))

    # 8) 拿 user_map
    print("👥 拿用户映射...")
    user_map = get_user_map_via_cdp()
    print(f"   ✅ {len(user_map)} 个用户")

    # 9) 保存
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = group_dir / f"{group_name}_{ts_str}.json"
    data = {
        "group_name": group_name,
        "conv_id": conv_id,
        "member_count": 311,
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_messages": len(merged),
        "mode": args.mode,
        "messages": merged,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON: {json_path} ({json_path.stat().st_size/1024/1024:.1f} MB)")

    # 10) 蒸馏 MD
    if not args.no_distill:
        md_path = group_dir / f"{group_name}_{ts_str}.md"
        distill_to_md(data, group_name, user_map, md_path)

    print(f"\n{'='*60}\n🎉 全部完成！\n{'='*60}")
    print(f"📂 输出目录: {group_dir}")


if __name__ == "__main__":
    main()
