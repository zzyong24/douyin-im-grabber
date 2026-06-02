# douyin-im-grabber · 详细使用手册

> 一键抓取抖音群聊全量聊天记录，输出原始 JSON + 蒸馏 MD。
> 适用场景：群聊内容备份 / 关键决策归档 / 内容分析 / 长期复盘。

---

## 🎯 工具能做什么

- ✅ 全量抓取一个群聊的所有历史消息
- ✅ 增量续跑（不丢旧数据，只追加新消息）
- ✅ 按群名匹配（不用手动找 conv_id）
- ✅ 输出原始结构化 JSON（**含 server_id / sender_uid / 时间戳 / 类型**）
- ✅ 输出蒸馏版 Markdown（**含 Top 20 发言榜 + 消息记录**）

## ❌ 工具不能做什么

- ❌ 不能抓**单聊**（抖音单聊是不同协议）
- ❌ 不能抓**图片/视频/语音**的**内容**（只能拿到元数据 JSON + URL）
- ❌ 不能实时监控（必须每次手动触发）
- ❌ 不能绕开抖音登录（必须**用户自己登录**才能拿 cookie）

---

## 🚀 快速开始（3 步）

### 1. 准备 Chrome

Chrome 必须以 **CDP 调试模式**启动：

```bash
# 退出当前 Chrome
pkill -a "Google Chrome"

# 启动 CDP Chrome
open -a "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome_cdp \
  --remote-allow-origins=*
```

> **为什么需要 CDP**？工具通过 Chrome DevTools Protocol 拿你的 douyin.com cookies（不用你手动复制粘贴 71 个 cookie）。

### 2. 打开抖音聊天

Chrome 里访问：

```
https://www.douyin.com/chat?isPopup=1
```

**确保目标群在你的会话列表里**（即你能看到那个群）。

> 不需要"切到"那个群，工具会自己通过群名匹配。

### 3. 跑抓取命令

```bash
# 从仓库根目录
python3 -m douyin_im_grabber.grab --group "你的群名" --mode full

# 或用一键脚本
./scripts/grab.sh --group "你的群名" --mode full
```

**等待 3-10 分钟**（取决于群大小）。

---

## 📊 输出示例

```
./groups/<群名>/
├── <群名>_20260602_120128.json   (10.9 MB)  ← 原始结构化
└── <群名>_20260602_120128.md     (350 KB)    ← 蒸馏版
```

### JSON 结构（部分）

```json
{
  "group_name": "你的群名",
  "conv_id": "7566658350746845732",
  "member_count": 311,
  "fetch_time": "2026-06-02 12:01:28",
  "total_messages": 16606,
  "mode": "full",
  "messages": [
    {
      "server_id": "7644987782909920795",
      "created_at_us": "1672502516080000",
      "sender_uid": "369908839616141",
      "type_code": 7,
      "text": "有遇到过的么"
    },
    ...
  ]
}
```

### MD 蒸馏版（部分）

```markdown
# 抖音群聊『你的群名』聊天记录（蒸馏版）

## 📊 基础信息
- 消息总数: 16606 条
- 纯文本: 13868 条
- 非文本: 2738 条

## 🏆 发消息 Top 20
| 排名 | 消息数 | 发送人 |
|---|---:|---|
| 1 | 3261 | 张三 |
| 2 | 1165 | 李四 |
| ...

## 📝 消息记录（按时间正序）
- **00:01:56** `369908839616141`: 有遇到过的么
- **00:01:56** `95059474105`: 那些房地产下游、装修、建材想流量想疯了
...
```

---

## 🔧 高级用法

### 用 1: 全量首次抓取

```bash
python3 -m douyin_im_grabber.grab --group "你的群名" --mode full
```

### 用 2: 增量续跑

新消息来了，再跑一次：

```bash
python3 -m douyin_im_grabber.grab --group "你的群名" --mode incremental
```

**自动行为**：
- 找群里最新一份 JSON
- 重新全量拉一遍（API 不支持真正的"按时间增量"）
- **按 server_id 去重合并**到新文件

### 用 3: 直接指定 conv_id

跳过群名匹配（适合抓很多群的场景）：

```bash
python3 -m douyin_im_grabber.grab --conv-id 7566658350746845732 --mode full
```

### 用 4: 只蒸馏，不抓数据

已有 JSON，只想重新生成 MD：

```bash
python3 -m douyin_im_grabber.grab --group "你的群名" --distill-only
```

### 用 5: 只输出 JSON（不蒸馏）

```bash
python3 -m douyin_im_grabber.grab --group "你的群名" --no-distill
```

