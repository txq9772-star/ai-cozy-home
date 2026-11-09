"""小窝的日子：天气、节日、偶尔发生的小事。都是本地规则，不联网，也不调用模型。"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

WEATHER = {"clear": ("晴", "☀"), "cloudy": ("多云", "⛅"), "rain": ("下雨", "🌧")}
RAIN_CHANCE, CLOUDY_CHANCE = 0.18, 0.27
BLOCK_HOURS = 6               # 天气每 6 小时可能变一次

FIXED = {"01-01": "元旦", "02-14": "情人节", "05-01": "劳动节", "06-01": "儿童节", "10-01": "国庆节",
         "12-24": "平安夜", "12-25": "圣诞节"}
# 农历节日换算成公历，只列到 2030 年，之后在 home.yaml 的 life.festivals 里补
LUNAR = {"2026-02-17": "春节", "2027-02-06": "春节", "2028-01-26": "春节", "2029-02-13": "春节", "2030-02-03": "春节",
         "2026-09-25": "中秋节", "2027-09-15": "中秋节", "2028-10-03": "中秋节", "2029-09-22": "中秋节", "2030-09-12": "中秋节"}

# weather：只在这种天气发生；day：只在白天
EVENTS: list[dict[str, Any]] = [
    {"text": "门口来了个快递，{name}去拿了回来", "line": "谁买的这么大一箱？", "memo": "帮大家拿过快递"},
    {"text": "一只猫溜进了院子，{name}蹲着看了半天", "line": "别动，它过来了。", "memo": "院子里来过一只猫", "day": True, "weather": ("clear", "cloudy")},
    {"text": "厨房飘出一股糊味，{name}赶紧过去看", "line": "谁忘了关火？", "memo": "厨房差点烧糊过东西"},
    {"text": "家里的灯闪了两下，{name}抬头看了看", "line": "刚才是不是闪了一下？", "memo": "家里的灯闪过"},
    {"text": "{name}在沙发缝里摸出一枚硬币", "line": "这算我的吧？", "memo": "在沙发缝里捡过硬币"},
    {"text": "雨飘进了窗户，{name}跑过去关上", "line": "窗台全湿了。", "memo": "下雨那天窗户忘了关", "weather": ("rain",)},
    {"text": "{name}看见窗外有道彩虹", "line": "快看外面！", "memo": "看见过彩虹", "day": True, "weather": ("clear",)},
]


def _roll(key: str) -> float:
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def weather_at(when: datetime, seed: str = "", chances: dict[str, Any] | None = None) -> str:
    """同一天同一时段算出来的天气总是一样，重启也不会变。"""
    c = chances or {}
    v = _roll(f"{seed}{when:%Y%m%d}{when.hour // BLOCK_HOURS}")
    rain, cloudy = float(c.get("rain", RAIN_CHANCE)), float(c.get("cloudy", CLOUDY_CHANCE))
    return "rain" if v < rain else "cloudy" if v < rain + cloudy else "clear"


def festival_on(when: datetime, extra: list[dict[str, Any]] | None = None) -> str:
    full, short = when.strftime("%Y-%m-%d"), when.strftime("%m-%d")
    for f in extra or []:
        if str(f.get("date")) in (full, short):
            return str(f.get("name") or "")
    return LUNAR.get(full) or FIXED.get(short) or ""


def talk_lines(weather: str, festival: str) -> list[tuple[str, str]]:
    lines = {"rain": [("外面雨大吗？", "挺大的，别出去了。"), ("雨什么时候停？", "不知道，先窝着吧。")],
             "cloudy": [("外面天气怎么样？", "阴阴的，不算冷。")],
             "clear": [("外面天气怎么样？", "挺好，可以出去走走。")]}[weather]
    return lines + ([(f"今天{festival}，要不要弄点好吃的？", "好啊，我去看看冰箱。")] if festival else [])
