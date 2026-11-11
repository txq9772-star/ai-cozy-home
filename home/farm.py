"""农场：地块、作物生长、牲口、仓库、农机干活。

地块和圈舍写在场地模板里（rooms/farm.yaml 的 field / pen 家具），这里只管它们的状态。
作物按小窝时间慢慢长：翻地 → 播种 → 出苗 → 长高 → 成熟 → 收割，收完剩茬，再翻地。
土干了就不长，下雨或者浇水才接着长。用农机干的活（翻地、播种、浇水、收割、拉去卖）要开一会儿，
开完了地才变样；喂牲口、挤奶、捡蛋这些手上的活当场就算。
"""
from __future__ import annotations

import random
import time
from typing import Any

CROPS: dict[str, dict[str, Any]] = {
    "rice":   {"name": "稻子", "item": "稻谷", "unit": "袋", "hours": 72, "yield": (8, 12), "field": "稻田"},
    "wheat":  {"name": "麦子", "item": "麦子", "unit": "袋", "hours": 48, "yield": (8, 12), "field": "麦田"},
    "corn":   {"name": "玉米", "item": "玉米", "unit": "袋", "hours": 60, "yield": (10, 14), "field": "玉米地"},
    "potato": {"name": "土豆", "item": "土豆", "unit": "筐", "hours": 36, "yield": (12, 18), "field": "土豆地"},
}
ANIMALS: dict[str, dict[str, Any]] = {
    "cow":     {"name": "牛", "product": "牛奶", "unit": "桶", "every": 12, "job": "milk", "per": 0.4},
    "sheep":   {"name": "羊", "product": "羊毛", "unit": "包", "every": 72, "job": "shear", "per": 0.35},
    "chicken": {"name": "鸡", "product": "鸡蛋", "unit": "个", "every": 8, "job": "eggs", "per": 0.7},
}
UNITS = {c["item"]: c["unit"] for c in CROPS.values()} | {a["product"]: a["unit"] for a in ANIMALS.values()}
SELL_AT = {"袋": 24, "筐": 30, "桶": 10, "个": 48, "包": 6}       # 攒到这么多就可以拉去卖
FEED_ITEMS = ("玉米", "麦子")                                     # 喂牲口优先用自家的粮
WATER_HOURS = 30          # 浇一次水管这么久，过了地就干，作物停着不长
FEED_HOURS = 10           # 喂一次能管这么久
HUNGRY_HOURS = 24         # 这么久没喂，就不出奶、不下蛋
MACHINE_SECONDS = 80      # 农机干一趟活的时长（真实秒数，和页面上开车的动画对得上）
GROWING = ("sown", "sprout", "growing", "ripe")
STAGE_NAMES = {"stubble": "收完剩茬", "plowed": "翻好了", "sown": "刚种下", "sprout": "出苗了", "growing": "正在长",
               "ripe": "熟了"}
MACHINE_JOBS = ("plow", "sow", "water", "harvest", "sell")
PLOT_JOBS = ("plow", "sow", "water", "harvest")
PEN_JOBS = ("feed", "milk", "eggs", "shear")
CROP_WORDS = {"rice": ("稻", "水稻", "稻谷"), "wheat": ("麦",), "corn": ("玉米", "苞米"), "potato": ("土豆", "马铃薯", "洋芋")}
ANIMAL_WORDS = {"cow": ("牛",), "sheep": ("羊",), "chicken": ("鸡", "鸡蛋")}
LOG_KEEP = 30

# 用自家东西做的菜：厨房做饭时有就用上
DISHES: dict[str, list[str]] = {
    "土豆": ["土豆炖牛肉", "酸辣土豆丝", "一锅土豆泥", "孜然土豆块"],
    "稻谷": ["一锅新米饭", "蛋炒饭", "皮蛋瘦肉粥"],
    "麦子": ["手擀面", "一锅馒头", "葱油饼"],
    "玉米": ["玉米排骨汤", "一锅煮玉米", "松仁玉米"],
    "鸡蛋": ["番茄炒蛋", "蒸蛋羹", "紫菜蛋花汤"],
    "牛奶": ["牛奶布丁", "双皮奶", "奶香馒头"],
}


