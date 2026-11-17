"""Renders benchmark/results.jsonl as an animated "race" GIF for the README.

Each task gets two bars that grow at the same sped-up clock: DeepSeek Harness alone, and
with dsh-ai-os. The data is the README table's: the `off` runs and the latest `on-v2` run
of each task.

    python scripts/make_race_gif.py            # writes assets/race.zh.gif and assets/race.en.gif
"""

from __future__ import annotations

import json
import pathlib
import statistics

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / "benchmark" / "results.jsonl"
OUT = ROOT / "assets"

TASKS = ["calc_multiply", "calc_scientific", "dark_mode", "web_form", "explorer_folder", "notepad_save"]
TEXT = {
    "zh": {
        "title": "同样 6 个桌面任务：DeepSeek Harness 单独做 vs 装上 dsh-ai-os",
        "speed": "实测数据 · {speed} 倍速",
        "off": "仅 DSH",
        "on": "+ dsh-ai-os",
        "tasks": ["计算器乘法", "计算器切换科学模式", "设置里切换深色模式",
                  "浏览器填写表单", "资源管理器新建文件夹", "记事本写入并保存"],
        "summary": "耗时中位数 {off:.0f} 秒 → {on:.0f} 秒 · token 少 {saved:.0%} · 成功率都是 6/6",
        "font": "msyh.ttc",
        "bold": "msyhbd.ttc",
    },
    "en": {
        "title": "Same 6 desktop tasks: DeepSeek Harness alone vs with dsh-ai-os",
        "speed": "measured runs · {speed}x speed",
        "off": "DSH alone",
        "on": "+ dsh-ai-os",
        "tasks": ["Calculator: multiply", "Calculator: scientific mode", "Settings: dark mode",
                  "Browser: fill a form", "Explorer: new folder", "Notepad: write and save"],
        "summary": "Median time {off:.0f}s → {on:.0f}s · {saved:.0%} fewer tokens · both 6/6 succeeded",
        "font": "segoeui.ttf",
        "bold": "segoeuib.ttf",
    },
}

W, H = 960, 560
BG = (13, 17, 23)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
OFF = (110, 118, 129)
ON = (77, 107, 254)
DONE = (63, 185, 80)
SPEED = 20
FPS = 10
HOLD_SECONDS = 4


def load() -> dict[str, dict[str, dict]]:
    runs: dict[str, dict[str, dict]] = {"off": {}, "on": {}}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["task"] not in TASKS:
            continue
        if r["mode"] == "off" and not r.get("label"):
            runs["off"][r["task"]] = r
        elif r.get("label") == "on-v2":
            runs["on"][r["task"]] = r
    return runs


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(pathlib.Path("C:/Windows/Fonts") / name), size)


def render(lang: str, runs: dict[str, dict[str, dict]]) -> pathlib.Path:
    t = TEXT[lang]
    regular, small, bold, big = (font(t["font"], 17), font(t["font"], 14),
                                 font(t["bold"], 22), font(t["bold"], 30))
    longest = max(r["seconds"] for mode in runs.values() for r in mode.values())
    off_median = statistics.median(runs["off"][k]["seconds"] for k in TASKS)
    on_median = statistics.median(runs["on"][k]["seconds"] for k in TASKS)
    saved = 1 - sum(runs["on"][k]["tokens"] for k in TASKS) / sum(runs["off"][k]["tokens"] for k in TASKS)

    left, right, top, row_h = 250, 870, 110, 64
    bar_w = right - left

    frames = []
    steps = int(longest / SPEED * FPS) + 1
    for i in range(steps + HOLD_SECONDS * FPS):
        clock = min(i * SPEED / FPS, longest)
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.text((30, 24), t["title"], font=bold, fill=FG)
        d.text((30, 60), t["speed"].format(speed=SPEED), font=small, fill=MUTED)
        d.text((W - 30, 22), f"{int(clock) // 60}:{int(clock) % 60:02d}", font=big, fill=FG, anchor="ra")

        legend_y = 64
        for color, name, x in ((OFF, t["off"], 560), (ON, t["on"], 700)):
            d.rectangle((x, legend_y, x + 14, legend_y + 14), fill=color)
            d.text((x + 22, legend_y - 3), name, font=small, fill=MUTED)

        for row, (task, name) in enumerate(zip(TASKS, t["tasks"])):
            y = top + row * row_h
            d.text((30, y + 12), name, font=regular, fill=FG)
            for offset, mode, color in ((0, "off", OFF), (24, "on", ON)):
                seconds = runs[mode][task]["seconds"]
                shown = min(clock, seconds)
                x1 = left + bar_w * shown / longest
                d.rounded_rectangle((left, y + offset, max(x1, left + 4), y + offset + 18), radius=4, fill=color)
                if clock >= seconds:
                    cy = y + offset + 9
                    d.line([(x1 + 8, cy), (x1 + 12, cy + 4), (x1 + 19, cy - 4)], fill=DONE, width=2)
                    d.text((x1 + 25, cy), f"{seconds:.0f}s", font=small, fill=DONE, anchor="lm")

        if clock >= longest:
            summary = t["summary"].format(off=off_median, on=on_median, saved=saved)
            d.text((W // 2, H - 40), summary, font=bold, fill=FG, anchor="mm")
        frames.append(img.convert("P", palette=Image.ADAPTIVE, colors=32))

    OUT.mkdir(exist_ok=True)
    path = OUT / f"race.{lang}.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=1000 // FPS, loop=0, optimize=True)
    return path


def main() -> None:
    runs = load()
    for lang in TEXT:
        path = render(lang, runs)
        print(f"wrote {path} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
