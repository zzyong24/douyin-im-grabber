# douyin-im-grabber

> 抖音群聊全量抓取工具 — 通过 Chrome CDP Network 拦截导出群聊历史

**这个仓库同时是一个 Hermes skill** —— 详见 [SKILL.md](./SKILL.md)。

## 这是什么

通过 Chrome 远程调试监听抖音聊天页的 IM protobuf 响应，把指定群聊的历史消息导出为 JSON 和 Markdown。

**适用场景**：把抖音群里有价值的内容沉淀到本地做知识管理。

## 前置条件

- **macOS / Linux**（用到 Chrome 远程调试）
- **Chrome** 已登录抖音（Web 版）
- **Python 3.10+**
- **Chrome 启动时开启远程调试**（9222 端口）：

  ```bash
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --remote-allow-origins=*
  ```

  ⚠️ 平时用的 Chrome 实例会占用 9222 端口，**先完全退出 Chrome 再用上面命令启动**。

## 安装

```bash
git clone https://github.com/zzyong24/douyin-im-grabber.git
cd douyin-im-grabber
pip install -r requirements.txt
```

## 使用

```bash
# 1. 在已登录抖音的 Chrome 里打开 https://www.douyin.com/chat?isPopup=1
# 2. 确保目标群聊在左侧会话列表中
# 3. 回到终端：

# 方式 A：一键脚本（推荐）
./scripts/grab.sh --group "你的群名" --max-rounds 160 --idle-rounds 10

# 方式 B：直接 python（需要 PYTHONPATH=./src）
PYTHONPATH=./src python3 -m douyin_im_grabber.net_grab --group "你的群名"

# 方式 C：作为包安装到环境
pip install -e .
python3 -m douyin_im_grabber.net_grab --group "你的群名"
```

### 参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `--group` | 群名（自动匹配 conv_id） | — |
| `--max-rounds` | 最大滚动轮数 | 120 |
| `--idle-rounds` | 连续无新增多少轮后停止 | 10 |
| `--wheel-events` | 每轮滚轮事件数 | 24 |
| `--delta-y` | 滚轮方向/幅度；补漏可尝试 `1200` | -1200 |
| `--no-md` | 只输出 JSON，不生成 MD | — |

### 输出

```
./groups/<群名>/
├── <群名>_<时间戳>.json   # 原始消息数据
├── <群名>_<时间戳>.md     # 蒸馏后的人话总结
└── media/                  # 图片/视频/文件
```

## 工作原理

1. **CDP 连 Chrome** → 监听已登录聊天页的 Network 响应
2. **真实点击目标群** → 让网页自己发起 IM 请求
3. **滚动虚拟列表** → 触发 `get_by_conversation` / `get_by_id`
4. **本地解码 protobuf** → 按 `server_id` 去重，补齐真实 `created_at_ms`
5. **输出 JSON + Markdown**

> 内部用了对抖音 IM 协议的反向工程。协议可能随时变更，遇到错误请提 Issue。

## 常见问题

**Q: 提示 "Chrome 未在 9222 端口监听"？**
A: Chrome 没用 `--remote-debugging-port=9222` 启动，或端口被其他进程占。

**Q: 抓到的时间段不完整？**
A: 抖音聊天页是虚拟列表，当前窗口可能停在历史中段。刷新 `https://www.douyin.com/chat?isPopup=1` 后再跑一次，从最新窗口往前补；最终按 `server_id` 合并。

**Q: 群名匹配不到？**
A: 在 Chrome 里搜索或点击一次目标群，让它出现在左侧会话列表。

## License

MIT
