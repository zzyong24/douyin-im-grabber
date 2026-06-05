# douyin_im_grabber

抖音群聊全量抓取工具集 — 通过 CDP + IM API 拿群聊历史。

## 工具

| 文件 | 用途 | 限制 |
|------|------|------|
| `grab.py` | 旧 IM API 抓取实验 | `get_by_conversation` 直连会返 2023 假时间，不推荐 |
| `net_grab.py` | 拦截 Network 响应，真实点击群并滚动历史 | 推荐入口；按 `server_id` 去重 |
| `mem_grab.py` | 从 DOM 提取（已弃用） | DOM 不渲染消息，失败 |

## 真实 endpoint 真相

| Endpoint | 行为 | 推荐？ |
|----------|------|--------|
| `get_by_conversation` 直连 | 容易返 50 条 **2023-01-01 假时间** | ❌ |
| `get_by_conversation` Network 响应 | 批量返真实内容；真实时间在 metadata | ✅ |
| `get_by_id` Network 响应 | 少量补充消息，结构更深 | ✅ |

## 用法

```bash
# Network 拦截版
PYTHONPATH=../../src python3 -m douyin_im_grabber.net_grab \
  --group "财富自由团" --max-rounds 160 --idle-rounds 10

# 或从仓库根目录
./scripts/grab.sh --group "财富自由团" --max-rounds 160 --idle-rounds 10
```

## 关键技术发现

### IM API body 是 protobuf (binary)
- 不能用 form-encoded 字段
- 必须用 `application/x-protobuf`
- **不能用 JSON 解析**

### Network 拦截优先
- 让已登录的抖音网页自己发起 protobuf 请求
- CDP `Network.responseReceived` + `Network.getResponseBody` 拿响应
- `get_by_conversation` 批量给内容，`get_by_id` 可补少量消息
- 真实时间在 metadata `s:server_message_create_time`

### 字段单位
- `created_at_us` = microseconds (13-14 位)
- `created_at_ms` = milliseconds (13 位)
- `timestamp` 参数 = microseconds (不是 ms)
- `server_id` = 20 位大整数 → 转字符串

### CDP 操作
- Chrome 必须用 `--remote-debugging-port=9222` 启动
- WebSocket 端点 `ws://localhost:9222/devtools/browser/<id>`
- `get_by_conversation` 是当前 wheel 事件触发的主要历史 endpoint
- 真实滚轮用 `Input.dispatchMouseEvent` type=`mouseWheel`

## 已知问题

1. **conv_id 必须是数字形式**（不是字符串）
2. 直连 **get_by_conversation** 容易返 2023 假时间；Network 响应需解析 metadata 才有真实 `created_at_ms`
3. **server 端 has_more 字段缺失**（必须按 max-rounds / idle-rounds 限）
4. **DOM 提取不可靠**（React 不渲染就用 network interception）

## 抓包工作流

1. 在 Chrome 打开 `https://www.douyin.com/chat?isPopup=1`
2. 启用 CDP: 启动 Chrome 加 `--remote-debugging-port=9222 --remote-allow-origins=*`
3. CDP `Network.enable` 监听
4. 在浏览器里操作（点击群、滚动等）
5. 用 `Network.getResponseBody` 读取 protobuf 响应体
6. 解析消息、metadata、按 `server_id` 去重

## 输出

`groups/<群名>/<群名>_<时间戳>.json` + `.md`

```json
{
  "group_name": "财富自由团",
  "conv_id": "7566658350746845732",
  "fetch_time": "2026-06-05 11:08:00",
  "total_messages": 80,
  "member_count": 497,
  "messages": [
    {
      "conv_id": "7566658350746845732",
      "server_id": "7647741162309012005",
      "sender_uid": "7566658350746845732",
      "sender_uid_short": "MS4wLjABAAAA...",
      "type_code": 50001,
      "created_at_ms": 1780628501936,
      "created_at_us": "1780628501936",
      "text": "{\"command_type\":1,...}"
    }
  ]
}
```

## License

MIT
