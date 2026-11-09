#!/usr/bin/env python3
"""小窝主程序。

一个进程同时是两样东西：
  1. 小窝本体：3D 页面（http://本机IP:8760/）、页面用的接口、住户的日常。
  2. 外部控制台的一个热插拔模块：按控制台的模块协议注册到中枢，控制台里多一页「小窝」，
     能看住户状态、动态、群聊，能暂停 / 让谁去做点什么。中枢不在线也不影响小窝本身。

运行：
  python home/server.py                      # 读 home.yaml（没有就读 home.example.yaml），连 COZY_HUB 指的中枢
  python home/server.py --mock --fast        # 模拟住户 + 加速，不调用模型，用来试运行
  python home/server.py --no-hub             # 不连控制台，单独跑
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from home_module import Module  # noqa: E402

from home.drivers import make_driver  # noqa: E402
from home.layout import LayoutError, build_layout, load_templates  # noqa: E402
from home.life import Life  # noqa: E402
from home.store import Store  # noqa: E402

log = logging.getLogger("home")
VERSION = "0.1.0"
DEFAULT_ROOMS = [{"template": t} for t in ("living", "study", "play", "kitchen", "storage", "lounge", "library")]
DEFAULT_BEDROOMS = 8
DEFAULT_OUTDOORS = [{"template": "playground"}, {"template": "lake"}]
MOVE_IN_KEY = "__movein__"
MOVE_IN_DRIVERS = ("openai_api", "mock")
WEB = ROOT / "web"


# ====================================================================== 配置
def load_config(path: Path) -> tuple[dict[str, Any], Path]:
    p = path if path.exists() else ROOT / "home.example.yaml"
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    ids = [str(r.get("id", "")) for r in cfg.get("residents") or []]
    if not ids or any(not i for i in ids):
        raise ValueError(f"{p.name}：residents 里每个住户都要有 id")
    if len(set(ids)) != len(ids):
        raise ValueError(f"{p.name}：住户 id 重复")
    reserved = {"owner", "hall", "__home__", "__owner__"}
    if reserved & set(ids):
        raise ValueError(f"{p.name}：住户 id 不能用 {', '.join(reserved & set(ids))}")
    return cfg, p


def with_move_ins(cfg: dict[str, Any], store: Store) -> dict[str, Any]:
    """页面上办了入住的住户存在数据库里，不碰 home.yaml。入住功能关着时不生效。"""
    if not (cfg.get("life") or {}).get("move_in", False):
        return cfg
    have = {str(r.get("id")) for r in cfg["residents"]}
    extra = [r for r in store.load_state(MOVE_IN_KEY).get("residents") or [] if str(r.get("id")) not in have]
    return {**cfg, "residents": [*cfg["residents"], *extra]} if extra else cfg


def clean_move_in(body: dict[str, Any], taken: set[str]) -> dict[str, Any]:
    rid = str(body.get("id", "")).strip().lower()
    name = str(body.get("name", "")).strip()[:12]
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,15}", rid):
        raise ValueError("id 用小写字母开头，只能有字母、数字、下划线")
    if rid in taken or rid in ("owner", "hall") or rid.startswith("vacant"):
        raise ValueError(f"id {rid} 已经有人用了")
    if not name:
        raise ValueError("起个名字")
    d = body.get("driver") or {}
    kind = str(d.get("type", "openai_api"))
    if kind not in MOVE_IN_DRIVERS:
        raise ValueError("页面上只能办 OpenAI 兼容接口的入住，其他接入方式写 home.yaml")
    driver: dict[str, Any] = {"type": kind}
    if kind == "openai_api":
        url, model, env = str(d.get("base_url", "")).strip(), str(d.get("model", "")).strip(), str(d.get("api_key_env", "")).strip()
        if not re.match(r"https?://", url) or not model:
            raise ValueError("接口地址和模型名都要填")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*_API_KEY", env):       # 只接受这种名字，别的环境变量不会被发到接口上
            raise ValueError("key 的环境变量名要像 GLM_API_KEY 这样，以 _API_KEY 结尾")
        driver.update(base_url=url, model=model, api_key_env=env)
    color = str(body.get("color") or "#8aa0b8")
    return {"id": rid, "name": name, "model_label": str(body.get("model_label", "")).strip()[:16], "color": color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#8aa0b8",
            "sleep": ["01:00", "08:30"], "daily_calls": 30, "likes": {}, "persona": str(body.get("persona", "")).strip()[:200], "driver": driver}


def load_activities() -> dict[str, dict[str, Any]]:
    p = ROOT / "activities.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def make_layout(cfg: dict[str, Any]) -> dict[str, Any]:
    templates = load_templates(ROOT / "rooms")
    return build_layout(cfg["residents"], cfg.get("rooms") or DEFAULT_ROOMS, templates, cfg.get("outdoors", DEFAULT_OUTDOORS),
                        cfg.get("bedrooms", DEFAULT_BEDROOMS))


# ====================================================================== 启动
def main() -> None:
    ap = argparse.ArgumentParser(description="小窝", add_help=False)
    ap.add_argument("--config", default=os.environ.get("HOME_CONFIG", str(ROOT / "home.yaml")))
    ap.add_argument("--data", default=os.environ.get("HOME_DATA", str(ROOT / "data")))
    ap.add_argument("--mock", action="store_true", help="所有住户用模拟接入，不调用模型")
    ap.add_argument("--fast", action="store_true", help="时间加速：分钟当秒用，试运行时看得快一点")
    ap.add_argument("--no-hub", action="store_true", help="不连控制台中枢，单独运行")
    args, rest = ap.parse_known_args()
    args.no_hub = args.no_hub or not (os.environ.get("COZY_HUB") or "--hub" in rest)     # 默认单独运行，配了中枢地址才连

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg, cfg_path = load_config(Path(args.config))
    log.info("配置：%s", cfg_path)
    store = Store(Path(args.data) / "home.db")
    cfg = with_move_ins(cfg, store)
    layout = make_layout(cfg)

    m = Module(kind="home", name=cfg.get("name") or "小窝", version=VERSION, description="AI 住户的虚拟小窝",
               order=60, default_port=int(cfg.get("port", 8760)), section="xiaowo", section_title="小窝",
               home_stats="home_stats", summary="summary", alerts="alerts")
    hub = Hub()
    life = Life(cfg, layout, load_activities(), store, Path(args.data), mock=args.mock, fast=args.fast, emit=hub.emit)
    hub.module = m
    state = {"cfg_path": cfg_path, "config_arg": Path(args.config)}

    register_api(m, life, store, hub, state)
    register_panels(m, life, store)

    async def on_start():
        hub.loop = asyncio.get_running_loop()
        hub.task = asyncio.create_task(hub.run())
        life.start()
        log.info("小窝开张：住户 %s%s", "、".join(r.name for r in life.residents.values()),
                 "（模拟模式）" if args.mock else "")

    async def on_stop():
        life.stop()

    m.on_start.append(on_start)
    m.on_stop.append(on_stop)

    if args.no_hub:
        async def no_presence():
            await asyncio.Event().wait()

        async def no_unregister():
            return None
        m._presence_loop = no_presence      # type: ignore[method-assign]
        m._unregister = no_unregister        # type: ignore[method-assign]
    m.run(rest)


# ====================================================================== 实时推送
class Hub:
    """把住户线程里的事件推给所有打开的小窝页面，同时转一份给控制台中枢。"""
    HUB_TOPICS = {"feed": "home_feed", "chat": "home_chat", "resident": "home_residents", "home": "home_residents"}

    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: asyncio.Queue | None = None
        self.clients: set[WebSocket] = set()
        self.module: Module | None = None
        self.task = None
        self._last_resident_emit = 0.0

    def emit(self, typ: str, data: Any) -> None:
        msg = json.dumps({"type": typ, "data": data}, ensure_ascii=False, default=str)
        if self.loop and self.queue is not None:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, msg)
        topic = self.HUB_TOPICS.get(typ)
        if topic and self.module:
            if topic == "home_residents":   # 住户状态变化频繁，给控制台的提示每 3 秒最多一次
                now = time.time()
                if now - self._last_resident_emit < 3:
                    return
                self._last_resident_emit = now
            self.module.emit(topic, None)

    async def run(self) -> None:
        self.queue = asyncio.Queue(maxsize=2000)
        while True:
            msg = await self.queue.get()
            dead = []
            for ws in list(self.clients):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.clients.discard(ws)


# ====================================================================== 小窝页面用的接口
def register_api(m: Module, life: Life, store: Store, hub: Hub, state: dict[str, Any]) -> None:
    r = m.router

    def token() -> str:
        return str(life.cfg.get("access_token") or "")

    def guard(request: Request) -> None:
        t = token()
        if t and request.headers.get("x-home-token") != t and request.query_params.get("token") != t:
            raise HTTPException(401, "需要访问口令")

    def safe_file(base: Path, rel: str) -> Path:
        p = (base / rel).resolve()
        if not p.is_relative_to(base.resolve()) or not p.is_file():
            raise HTTPException(404, "没有这个文件")
        return p

    @r.get("/")
    async def index():
        return FileResponse(WEB / "index.html", headers={"cache-control": "no-cache"})

    @r.get("/avatars")
    async def avatars():
        return FileResponse(WEB / "avatars.html", headers={"cache-control": "no-cache"})

    @r.get("/web/{path:path}")
    async def web_file(path: str):
        return FileResponse(safe_file(WEB, path), headers={"cache-control": "no-cache"})

    @r.get("/skin/{path:path}")
    async def skin_file(path: str):
        skin = Path(life.cfg.get("skin_dir") or ROOT / "skin")
        if not skin.is_absolute():
            skin = ROOT / skin
        return FileResponse(safe_file(skin, path), headers={"cache-control": "max-age=3600"})

    @r.get("/api/state")
    async def api_state(request: Request):
        guard(request)
        return life.state()

    @r.get("/api/layout")
    async def api_layout(request: Request):
        guard(request)
        return life.layout

    @r.get("/api/feed")
    async def api_feed(request: Request, limit: int = 40, before: int | None = None):
        guard(request)
        return {"items": store.list_feed(min(limit, 200), before)}

    @r.post("/api/feed/{fid}/seen")
    async def api_seen(fid: int, request: Request):
        guard(request)
        row = store.mark_seen(fid)
        hub.emit("feed_update", row)
        return row

    @r.get("/api/chat")
    async def api_chat(request: Request, limit: int = 60, before: int | None = None):
        guard(request)
        return {"items": store.list_chat(min(limit, 300), before)}

    @r.post("/api/chat")
    async def api_chat_post(request: Request):
        guard(request)
        body = await request.json()
        try:
            return life.post_owner(body.get("text", ""))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @r.get("/api/residents/{rid}")
    async def api_resident(rid: str, request: Request):
        guard(request)
        res = life.residents.get(rid)
        if not res:
            raise HTTPException(404, "没有这个住户")
        return {**life.public(res), "memory": store.list_memory(rid), "persona": res.cfg.get("persona", ""),
                "relations": life.relations_public(res)}

    @r.post("/api/residents/{rid}/poke")
    async def api_poke(rid: str, request: Request):
        guard(request)
        try:
            return {"ok": True, "message": life.poke(rid)}
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    @r.post("/api/residents/{rid}/interact")
    async def api_interact(rid: str, request: Request):
        guard(request)
        body = await request.json()
        try:
            return {"ok": True, "message": life.interact(rid, str(body.get("action", "")))}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @r.post("/api/party")
    async def api_party(request: Request):
        guard(request)
        return {"ok": True, "message": life.party()}

    @r.post("/api/touch")
    async def api_touch(request: Request):
        guard(request)
        body = await request.json()
        try:
            return life.touch(str(body.get("room", "")), str(body.get("kind", "")))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @r.get("/api/weekly")
    async def api_weekly(request: Request, end: str | None = None):
        guard(request)
        try:
            return life.weekly(end)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    def need_move_in() -> None:
        if not life.life.get("move_in", False):
            raise HTTPException(403, "入住功能没打开，home.yaml 里 life.move_in 写 true 才能用")

    @r.post("/api/movein/check")
    async def api_movein_check(request: Request):
        guard(request)
        need_move_in()
        body = await request.json()
        try:
            rc = clean_move_in(body, set(life.residents))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        def trial() -> dict[str, Any]:
            drv = make_driver(rc["driver"], life.data_dir / "sandbox" / rc["id"], 40)
            ok, info = drv.check()
            if not ok:
                return {"ok": False, "message": info}
            gen = drv.generate("你在做接入测试。", "回一个字：好", "line")
            return {"ok": gen.ok, "message": f"接通了，回复：{gen.text[:30]}" if gen.ok else gen.error}
        return await asyncio.to_thread(trial)

    @r.post("/api/movein")
    async def api_movein(request: Request):
        guard(request)
        need_move_in()
        body = await request.json()
        try:
            rc = clean_move_in(body, set(life.residents))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        saved = store.load_state(MOVE_IN_KEY).get("residents") or []
        store.save_state(MOVE_IN_KEY, {"residents": [*saved, rc]})
        try:
            msg = reload_config(life, state)
        except (ValueError, LayoutError, yaml.YAMLError) as exc:
            store.save_state(MOVE_IN_KEY, {"residents": saved})
            raise HTTPException(400, str(exc))
        return {"ok": True, "message": f"{rc['name']} 搬进来了。{msg}"}

    @r.post("/api/gather")
    async def api_gather(request: Request):
        guard(request)
        return {"ok": True, "message": life.gather()}

    # ---------- 记忆管理
    def memory_row(mid: int) -> dict[str, Any]:
        row = store.get_memory(mid)
        if not row:
            raise HTTPException(404, "没有这条记忆")
        return row

    @r.get("/api/residents/{rid}/memory")
    async def api_memory(rid: str, request: Request):
        guard(request)
        if rid not in life.residents:
            raise HTTPException(404, "没有这个住户")
        return {"items": store.list_memory(rid)}

    @r.post("/api/residents/{rid}/memory")
    async def api_memory_add(rid: str, request: Request):
        guard(request)
        res = life.residents.get(rid)
        if not res:
            raise HTTPException(404, "没有这个住户")
        body = await request.json()
        try:
            return life.remember(res, body.get("text", ""), "owner", 2)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @r.patch("/api/memory/{mid}")
    async def api_memory_edit(mid: int, request: Request):
        guard(request)
        memory_row(mid)
        body = await request.json()
        try:
            return store.update_memory(mid, body.get("text"), body.get("pinned"), body.get("importance"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc))

    @r.delete("/api/memory/{mid}")
    async def api_memory_delete(mid: int, request: Request):
        guard(request)
        memory_row(mid)
        store.delete_memory(mid)
        return {"ok": True}

    # ---------- 留言、日报、回放、用量、天气
    @r.get("/api/notes")
    async def api_notes(request: Request, limit: int = 50):
        guard(request)
        return {"items": store.list_notes(min(limit, 200))}

    @r.post("/api/notes")
    async def api_note_add(request: Request):
        guard(request)
        body = await request.json()
        try:
            return life.post_note(str(body.get("to", "")), body.get("text", ""))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @r.post("/api/notes/read")
    async def api_notes_read(request: Request):
        guard(request)
        life.read_owner_notes()
        return {"ok": True}

    @r.get("/api/daily")
    async def api_daily(request: Request, day: str | None = None):
        guard(request)
        try:
            return life.daily(day)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @r.get("/api/replay")
    async def api_replay(request: Request, day: str | None = None):
        guard(request)
        try:
            return life.replay(day)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @r.get("/api/usage")
    async def api_usage(request: Request, days: int = 7):
        guard(request)
        return life.usage_report(days)

    @r.post("/api/weather")
    async def api_weather(request: Request):
        guard(request)
        body = await request.json()
        try:
            return {"ok": True, "message": life.force_weather(str(body.get("kind", "")))}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @r.post("/api/pause")
    async def api_pause(request: Request):
        guard(request)
        body = await request.json()
        life.set_paused(bool(body.get("paused")))
        return life.home_info()

    @r.post("/api/recheck")
    async def api_recheck(request: Request):
        guard(request)
        life.recheck()
        return {"ok": True}

    @r.post("/api/reload")
    async def api_reload(request: Request):
        guard(request)
        try:
            msg = reload_config(life, state)
        except (ValueError, LayoutError, yaml.YAMLError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return {"ok": True, "message": msg}

    @r.websocket("/ws")
    async def ws(sock: WebSocket):
        t = token()
        if t and sock.query_params.get("token") != t:
            await sock.close(code=4401)
            return
        await sock.accept()
        hub.clients.add(sock)
        life.owner_online(len(hub.clients))
        try:
            while True:
                await sock.receive_text()       # 页面不往这里发东西，只用来保持连接
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(sock)
            life.owner_online(len(hub.clients))


def reload_config(life: Life, state: dict[str, Any]) -> str:
    cfg, p = load_config(state["config_arg"])
    cfg = with_move_ins(cfg, life.store)
    layout = make_layout(cfg)
    life.apply(cfg, layout, load_activities())
    state["cfg_path"] = p
    return f"已重新读取 {p.name}：{len(life.residents)} 个住户，{len(layout['rooms'])} 个房间"


# ====================================================================== 控制台里的「小窝」页
def register_panels(m: Module, life: Life, store: Store) -> None:
    STATUS = {"offline": ("离线", "crit"), "asleep": ("睡着", ""), "idle": ("醒着", "ok"), "busy": ("忙", "ok")}

    def page_url() -> str:
        host = (m.base_url or "").split("//")[-1].split(":")[0] or "本机IP"
        return f"http://{host}:{m.base_url.rsplit(':', 1)[-1] if m.base_url else life.cfg.get('port', 8760)}/"

    m.panel("overview", "stats", "小窝", source="overview", refresh=10, width=2, refresh_on=["home_residents"])
    m.panel("residents", "table", "住户", source="residents", refresh=15, width=2, refresh_on=["home_residents"])
    m.panel("feed", "log", "动态", source="feed", refresh=30, refresh_on=["home_feed"])
    m.panel("chat", "log", "群聊", source="chat", refresh=30, refresh_on=["home_chat"])
    m.panel("links", "kv", "打开", source="links", refresh=0)
    m.panel("ops", "actions", "操作")

    @m.source("overview")
    def overview():
        rs = list(life.residents.values())
        awake = sum(1 for r in rs if r.status in ("idle", "busy"))
        calls = sum(store.usage(life.day(), r.id)["calls"] for r in rs)
        return {"items": [
            {"label": "醒着", "value": f"{awake}/{len(rs)}", "level": "ok" if awake else ""},
            {"label": "离线", "value": sum(1 for r in rs if r.status == "offline"),
             "level": "warn" if any(r.status == "offline" for r in rs) else ""},
            {"label": "今日动态", "value": store.feed_count_today(life.day_start())},
            {"label": "今日调用", "value": calls},
            {"label": "全屋", "value": "暂停中" if life.paused else "正常", "level": "warn" if life.paused else "ok"},
        ]}

    @m.source("residents")
    def residents():
        rows = []
        for r in life.residents.values():
            st, lv = STATUS.get(r.status, (r.status, ""))
            use = store.usage(life.day(), r.id)
            rows.append({"cells": [r.name, life.place_name(r.room, r.spot) or "-", r.activity, r.driver.label,
                                   {"text": f"{use['calls']}/{r.daily_calls}",
                                    "bar": min(100, round(use["calls"] * 100 / max(r.daily_calls, 1)))},
                                   {"text": st + (f" · {r.note[:40]}" if r.note else ""), "level": lv}],
                         "actions": [{"action": "poke", "label": "去做点什么", "params": {"resident": r.id}}]})
        return {"columns": ["住户", "在哪", "在做什么", "接入", "今日调用", "状态"], "rows": rows}

    def who(rid: str) -> str:
        if rid == "owner":
            return life.cfg.get("owner", "主人")
        r = life.residents.get(rid)
        return r.name if r else (rid or "小窝")

    @m.source("feed")
    def feed():
        lines = []
        for f in store.list_feed(30):
            t = life.clock(f["ts"]).strftime("%m-%d %H:%M")
            extra = f" ——{f['detail']}" if f.get("detail") else ""
            lines.append({"text": f"{t} {who(f['resident'])} {f['text']}{extra}",
                          "level": "warn" if f["kind"] == "system" else ""})
        return {"lines": lines}

    @m.source("chat")
    def chat():
        return {"lines": [f"{life.clock(c['ts']).strftime('%H:%M')} {who(c['sender'])}：{c['text']}"
                          for c in reversed(store.list_chat(30))]}

    @m.source("links")
    def links():
        return {"items": [{"label": "小窝页面", "value": page_url()},
                          {"label": "模式", "value": "模拟住户" if life.mock else "真实接入"}]}

    @m.source("home_stats")
    def home_stats():
        rs = list(life.residents.values())
        awake = sum(1 for r in rs if r.status in ("idle", "busy"))
        return {"items": [{"label": "小窝醒着", "value": f"{awake}/{len(rs)}", "level": ""}]}

    @m.source("summary")
    def summary():
        rs = list(life.residents.values())
        return {"text": "小窝 · " + " ".join(f"{r.name}{STATUS.get(r.status, ('', ''))[0]}" for r in rs), "level": ""}

    @m.source("alerts")
    def alerts():
        return {"items": [{"text": f"小窝：{r.name} 没接上（{r.note or r.ready_info}）", "level": "warn", "link": "#/xiaowo"}
                          for r in life.residents.values() if r.status == "offline"]}

    @m.source("resident_options")
    def resident_options():
        return {"options": [{"value": r.id, "label": r.name} for r in life.residents.values()]}

    @m.action("poke", "让她去做点什么", group="住户",
              params=[{"name": "resident", "label": "住户", "type": "choice", "options_source": "resident_options"}])
    def poke(resident: str):
        return {"output": life.poke(resident)}

    @m.action("say", "在群里说一句", group="住户",
              params=[{"name": "text", "label": "说什么", "type": "text"}])
    def say(text: str):
        life.post_owner(text)
        return {"output": "发出去了"}

    @m.action("pause", "全屋暂停", group="全屋", confirm=True)
    def pause():
        life.set_paused(True)
        return {"output": "已暂停：住户不再调用模型，也不换地方"}

    @m.action("resume", "恢复", group="全屋")
    def resume():
        life.set_paused(False)
        return {"output": "已恢复"}

    @m.action("recheck", "重新检查接入", group="全屋")
    def recheck():
        life.recheck()
        return {"output": "几秒后各住户会重新检查登录和 key"}


if __name__ == "__main__":
    main()
