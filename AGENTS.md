# AI OS 工作区约定

本项目是 Windows 桌面语音操作层（`ai-os`）。**操作本机桌面时，一律使用 `ai-os` MCP 工具，不要用 PowerShell 手写 Win32 代码。**

## 桌面操作工具优先级

| 要做的事 | 用这个工具 |
| --- | --- |
| 看前台窗口有哪些可点控件 | `get_screen_elements` |
| 点某个控件 | `click_element` |
| 输入文字 | `type_text` |
| 按快捷键 | `press_keys` |
| 滚动 | `scroll` |
| 打开应用 / 网址 / 文件 | `open_app` / `open_url` / `open_path` |
| 列出已打开的窗口 | `list_windows` |
| 切到某个窗口 | `focus_window` |
| 控件列表里找不到目标 | `look_at_screen` + `click_xy` |
| 等界面加载 | `wait` |

## 硬性规则

1. **禁止**用 `run_powershell`、`Add-Type`、`user32.dll`、`EnumWindows`、`GetWindowText` 等方式自己实现桌面操作。这些工具已经封装好了。
2. 需要「所有窗口」时，`list_windows` 就是完整答案。它只列可见窗口，这就是用户想看的内容；不要再为了「补上隐藏窗口」而另找办法。
3. 每个会改变界面的操作都会返回屏幕变化（新增/消失的控件）。**据此确认结果即可，不要额外截图验证。**
4. 一次操作失败时，先调用 `get_screen_elements` 重新读取当前界面，不要换工具重试同一件事。
5. 任务结束用一句话口语化说明结果，因为这句话会被朗读出来。
