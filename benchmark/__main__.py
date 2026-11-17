"""AI OS vs. plain DeepSeek Harness benchmark.

  python -m benchmark run --mode off     # dsh-ai-os plugin disabled
  python -m benchmark run --mode on      # dsh-ai-os plugin enabled
  python -m benchmark run --mode on --label on-v2   # a new plugin version, shown as its own column
  python -m benchmark report
"""
import argparse
import json
import os
import statistics
import time
from datetime import datetime

from ai_os.dpi import enable_dpi_awareness

enable_dpi_awareness()

import pyperclip  # noqa: E402

from .dsh_log import collect  # noqa: E402
from .tasks import HARD_TASKS, TASKS  # noqa: E402

RESULTS = os.path.join(os.path.dirname(__file__), "results.jsonl")


def run(mode: str, label: str, only: list[str] | None) -> None:
    if only == ["hard"]:
        only = HARD_TASKS
    tasks = [t for t in TASKS if not only or t.id in only]
    plugin = "开启" if mode == "on" else "关闭"
    print(f"\n=== 对比测试：dsh-ai-os 插件{plugin}，共 {len(tasks)} 个任务 ===")
    print(f"开始前请确认 DSH 插件页里 dsh-ai-os 已{plugin}，并已重启 DSH。")
    print("每个任务请在 DSH 里新建会话再发送，避免上一题的上下文影响结果。\n")

    for index, task in enumerate(tasks, 1):
        print(f"[{index}/{len(tasks)}] {task.title}")
        task.setup()
        pyperclip.copy(task.prompt)
        print(f"  指令（已复制到剪贴板）：{task.prompt}")
        started = time.time()
        try:
            answer = input("  在 DSH 新会话中粘贴发送，等它完成后回到这里按回车（输入 s 跳过）：").strip().lower()
            if answer != "s":
                success, detail = task.verify()
        finally:
            task.teardown()
        if answer == "s":
            print("  已跳过\n")
            continue
        metrics = collect(started)
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "mode": mode, "label": label, "task": task.id, "success": success, "detail": detail,
            "seconds": metrics.seconds, "turns": metrics.turns, "tool_calls": len(metrics.tool_calls),
            "ai_os_calls": metrics.ai_os_calls, "tokens": metrics.tokens, "retries": metrics.retries,
            "dsh_outcome": metrics.outcome, "tools": metrics.tool_calls,
        }
        with open(RESULTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"  {'✅ 成功' if success else '❌ 失败'}：{detail}")
        print(f"  耗时 {metrics.seconds}s，工具调用 {len(metrics.tool_calls)} 次"
              f"（其中 AI OS {metrics.ai_os_calls} 次），{metrics.tokens} tokens\n")


def report() -> None:
    if not os.path.exists(RESULTS):
        print("还没有测试结果，请先运行 run。")
        return
    latest: dict[tuple[str, str], dict] = {}
    labels: list[str] = []
    with open(RESULTS, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            label = r.get("label", r["mode"])
            if label not in labels:
                labels.append(label)
            latest[(label, r["task"])] = r

    def cell(r: dict | None) -> str:
        if r is None:
            return "—"
        mark = "✅" if r["success"] else "❌"
        return f"{mark} {r['seconds']}s / {r['tool_calls']} 次 / {r['tokens'] // 1000}K"

    print("\n各任务结果（成败 / 耗时 / 工具调用次数 / tokens）")
    print(f"{'任务':<20}" + "".join(f"{label:<28}" for label in labels))
    for task in TASKS:
        print(f"{task.title:<16}" + "".join(f"{cell(latest.get((label, task.id))):<28}" for label in labels))

    print("\n汇总")
    for label in labels:
        rows = [r for (lb, _), r in latest.items() if lb == label]
        ok = sum(r["success"] for r in rows)
        print(f"  {label}：成功 {ok}/{len(rows)}，耗时中位数 {statistics.median(r['seconds'] for r in rows):.1f}s，"
              f"平均工具调用 {statistics.mean(r['tool_calls'] for r in rows):.1f} 次，"
              f"平均 {statistics.mean(r['tokens'] for r in rows) / 1000:.0f}K tokens，"
              f"AI OS 工具使用 {sum(r['ai_os_calls'] for r in rows)} 次")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI OS 对比测试")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--mode", choices=["on", "off"], required=True, help="dsh-ai-os 插件是否开启")
    run_parser.add_argument("--label", help="报告中的列名，用于区分同一模式的不同版本，默认等于 mode")
    run_parser.add_argument("--only", nargs="*", help="只跑指定任务 id；hard 表示三个高难度任务")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "run":
        run(args.mode, args.label or args.mode, args.only)
    else:
        report()


main()
