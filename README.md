# douyin-im-grabber

> 抖音群聊全量抓取工具 — 通过 IM WebSocket 协议导出群聊历史

## 这是什么

通过 Chrome 远程调试 + 抖音 IM WebSocket 协议，把指定群聊的**全部历史消息**导出为 JSON 和 Markdown。

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
# 1. 在已登录抖音的 Chrome 里打开 https://www.douyin.com/chat
# 2. 找到目标群聊，点进去加载历史
# 3. 回到终端：

python3 -m douyin_im_grabber.grab --group "你的群名" --mode full
```

### 参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `--group` | 群名（自动匹配 conv_id） | — |
| `--conv-id` | 群会话 ID（跳过匹配） | — |
| `--mode` | `full` 全量 / `incremental` 增量 | `full` |
| `--max-pages` | 最大翻页数 | 500 |
| `--distill-only` | 只蒸馏 MD，不抓数据 | — |

### 输出

```
./groups/<群名>/
├── <群名>_<时间戳>.json   # 原始消息数据
├── <群名>_<时间戳>.md     # 蒸馏后的人话总结
└── media/                  # 图片/视频/文件
```

## 工作原理

1. **CDP 连 Chrome** → 拿到页面的 WebSocket（消息通过这个推）
2. **解析 `get_by_conversation` 响应**（Protobuf 编码）
3. **分页拉取历史**（50 条/页）
4. **本地解码** → JSON + MD

> 内部用了对抖音 IM 协议的反向工程。协议可能随时变更，遇到错误请提 Issue。

## 常见问题

**Q: 提示 "Chrome 未在 9222 端口监听"？**
A: Chrome 没用 `--remote-debugging-port=9222` 启动，或端口被其他进程占。

**Q: 抓到一半报 WebSocket 断开？**
A: Chrome 标签页被切走/关闭会断，保持前台不操作即可。

**Q: 群名匹配不到？**
A: 用浏览器开发者工具看 `get_by_conversation` 请求里的 `conversation_id`，用 `--conv-id` 直接传。

## License

MIT
