"""Exposes AI OS desktop control as an MCP server (stdio) for DeepSeek Harness, Claude Code, Cursor, etc.

Run: python -m ai_os.mcp_server
"""
from .dpi import enable_dpi_awareness

enable_dpi_awareness()

import time  # noqa: E402

import anyio  # noqa: E402
import mcp.types as types  # noqa: E402
from mcp.server.lowlevel import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402

from . import hotkey  # noqa: E402
from .actions import READ_ONLY_TOOLS, TOOLS, Actions  # noqa: E402
from .config import load_config  # noqa: E402
from .screen import ScreenReader  # noqa: E402

# Conversation and shell tools stay with the host, which owns its own user dialog and command approval.
HOST_OWNED_TOOLS = {"ask_user", "finish", "run_powershell"}

INSTRUCTIONS = """AI OS：Windows 桌面控制工具集。操作本机桌面只用这里的工具，不要用 PowerShell 自己实现。

【第一步】调用 get_screen_elements 获取前台窗口控件（带编号），再用 click_element 按编号点击。
【找控件】控件列表里找不到时（常见于网页和 Electron 应用），用 look_at_screen + click_xy。
【列窗口】用户要看已打开的窗口时，直接调用 list_windows。它返回的就是完整清单，不需要为了
“隐藏窗口”另想办法，更不要用 EnumWindows、GetWindowText、Add-Type 之类自己实现。
【确认结果】同一窗口内控件编号保持不变；每个改变界面的操作都会返回屏幕变化（新增/消失的控件，
切换窗口时返回完整列表），据此确认操作结果即可，不要再截图验证。
【失败时】先调用 get_screen_elements 重新读取当前界面，不要换工具重试同一件事。
【结束语】任务结束用一句口语化的中文说明结果，这句话会被朗读给用户。"""

CHANGES_NOTE = "返回结果附带操作后的屏幕变化，据此确认结果即可，无需另行截图验证。"

screen = ScreenReader()
actions = Actions(load_config(), screen, confirm=lambda _q: False, ask=lambda _q: "")
tool_specs = [t["function"] for t in TOOLS if t["function"]["name"] not in HOST_OWNED_TOOLS]
exposed = {spec["name"] for spec in tool_specs}


def _description(spec: dict) -> str:
    if spec["name"] in READ_ONLY_TOOLS:
        return spec["description"]
    return f"{spec['description']}{CHANGES_NOTE}"


async def list_tools(_ctx, _params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[
        types.Tool(name=spec["name"], description=_description(spec), input_schema=spec["parameters"])
        for spec in tool_specs
    ])


async def call_tool(_ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    if params.name not in exposed:
        return _text(f"未知工具：{params.name}", error=True)
    result = actions.dispatch(params.name, dict(params.arguments or {}))
    if params.name not in READ_ONLY_TOOLS and not result.startswith("错误"):
        time.sleep(0.6)
        try:
            result += "\n\n" + screen.changes()
        except Exception as e:
            result += f"\n\n（读取屏幕失败：{type(e).__name__}: {e}，可稍后调用 get_screen_elements）"
    return _text(result, error=result.startswith("错误"))


def _text(text: str, error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=error)


server = Server("ai-os", version="0.2.0", instructions=INSTRUCTIONS,
                on_list_tools=list_tools, on_call_tool=call_tool)


async def run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    hotkey.start()
    anyio.run(run)


if __name__ == "__main__":
    main()
