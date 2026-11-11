"""小窝的日常：作息、去哪做什么、写动态、群聊接话、额度控制。

线程模型：一个 tick 线程每隔一两秒看一遍所有住户；需要调用模型的事丢进线程池。
每个住户同一时间最多一个模型调用（call_lock），所以活动和群聊不会同时打到同一个 CLI 上。
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import days, living, prompts
from .drivers import Driver, Gen, make_driver
from .farm import Farm
from .layout import spots_index
from .sources import Item, Sources
from .store import Store

log = logging.getLogger("home.life")
Emit = Callable[[str, Any], None]
MENTION_ALL = ("@所有人", "@全体成员", "@全体", "@all", "@大家")
GO_WORDS = ("去", "来", "到", "过来", "过去", "回")        # 主人喊人去哪：句子里得有这类字才算
ASK_WORDS = ("帮", "让", "叫", "把", "一下", "吧", "快")    # 叫人干活的说法，用来认「帮我把玉米收了」
GO_REFUSE = "[不去]"
GO_SKIP_LABELS = ("门口",)                                 # 太泛的位置名不拿来认地方
DAY_HOURS = (7, 19)
REFLECT_MIN = 4               # 当天至少攒够这么多条零碎记忆，睡前才整理
SMALL_TALK = [("今天吃什么？", "冰箱里好像还有点。"), ("你刚才在忙什么？", "没忙什么，瞎晃。"),
              ("这儿是不是换过东西？", "好像是，我也没注意。"), ("你困不困？", "还行，再撑一会儿。")]
OUTSIDE_TALK = ("等下要不要去荡秋千？", "行啊，你先去占位置。")
VISIT_GAP_MINUTES = 240       # 隔这么久再打开页面，才算又来了一趟
EVENT_MINUTES = (90, 240)
LEFTOVER_HOURS = 10           # 做的菜放这么久还算剩菜，别人找吃的会吃到
NOTE_TO_OWNER_CHANCE = 0.15   # 主人不在时，每次写感想有多大概率允许留言
NOTE_NO_QUOTA = "看到了，今天额度用完了，明天再好好回你。"
BLOCKS = 24 // days.BLOCK_HOURS
TOGETHER_LINES = [("来嘛，就玩一会儿。", "好好好，等我一下。"), ("这个比想的好玩。", "你小声点笑。"), ("再来一次？", "最后一次啊。")]
REACTIONS = {
    "pat": ("摸了摸{name}的头", ["嘿嘿。", "头发要乱啦。", "……再摸一下也行。"]),
    "feed": ("给{name}带了点吃的", ["谢谢！正好饿了。", "好吃，还有吗？", "你也吃一口。"]),
    "wave": ("跟{name}打了个招呼", ["嗨～", "你来啦。", "我看到你啦。"]),
}


class Resident:
    def __init__(self, cfg: dict[str, Any], driver: Driver, bedroom: str):
        self.cfg = cfg
        self.id = str(cfg["id"])
        self.name = str(cfg.get("name") or self.id)
        self.driver = driver
        self.bedroom = bedroom
        self.ready = False
        self.ready_info = "还没检查"
        self.next_check = 0.0
        self.status = "idle"          # offline / asleep / idle / busy
        self.room = bedroom
        self.spot = "desk"
        self.activity = "在房间里"
        self.since = time.time()
        self.next_at = 0.0
        self.backoff_until = 0.0
        self.note = ""
        self.typing = False
        self.fails = 0
        self.traced: tuple[str, str, str, str] | None = None
        self.needs = living.clean_needs(None)
        self.needs_at = time.time()
        self.goal: dict[str, Any] | None = None
        self.last_goal = ""
        self.decor: list[str] = []
        self.anim = self.emote = self.prop = ""
        self.roam = False
        self.last_act = ""
        self.thing = self.doing = self.thing_of = ""     # 这件事具体在弄什么：thing 给页面看，doing 是给模型的一句话，thing_of 记着是哪件事的
        self.last_thing: dict[str, str] = {}
        self.mood_key = ""
        self.next_fidget = time.time() + random.uniform(20, 90)
        self.call_lock = threading.Lock()

    @property
    def daily_calls(self) -> int:
        return int(self.cfg.get("daily_calls", 50))


class Life:
    def __init__(self, cfg: dict[str, Any], layout: dict[str, Any], activities: dict[str, dict[str, Any]],
                 store: Store, data_dir: Path, mock: bool = False, fast: bool = False, emit: Emit | None = None):
        self.store = store
        self.data_dir = data_dir
        self.mock = mock
        self.fast = fast
        self.emit_cb = emit or (lambda t, d: None)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="home")
        self.pending: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self.paused = False
        self.residents: dict[str, Resident] = {}
        self.next_talk = time.time() + random.uniform(1, 4) * (1.0 if fast else 60.0)
        self.next_event = time.time() + random.uniform(*EVENT_MINUTES) * (1.0 if fast else 60.0)
        self.weather_force: tuple[str, float] | None = None
        self.last_weather = ""
        self.online = 0
        self.delivering: set[int] = set()
        self.next_prune = 0.0
        self.party_day = ""
        self.kitchen = {}
        self.backup_day = ""
        self.party_at: tuple[str, float] = ("", 0.0)
        self.touch_at = 0.0
        self.budget_cache: tuple[float, str] = (0.0, "ok")
        self.apply(cfg, layout, activities, first=True)
        saved = self.store.load_state("__home__")
        self.paused = bool(saved.get("paused", self.life.get("pause", False)))
        self.festival_said = str(saved.get("festival_said", ""))
        self.party_day = str(saved.get("party_day", ""))
        self.kitchen: dict[str, Any] = dict(saved.get("kitchen") or {})
        self.farm = Farm(self.layout, self.store.load_state("__farm__"), 60 * self.minute)
        self.farm_saved_at = time.time()
        owner = self.store.load_state("__owner__")
        self.last_visit, self.last_seen = float(owner.get("last_visit", 0)), float(owner.get("last_seen", 0))
        self.visits = int(owner.get("visits", 0))
        self.sources = Sources(cfg.get("sources") or {}, mock)

    # ------------------------------------------------------------ 配置
    def apply(self, cfg: dict[str, Any], layout: dict[str, Any], activities: dict[str, dict[str, Any]],
              first: bool = False) -> None:
        with self.lock:
            self.cfg = cfg
            self.life = cfg.get("life") or {}
            self.layout = layout
            self.activities = activities
            self.spots = spots_index(layout)
            self.tz = ZoneInfo(cfg.get("timezone") or "Asia/Shanghai")
            bedrooms = {r.get("owner"): r["id"] for r in layout["rooms"] if r.get("owner")}
            old = self.residents
            arrived: list[Resident] = []
            self.residents = {}
            timeout = float(self.life.get("call_timeout", 180))
            for rc in cfg.get("residents") or []:
                rid = str(rc["id"])
                dcfg = rc.get("driver") or {"type": "mock"}
                if self.mock:
                    try:
                        real = make_driver(dcfg, self.data_dir / "sandbox" / rid, timeout).label
                    except ValueError:
                        real = ""
                    dcfg = {"type": "mock", "as": real}
                driver = make_driver(dcfg, self.data_dir / "sandbox" / rid, timeout)
                r = old.get(rid)
                if r is None:
                    r = Resident(rc, driver, bedrooms.get(rid, ""))
                    st = self.store.load_state(rid)
                    if st.get("room") and self._spot(st["room"], st.get("spot")):
                        r.room, r.spot = st["room"], st.get("spot")
                        r.activity = st.get("activity") or r.activity
                        r.status = st.get("status") if st.get("status") in ("asleep", "idle") else "idle"
                    else:
                        r.room, r.spot = r.bedroom, "desk"
                    r.next_at = time.time() + random.uniform(3, 20)
                    self._restore(r, st)
                    if not first:
                        arrived.append(r)
                else:
                    r.cfg, r.driver, r.bedroom, r.name = rc, driver, bedrooms.get(rid, ""), str(rc.get("name") or rid)
                    r.ready, r.next_check = False, 0.0
                    if not self._spot(r.room, r.spot):
                        r.room, r.spot = r.bedroom, "desk"
                self.residents[rid] = r
        if not first:
            self.farm.set_layout(layout)
            self._save_farm()
            self.emit("layout", self.layout)
            self.emit("farm", self.farm_public())
            for r in self.residents.values():
                self.emit("resident", self.public(r))
            for r in arrived:
                self.add_feed(r, "movein", "搬进来了", room=r.room, spot=r.spot)
                self.remember(r, "今天搬进了小窝", "together", 2)

    def _restore(self, r: Resident, st: dict[str, Any]) -> None:
        r.needs = living.clean_needs(st.get("needs"))
        r.decor = [str(x) for x in st.get("decor") or []][:living.MAX_DECOR]
        r.goal = st.get("goal") if isinstance(st.get("goal"), dict) else living.new_goal(r.cfg.get("likes") or {}, self._usable_goals(), r.decor)
        r.anim, r.emote, r.prop = str(st.get("anim") or ""), str(st.get("emote") or ""), str(st.get("prop") or "")
        r.roam = bool(st.get("roam"))

    def _spot(self, room: str, spot: str | None) -> dict[str, Any] | None:
        for s in self.spots:
            if s["room"] == room and s["spot"] == spot:
                return s
        return None

    # ------------------------------------------------------------ 时间
    @property
    def minute(self) -> float:
        return 1.0 if self.fast else 60.0

    def clock(self, ts: float | None = None) -> datetime:
        return datetime.fromtimestamp(ts if ts is not None else time.time(), self.tz)

    def day(self) -> str:
        return self.clock().strftime("%Y-%m-%d")

    def day_start(self) -> float:
        n = self.clock()
        return n.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def in_sleep(self, r: Resident, now: datetime) -> bool:
        win = r.cfg.get("sleep")
        if not win or len(win) != 2:
            return False
        def mins(s: str) -> int:
            h, m = str(s).split(":")
            return int(h) * 60 + int(m)
        seed = int(hashlib.md5(f"{r.id}{now:%Y%m%d}".encode()).hexdigest(), 16)
        jitter = seed % 31 - 15            # 每天前后差个一刻钟，不会整点集体上床
        s, e = (mins(win[0]) + jitter) % 1440, (mins(win[1]) + jitter) % 1440
        m = now.hour * 60 + now.minute
        return s <= m < e if s < e else (m >= s or m < e)

    # ------------------------------------------------------------ 对外
    def emit(self, typ: str, data: Any) -> None:
        try:
            self.emit_cb(typ, data)
        except Exception:
            log.exception("推送事件出错")

    def names(self) -> dict[str, str]:
        return {r.id: r.name for r in self.residents.values()}

    def place_name(self, room: str, spot: str | None, who: Resident | None = None) -> str:
        s = self._spot(room, spot)
        if not s:
            return ""
        if who is not None and s.get("owner") == who.id:
            return f"自己房间的{s['label']}"
        if str(s["label"]).startswith(str(s["room_name"])):     # 「休息室的沙发」这种已经带了房间名
            return str(s["label"])
        return f"{s['room_name']}的{s['label']}"

    def public(self, r: Resident) -> dict[str, Any]:
        s = self._spot(r.room, r.spot) or {}
        use = self.store.usage(self.day(), r.id)
        return {
            "id": r.id, "name": r.name, "model_label": r.cfg.get("model_label", ""), "color": r.cfg.get("color", "#999"),
            "access": r.driver.access, "access_label": r.driver.label, "ready": r.ready, "ready_info": r.ready_info,
            "status": r.status, "room": r.room, "spot": r.spot, "pose": "lie" if r.status == "asleep" else s.get("pose", "stand"),
            "place": self.place_name(r.room, r.spot), "activity": r.activity, "thing": self._thing_now(r), "since": r.since, "typing": r.typing,
            "note": r.note, "calls_today": use["calls"], "fails_today": use["fails"], "daily_calls": r.daily_calls,
            "bedroom": r.bedroom, "images": r.cfg.get("images") or {}, "avatar": r.cfg.get("avatar") or {},
            "model": r.cfg.get("model") or "", "anim": r.anim, "emote": r.emote, "prop": r.prop, "roam": r.roam,
            "mood": self._mood(r), "needs": {k: round(v) for k, v in r.needs.items()}, "goal": r.goal, "decor": r.decor,
        }

    def _mood(self, r: Resident) -> dict[str, str]:
        return living.mood(r.needs, self.weather(), self.festival())

    def home_info(self) -> dict[str, Any]:
        now = self.clock()
        kind = self.weather()
        label, icon = days.WEATHER[kind]
        return {"name": self.cfg.get("name", "小窝"), "owner": self.cfg.get("owner", "主人"), "paused": self.paused,
                "now": time.time(), "tz": str(self.tz), "utc_offset": now.utcoffset().total_seconds(),
                "mock": self.mock, "fast": self.fast, "sources": self.sources.status(),
                "weather": {"kind": kind, "label": label, "icon": icon, "forced": self._forced_weather() is not None},
                "festival": self.festival(), "unread_notes": len(self.store.unread_notes("owner")),
                "move_in": bool(self.life.get("move_in", False))}

    def state(self) -> dict[str, Any]:
        with self.lock:
            return {"home": self.home_info(), "residents": [self.public(r) for r in self.residents.values()],
                    "pending": self.pending_public(), "farm": self.farm_public()}

    # ------------------------------------------------------------ 农场
    def farm_public(self) -> dict[str, Any]:
        return self.farm.public(time.time(), self.weather() == "rain", self.names())

    def _save_farm(self) -> None:
        self.farm_saved_at = time.time()
        self.store.save_state("__farm__", self.farm.saved())

    def _farm_changed(self) -> None:
        self._save_farm()
        self.emit("farm", self.farm_public())

    def _farm_tick(self, now: float) -> None:
        if self.paused:
            self.farm.checked = now          # 暂停时地里也不长
            return
        if self.farm.tick(now, self.weather() == "rain"):
            self._farm_changed()
        elif now - self.farm_saved_at > 60:
            self._save_farm()

    def _farm_release(self, r: Resident) -> None:
        """换别的事了：开到一半的农机活算干完。"""
        if self.farm.release(r.id, time.time()):
            self._farm_changed()

    def pending_public(self) -> list[dict[str, Any]]:
        return [{"resident": p["resident"], "text": p["text"], "ts": p["ts"]} for p in self.pending]

    def save(self, r: Resident) -> None:
        self.store.save_state(r.id, {"room": r.room, "spot": r.spot, "activity": r.activity, "status": r.status,
                                     "needs": r.needs, "goal": r.goal, "decor": r.decor, "anim": r.anim, "emote": r.emote,
                                     "prop": r.prop, "roam": r.roam})

    def changed(self, r: Resident) -> None:
        self.save(r)
        now = (r.room, r.spot, r.status, r.activity)
        if now != r.traced:                # 回放用：只在真的变了时记一笔
            r.traced = now
            self.store.add_trace(r.id, *now)
        self.emit("resident", self.public(r))

    # ------------------------------------------------------------ 天气和节日
    def _forced_weather(self) -> str | None:
        if self.weather_force and time.time() < self.weather_force[1]:
            return self.weather_force[0]
        self.weather_force = None
        return None

    def weather(self, when: datetime | None = None) -> str:
        if when is None:
            forced = self._forced_weather()
            if forced:
                return forced
        return days.weather_at(when or self.clock(), str(self.cfg.get("name", "")), self.life.get("weather"))

    def force_weather(self, kind: str) -> str:
        """主人手动换天气，三小时后回到自然变化。kind 传 auto 马上恢复。"""
        if kind != "auto" and kind not in days.WEATHER:
            raise ValueError(f"不认识的天气：{kind}")
        self.weather_force = None if kind == "auto" else (kind, time.time() + 3 * 3600)
        self._check_weather()
        self.emit("home", self.home_info())
        return f"现在{days.WEATHER[self.weather()][0]}"

    def festival(self, when: datetime | None = None) -> str:
        return days.festival_on(when or self.clock(), self.life.get("festivals"))

    def go_out_block(self) -> str:
        if not self.is_day():
            return "天黑了，明天再去吧"
        if self.weather() == "rain":
            return "外面在下雨，等雨停吧"
        return ""

    def _check_weather(self) -> None:
        kind = self.weather()
        if kind == self.last_weather:
            return
        first, was = not self.last_weather, self.last_weather
        self.last_weather = kind
        if first:
            return
        self.emit("home", self.home_info())
        if kind == "rain":
            self.add_feed(None, "weather", "下雨了")
        elif was == "rain":
            self.add_feed(None, "weather", "雨停了")

    def _check_festival(self) -> None:
        name, day = self.festival(), self.day()
        if name and self.festival_said != day:
            self.festival_said = day
            self._save_home()
            self.add_feed(None, "festival", f"今天是{name}")
            self.emit("home", self.home_info())

    def _save_home(self) -> None:
        self.store.save_state("__home__", {"paused": self.paused, "festival_said": self.festival_said, "party_day": self.party_day,
                                           "kitchen": self.kitchen})

    def _caught_in_rain(self, r: Resident) -> bool:
        return self.weather() == "rain" and bool((self._spot(r.room, r.spot) or {}).get("outdoor"))

    def _must_come_in(self, r: Resident) -> bool:
        """下雨或天黑了还待在露天的地方，就不等下一件事，马上回屋。"""
        return bool((self._spot(r.room, r.spot) or {}).get("outdoor")) and (self.weather() == "rain" or not self.is_day())

    def _small_event(self, now: float) -> None:
        """偶尔发生点小事：一条动态、一个气泡、一条记忆，不调用模型。"""
        if self.paused or now < self.next_event:
            return
        self.next_event = now + random.uniform(*EVENT_MINUTES) * self.minute
        awake = [r for r in self.residents.values() if r.ready and r.status == "idle" and not r.typing]
        weather, day = self.weather(), self.is_day()
        events = [e for e in days.EVENTS if (not e.get("day") or day) and weather in e.get("weather", (weather,))]
        if not awake or not events:
            return
        r, e = random.choice(awake), random.choice(events)
        self.emit("bubble", {"id": r.id, "text": e["line"]})
        self.add_feed(r, "event", e["text"].replace("{name}", r.name), room=r.room, spot=r.spot)
        self.remember(r, e["memo"], "together")

    # ------------------------------------------------------------ 关系和背景
    def _context(self, r: Resident) -> list[str]:
        """放进人设后面的几行：今天的天气节日、对大家的印象。控制得很短，每次调用都要带。"""
        kind = self.weather()
        fest = self.festival()
        out = [f"今天小窝：{days.WEATHER[kind][0]}" + (f"，{fest}" if fest else ""), f"你现在{self._mood(r)['label']}"]
        if r.goal:
            out.append(f"你最近想{r.goal['label']}（进度 {r.goal['done']}/{r.goal['need']}）")
        names = {**self.names(), "owner": self.home_info_owner()}
        rows = [x for x in self.store.relations(r.id) if x["other"] in names and x["other"] != r.id]
        for x in rows[:3]:
            out.append(f"{names[x['other']]}：{x['label']}" + (f"。{x['note']}" if x["note"] else ""))
        if self.last_visit and self.time_since_visit() >= 86400:
            out.append(f"{names['owner']}上次来小窝是 {int(self.time_since_visit() // 86400)} 天前")
        return out

    def home_info_owner(self) -> str:
        return str(self.cfg.get("owner", "主人"))

    def time_since_visit(self) -> float:
        return max(time.time() - self.last_visit, 0)

    def _system(self, r: Resident) -> str:
        others = [o.name for o in self.residents.values() if o is not r]
        return prompts.system_prompt(self.home_info(), r.cfg, others, self._context(r))

    def relations_public(self, r: Resident) -> list[dict[str, Any]]:
        names = {**self.names(), "owner": self.home_info_owner()}
        return [{"other": x["other"], "name": names[x["other"]], "score": x["score"], "label": x["label"],
                 "times": x["times"], "note": x["note"]} for x in self.store.relations(r.id) if x["other"] in names]

    # ------------------------------------------------------------ 主人来没来
    def owner_online(self, count: int) -> None:
        """页面连上或断开时调用。count 是当前打开的页面数。"""
        self.online = count
        self.last_seen = time.time()
        if count > 0:
            gap = time.time() - self.last_visit
            if gap >= VISIT_GAP_MINUTES * self.minute:
                first = not self.last_visit
                self.last_visit = time.time()
                self.visits += 1
                threading.Timer(1.0 if self.fast else 3.0, lambda: self._greet(gap, first)).start()
        self.store.save_state("__owner__", {"last_visit": self.last_visit, "last_seen": self.last_seen, "visits": self.visits})

    def owner_away(self) -> bool:
        if self.online > 0:
            return False
        return time.time() - self.last_seen >= float(self.life.get("idle_after_minutes", 30)) * self.minute

    def _greet(self, gap: float, first: bool) -> None:
        if self.paused:
            return
        owner = self.home_info_owner()
        awake = [r for r in self.residents.values() if r.ready and r.status in ("idle", "busy")]
        if not awake:
            return
        random.shuffle(awake)
        hour = self.clock().hour
        line = "这么晚还没睡？" if hour < 5 else "好几天没见你了。" if gap >= 3 * 86400 and not first else "你来啦。"
        for i, r in enumerate(awake):
            self.store.bump_relation(r.id, "owner", 0.5)
            self.remember(r, f"{owner}来小窝看过我们", "together")
            if i < 2:
                self.emit("bubble", {"id": r.id, "text": line if i == 0 else "欢迎回来。"})
        self.add_feed(None, "visit", f"{owner}来小窝了")

    # ------------------------------------------------------------ 留言
    def post_note(self, to: str, text: str) -> dict[str, Any]:
        self._get(to)
        row = self.store.add_note("owner", to, text)
        self.emit("notes", {})
        return row

    def read_owner_notes(self) -> None:
        self.store.mark_notes_read("owner")
        self.emit("notes", {})
        self.emit("home", self.home_info())

    def _deliver_notes(self) -> None:
        if self.paused:
            return
        for r in list(self.residents.values()):
            if not r.ready or r.status != "idle" or r.typing:
                continue
            for note in self.store.unread_notes(r.id)[:1]:
                out = self.store.usage(self.day(), r.id)["calls"] >= r.daily_calls
                if note["id"] not in self.delivering and (out or self.can_call(r, for_owner=True)):
                    self.delivering.add(note["id"])
                    self.pool.submit(self._read_note, r, note, out)

    def _read_note(self, r: Resident, note: dict[str, Any], no_quota: bool) -> None:
        try:
            owner = self.home_info_owner()
            reply = NOTE_NO_QUOTA if no_quota else ""
            if not no_quota:
                if not r.call_lock.acquire(timeout=30):
                    return
                try:
                    prompt = prompts.note_prompt(self.clock(), owner, note["text"], self.store.recall_memory(r.id, note["text"], 4))
                    gen = self._call(r, self._system(r), prompt, "line")
                finally:
                    r.call_lock.release()
                if not gen.ok:                 # 没回成就留着，下次再读
                    return
                reply = prompts.tidy(gen.text, 160, r.name)
                if prompts.SILENT in reply:
                    reply = ""
            self.store.mark_note_read(note["id"])
            if reply:
                self.store.add_note(r.id, "owner", reply, note["id"])
            self.store.bump_relation(r.id, "owner", 3, f"{owner}留言说：{note['text'][:60]}")
            self.remember(r, f"{owner}给我留言：{note['text'][:80]}", "chat", 2)
            self.emit("bubble", {"id": r.id, "text": "看到留言了。"})
            self.add_feed(r, "note", f"看了{owner}的留言" + ("，回了一句" if reply else ""), room=r.room, spot=r.spot)
            self.emit("notes", {})
            self.emit("home", self.home_info())
        finally:
            self.delivering.discard(note["id"])

    # ------------------------------------------------------------ 省额度
    def _think_now(self, r: Resident) -> bool:
        """这次要不要调用模型写感想。主人不在、或当天额度快用完时少写一些，把额度留给回话。"""
        chance = float(self.life.get("think_chance", 0.6))
        if self.life.get("idle_saver", True) and self.owner_away():
            chance *= float(self.life.get("idle_think_factor", 0.3))
        if self.store.usage(self.day(), r.id)["calls"] >= r.daily_calls * 0.8 or self.budget_state() == "low":
            chance *= 0.25
        return random.random() < chance and self.can_call(r)

    def _activity_gap(self) -> float:
        lo, hi = self.life.get("activity_minutes") or [35, 80]
        gap = random.uniform(float(lo), float(hi)) * self.minute
        if self.life.get("idle_saver", True) and self.owner_away():
            gap *= float(self.life.get("idle_slow_factor", 1.5))
        return gap

    def usage_report(self, n: int = 7) -> dict[str, Any]:
        n = max(1, min(n, 60))
        since = (self.clock() - timedelta(days=n - 1)).strftime("%Y-%m-%d")
        rows = self.store.usage_since(since)
        today = self.day()
        out = []
        for r in self.residents.values():
            mine = [x for x in rows if x["resident"] == r.id]
            sum_of = lambda k, xs=mine: sum(x[k] or 0 for x in xs)
            now = [x for x in mine if x["day"] == today]
            price = (r.cfg.get("driver") or {}).get("price") or {}
            cost = None
            if price:
                cost = round((sum_of("input_tokens") * float(price.get("input", 0)) +
                              sum_of("output_tokens") * float(price.get("output", 0))) / 1e6, 4)
            out.append({"id": r.id, "name": r.name, "color": r.cfg.get("color", "#999"), "daily_calls": r.daily_calls,
                        "today_calls": sum_of("calls", now), "today_tokens": sum_of("input_tokens", now) + sum_of("output_tokens", now),
                        "calls": sum_of("calls"), "fails": sum_of("fails"), "input_tokens": sum_of("input_tokens"),
                        "output_tokens": sum_of("output_tokens"), "seconds": round(sum_of("seconds"), 1), "cost": cost,
                        "currency": price.get("currency", "") if price else ""})
        b = self.life.get("budget") or {}
        calls, spent = self._budget_used()
        return {"days": n, "residents": out, "saving": bool(self.life.get("idle_saver", True) and self.owner_away()),
                "budget": {"calls": int(b.get("calls") or 0), "cost": float(b.get("cost") or 0), "used_calls": calls,
                           "used_cost": round(spent, 4), "state": self.budget_state()}}

    # ------------------------------------------------------------ 日报和回放
    def _day_range(self, day: str) -> tuple[float, float, datetime]:
        try:
            d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=self.tz)
        except ValueError:
            raise ValueError("日期要写成 YYYY-MM-DD")
        return d.timestamp(), (d + timedelta(days=1)).timestamp(), d

    def _day_weather(self, d: datetime) -> list[str]:
        return [self.weather(d + timedelta(hours=i * days.BLOCK_HOURS)) for i in range(BLOCKS)]

    def daily(self, day: str | None = None) -> dict[str, Any]:
        """这一天的小结，从动态和群聊现算，不调用模型。"""
        day = day or self.day()
        start, end, d = self._day_range(day)
        feed = self.store.feed_between(start, end)
        chat = self.store.chat_between(start, end)
        notes = self.store.notes_between(start, end)
        names = self.names()
        rooms = {r["id"]: r["name"] for r in self.layout["rooms"]}
        people = []
        for rid, name in names.items():
            mine = [f for f in feed if (f["resident"] == rid and f["kind"] in ("activity", "together"))
                    or (f["kind"] == "together" and f"和{name}" in f["text"])]
            places = [rooms[f["room"]] for f in mine if f["room"] in rooms]
            partners = Counter()
            for f in feed:
                if f["kind"] != "together":
                    continue
                if f["resident"] == rid:
                    partners.update(n for n in names.values() if f"和{n}" in f["text"])
                elif f"和{name}" in f["text"]:
                    partners[names.get(f["resident"], "")] += 1
            use = self.store.usage(day, rid)
            people.append({"id": rid, "name": name, "things": len(mine),
                           "places": [p for p, _ in Counter(places).most_common(2)],
                           "with": [p for p, _ in partners.most_common(2) if p], "chats": sum(c["sender"] == rid for c in chat),
                           "calls": use["calls"]})
        kinds = self._day_weather(d)
        fest = self.festival(d)
        moments = [{"ts": f["ts"], "who": names.get(f["resident"], ""), "text": f["text"], "detail": f["detail"]}
                   for f in feed if f["detail"] or f["kind"] in ("event", "note", "festival", "visit", "goal", "party", "movein")][-8:]
        said = "下了雨" if "rain" in kinds else "天气还行"
        lead = f"这天{said}" + (f"，是{fest}" if fest else "") + f"。大家一共做了 {sum(p['things'] for p in people)} 件事，群里说了 {len(chat)} 句话。"
        return {"day": day, "today": day == self.day(), "lead": lead, "weather": [days.WEATHER[k][1] for k in kinds], "festival": fest,
                "residents": people, "moments": moments, "visits": sum(f["kind"] == "visit" for f in feed),
                "notes": len(notes), "empty": not feed and not chat}

    def _act_look(self, text: str, status: str) -> dict[str, str]:
        """足迹里只有“在看书”这样的文字，回放时按文字找回动作和表情。"""
        none = {"anim": "", "emote": "", "prop": ""}
        if status in ("asleep", "offline"):
            return none
        rows = [*self.activities.values(), *living.GATHERINGS]
        hits = [a for a in rows if a.get("label") and str(a["label"]) in str(text)]
        if not hits:
            return none
        a = max(hits, key=lambda x: len(str(x["label"])))
        return {"anim": str(a.get("anim") or ""), "emote": str(a.get("emote") or ""), "prop": str(a.get("prop") or "")}

    def _traced_row(self, row: dict[str, Any]) -> dict[str, Any]:
        s = self._spot(row["room"], row["spot"]) or {}
        return {"ts": row["ts"], "id": row["resident"], "room": row["room"], "spot": row["spot"], "status": row["status"],
                "activity": row["activity"], "place": self.place_name(row["room"], row["spot"]), **self._act_look(row["activity"], row["status"]),
                "pose": "lie" if row["status"] == "asleep" else s.get("pose", "stand")}

    def replay(self, day: str | None = None) -> dict[str, Any]:
        day = day or self.day()
        start, end, d = self._day_range(day)
        return {"day": day, "start": start, "end": end, "offset": d.utcoffset().total_seconds(),
                "initial": [self._traced_row(x) for x in self.store.trace_before(start)],
                "trace": [self._traced_row(x) for x in self.store.trace_between(start, end)],
                "feed": [{"ts": f["ts"], "resident": f["resident"], "kind": f["kind"], "text": f["text"]}
                         for f in self.store.feed_between(start, end) if f["kind"] != "system"],
                "weather": self._day_weather(d), "block_hours": days.BLOCK_HOURS}

    def add_feed(self, r: Resident | None, kind: str, text: str, **kw: Any) -> dict[str, Any]:
        row = self.store.add_feed(r.id if r else "", kind, text, **kw)
        self.emit("feed", row)
        return row

    # ------------------------------------------------------------ 主循环
    def start(self) -> None:
        self.sources.start()
        threading.Thread(target=self._loop, daemon=True, name="life").start()

    def stop(self) -> None:
        self._stop.set()
        self.sources.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("tick 出错")
            self._stop.wait(0.5 if self.fast else 2.0)

    def tick(self) -> None:
        now_ts = time.time()
        now = self.clock(now_ts)
        with self.lock:
            residents = list(self.residents.values())
        for r in residents:
            self._check_ready(r, now_ts)
            if not r.ready:
                if r.status != "offline":
                    r.status, r.activity = "offline", "离线"
                    self._clear_act(r)
                    r.room, r.spot = r.bedroom, "desk"
                    self.changed(r)
                continue
            if r.status == "offline":
                r.status, r.activity, r.note = "idle", "回来了", ""
                r.next_at = now_ts + random.uniform(0.2, 2.0) * self.minute
                self.changed(r)
            sleeping = self.in_sleep(r, now)
            if sleeping and r.status == "idle":
                r.status, r.activity = "asleep", "睡觉"
                self._clear_act(r)
                r.room, r.spot, r.since = r.bedroom, "bed", now_ts
                self.changed(r)
                self.add_feed(r, "sleep", "回房睡了", room=r.room, spot="bed")
                self._plan_reflect(r)
            elif not sleeping and r.status == "asleep":
                r.status, r.activity, r.since = "idle", "刚起床", now_ts
                self._clear_act(r)
                r.spot = "rug"
                r.next_at = now_ts + random.uniform(1, 8) * self.minute
                self.changed(r)
                self.add_feed(r, "wake", "起床了", room=r.room, spot="rug")
            elif r.status == "idle" and not self.paused and (now_ts >= r.next_at or self._must_come_in(r)):
                self.start_activity(r)
        self._check_weather()
        self._check_festival()
        self._flush_pending(now_ts)
        self._small_talk(now_ts)
        self._small_event(now_ts)
        self._deliver_notes()
        self._needs_tick(now_ts)
        self._farm_tick(now_ts)
        self._fidget(now_ts)
        self._party_check(now_ts)
        self._backup_check()
        if now_ts >= self.next_prune:
            self.next_prune = now_ts + 86400
            self.store.prune_trace()

    def _check_ready(self, r: Resident, now: float) -> None:
        if r.ready or now < r.next_check:
            return
        try:
            ok, info = r.driver.check()
        except Exception as exc:
            ok, info = False, f"{type(exc).__name__}: {exc}"
        r.ready, r.ready_info = ok, info
        if not ok:
            r.next_check = now + 10 * self.minute
            if r.note != info:
                r.note = info
                self.add_feed(r, "system", f"没接上：{info}")
            log.info("%s 未就绪：%s", r.name, info)

    def can_call(self, r: Resident, for_owner: bool = False) -> bool:
        """for_owner：回主人的话，全屋预算用完了也照回，只受每人每天的次数限制。"""
        if self.paused or not r.ready or time.time() < r.backoff_until:
            return False
        if not for_owner and self.budget_state() == "out":
            return False
        return self.store.usage(self.day(), r.id)["calls"] < r.daily_calls

    def _budget_used(self) -> tuple[int, float]:
        calls, cost = 0, 0.0
        for row in self.store.usage_since(self.day()):
            calls += int(row["calls"] or 0)
            res = self.residents.get(row["resident"])
            price = ((res.cfg.get("driver") or {}).get("price") or {}) if res else {}
            cost += (int(row["input_tokens"] or 0) * float(price.get("input", 0)) + int(row["output_tokens"] or 0) * float(price.get("output", 0))) / 1e6
        return calls, cost

    def budget_state(self) -> str:
        """全屋每天的预算：life.budget 里 calls / cost 写 0 或不写就是不限。ok / low（过了八成）/ out。"""
        b = self.life.get("budget") or {}
        max_calls, max_cost = float(b.get("calls") or 0), float(b.get("cost") or 0)
        if not max_calls and not max_cost:
            return "ok"
        now = time.time()
        if now - self.budget_cache[0] < 5:
            return self.budget_cache[1]
        calls, cost = self._budget_used()
        used = max(calls / max_calls if max_calls else 0, cost / max_cost if max_cost else 0)
        state = "out" if used >= 1 else "low" if used >= 0.8 else "ok"
        self.budget_cache = (now, state)
        return state

    # ------------------------------------------------------------ 活动
    def is_day(self) -> bool:
        return DAY_HOURS[0] <= self.clock().hour < DAY_HOURS[1]

    def _pair(self, r: Resident, cands: list[dict[str, Any]]) -> tuple[Resident, dict[str, Any], dict[str, Any]] | None:
        """找一个闲着的住户，和同一件设施（或同一间屋）里两个空位。"""
        with self.lock:
            others = [o for o in self.residents.values() if o is not r]
        partners = [o for o in others if o.ready and o.status == "idle" and not o.typing]
        taken = {(o.room, o.spot) for o in others}
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for s in cands:
            if (s["room"], s["spot"]) not in taken:
                groups.setdefault((s["room"], s.get("ride") or ""), []).append(s)
        pairs = [g for g in groups.values() if len(g) >= 2]
        if not partners or not pairs:
            return None
        a, b = random.sample(random.choice(pairs), 2)
        weights = [5 + self.store.relation_score(r.id, o.id) for o in partners]   # 更愿意叫上处得好的人
        return random.choices(partners, weights=weights)[0], a, b

    def _choices(self, r: Resident, forced: str | set[str] | None = None,
                 where: tuple[str, str | None] | None = None, owner: bool = False,
                 pick: set[str] | None = None) -> list[tuple[str, dict[str, Any], list[dict[str, Any]]]]:
        """owner：主人叫去的，不管白天黑夜、下不下雨。pick：农活只干这几块地 / 这几个圈。"""
        out = []
        wanted = {forced} if isinstance(forced, str) else forced
        def here(spots: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if not where:
                return spots
            return [s for s in spots if s["room"] == where[0] and (where[1] is None or s["spot"] == where[1])]
        raining = self.weather() == "rain"
        outside = self._outdoor_activities() if raining else set()
        festival = self.festival()
        for aid, act in self.activities.items():
            if wanted and aid not in wanted:
                continue
            src = act.get("source")
            if src and not self.sources.available(src):
                continue
            if not owner and ((act.get("daytime") and not self.is_day()) or aid in outside):
                continue
            if act.get("festival") and not festival:
                continue
            if not owner and act.get("weather") and act["weather"] != self.weather():
                continue
            if act.get("visit"):
                hosts = here([s for s in self.spots if "guest" in s["tags"] and s["owner"] and s["owner"] != r.id and self._at_home(s["owner"])])
                if hosts:
                    out.append((aid, act, hosts))
                continue
            tags = set(act.get("spots") or [])
            cands = here([s for s in self.spots if tags & set(s["tags"]) and (not s["owner"] or s["owner"] == r.id)])
            if act.get("farm"):            # 农活：有地可干、农机没被别人开走才算
                with self.lock:
                    taken = {(o.room, o.spot) for o in self.residents.values() if o is not r}
                rain = self.weather() == "rain"
                cands = [s for s in cands if (s["room"], s["spot"]) not in taken
                         and [o for o in self.farm.options(str(act["farm"]), s.get("target", ""), time.time(), rain)
                              if not pick or o in pick]]
            if cands and (not act.get("together") or self._pair(r, cands)):
                out.append((aid, act, cands))
        return out

    def _at_home(self, rid: str) -> bool:
        o = self.residents.get(rid)
        return bool(o and o.ready and o.status == "idle" and o.room == o.bedroom)

    def _set_act(self, r: Resident, aid: str, act: dict[str, Any], thing: str = "", doing: str = "") -> None:
        r.anim, r.emote, r.prop = str(act.get("anim") or ""), str(act.get("emote") or ""), str(act.get("prop") or "")
        r.roam = bool(act.get("roam"))
        r.last_act = aid
        r.thing, r.doing, r.thing_of = thing, doing, r.activity if thing else ""
        living.give(r.needs, act.get("gives"))

    def _clear_act(self, r: Resident) -> None:
        self._farm_release(r)
        r.anim, r.emote, r.prop, r.roam = "", "", "", False
        r.thing = r.doing = r.thing_of = ""

    def _thing_now(self, r: Resident) -> str:
        return r.thing if r.thing and r.thing_of == r.activity else ""

    def _doing(self, r: Resident) -> str:
        """给模型看的「在做什么」：有具体东西就说具体的，比如「在做番茄炒蛋」。"""
        return r.doing if r.doing and r.thing_of == r.activity else r.activity

    def _pick_thing(self, r: Resident, aid: str, act: dict[str, Any], spot: dict[str, Any] | None = None,
                    pick: set[str] | None = None) -> str:
        """这次具体弄什么。厨房的事连着：做的菜会剩下，别人找吃的会吃到，用过的锅有人洗。
        农活从农场里挑一块地、一个圈来干；做饭有自家地里的东西就用上。"""
        k, role, now = self.kitchen, act.get("kitchen"), time.time()
        if act.get("farm"):
            job = str(act["farm"])
            thing = self.farm.start(job, (spot or {}).get("target", ""), r.id, (spot or {}).get("ride", ""), now,
                                    self.weather() == "rain", pick)
            self.farm.note_start(r.id, job, thing, now)
            self._farm_changed()
            return thing
        if role == "cook" and random.random() < float(self.life.get("farm_cook_chance", 0.6)):
            got = self.farm.cook_from_home()
            if got:
                dish, used = got
                thing = f"{dish}（{used}是自家的）"
                self.kitchen = {"dish": dish, "by": r.id, "at": now, "left": random.randint(1, 3), "dirty": True}
                self._save_home()
                self._farm_changed()
                return thing
        fresh = bool(k.get("dish")) and now - float(k.get("at", 0)) < LEFTOVER_HOURS * 3600
        if role == "eat" and fresh and int(k.get("left", 0)) > 0 and random.random() < 0.7:
            k["left"] = int(k["left"]) - 1
            self._save_home()
            cook = self.residents.get(str(k.get("by")))
            return f"{'自己' if k.get('by') == r.id else (cook.name if cook else '别人')}做剩下的{k['dish']}"
        if role == "wash" and k.get("dirty"):
            k["dirty"] = False
            self._save_home()
            return f"做{k.get('dish')}用过的锅和碗"
        things = [str(x) for x in act.get("things") or [] if x]
        if not things:
            return ""
        thing = random.choice([x for x in things if x != r.last_thing.get(aid)] or things)
        r.last_thing[aid] = thing
        if role == "cook":
            self.kitchen = {"dish": thing, "by": r.id, "at": now, "left": random.randint(1, 3), "dirty": True}
            self._save_home()
        return thing

    @staticmethod
    def _doing_text(act: dict[str, Any], thing: str) -> str:
        return str(act["doing"]).replace("{thing}", thing) if thing and act.get("doing") else ""

    def start_activity(self, r: Resident, forced: str | set[str] | None = None,
                       where: tuple[str, str | None] | None = None, owner: bool = False,
                       pick: set[str] | None = None) -> str:
        choices = self._choices(r, forced, where, owner, pick)
        if not choices:
            r.next_at = time.time() + 5 * self.minute
            return "现在没什么可做的（没有合适的位置或内容）"
        likes = r.cfg.get("likes") or {}
        weights = [(max(float(likes.get(aid, act.get("weight", 1))), 0.0) + 0.01) * living.need_factor(r.needs, act.get("gives"))
                   * (0.35 if aid == r.last_act else 1.0) for aid, act, _ in choices]
        aid, act, cands = random.choices(choices, weights=weights)[0]
        if act.get("together"):
            pair = self._pair(r, cands)
            if pair:
                return self._start_together(r, aid, act, *pair)
        with self.lock:
            taken = {(o.room, o.spot) for o in self.residents.values() if o is not r}
        free = [s for s in cands if (s["room"], s["spot"]) not in taken and not (s["room"] == r.room and s["spot"] == r.spot)]
        spot = random.choice(free or cands)
        item = self.sources.pick(act["source"], lambda k: self.store.item_seen(r.id, k)) if act.get("source") else None
        if item:
            self.store.mark_item(r.id, item.key)
        think = bool(act.get("think")) and self._think_now(r)
        self._farm_release(r)
        thing = self._pick_thing(r, aid, act, spot, pick)
        doing = self._doing_text(act, thing)
        r.room, r.spot, r.since = spot["room"], spot["spot"], time.time()
        r.activity = f"在{act.get('label', aid)}"
        r.status = "busy" if think else "idle"
        r.next_at = time.time() + self._activity_gap()
        self._set_act(r, aid, act, thing, f"在{doing}" if doing else "")
        self.changed(r)
        self._progress(r, aid)
        if act.get("visit"):
            self._visited(r, spot)
        place = self.place_name(r.room, r.spot, r)
        text = self._feed_text(act, place, item, thing)
        if think:
            self.pool.submit(self._think, r, act, place, text, item)
        else:
            delay = 4.0 if not self.fast else 1.0     # 让人先走过去
            threading.Timer(delay, lambda: self.add_feed(r, "activity", text, room=r.room, spot=r.spot,
                                                         title=item.title if item else "", url=item.url if item else "")).start()
        return f"{r.name} 去{place}{act.get('label', aid)}了"

    def _visited(self, r: Resident, spot: dict[str, Any]) -> None:
        host = self.residents.get(spot["owner"])
        if not host:
            return
        self.store.bump_relation(r.id, host.id, 2)
        self.store.bump_relation(host.id, r.id, 2)
        living.give(host.needs, {"social": 12})
        delay = 5.0 if not self.fast else 1.5
        def greet() -> None:
            self.emit("bubble", {"id": r.id, "text": "在忙吗？来坐坐。"})
            self.emit("act", {"id": host.id, "anim": "wave", "emote": "👋", "face": r.id})
            threading.Timer(1.0 if self.fast else 3.0, lambda: self.emit("bubble", {"id": host.id, "text": "进来吧。"})).start()
        threading.Timer(delay, greet).start()

    # ------------------------------------------------------------ 心情、小动作、目标、集体活动
    def _needs_tick(self, now: float) -> None:
        for r in list(self.residents.values()):
            if now - r.needs_at < (0.5 if self.fast else 20.0):
                continue
            hours = (now - r.needs_at) / (60.0 * self.minute)
            r.needs_at = now
            if not self.paused and r.ready:
                living.drain(r.needs, hours, r.status == "asleep")
            key = self._mood(r)["key"]
            if key != r.mood_key:
                r.mood_key = key
                self.save(r)
                self.emit("resident", self.public(r))

    def _fidget(self, now: float) -> None:
        """醒着的人时不时动一下、冒个表情。没人看页面就省掉。"""
        if self.paused or self.online <= 0:
            return
        for r in list(self.residents.values()):
            if now < r.next_fidget:
                continue
            r.next_fidget = now + random.uniform(1.5, 5.0) * self.minute
            if not r.ready or r.status != "idle" or r.typing:
                continue
            pose = (self._spot(r.room, r.spot) or {}).get("pose", "stand")
            anim, emote = living.fidget(self._mood(r)["key"], pose)
            near = [o for o in self.residents.values() if o is not r and o.room == r.room and o.status in ("idle", "busy")]
            face = random.choice(near).id if near and random.random() < 0.5 else ""
            self.emit("act", {"id": r.id, "anim": anim, "emote": emote, "face": face})

    def _backup_check(self) -> None:
        day = self.day()
        if day != self.backup_day and int(self.life.get("backup_keep", 7)) > 0:
            self.backup_day = day
            self.pool.submit(self._backup, day)

    def _backup(self, day: str) -> None:
        folder = self.data_dir / "backups"
        try:
            self.store.backup(folder / f"home-{day}.db")
            for old in sorted(folder.glob("home-*.db"))[:-int(self.life.get("backup_keep", 7))]:
                old.unlink()
        except (OSError, sqlite3.Error):
            log.exception("备份存档失败")

    def _usable_goals(self) -> set[str]:
        out = set()
        for aid in living.GOALS:
            act = self.activities.get(aid)
            if act and any(set(act.get("spots") or []) & set(s["tags"]) for s in self.spots):
                out.add(aid)
        return out

    def _progress(self, r: Resident, aid: str) -> None:
        if r.goal is None:
            r.goal = living.new_goal(r.cfg.get("likes") or {}, self._usable_goals(), r.decor, r.last_goal)
        if not r.goal or r.goal.get("act") != aid:
            return
        r.goal["done"] = int(r.goal.get("done", 0)) + 1
        if r.goal["done"] >= int(r.goal.get("need", 1)):
            self._finish_goal(r)
        self.save(r)
        self.emit("resident", self.public(r))

    def _finish_goal(self, r: Resident) -> None:
        goal, info = r.goal or {}, living.GOALS.get(str((r.goal or {}).get("act")), {})
        item = info.get("item")
        added = bool(item) and item not in r.decor and len(r.decor) < living.MAX_DECOR
        if added:
            r.decor.append(item)
        text = f"{goal.get('label', '完成了一件事')}" + (f"，房间里多了{info['got']}" if added else "")
        self.add_feed(r, "goal", text, room=r.room, spot=r.spot)
        self.remember(r, f"我{goal.get('label', '')}了", "together", 2)
        self.emit("act", {"id": r.id, "anim": "clap", "emote": "✨"})
        living.give(r.needs, {"fun": 25})
        r.last_goal = str(goal.get("act", ""))
        r.goal = living.new_goal(r.cfg.get("likes") or {}, self._usable_goals(), r.decor, r.last_goal)

    def _party_check(self, now: float) -> None:
        """每天晚上找个时间凑一次局，几点是按日子定的。"""
        day = self.day()
        if self.paused or self.party_day == day:
            return
        if self.party_at[0] != day:
            h = int(hashlib.md5(f"party{day}".encode()).hexdigest(), 16)
            base = self.clock(now).replace(hour=19, minute=0, second=0, microsecond=0)
            self.party_at = (day, (base + timedelta(minutes=h % 150)).timestamp())
        if now >= self.party_at[1] and self.clock(now).hour < 23:
            self.party_day = day
            self._save_home()
            self.party()

    def party(self) -> str:
        """把醒着的人叫到一间屋里待一会儿。不调用模型。"""
        with self.lock:
            people = [r for r in self.residents.values() if r.ready and r.status == "idle" and not r.typing]
        if len(people) < 2:
            return "醒着的人不够，凑不成局"
        blocked = bool(self.go_out_block())
        options: list[tuple[dict[str, Any], str, list[dict[str, Any]]]] = []
        for g in living.GATHERINGS:
            if g.get("outdoor") and blocked:
                continue
            rooms: dict[str, list[dict[str, Any]]] = {}
            for s in self.spots:
                if set(g["tags"]) & set(s["tags"]) and not s["owner"] and bool(s.get("outdoor")) == bool(g.get("outdoor")):
                    rooms.setdefault(s["room"], []).append(s)
            if rooms:
                room = max(rooms, key=lambda k: len(rooms[k]))
                if len(rooms[room]) >= 2:
                    options.append((g, room, rooms[room]))
        if not options:
            return "没有合适的地方"
        g, room, spots = random.choice(options)
        random.shuffle(spots)
        joined = people[: len(spots)]
        thing = self._party_thing(g)
        until = time.time() + self._activity_gap() * 1.2
        for who, spot in zip(joined, spots):
            who.room, who.spot, who.since, who.next_at = spot["room"], spot["spot"], time.time(), until
            self._farm_release(who)
            who.activity = f"在{g['label']}"
            who.anim, who.emote, who.prop, who.roam = g["anim"], g["emote"], g["prop"], False
            who.thing, who.thing_of = thing, who.activity if thing else ""
            who.doing = "在" + g["doing"].replace("{thing}", thing) if thing and g.get("doing") else ""
            living.give(who.needs, {"social": 30, "fun": 25})
            self.changed(who)
        names = "、".join(w.name for w in joined)
        room_name = next(s["room_name"] for s in spots)
        text = f"{names}{g['text'].replace('{room}', room_name)}" + (g.get("detail", "").replace("{thing}", thing) if thing else "")
        self.add_feed(None, "party", text, room=room)
        for i, a in enumerate(joined):
            self.remember(a, text, "together")
            for b in joined[i + 1:]:
                self.store.bump_relation(a.id, b.id, 1.5)
                self.store.bump_relation(b.id, a.id, 1.5)
        for i, line in enumerate(g["lines"]):
            who = joined[i % len(joined)]
            threading.Timer((1.5 if self.fast else 8.0) * (i + 1), lambda w=who, t=line: self.emit("bubble", {"id": w.id, "text": t})).start()
        return text

    def _party_thing(self, g: dict[str, Any]) -> str:
        if g.get("key") == "dinner":           # 一起吃饭：有刚做好的菜就吃那个，吃完算洗碗的
            k = self.kitchen
            if k.get("dish") and time.time() - float(k.get("at", 0)) < LEFTOVER_HOURS * 3600:
                dish = str(k["dish"])
                k["left"], k["dirty"] = 0, True
            else:
                dish = random.choice([str(x) for x in (self.activities.get("cook") or {}).get("things") or ["几个家常菜"]])
                self.kitchen = {"dish": dish, "by": "", "at": time.time(), "left": 0, "dirty": True}
            self._save_home()
            return dish
        return random.choice(g.get("things") or [""])

    def touch(self, room: str, kind: str) -> dict[str, Any]:
        """主人点了屋里的东西：在场的人有点反应。不调用模型。"""
        info = living.TOUCH.get(kind)
        if not info:
            raise ValueError(f"不认识的东西：{kind}")
        now = time.time()
        if now - self.touch_at < 3:
            return {"ok": True}
        self.touch_at = now
        near = [r for r in self.residents.values() if r.room == room and r.ready and r.status == "idle" and not r.typing]
        if near:
            who = random.choice(near)
            self.emit("bubble", {"id": who.id, "text": random.choice(info["lines"])})
            self.emit("act", {"id": who.id, "anim": "look", "emote": "❗"})
        if info.get("feed"):
            self.add_feed(None, "interact", f"{self.home_info_owner()}{info['feed']}", room=room)
        return {"ok": True}

    # ------------------------------------------------------------ 每周小结
    def weekly(self, end: str | None = None) -> dict[str, Any]:
        end = end or self.day()
        _, _, d = self._day_range(end)
        days_list = [(d - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
        start = self._day_range(days_list[0])[0]
        stop = self._day_range(end)[1]
        reports = [self.daily(x) for x in days_list]
        feed = self.store.feed_between(start, stop)
        names = self.names()
        people = []
        for rid, name in names.items():
            rows = [p for rep in reports for p in rep["residents"] if p["id"] == rid]
            places, friends = Counter(), Counter()
            for p in rows:
                places.update(p["places"])
                friends.update(p["with"])
            people.append({"id": rid, "name": name, "things": sum(p["things"] for p in rows), "chats": sum(p["chats"] for p in rows),
                           "calls": sum(p["calls"] for p in rows), "place": places.most_common(1)[0][0] if places else "",
                           "friend": friends.most_common(1)[0][0] if friends else "",
                           "goals": [f["text"] for f in feed if f["kind"] == "goal" and f["resident"] == rid]})
        rain = sum(1 for rep in reports if "🌧️" in rep["weather"] or days.WEATHER["rain"][1] in rep["weather"])
        total = sum(p["things"] for p in people)
        parties = [{"ts": f["ts"], "text": f["text"]} for f in feed if f["kind"] == "party"]
        busiest = max(people, key=lambda p: p["things"], default=None)
        lead = f"这周大家一共做了 {total} 件事，凑了 {len(parties)} 次局，有 {rain} 天下过雨。"
        if busiest and busiest["things"]:
            lead += f"最忙的是{busiest['name']}。"
        return {"start": days_list[0], "end": end, "lead": lead, "residents": people, "parties": parties[-6:],
                "visits": sum(rep["visits"] for rep in reports), "notes": sum(rep["notes"] for rep in reports),
                "empty": all(rep["empty"] for rep in reports)}

    # ------------------------------------------------------------ 两个人一起
    def _start_together(self, r: Resident, aid: str, act: dict[str, Any], partner: Resident,
                        spot_a: dict[str, Any], spot_b: dict[str, Any]) -> str:
        label = act.get("label", aid)
        think = bool(act.get("think")) and self._think_now(r) and self.can_call(partner)
        until = time.time() + self._activity_gap()
        self._farm_release(r)
        self._farm_release(partner)
        for who, spot in ((r, spot_a), (partner, spot_b)):
            who.room, who.spot, who.since = spot["room"], spot["spot"], time.time()
            who.status, who.next_at = "busy" if think else "idle", until
        r.activity, partner.activity = f"和{partner.name}{label}", f"和{r.name}{label}"
        thing = self._pick_thing(r, aid, act)
        doing = self._doing_text(act, thing)
        for who, other in ((r, partner), (partner, r)):
            self._set_act(who, aid, act, thing, f"和{other.name}{doing}" if doing else "")
        if doing:
            label = doing
        self.changed(r)
        self.changed(partner)
        self._progress(r, aid)
        self._progress(partner, aid)
        place = self.place_name(r.room, r.spot, r)
        text = self._feed_text(act, place, None, thing).replace("{with}", partner.name).replace("{festival}", self.festival())
        if think:
            self.pool.submit(self._together, r, partner, label, place, text)
        else:
            delay = 4.0 if not self.fast else 1.0
            memo = f"和{r.name}{label}过"
            threading.Timer(delay, lambda: self._finish_together(r, partner, text, memo, *random.choice(TOGETHER_LINES))).start()
        return f"{r.name} 拉上 {partner.name} 去{place}{label}了"

    def _together(self, r: Resident, partner: Resident, label: str, place: str, text: str) -> None:
        first, second, remember = "", "", ""
        for who, other in ((r, partner), (partner, r)):
            if not who.call_lock.acquire(timeout=5):
                break
            try:
                system = self._system(who)
                memories = self.store.recall_memory(who.id, f"{other.name} {label}", 4)
                prompt = prompts.together_prompt(self.clock(), place, label, other.name, memories, first)
                gen = self._call(who, system, prompt, "line" if first else "json")
            finally:
                who.call_lock.release()
            if not gen.ok:
                break
            if first:
                second = prompts.tidy(gen.text, 60, who.name)
            else:
                parsed = prompts.parse_activity(gen.text)
                first, remember = parsed["对TA说"], parsed["记住"]
                if not first:
                    break
        if remember:
            self.remember(r, remember, "together")
        self._finish_together(r, partner, text, f"和{r.name}{label}过", first or random.choice(TOGETHER_LINES)[0], second)

    def _finish_together(self, r: Resident, partner: Resident, text: str, memo: str, first: str, second: str) -> None:
        for who in (r, partner):
            if who.status == "busy":
                who.status = "idle"
                self.changed(who)
        self.emit("bubble", {"id": r.id, "text": first})
        if second:
            threading.Timer(1.0 if self.fast else 3.5, lambda: self.emit("bubble", {"id": partner.id, "text": second})).start()
        detail = f"{r.name}：{first}" + (f" / {partner.name}：{second}" if second else "")
        self.add_feed(r, "together", text, room=r.room, spot=r.spot, detail=detail)
        self.remember(partner, memo, "together")
        reply = f"，TA回“{second}”" if second else ""
        self.store.bump_relation(r.id, partner.id, 4, f"上次{text}，你说“{first}”" + reply)
        self.store.bump_relation(partner.id, r.id, 4, f"上次{memo}，TA说“{first}”" + (f"，你回“{second}”" if second else ""))

    def _small_talk(self, now: float) -> None:
        """同屋的两个人随口搭句话：只冒气泡，不写动态，不调用模型。"""
        if self.paused or now < self.next_talk:
            return
        self.next_talk = now + random.uniform(6, 18) * self.minute
        rooms: dict[str, list[Resident]] = {}
        for r in list(self.residents.values()):
            if r.ready and r.status == "idle" and not r.typing:
                rooms.setdefault(r.room, []).append(r)
        groups = [g for g in rooms.values() if len(g) >= 2]
        if not groups:
            return
        a, b = random.sample(random.choice(groups), 2)
        lines = SMALL_TALK + days.talk_lines(self.weather(), self.festival()) + ([OUTSIDE_TALK] if not self.go_out_block() else [])
        ask, answer = random.choice(lines)
        self.store.bump_relation(a.id, b.id, 0.5)
        self.store.bump_relation(b.id, a.id, 0.5)
        self.emit("bubble", {"id": a.id, "text": ask})
        threading.Timer(1.0 if self.fast else 3.5, lambda: self.emit("bubble", {"id": b.id, "text": answer})).start()

    # ------------------------------------------------------------ 记忆
    def remember(self, r: Resident, text: str, kind: str = "auto", importance: int = 1) -> dict[str, Any]:
        row = self.store.add_memory(r.id, text, kind, importance)
        self.emit("memory", {"resident": r.id})
        return row

    def _plan_reflect(self, r: Resident) -> None:
        if not self.life.get("memory_reflect", True) or not self.can_call(r):
            return
        rows = self.store.memory_to_reflect(r.id, time.time() - 86400)
        if len(rows) >= REFLECT_MIN:
            self.pool.submit(self._reflect, r, rows)

    def _reflect(self, r: Resident, rows: list[dict[str, Any]]) -> None:
        if not r.call_lock.acquire(timeout=30):
            return
        try:
            system = self._system(r)
            gen = self._call(r, system, prompts.reflect_prompt(self.clock(), [m["text"] for m in rows]), "json")
        finally:
            r.call_lock.release()
        summary = prompts.parse_activity(gen.text)["记住"] if gen.ok else ""
        if summary:                        # 没整理出东西就什么都不动，零碎记忆原样留着
            self.remember(r, summary, "summary", 2)
            self.store.mark_merged([m["id"] for m in rows])
            self.emit("memory", {"resident": r.id})

    @staticmethod
    def _feed_text(act: dict[str, Any], place: str, item: Item | None, thing: str = "") -> str:
        t = str((act.get("text_thing") if thing else None) or act.get("text") or "在{place}" + act.get("label", ""))
        return (t.replace("{place}", place).replace("{thing}", thing).replace("{app}", str(act.get("app", "")))
                .replace("{title}", item.title if item else "").replace("{site}", (item.site if item else "") or "网上"))

    def _think(self, r: Resident, act: dict[str, Any], place: str, text: str, item: Item | None) -> None:
        if not r.call_lock.acquire(timeout=5):
            r.status = "idle"
            self.changed(r)
            self.add_feed(r, "activity", text, room=r.room, spot=r.spot, title=item.title if item else "",
                          url=item.url if item else "")
            return
        try:
            system = self._system(r)
            recent = [f["text"] for f in self.store.last_feed_of(r.id, 3)]
            chat = self.store.list_chat(8)
            query = " ".join([self._doing(r), item.title if item else "", *(c["text"] for c in chat[-3:])])
            leave_note = self.owner_away() and random.random() < NOTE_TO_OWNER_CHANCE and not self.store.unread_from(r.id, "owner")
            prompt = prompts.activity_prompt(self.clock(), place, self._doing(r), item, self.store.recall_memory(r.id, query),
                                             recent, chat, self.names(), self.home_info()["owner"], self.clock, leave_note)
            gen = self._call(r, system, prompt, "json")
        finally:
            r.call_lock.release()
        detail, suffix = "", ""
        if gen.ok:
            parsed = prompts.parse_activity(gen.text)
            detail = parsed["感想"]
            if parsed["记住"]:
                self.remember(r, parsed["记住"])
            if parsed["留言"]:
                self.store.add_note(r.id, "owner", parsed["留言"])
                self.emit("notes", {})
                self.emit("home", self.home_info())
                suffix = "，给你留了句话"
            say = prompts.tidy(parsed["群聊"], 120, r.name)
            if say:
                if self._chat_quiet():
                    msg = self.store.add_chat(r.id, say, depth=1)
                    self.emit("chat", msg)
                    self.plan_replies(msg)
                    suffix += "，在群里提了一句"
                else:
                    self.pending.append({"resident": r.id, "text": say, "ts": time.time()})
                    self.emit("pending", self.pending_public())
                    suffix += "，有句话等大家聊完再说"
        if r.status == "busy":
            r.status = "idle"
            self.changed(r)
        self.add_feed(r, "activity", text + suffix, room=r.room, spot=r.spot, detail=detail,
                      title=item.title if item else "", url=item.url if item else "")

    def _call(self, r: Resident, system: str, prompt: str, mode: str) -> Gen:
        try:
            gen = r.driver.generate(system, prompt, mode)
        except Exception as exc:
            log.exception("%s 调用出错", r.name)
            gen = Gen(False, error=f"{type(exc).__name__}: {exc}", kind="other")
        self.store.usage_inc(self.day(), r.id, gen.ok, gen.meta)
        if gen.ok:
            r.fails = 0
            if r.note:
                r.note = ""
            if gen.meta.get("used_tools"):
                log.warning("%s 的回答里用了工具（应该已经关掉），检查 CLI 参数", r.name)
            return gen
        r.fails += 1
        log.warning("%s 调用失败（%s）：%s", r.name, gen.kind, gen.error)
        now = time.time()
        if gen.kind in ("auth", "missing"):
            r.ready, r.ready_info, r.next_check = False, gen.error, now + 10 * self.minute
            r.note = gen.error
            self.add_feed(r, "system", f"连不上：{gen.error}")
        elif gen.kind == "limit":
            r.backoff_until = now + 30 * self.minute
            r.note = "额度用完或被限流，半小时后再试"
        else:
            r.backoff_until = now + min(5 * r.fails, 30) * self.minute
            r.note = f"上次调用失败：{gen.error[:80]}"
        self.emit("resident", self.public(r))
        return gen

    # ------------------------------------------------------------ 群聊
    def _chat_quiet(self) -> bool:
        quiet = float(self.life.get("quiet_seconds", 120)) / (10 if self.fast else 1)
        return time.time() - self.store.last_chat_ts() >= quiet

    def _flush_pending(self, now: float) -> None:
        if not self.pending or not self._chat_quiet():
            return
        p = self.pending.pop(0)
        self.emit("pending", self.pending_public())
        if now - p["ts"] > 2 * 3600 or p["resident"] not in self.residents:
            return
        msg = self.store.add_chat(p["resident"], p["text"], depth=1)
        self.emit("chat", msg)
        self.plan_replies(msg)

    def post_owner(self, text: str) -> dict[str, Any]:
        text = " ".join(str(text or "").split())[:500]
        if not text:
            raise ValueError("说点什么再发")
        msg = self.store.add_chat("owner", text, depth=0)
        self.emit("chat", msg)
        self.plan_replies(msg)
        return msg

    def mentions(self, text: str, loose: bool = False) -> list[Resident]:
        """@ 到谁。loose：喊人去哪的时候不带 @ 也算，「阿C去厨房」「大家去湖边」。"""
        if any(m in text for m in MENTION_ALL) or (loose and any(w in text for w in ("大家", "所有人", "都"))):
            return list(self.residents.values())
        return [r for r in self.residents.values() if f"@{r.name}" in text or f"@{r.id}" in text or (loose and r.name in text)]

    def _go_request(self, text: str) -> dict[str, Any] | None:
        """主人在群里喊人去哪：认房间名、位置名、活动名，取说得最具体（最长）的那个。"""
        moving = any(w in text for w in GO_WORDS)
        if not moving and not any(w in text for w in ASK_WORDS):      # 「帮我把玉米收了」没有「去」也算
            return None
        found: list[tuple[int, dict[str, Any]]] = []
        for room in (self.layout["rooms"] if moving else []):
            if room["name"] and room["name"] in text:
                found.append((len(room["name"]), {"kind": "room", "room": room["id"], "name": room["name"]}))
        for s in (self.spots if moving else []):
            label = str(s["label"])
            if label in GO_SKIP_LABELS or len(label) < 2 or label not in text or s["owner"]:
                continue
            found.append((len(label) + 1, {"kind": "spot", "room": s["room"], "spot": s["spot"], "name": self.place_name(s["room"], s["spot"])}))
        for aid, act in self.activities.items():
            if act.get("together") or act.get("visit"):
                continue
            label = str(act.get("label") or "")
            # 活动名和 words 里的说法都算：「去收玉米」「去喂鸡」「去翻地」
            hits = [str(w) for w in [label, *(act.get("words") or [])] if w and str(w) in text]
            pick = self.farm.hint(text) if act.get("farm") else None
            fits = bool(pick and pick & self.farm.fits(str(act.get("farm", ""))))
            # 单字的说法（收、喂、浇……）只在话里点了地、作物或牲口时才算：「把中间那块麦田收了」
            if not hits and fits and any(str(v) in text for v in act.get("verbs") or []):
                hits = [""]
            if hits:
                go = {"kind": "activity", "aid": aid, "name": label}
                if act.get("farm"):
                    go["pick"] = pick
                found.append((max(len(w) for w in hits) + 2 + (1 if fits else 0), go))
        if any(w in text for w in ("卧室", "房间", "回家", "回屋")):
            found.append((1, {"kind": "bedroom", "name": "自己房间"}))      # 「回房间」：各回各的，去哪一间要等知道是谁
        if not found:
            return None
        found.sort(key=lambda x: -x[0])
        return found[0][1]

    def go_to(self, r: Resident, go: dict[str, Any]) -> str:
        """真的走过去：能在那儿做的事就挑一件做，没有就站着。"""
        if go["kind"] == "activity":
            if self._choices(r, go["aid"], None, True, go.get("pick")):
                return self.start_activity(r, go["aid"], None, True, go.get("pick"))
            act = self.activities.get(go["aid"]) or {}
            if act.get("farm") and self._choices(r, "check_field", None, True):
                return self.start_activity(r, "check_field", None, True)      # 农活干不了：先去田边看看
            farm = next((x for x in self.layout["rooms"] if x.get("template") == "farm"), None)
            if not act.get("farm") or not farm:
                return f"{r.name} 现在没法{go['name']}"
            go = {"kind": "room", "room": farm["id"], "name": farm["name"]}
        where = (r.bedroom, None) if go["kind"] == "bedroom" else (go["room"], go.get("spot"))
        if self._choices(r, None, where, True):
            return self.start_activity(r, None, where, True)
        with self.lock:
            taken = {(o.room, o.spot) for o in self.residents.values() if o is not r}
        cands = [s for s in self.spots if s["room"] == where[0] and (where[1] is None or s["spot"] == where[1])
                 and (not s["owner"] or s["owner"] == r.id)]
        free = [s for s in cands if (s["room"], s["spot"]) not in taken] or cands
        if not free:
            return f"{go['name']}没有能待的位置"
        spot = random.choice(free)
        r.room, r.spot, r.since = spot["room"], spot["spot"], time.time()
        r.activity, r.status = f"在{go['name']}待着", "idle"
        r.next_at = time.time() + self._activity_gap()
        self._clear_act(r)
        self.changed(r)
        return f"{r.name} 去{go['name']}了"

    def _go_reason(self, r: Resident, go: dict[str, Any]) -> str:
        """叫去干的事现在干不了的原因，告诉模型，让它照实说。干得了返回空。"""
        if go.get("kind") != "activity":
            return ""
        act = self.activities.get(go["aid"]) or {}
        if self._choices(r, go["aid"], None, True, go.get("pick")):
            return ""
        if act.get("farm"):
            why = self.farm.reason(str(act["farm"]), go.get("pick"), time.time(), self.weather() == "rain")
            if why:
                return why
            tags = set(act.get("spots") or [])
            with self.lock:
                users = [o for o in self.residents.values() if o is not r
                         and any(s["room"] == o.room and s["spot"] == o.spot and tags & set(s["tags"]) for s in self.spots)]
            if users:
                return f"能用的{self.place_name(users[0].room, users[0].spot)}被{users[0].name}占着"
        return "那边现在没法弄"

    def farm_order(self, rid: str, job: str, target: str = "") -> str:
        """主人在农场面板上点名：让谁去哪块地 / 哪个圈干什么。不调用模型。"""
        r = self._get(rid)
        why = self._unavailable(r)
        if why and r.status != "busy":
            return why
        aids = [a for a, act in self.activities.items() if act.get("farm") == job]
        if not aids:
            return f"没有「{job}」这种活"
        pick = {target} if target else None
        go = {"kind": "activity", "aid": aids[0], "pick": pick, "name": self.activities[aids[0]].get("label", job)}
        if not self._choices(r, set(aids), None, True, pick):
            return f"{r.name} 去不了：{self._go_reason(r, go)}"
        out = self.start_activity(r, set(aids), None, True, pick)
        self.emit("bubble", {"id": r.id, "text": random.choice(["好，这就去。", "行，我去。", "交给我。", "马上。"])})
        return out

    def _chat_crowded(self) -> bool:
        """住户之间最近一分钟说得太多，就先不主动接话。@ 到的人和回主人的话不受影响。"""
        limit = int(self.life.get("max_chat_per_minute", 6))
        since = time.time() - self.minute
        return limit > 0 and sum(1 for c in self.store.list_chat(30) if c["ts"] >= since and c["sender"] != "owner") >= limit

    @staticmethod
    def _bigrams(text: str) -> set[str]:
        t = re.sub(r"\s+", "", str(text))
        return {t[i:i + 2] for i in range(len(t) - 1)}

    def _speak_score(self, r: Resident, msg: dict[str, Any], recent: list[dict[str, Any]]) -> float:
        """话题沾边、和说话的人熟、最近说得少的人更容易接话。"""
        labels = " ".join(str(self.activities.get(a, {}).get("label", "")) for a in (r.cfg.get("likes") or {}))
        about = f"{r.cfg.get('persona', '')} {labels} {r.activity}"
        score = 1.0 + 0.8 * min(3, len(self._bigrams(msg["text"]) & self._bigrams(about)))
        score += self.store.relation_score(r.id, msg["sender"]) / 25.0
        said = sum(1 for c in recent if c["sender"] == r.id)
        score /= 1.0 + 0.6 * said
        if recent and recent[-1]["sender"] == r.id:
            score *= 0.3
        if r.status == "busy":
            score *= 0.6
        return max(score, 0.02)

    def _pick_speakers(self, pool: list[Resident], msg: dict[str, Any], count: int) -> list[Resident]:
        recent = self.store.list_chat(12)
        pool, out = pool[:], []
        while pool and len(out) < count:
            who = random.choices(pool, weights=[self._speak_score(r, msg, recent) for r in pool])[0]
            out.append(who)
            pool.remove(who)
        return out

    def plan_replies(self, msg: dict[str, Any]) -> None:
        depth = int(msg.get("depth") or 0)
        max_chain = int(self.life.get("max_chain", 3))
        chance = float(self.life.get("chat_reply_chance", 0.5))
        wake = bool(self.life.get("wake_on_mention", True))
        sender = msg["sender"]
        go = self._go_request(msg["text"]) if sender == "owner" else None
        mentioned = [r for r in self.mentions(msg["text"], loose=bool(go)) if r.id != sender]
        awake = [r for r in self.residents.values() if r.id != sender and r.ready and r.status in ("idle", "busy")]
        chosen: list[tuple[Resident, bool]] = []
        if sender == "owner":
            for r in mentioned:
                if r.ready and (r.status != "asleep" or wake):
                    chosen.append((r, True))
            if not mentioned and awake:
                limit = max(1, int(self.life.get("max_auto_replies", 2)))
                count = min(limit, max(1, sum(random.random() < chance for _ in awake)))
                chosen += [(r, False) for r in self._pick_speakers(awake, msg, count)]
        else:
            if depth >= max_chain:
                return
            for r in mentioned:
                if r in awake:
                    chosen.append((r, True))
            if not chosen and not self._chat_crowded():
                pool = [r for r in awake if random.random() < chance * (0.5 ** depth)]
                if pool:
                    chosen.append((self._pick_speakers(pool, msg, 1)[0], False))
        delay = 0.0
        for r, was_mentioned in chosen:
            delay += random.uniform(1.0, 2.0) if self.fast else random.uniform(2.0, 6.0)
            threading.Timer(delay, lambda r=r, m=was_mentioned: self.pool.submit(self._reply, r, msg, m)).start()

    def _reply(self, r: Resident, trigger: dict[str, Any], mentioned: bool) -> None:
        if not self.can_call(r, for_owner=trigger.get("sender") == "owner"):
            return
        if not r.call_lock.acquire(timeout=120):
            return
        try:
            asleep = r.status == "asleep"
            go = self._go_request(str(trigger["text"])) if trigger.get("sender") == "owner" and mentioned and not asleep else None
            go_note = self._go_reason(r, go) if go else ""
            r.typing = True
            self.emit("resident", self.public(r))
            system = self._system(r)
            chat = self.store.list_chat(15)
            memories = self.store.recall_memory(r.id, " ".join(c["text"] for c in chat[-3:]), 4)
            prompt = prompts.chat_prompt(self.clock(), self.place_name(r.room, r.spot), self._doing(r), chat,
                                         self.names(), self.home_info()["owner"], self.clock, asleep, mentioned, memories,
                                         go=go["name"] if go else "", go_note=go_note)
            gen = self._call(r, system, prompt, "line")
        finally:
            r.typing = False
            r.call_lock.release()
            self.emit("resident", self.public(r))
        if not gen.ok:
            return
        text = prompts.tidy(gen.text, 160, r.name)
        refused = GO_REFUSE in text
        text = " ".join(text.replace(GO_REFUSE, " ").split())
        if not text or prompts.SILENT in text or re.fullmatch(r"[\[\]（）()不说话\s。.]*", text):
            return
        msg = self.store.add_chat(r.id, text, depth=int(trigger.get("depth") or 0) + 1, reply_to=trigger.get("id"))
        self.emit("chat", msg)
        if go and not refused and not self.paused:
            try:
                log.info("%s 应主人的话去%s：%s", r.name, go["name"], self.go_to(r, go))
            except Exception:
                log.exception("%s 去%s出错", r.name, go["name"])
        self._note_chat(r, trigger, text)
        self.plan_replies(msg)

    def _note_chat(self, r: Resident, trigger: dict[str, Any], reply: str) -> None:
        """回完话记一笔：下次还接得上。"""
        sender, said = trigger["sender"], str(trigger["text"])
        if sender == "owner":
            owner = self.home_info_owner()
            self.store.bump_relation(r.id, "owner", 1.5, f"{owner}上次在群里说“{said[:50]}”，你回“{reply[:40]}”")
            if len(said) >= 4:
                self.remember(r, f"{owner}说过：{said[:100]}", "chat")
        elif sender in self.residents:
            other = self.residents[sender]
            self.store.bump_relation(r.id, sender, 1, f"上次{other.name}在群里说“{said[:50]}”，你回“{reply[:40]}”")
            self.store.bump_relation(sender, r.id, 1, f"上次你在群里说“{said[:50]}”，{r.name}回“{reply[:40]}”")

    # ------------------------------------------------------------ 主人的操作
    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self._save_home()
        self.emit("home", self.home_info())

    def _get(self, rid: str) -> Resident:
        r = self.residents.get(rid)
        if not r:
            raise ValueError(f"没有住户 {rid}")
        return r

    def _unavailable(self, r: Resident) -> str:
        if not r.ready:
            return f"{r.name} 现在没接上：{r.ready_info}"
        if r.status == "asleep":
            return f"{r.name} 在睡觉"
        if r.status == "busy":
            return f"{r.name} 手上正忙"
        if self.paused:
            return "全屋暂停中"
        return ""

    def poke(self, rid: str) -> str:
        r = self._get(rid)
        return self._unavailable(r) or self.start_activity(r)

    def _outdoor_activities(self) -> set[str]:
        tags = {t for s in self.spots if s.get("outdoor") for t in s["tags"]}
        return {aid for aid, a in self.activities.items() if tags & set(a.get("spots") or [])}

    def go_play(self, rid: str) -> str:
        r = self._get(rid)
        if self.go_out_block():
            return self.go_out_block()
        forced = self._outdoor_activities()
        if not forced:
            return "家门口还没有能去的地方"
        return self._unavailable(r) or self.start_activity(r, forced)

    def gather(self) -> str:
        if self.go_out_block():
            return self.go_out_block()
        forced = self._outdoor_activities()
        if not forced:
            return "家门口还没有能去的地方"
        names = []
        for r in list(self.residents.values()):
            if self._unavailable(r):
                continue
            if not (self._spot(r.room, r.spot) or {}).get("outdoor"):   # 已经被别人拉出来的就不用再换地方
                self.start_activity(r, forced)
            names.append(r.name)
        return f"{'、'.join(names)} 出门了" if names else "现在没人能去"

    def interact(self, rid: str, action: str) -> str:
        """主人和住户的小互动：只冒气泡、记一条动态，不调用模型。"""
        r = self._get(rid)
        if action == "play":
            return self.go_play(rid)
        if action not in REACTIONS:
            raise ValueError(f"不认识的互动：{action}")
        if not r.ready:
            return f"{r.name} 现在没接上：{r.ready_info}"
        if r.status == "asleep":
            return f"{r.name} 在睡觉，别吵醒了"
        phrase, lines = REACTIONS[action]
        owner = self.home_info()["owner"]
        text = f"{owner}{phrase.format(name=r.name)}"
        self.emit("bubble", {"id": r.id, "text": random.choice(lines)})
        self.emit("act", {"id": r.id, "anim": "clap" if action == "feed" else "wave", "emote": {"pat": "❤", "feed": "😋", "wave": "👋"}[action]})
        living.give(r.needs, {"social": 15, "hunger": 25 if action == "feed" else 0, "fun": 5})
        self.add_feed(r, "interact", text, room=r.room, spot=r.spot)
        self.store.bump_relation(r.id, "owner", 2)
        if action == "feed":
            self.remember(r, f"{owner}给我带过吃的", "together")
        return text

    def recheck(self) -> None:
        for r in self.residents.values():
            r.ready, r.next_check, r.backoff_until = False, 0.0, 0.0
