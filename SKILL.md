---
name: douyin-im-grabber
description: 抓取抖音群聊的全量聊天记录，输出原始 JSON 和蒸馏后的 Markdown。
triggers:
  - "抓抖音群聊"
  - "导出抖音聊天记录"
  - "douyin grab"
  - "douyin group export"
  - "抖音群消息"
  - "抖音聊天记录"
---

# 抖音群聊抓取器 · douyin-im-grabber

> 通过 Chrome CDP 监听抖音网页版聊天页的 Network 响应，抓取真实 IM protobuf 消息。
> 不手动复制 cookie；由已登录的 Chrome 负责鉴权，skill 只点击目标群、滚动历史、解析响应并导出。

## 这是什么

这个仓库**同时是**：

- 🐍 **Python 包** — 别人 `pip install` 就能用
- 🛠️ **Hermes skill** — clone 到 `~/.hermes/skills/douyin-im-grabber/` 后，Hermes 会自动识别

## 激活时机

用户说以下任何一句都激活：
- "**抓抖音群聊**" / "**抓一下财富自由团**"
- "**导出抖音聊天记录**"
- "**douyin grab 群名xxx**"
- "**全量抓抖音群消息**"

## 工作流（5 步）

### Step 1: 确认 Chrome 状态
- 用户应该已经打开 Chrome，**登录了 douyin.com**
- Chrome 必须以 `--remote-debugging-port=9222` 启动（Hermes 默认 CDP 端口）
- 如果 Chrome 没启 CDP → 引导用户：
  ```bash
  pkill -a "Google Chrome"
  open -a "Google Chrome" --args \
    --remote-debugging-port=9222 \
    --user-data-dir=/tmp/chrome_cdp \
    --remote-allow-origins=*
  ```

### Step 2: 确认目标群在会话列表
- 用户应在 Chrome 里**打开抖音聊天页面** `https://www.douyin.com/chat?isPopup=1`
- **目标群需要在 conversationStore 里**（即用户在 Chrome 里能看到这个群）
- 不需要提前切到群；脚本会真实点击左侧群条目，失败才用 `conversationStore` 兜底。

### Step 3: 跑抓取

```bash
PYTHONPATH=src .venv/bin/python -m douyin_im_grabber.net_grab \
  --group "你的群名" --max-rounds 160 --idle-rounds 10
```

或者用一键脚本：
```bash
./scripts/grab.sh --group "你的群名" --max-rounds 160 --idle-rounds 10
```

**预期运行时间**：每 1000 条约 20-40 秒，取决于网页滚动和响应体大小。

### Step 4: 验证输出

- 路径：`./groups/<群名>/`（仓库根目录下的 `groups/`，**已 gitignore**）
- 文件：`<群名>_<时间戳>.json`（原始结构化数据）
- 文件：`<群名>_<时间戳>.md`（蒸馏版，含 Top 20 发言榜 + 消息记录）

**质量检查**：
- JSON 中 `total_messages` 应等于 `server_id` 去重后的消息数
- `created_at_ms` 应为真实 2026 时间，不应停留在 2023 假时间
- MD 顶部"基础信息"应正确，非文本消息应显示为 `[图片]`、`[表情]`、`[卡片]` 等摘要
- 如果分段多次抓取，按 `server_id` 合并去重后再交付最终文件

### Step 5: 报告给用户

回复包含：
1. **共抓 N 条消息**（含纯文本/非文本分类）
2. **Top 1-3 发言人** + 消息数
3. **输出文件路径**（JSON + MD，相对当前目录）
4. **抓取耗时**
5. **风控提醒**：如果跑了 >1 万页，建议冷却 1 小时再跑

## 关键参数

| 参数 | 默认值 | 含义 |
|---|---|---|
| `--group` | 无 | 群名（自动匹配） |
| `--max-rounds` | `120` | 最大滚动轮数 |
| `--idle-rounds` | `10` | 连续无新增多少轮后停止 |
| `--wheel-events` | `24` | 每轮滚轮事件数 |
| `--delta-y` | `-1200` | 滚轮方向/幅度；补漏可尝试 `1200` |
| `--no-md` | `false` | 不生成 MD（只出 JSON） |

## 输出位置

```
./groups/
└── <群名>/
    ├── <群名>_<时间戳>.json   ← 原始结构化（10MB+ for 大群）
    └── <群名>_<时间戳>.md     ← 蒸馏版（人读，含 Top 发言榜）
```

> ⚠️ `groups/` 在 `.gitignore` 里，**抓取内容不会进 git**。

## 风控注意事项

1. **不要连续跑** —— 抖音有限速，每次抓取后建议**至少冷却 1 小时**
2. **sessionid 会过期** —— 跑前确认 Chrome 还在登录态；如果失败先重新登录
3. **单次 max-rounds 控制上限** —— 防止网页虚拟列表异常循环
4. **分段补抓要合并** —— 如果刷新后补到不同时间段，最终按 `server_id` 去重合并

## 作为 Hermes skill 安装

```bash
# 1. clone 到 skills 目录
git clone https://github.com/zzyong24/douyin-im-grabber.git \
  ~/.hermes/skills/douyin-im-grabber

# 2. 装依赖（用 Hermes 的 venv）
~/.hermes/hermes-agent/.venv/bin/pip install -r \
  ~/.hermes/skills/douyin-im-grabber/requirements.txt

# 3. 重启 Hermes 即可识别
```

## 常见错误处理

| 错误 | 原因 | 解决 |
|---|---|---|
| `无法连接 Chrome CDP` | Chrome 未启 CDP | 重启 Chrome + `--remote-debugging-port=9222` |
| `找不到 douyin.com tab` | Chrome 没开抖音页面 | 用户打开 `https://www.douyin.com/chat?isPopup=1` |
| `找不到群: xxx` | 群不在当前会话列表 | 用户在 Chrome 里搜索/点开一次那个群 |
| `conversation not found` | sessionid 过期 | 重新登录抖音 |
| `HTTP 429` | 限速 | 等待 1 小时后重跑，减少 `--wheel-events` 或增加冷却 |
| 只抓到局部时间段 | 页面虚拟列表停在历史窗口 | 刷新 `chat?isPopup=1` 后从最新窗口再跑，并与旧 JSON 按 `server_id` 合并 |

## License

MIT