def farm_parts(layout: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """从布局里找出所有地块和圈舍。"""
    plots: dict[str, dict[str, Any]] = {}
    pens: dict[str, dict[str, Any]] = {}
    for room in layout.get("rooms") or []:
        for f in room.get("furniture") or []:
            if f.get("type") == "field" and f.get("plot") and f.get("crop") in CROPS:
                plots[str(f["plot"])] = {"crop": f["crop"], "name": str(f.get("name") or f["plot"]), "room": room["id"]}
            elif f.get("type") == "pen" and f.get("pen") and f.get("kind") in ANIMALS:
                pens[str(f["pen"])] = {"kind": f["kind"], "count": int(f.get("count") or 4), "name": str(f.get("name") or f["pen"]),
                                       "room": room["id"]}
    return plots, pens


class Farm:
    def __init__(self, layout: dict[str, Any], saved: dict[str, Any] | None = None, hour: float = 3600.0,
                 rng: random.Random | None = None):
        self.hour = hour
        self.rng = rng or random.Random()
        saved = saved or {}
        self.plots: dict[str, dict[str, Any]] = {k: dict(v) for k, v in (saved.get("plots") or {}).items()}
        self.pens: dict[str, dict[str, Any]] = {k: dict(v) for k, v in (saved.get("pens") or {}).items()}
        self.store: dict[str, int] = {k: int(v) for k, v in (saved.get("store") or {}).items()}
        self.sold: dict[str, int] = {k: int(v) for k, v in (saved.get("sold") or {}).items()}
        self.work: list[dict[str, Any]] = [dict(w) for w in saved.get("work") or []]
        self.log: list[dict[str, Any]] = list(saved.get("log") or [])[-LOG_KEEP:]
        self.checked = float(saved.get("checked") or time.time())
        self.fresh = not saved.get("plots")
        self.set_layout(layout)

    # ------------------------------------------------------------ 布局变了：补上新地块，去掉没了的
    def set_layout(self, layout: dict[str, Any]) -> None:
        plots, pens = farm_parts(layout)
        now = time.time()
        self.info, self.pen_info = plots, pens
        for pid, p in plots.items():
            if pid not in self.plots or self.plots[pid].get("crop") != p["crop"]:
                self.plots[pid] = self._seed_plot(p["crop"], now)
        for pid in [k for k in self.plots if k not in plots]:
            del self.plots[pid]
        for pid, p in pens.items():
            if pid not in self.pens:
                every = ANIMALS[p["kind"]]["every"]
                self.pens[pid] = {"fed_at": now - 8 * self.hour, "got_at": now - every * self.hour * 0.8}
        for pid in [k for k in self.pens if k not in pens]:
            del self.pens[pid]
        self.work = [w for w in self.work if w["target"] in self.plots or w["target"] in self.pens or w["job"] == "sell"]
        if self.fresh and plots and not self.store:
            self.store = {"稻谷": 6, "麦子": 4, "玉米": 5, "土豆": 8, "鸡蛋": 12, "牛奶": 2, "羊毛": 1}

    def _seed_plot(self, crop: str, now: float) -> dict[str, Any]:
        """新开的地：各块地进度错开，一打开就有熟的、在长的、刚收完的。"""
        hours = CROPS[crop]["hours"]
        roll = self.rng.random()
        if roll < 0.2:
            return {"crop": crop, "stage": "stubble", "grown": 0.0, "watered_at": now}
        if roll < 0.3:
            return {"crop": crop, "stage": "plowed", "grown": 0.0, "watered_at": now}
        grown = hours * (1.05 if roll > 0.82 else self.rng.uniform(0.05, 0.95))
        p = {"crop": crop, "stage": "sown", "grown": grown, "watered_at": now - self.rng.uniform(0, 10) * self.hour}
        p["stage"] = self._grow_stage(p)
        return p

    # ------------------------------------------------------------ 时间往前走
    @staticmethod
    def _grow_stage(p: dict[str, Any]) -> str:
        f = float(p.get("grown", 0)) / CROPS[p["crop"]]["hours"]
        return "sown" if f < 0.12 else "sprout" if f < 0.4 else "growing" if f < 1 else "ripe"

    def moist(self, p: dict[str, Any], now: float, raining: bool) -> bool:
        return raining or now - float(p.get("watered_at", 0)) < WATER_HOURS * self.hour

    def tick(self, now: float, raining: bool) -> bool:
        """作物长一点、干完的活落地。返回 True 表示页面上能看出变化。"""
        changed = False
        dt = max(0.0, now - self.checked) / self.hour
        self.checked = now
        for p in self.plots.values():
            if raining and p["stage"] in GROWING:
                p["watered_at"] = now
            if p["stage"] in GROWING and p["stage"] != "ripe" and self.moist(p, now, raining):
                p["grown"] = float(p.get("grown", 0)) + dt
                st = self._grow_stage(p)
                if st != p["stage"]:
                    p["stage"], changed = st, True
        for w in [w for w in self.work if now >= float(w["done_at"])]:
            self._finish(w, now)
            changed = True
        return changed

    # ------------------------------------------------------------ 能干什么
    def options(self, job: str, target: str, now: float, raining: bool) -> list[str]:
        busy = {w["target"] for w in self.work} | {k for w in self.work for k in w.get("also", [])}
        if job in ("plow", "sow", "water", "harvest", "check"):
            out = []
            for pid, p in self.plots.items():
                if pid in busy and job != "check":
                    continue
                st, crop = p["stage"], p["crop"]
                if job == "plow" and st == "stubble":
                    out.append(pid)
                elif job == "sow" and st == "plowed":
                    out.append(pid)
                elif job == "water" and st in GROWING and st != "ripe" and not raining \
                        and now - float(p.get("watered_at", 0)) > WATER_HOURS * self.hour * 0.5:
                    out.append(pid)
                elif job == "harvest" and st == "ripe" and (not target or crop in target.split(",")):
                    out.append(pid)
                elif job == "check" and (not target or pid == target):
                    out.append(pid)
            return out
        if job == "feed":
            return [pid for pid in self._pens(target) if pid not in busy
                    and now - float(self.pens[pid].get("fed_at", 0)) > FEED_HOURS * self.hour * 0.6]
        if job in ("milk", "eggs", "shear"):
            out = []
            for pid in self._pens(target):
                kind = self.pen_info[pid]["kind"]
                st = self.pens[pid]
                if ANIMALS[kind]["job"] == job and pid not in busy and now - float(st.get("fed_at", 0)) < HUNGRY_HOURS * self.hour \
                        and now - float(st.get("got_at", 0)) >= ANIMALS[kind]["every"] * self.hour:
                    out.append(pid)
            return out
        if job == "count":
            return ["barn"] if self.plots or self.store else []
        if job == "sell":
            return [] if "sell" in {w["job"] for w in self.work} else \
                [item for item, n in self.store.items() if n >= SELL_AT.get(UNITS.get(item, "袋"), 24)]
        return []

    def hint(self, text: str) -> set[str] | None:
        """主人话里说到的地或圈：点了地名就是那块；说了作物就是那种作物的地；说了牛羊鸡就是那个圈。"""
        named = [pid for pid, info in self.info.items() if info["name"] in text]
        if named:
            return {max(named, key=lambda k: len(self.info[k]["name"]))}
        out = {pid for pid, p in self.plots.items() if any(w in text for w in CROP_WORDS.get(p["crop"], ()))}
        out |= {pid for pid, info in self.pen_info.items() if info["name"] in text
                or any(w in text for w in ANIMAL_WORDS.get(info["kind"], ()))}
        return out or None

    def reason(self, job: str, pick: set[str] | None, now: float, raining: bool) -> str:
        """这活现在为什么干不了。干得了返回空。"""
        opts = self.options(job, "", now, raining)
        if pick:
            opts = [o for o in opts if o in pick]
        if opts:
            return ""
        crops = sorted({CROPS[self.plots[k]["crop"]]["name"] for k in (pick or []) if k in self.plots})
        what = "、".join(crops) or "庄稼"
        pens = [self.pen_info[k] for k in (pick or []) if k in self.pen_info]
        animal = "、".join(ANIMALS[p["kind"]]["name"] for p in pens) or "牲口"
        busy = [w for w in self.work if not pick or w["target"] in pick]
        if busy and job in PLOT_JOBS + PEN_JOBS:
            return f"{self._target_name(busy[0]['target'])}已经有人在弄了"
        if job == "harvest":
            near = [k for k, p in self.plots.items() if (not pick or k in pick) and p["stage"] in GROWING]
            if near:
                k = max(near, key=lambda x: self.plots[x].get("grown", 0) / CROPS[self.plots[x]["crop"]]["hours"])
                p = self.plots[k]
                left = (CROPS[p["crop"]]["hours"] - float(p.get("grown", 0))) * self.hour / 3600
                return f"地里的{what}还没熟，最快的{self.info[k]['name']}还得长 {max(1, round(left))} 小时左右"
            return f"地里没有{what}可收"
        if job == "plow":
            return "没有收完要翻的地"
        if job == "sow":
            return "没有翻好等着下种的地，得先翻地"
        if job == "water":
            return "正下着雨，用不着浇" if raining else f"地里的{what}都不缺水"
        if job == "feed":
            return f"{animal}刚喂过，还饱着"
        if job in ("milk", "eggs", "shear"):
            ids = [k for k in (pick or []) if k in self.pens] or                 [k for k, info in self.pen_info.items() if ANIMALS[info["kind"]]["job"] == job]
            if any(now - float(self.pens[k].get("fed_at", 0)) > HUNGRY_HOURS * self.hour for k in ids):
                return f"{animal}饿着，得先喂"
            return {"milk": "牛刚挤过奶，过几个小时再挤", "eggs": "鸡蛋刚捡过，鸡还没下新的", "shear": "羊毛还没长起来"}[job]
        if job == "sell":
            return "粮仓里的东西还不多，不够拉一车"
        return "现在没这活"

    def fits(self, job: str) -> set[str]:
        """这种活对哪些东西干：地里的活对地块，圈里的活对圈。"""
        return set(self.plots) if job in PLOT_JOBS + ("check",) else set(self.pens) if job in PEN_JOBS else set()

    def _target_name(self, k: str) -> str:
        return (self.info.get(k) or self.pen_info.get(k) or {"name": k})["name"]

    def _pens(self, target: str) -> list[str]:
        return [pid for pid in self.pens if not target or pid == target or self.pen_info[pid]["kind"] == target]

    # ------------------------------------------------------------ 开始干
    def start(self, job: str, target: str, by: str, ride: str, now: float, raining: bool,
              pick: set[str] | None = None) -> str:
        """挑一块地或一个圈开始干，返回这次具体干的什么（写进动态）。没得干返回空。
        pick 是主人点名要干的那几块地 / 那几个圈。"""
        every = self.options(job, target, now, raining)
        opts = [o for o in every if o in pick] if pick else every
        if not opts:
            return ""
        if job == "harvest":
            pick = max(opts, key=lambda k: self.plots[k].get("grown", 0))
        elif job == "sell":
            pick = max(opts, key=lambda k: self.store[k] / SELL_AT.get(UNITS.get(k, "袋"), 24))
        else:
            pick = self.rng.choice(opts)
        w: dict[str, Any] = {"job": job, "target": pick, "by": by, "ride": ride, "start": now,
                             "done_at": now + (MACHINE_SECONDS if job in MACHINE_JOBS else 0)}
        thing = ""
        if job in ("plow", "sow", "water", "harvest"):
            p, info = self.plots[pick], self.info[pick]
            crop = CROPS[p["crop"]]
            if job == "plow":
                thing = info["name"]
            elif job == "sow":
                thing = f"{info['name']}种下了{crop['name']}"
            elif job == "water":            # 洒水车一趟把同一种作物缺水的地都浇了
                w["also"] = [k for k in every if k != pick and self.plots[k]["crop"] == p["crop"]]
                where = info["name"] if not w["also"] else f"{len(w['also']) + 1} 块{crop['field']}"
                thing = where + ("灌了水" if p["crop"] == "rice" else "浇了水")
            else:
                lo, hi = crop["yield"]
                w["amount"] = max(1, self.rng.randint(lo, hi) - (0 if self.moist(p, now, raining) else 2))
                thing = f"{info['name']}，收了 {w['amount']} {crop['unit']}{crop['item']}"
        elif job == "sell":
            n = self.store[pick] // 2 + self.rng.randint(0, self.store[pick] // 4)
            w["amount"], w["item"] = n, pick
            self.store[pick] -= n           # 先装车，路上不能再拿去做饭
            thing = f"{n} {UNITS.get(pick, '袋')}{pick}"
        elif job == "feed":
            thing = self._feed(pick, now)
            w["done_at"] = now
        elif job in ("milk", "eggs", "shear"):
            thing = self._collect(pick, now)
            w["done_at"] = now
        elif job == "check":
            return self._look(pick, now, raining)
        elif job == "count":
            return self.summary() or "粮仓空着"
        if w["done_at"] > now:
            self.work.append(w)
        else:
            self._note(by, job, thing, now)
        return thing

    def _feed(self, pid: str, now: float) -> str:
        info = self.pen_info[pid]
        a = ANIMALS[info["kind"]]
        self.pens[pid]["fed_at"] = now
        own = [x for x in FEED_ITEMS if self.store.get(x, 0) > 0]
        if own:
            item = self.rng.choice(own)
            n = 1 if info["kind"] == "chicken" else min(self.store[item], max(1, info["count"] // 4))
            self.store[item] -= n
            what = f"一把{item}" if info["kind"] == "chicken" else f"{n} 袋{item}"
            return f"{a['name']}喂了{what}"
        return f"{a['name']}添了草料" if info["kind"] != "chicken" else "鸡撒了一把谷糠"

    def _collect(self, pid: str, now: float) -> str:
        info = self.pen_info[pid]
        a = ANIMALS[info["kind"]]
        n = max(1, round(info["count"] * a["per"] * self.rng.uniform(0.8, 1.2)))
        self.pens[pid]["got_at"] = now
        self.store[a["product"]] = self.store.get(a["product"], 0) + n
        return f"{n} {a['unit']}{a['product']}"

    def _look(self, pid: str, now: float, raining: bool) -> str:
        p, info = self.plots[pid], self.info[pid]
        crop = CROPS[p["crop"]]
        st = p["stage"]
        if st == "stubble":
            return f"{info['name']}收完了，还没翻"
        if st == "plowed":
            return f"{info['name']}翻好了，等着下种"
        if not self.moist(p, now, raining):
            return f"{info['name']}的土干了，{crop['name']}蔫蔫的"
        f = float(p.get("grown", 0)) / crop["hours"]
        if st == "ripe":
            return f"{info['name']}的{crop['name']}熟了，可以收了"
        if st == "sown":
            return f"{info['name']}刚种下，还看不出苗"
        if st == "sprout":
            return f"{info['name']}的{crop['name']}冒出了一层小苗"
        stage = {"rice": "抽穗了", "wheat": "抽穗了", "corn": "长得比人还高了", "potato": "开了小白花"}[p["crop"]] if f > 0.7 \
            else "长得挺齐"
        return f"{info['name']}的{crop['name']}{stage}"

    # ------------------------------------------------------------ 干完
    def release(self, by: str, now: float) -> bool:
        """这个人不干了（换别的事、去睡觉）：开到一半的活也算干完。"""
        done = [w for w in self.work if w["by"] == by]
        for w in done:
            self._finish(w, now)
        return bool(done)

    def _finish(self, w: dict[str, Any], now: float) -> None:
        if w in self.work:
            self.work.remove(w)
        job, pid = w["job"], w["target"]
        p = self.plots.get(pid)
        if job == "plow" and p and p["stage"] == "stubble":
            p.update(stage="plowed", grown=0.0)
        elif job == "sow" and p and p["stage"] == "plowed":
            p.update(stage="sown", grown=0.0, watered_at=now)
        elif job == "water" and p:
            for k in [pid, *w.get("also", [])]:
                if k in self.plots:
                    self.plots[k]["watered_at"] = now
        elif job == "harvest" and p and p["stage"] == "ripe":
            crop = CROPS[p["crop"]]
            self.store[crop["item"]] = self.store.get(crop["item"], 0) + int(w.get("amount", 0))
            p.update(stage="stubble", grown=0.0)
        elif job == "sell":
            self.sold[w["item"]] = self.sold.get(w["item"], 0) + int(w.get("amount", 0))

    def _note(self, by: str, job: str, thing: str, now: float) -> None:
        self.log.append({"ts": now, "by": by, "job": job, "text": thing})
        self.log = self.log[-LOG_KEEP:]

    def note_start(self, by: str, job: str, thing: str, now: float) -> None:
        if job in MACHINE_JOBS and thing:
            self._note(by, job, thing, now)

    def summary(self) -> str:
        """粮仓里有什么，一句话：稻谷 14 袋、土豆 20 筐。"""
        return "、".join(f"{k} {v} {UNITS.get(k, '')}" for k, v in sorted(self.store.items(), key=lambda x: -x[1]) if v > 0)

    # ------------------------------------------------------------ 厨房拿东西
    def cook_from_home(self) -> tuple[str, str] | None:
        """做饭用自家的东西：返回 (菜名, 用了什么)，没有就 None。"""
        have = [x for x in DISHES if self.store.get(x, 0) > 0]
        if not have:
            return None
        item = self.rng.choice(have)
        self.store[item] -= 1
        return self.rng.choice(DISHES[item]), "米" if item == "稻谷" else "面" if item == "麦子" else item

    # ------------------------------------------------------------ 存盘和给页面
    def saved(self) -> dict[str, Any]:
        return {"plots": self.plots, "pens": self.pens, "store": self.store, "sold": self.sold, "work": self.work,
                "log": self.log, "checked": self.checked}

    def public(self, now: float, raining: bool, names: dict[str, str] | None = None) -> dict[str, Any]:
        names = names or {}
        can = {j: set(self.options(j, "", now, raining)) for j in PLOT_JOBS + PEN_JOBS}
        plots = []
        for pid, p in self.plots.items():
            crop = CROPS[p["crop"]]
            plots.append({"id": pid, "crop": p["crop"], "crop_name": crop["name"], "name": self.info[pid]["name"],
                          "stage": p["stage"], "stage_name": STAGE_NAMES[p["stage"]],
                          "progress": round(min(1.0, float(p.get("grown", 0)) / crop["hours"]), 3) if p["stage"] in GROWING else 0,
                          "dry": p["stage"] in GROWING and p["stage"] != "ripe" and not self.moist(p, now, raining),
                          "can": [j for j in PLOT_JOBS if pid in can[j]]})
        pens = []
        for pid, st in self.pens.items():
            info = self.pen_info[pid]
            a = ANIMALS[info["kind"]]
            hungry = now - float(st.get("fed_at", 0)) > HUNGRY_HOURS * self.hour
            pens.append({"id": pid, "kind": info["kind"], "name": info["name"], "count": info["count"], "animal": a["name"],
                         "hungry": hungry, "fed_ago": round((now - float(st.get("fed_at", 0))) / self.hour, 1),
                         "fed_ts": float(st.get("fed_at", 0)),
                         "ready": not hungry and now - float(st.get("got_at", 0)) >= a["every"] * self.hour, "product": a["product"],
                         "can": [j for j in PEN_JOBS if pid in can[j]]})
        work = [{"job": w["job"], "target": w["target"], "ride": w.get("ride", ""), "by": w["by"], "by_name": names.get(w["by"], w["by"]),
                 "start": w["start"], "done_at": w["done_at"]} for w in self.work]
        store = [{"item": k, "count": v, "unit": UNITS.get(k, "")} for k, v in self.store.items() if v > 0]
        sold = [{"item": k, "count": v, "unit": UNITS.get(k, "")} for k, v in self.sold.items() if v > 0]
        log = [{"ts": x["ts"], "by": names.get(x["by"], x["by"]), "job": x["job"], "text": x["text"]} for x in self.log[-12:]][::-1]
        return {"plots": plots, "pens": pens, "work": work, "store": store, "sold": sold, "log": log,
                "can_sell": bool(self.options("sell", "", now, raining))}
