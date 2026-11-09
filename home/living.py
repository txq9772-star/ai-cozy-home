"""住着的感觉：精力、饱腹这些需求，由此而来的心情，小动作，长期目标和集体活动。这里的东西都不调用模型。"""
from __future__ import annotations

import random
from typing import Any

NEEDS = ("energy", "hunger", "social", "fun")
DRAIN = {"energy": 6.0, "hunger": 9.0, "social": 5.0, "fun": 7.0}     # 每小时掉多少
SLEEP_ENERGY = 15.0
LOW = 28.0
GOOD = 62.0
MAX_DECOR = 6


def clean_needs(saved: Any) -> dict[str, float]:
    out = {k: 70.0 for k in NEEDS}
    if isinstance(saved, dict):
        for k in NEEDS:
            try:
                out[k] = max(0.0, min(100.0, float(saved.get(k, 70.0))))
            except (TypeError, ValueError):
                pass
    return out


def drain(needs: dict[str, float], hours: float, asleep: bool) -> None:
    for k in NEEDS:
        rate = DRAIN[k] * (0.3 if asleep else 1.0)
        if k == "energy" and asleep:
            needs[k] = min(100.0, needs[k] + SLEEP_ENERGY * hours)
        else:
            needs[k] = max(0.0, needs[k] - rate * hours)


def give(needs: dict[str, float], gives: dict[str, Any] | None) -> None:
    for k, v in (gives or {}).items():
        if k in needs:
            needs[k] = max(0.0, min(100.0, needs[k] + float(v)))


def need_factor(needs: dict[str, float], gives: dict[str, Any] | None) -> float:
    """这件事能补上多少眼下缺的东西，缺得越多越想做。"""
    factor = 1.0
    for k, v in (gives or {}).items():
        if k in needs and float(v) > 0:
            factor += max(0.0, 55.0 - needs[k]) / 55.0 * float(v) / 12.0
    return factor


def mood(needs: dict[str, float], weather: str = "", festival: str = "") -> dict[str, str]:
    if needs["energy"] < LOW:
        return {"key": "sleepy", "label": "有点困", "icon": "😪"}
    if needs["hunger"] < LOW:
        return {"key": "hungry", "label": "饿了", "icon": "🍙"}
    if needs["social"] < LOW:
        return {"key": "lonely", "label": "想找人说话", "icon": "💭"}
    if needs["fun"] < LOW:
        return {"key": "bored", "label": "有点无聊", "icon": "😑"}
    if festival or all(needs[k] >= GOOD for k in NEEDS):
        return {"key": "happy", "label": "心情不错", "icon": "😊"}
    if weather == "rain":
        return {"key": "lazy", "label": "懒懒的", "icon": "🌧️"}
    return {"key": "calm", "label": "还行", "icon": "🙂"}


# ---------------------------------------------------------------- 小动作
_FIDGET = {
    "sleepy": [("yawn", "🥱"), ("doze", "💤")],
    "hungry": [("look", "🍙"), ("shake", "…")],
    "lonely": [("look", "💭"), ("wave", "👋")],
    "bored": [("yawn", "😑"), ("look", "…")],
    "happy": [("dance", "♪"), ("clap", "😊"), ("wave", "✨")],
    "lazy": [("look", "🌧️"), ("yawn", "🥱")],
    "calm": [("look", ""), ("nod", ""), ("stretch", "")],
}
SEATED_OK = {"look", "nod", "yawn", "doze", "clap", "wave"}


def fidget(mood_key: str, pose: str) -> tuple[str, str]:
    rows = _FIDGET.get(mood_key) or _FIDGET["calm"]
    if pose != "stand":
        rows = [x for x in rows if x[0] in SEATED_OK] or [("nod", "")]
    return random.choice(rows)


