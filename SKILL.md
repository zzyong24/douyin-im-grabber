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

> 通过抖音网页版 IM API (`imapi.douyin.com/v1/message/get_by_conversation`) 全量抓取群消息。
> 协议为 protobuf 二进制，**用纯后端 HTTP 调用 + 浏览器 cookie**，不依赖 UI 自动化。

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

### Step 2: 确认目标群已打开
- 用户应在 Chrome 里**打开抖音聊天页面** `https://www.douyin.com/chat?isPopup=1`
- **目标群需要在 conversationStore 里**（即用户在 Chrome 里能看到这个群）
- 不需要"切到"那个群（skill 自己会通过 `conversationStore.conversationMap` 找群名→conv_id）

### Step 3: 跑抓取

```bash
# 找 skill 根目录
SKILL_DIR="$(dirname "$(realpath "$0" 2>/dev/null || python3 -c "import os; print(os.path.dirname(os.path.abspath('')))")")"

python3 "$SKILL_DIR/src/douyin_im_grabber/grab.py" \
  --group "你的群名" --mode full
```

或者用一键脚本：
```bash
./scripts/grab.sh --group "你的群名" --mode full
```

**预期运行时间**：每 1000 条 ≈ 1 分钟（限速 0.3s/页）。

### Step 4: 验证输出

- 路径：`./groups/<群名>/`（仓库根目录下的 `groups/`，**已 gitignore**）
- 文件：`<群名>_<时间戳>.json`（原始结构化数据）
- 文件：`<群名>_<时间戳>.md`（蒸馏版，含 Top 20 发言榜 + 消息记录）

**质量检查**：
- JSON 总消息数应等于 page 累计的总数
- MD 顶部"基础信息"应正确
- 文本消息数（type=7）应在 60-80% 之间

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
| `--conv-id` | 无 | 直接指定 conv_id（跳过匹配） |
| `--mode` | `full` | `full`=全量 / `incremental`=增量续跑 |
| `--max-pages` | `500` | 最大翻页数（防失控） |
| `--distill-only` | `false` | 只蒸馏不抓 |
| `--no-distill` | `false` | 不生成 MD（只出 JSON） |

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
3. **单次 MAX_PAGES=500** —— 防止意外循环（500 页 = 25000 条，足够大多数群）
4. **HAR 提取参数** —— 适配 cursor 特殊的群（财富自由团这种）

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
| `找不到群: xxx` | 群不在当前 conversationStore | 用户在 Chrome 里点开一次那个群 |
| `conversation not found` | sessionid 过期 | 重新登录抖音 |
| `HTTP 429` | 限速 | 等待 1 小时后重跑，或增大 `SLEEP_BETWEEN_PAGES` |

## License

MIT