### 用 6: 限制最大翻页数（防失控）

```bash
python3 -m douyin_im_grabber.grab --group "小群" --max-pages 50
```

### 用 7: 改输出目录

```bash
GROUPS_DIR=/path/to/your/backup python3 -m douyin_im_grabber.grab --group "xxx"
```

---

## 🛠 故障排查

| 错误 | 原因 | 解决 |
|---|---|---|
| `无法连接 Chrome CDP (http://localhost:9222)` | Chrome 未启 CDP | 重新启动 Chrome（看上面"准备 Chrome"） |
| `找不到 douyin.com tab` | Chrome 没开抖音 | 访问 `https://www.douyin.com/chat?isPopup=1` |
| `找不到群: xxx` | 群不在当前会话列表 | 在 Chrome 里点开一次那个群 |
| `conversation not found` (HTTP 200) | sessionid 过期 | 在 Chrome 里重新登录抖音 |
| `HTTP 429 Too Many Requests` | 触发限速 | 等待 1 小时后重跑 |
| 抓取只到 ~100 条就停 | cursor/timestamp 失效 | 重新登录抖音 + 重启 CDP Chrome |

---

## ⚠️ 风控注意事项

1. **不要频繁跑** —— 抖音有反爬虫，**每次跑完冷却至少 1 小时**
2. **大量抓取可能被警告** —— 如果你抖音收到"账号异常"通知，立即停用 24 小时
3. **数据不要公开发布** —— 涉及群里其他人的隐私，存自己电脑就好
4. **协议可能失效** —— 抖音偶尔会改 API，**如果突然抓不到**，可能需要重新调试（参考下面的"技术原理"）

---

## 🔬 技术原理（给好奇的人）

### 1. 抖音 IM 协议

抖音网页版聊天用 **Protobuf 二进制协议** + **HTTP POST** + **WebSocket**：

```
POST https://imapi.douyin.com/v1/message/get_by_conversation
  Content-Type: application/x-protobuf
  Cookie: <71 个 douyin.com cookies>
  Body: <protobuf binary，含 conv_id / cursor / timestamp>
  Response: <protobuf binary，含 50 条消息 + next_ts>
```

### 2. 翻页机制

```
初始: cursor=conv_id, timestamp=1672502566070000
  ↓ 拿 50 条消息 + has_more + next_ts
循环: cursor 不变, timestamp = next_ts
  ↓ 继续翻
终止: has_more = 0
```

### 3. 关键字段

| 字段 | 来源 | 用途 |
|---|---|---|
| `conv_id` | `window.conversationStore.curConversationId` | 群唯一标识 |
| `cursor` | 固定用 `conv_id` | 游标 |
| `timestamp` | 首次用 1672502566070000 (HAR 提取) | 时间游标 |
| `next_ts` | 响应里的 `field 2` | 翻页用 |
| `has_more` | 响应里的 `field 3` | 终止判断 |
| `server_id` | 消息里的 `field 3` | 去重 key |
| `created_at_us` | 消息里的 `field 4` | 时间戳 |
| `sender_uid` | 消息里的 `field 7` | 发送者 UID |
| `type_code` | 消息里的 `field 6` | 消息类型（7=文本） |
| `text` | 消息里的 `field 8` | 文本内容 |

### 4. 已知坑

- **cursor 固定，timestamp 每页减 5e6 微秒**
- **method_id 每次 +1，从 10357 起**
- **`field 15` 必须 repeated**（每个指纹键值对独立条目）
- **时间戳精度降级**：抖音群聊把所有消息时间都打到一个很早的日期（"2023-01-01"），无法还原真实秒级时间
- **server_id 才是真正的"时间顺序"**：按 created_at_us 排序就是真实顺序

---

## 📁 目录约定

所有抓取的数据存在仓库根目录下的 `groups/` 子目录（**已在 `.gitignore` 里**，不会上传）：

```
groups/
├── <群名>/
│   ├── <群名>_<时间戳>.json
│   ├── <群名>_<时间戳>.md
│   └── (历史抓取文件)
├── <另一个群名>/
│   └── ...
```

---

## 🤝 配合 AI 使用

如果你用的是 **Hermes Agent**，把这个仓库 clone 到 `~/.hermes/skills/douyin-im-grabber/` 后，触发词包括：

- "**抓抖音群聊**" → 自动激活 skill
- "**抖音群 xxx 增量**" → 跑增量模式
- "**xxx 蒸馏**" → 只生成 MD

AI 会按 skill 工作流走 5 步：检查 Chrome → 确认群 → 跑脚本 → 验证 → 报告。

---

## 📝 License

MIT