# ---------------------------------------------------------------- 长期目标：做够次数，屋里添一样东西
GOALS: dict[str, dict[str, Any]] = {
    "read": {"label": "读完一本厚书", "need": 8, "item": "book_pile", "got": "一摞看完的书"},
    "cook": {"label": "学会一道新菜", "need": 6, "item": "recipe", "got": "一本手写菜谱"},
    "water": {"label": "把一盆花养开", "need": 5, "item": "flower", "got": "一盆开花的植物"},
    "paint": {"label": "画完一幅画", "need": 6, "item": "painting", "got": "一幅自己的画"},
    "piano": {"label": "练熟一首曲子", "need": 7, "item": "sheet", "got": "一叠曲谱"},
    "feed_ducks": {"label": "和湖里的鸭子混熟", "need": 5, "item": "plush_duck", "got": "一只鸭子玩偶"},
    "fishing": {"label": "钓上一条大鱼", "need": 6, "item": "fish_trophy", "got": "一块鱼形木牌"},
    "stretch": {"label": "坚持拉伸一阵子", "need": 8, "item": "dumbbell", "got": "一对小哑铃"},
    "tv": {"label": "追完一部剧", "need": 7, "item": "poster", "got": "一张海报"},
    "browse": {"label": "攒一份收藏夹", "need": 8, "item": "photo", "got": "一个相框"},
    "pet_cat": {"label": "让猫愿意亲近", "need": 5, "item": "cat_toy", "got": "一个逗猫玩具"},
}


def new_goal(likes: dict[str, Any], usable: set[str], decor: list[str], last: str = "") -> dict[str, Any] | None:
    keys = [k for k in GOALS if k in usable and k != last and GOALS[k]["item"] not in decor] or [k for k in GOALS if k in usable and k != last]
    if not keys:
        return None
    aid = random.choices(keys, weights=[max(float(likes.get(k, 1)), 0.2) for k in keys])[0]
    g = GOALS[aid]
    return {"act": aid, "label": g["label"], "need": g["need"], "done": 0}


# ---------------------------------------------------------------- 集体活动
GATHERINGS = [
    {"key": "movie", "label": "看电影", "tags": ["tv", "beanbag"], "emote": "🍿", "anim": "look", "prop": "cup",
     "lines": ["这段别快进。", "谁把爆米花吃完了？"], "text": "凑在{room}看了一部电影"},
    {"key": "book", "label": "开读书会", "tags": ["reading"], "emote": "📖", "anim": "read", "prop": "book",
     "lines": ["这一章你怎么看？", "我觉得结局早写好了。"], "text": "在{room}开了个读书会"},
    {"key": "dinner", "label": "一起吃饭", "tags": ["table", "stove", "fridge"], "emote": "🍲", "anim": "sip", "prop": "cup",
     "lines": ["今天这个咸了一点。", "还有饭吗？"], "text": "聚在{room}一起吃了顿饭"},
    {"key": "concert", "label": "听小音乐会", "tags": ["piano", "sofa"], "emote": "♪", "anim": "nod", "prop": "",
     "lines": ["再弹一首吧。", "这段是不是错了个音？"], "text": "在{room}听了场小音乐会"},
    {"key": "picnic", "label": "在湖边野餐", "tags": ["lake_feed", "bench", "fish"], "emote": "🧺", "anim": "look", "prop": "cup",
     "lines": ["鸭子过来了！", "别喂太多。"], "text": "去{room}野餐了", "outdoor": True},
]

TOUCH: dict[str, dict[str, Any]] = {
    "tv": {"lines": ["谁换的台？", "哎，正看着呢。"]},
    "lamp": {"lines": ["灯怎么了？", "这样暗一点也好。"]},
    "plant": {"lines": ["它是不是长高了？", "该浇水了吧。"]},
    "fridge": {"lines": ["里面还有吃的吗？", "别一直开着门。"]},
    "piano": {"lines": ["谁按的？", "这个音不准。"]},
    "cat": {"lines": ["它今天肯让人摸？", "别把它吵醒了。"], "feed": "摸了摸猫"},
    "lake": {"lines": ["鸭子都游过来了。", "天鹅好像不太高兴。"], "feed": "往湖里撒了点吃的"},
}
