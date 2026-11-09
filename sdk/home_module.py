"""模块 SDK（Python）

用法见 docs/PROTOCOL.md 和 modules/ 下的例子。一个模块 = 一个独立进程：

    from home_module import Module
    m = Module(kind="demo", name="示例")
    m.panel("hello", "stats", "问候", source="hello", refresh=5)

    @m.source("hello")
    def hello():
        return {"items": [{"label": "时间", "value": time.strftime("%H:%M:%S")}]}

    m.run()   # 自动注册到中枢、定时心跳、退出时注销

SDK 负责：起一个小 HTTP 服务（/manifest /health /data/* /action/*）、
找到本机对中枢可达的 IP、注册与心跳、中枢重启后自动重新注册。
模块里任何一个数据源或动作抛异常，只影响那一个面板，不会拖垮模块或中枢。
不用 Python 也可以写模块，只要实现同样的 HTTP 协议。
"""
from __future__ import annotations

import argparse
import asyncio
import queue
import threading
import inspect
from pathlib import Path
import logging
import os
import platform
import socket
import time
import traceback
from contextlib import asynccontextmanager
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

PROTOCOL_VERSION = 1
log = logging.getLogger("cozy.module")


class Module:
    def __init__(self, kind: str, name: str, version: str = "0.1.0",
                 description: str = "", icon: str = "", order: int = 100, default_port: int = 0,
                 section: str = "", **meta: Any):
        """section：放在控制台的哪个页面（自定义名字，配 section_title）。
        meta 里可以声明给控制台外框用的数据源名：summary（设备列表里的一句话）、home_stats（首页底栏读数）、
        alerts（通知铃铛）、device_directory（设备清单）。前端只按这些名字取数，不认识具体模块。"""
        self.kind = kind
        self.section = section
        self.meta = {k: v for k, v in meta.items() if v not in (None, "")}
        self.name = name
        self.version = version
        self.description = description
        self.icon = icon
        self.order = order
        self.host_label = platform.node()
        self.panels: list[dict[str, Any]] = []
        self.sources: dict[str, Callable[..., Any]] = {}
        self.actions: dict[str, dict[str, Any]] = {}
        self.action_fns: dict[str, Callable[..., Any]] = {}
        self.files: dict[str, Callable[[], Any]] = {}
        self.hub_url = ""
        self.token = ""
        self.base_url = ""
        self.hub_reachable = False
        self.default_port = default_port
        self.layout = ""  # "split" = 左边信息、右边封面图铺满半屏；"wide" = 占满整行
        self.on_start: list[Callable[[], Any]] = []
        self.on_stop: list[Callable[[], Any]] = []
        # 模块自己的额外接口（例如编排中心给 agent 用的 API），挂在同一个端口上
        self.router = APIRouter()
        self._events: queue.Queue = queue.Queue(maxsize=5000)
        self._dropped = 0

    # ------------------------------------------------------------ 声明
    @property
    def id(self) -> str:
        return f"{self.kind}@{self.host_label}"

    def panel(self, id: str, type: str, title: str, source: str | None = None,
              refresh: float = 5, width: int = 1, **extra: Any) -> None:
        """声明一个面板。type: stats / table / log / actions / kv / text / board / constellation / pipeline / hero。
        refresh 秒，0 = 只在打开和手动刷新时拉取。width: 1 或 2（在卡片内占一列或整行）。
        extra 里可写 tab（页面里的子栏目名）和 section（这个面板单独放到别的页面）。"""
        self.panels.append({"id": id, "type": type, "title": title, "source": source,
                            "refresh": refresh, "width": width, **extra})

    def source(self, name: str):
        def deco(fn: Callable[..., Any]):
            self.sources[name] = fn
            return fn
        return deco

    def file(self, name: str, path: Any) -> None:
        """声明一个可以给页面用的文件（图片、视频），页面经中枢的 /api/m/<模块>/file/<name> 读取。
        path 可以是路径，也可以是返回路径的函数（返回空表示暂时没有）。只暴露这里登记的文件，不按路径浏览。"""
        self.files[name] = path if callable(path) else (lambda p=path: p)

    def action(self, id: str, label: str, confirm: bool = False, danger: bool = False,
               group: str = "", params: list[dict[str, Any]] | None = None, description: str = ""):
        """声明一个动作。confirm=True 时前端会二次确认；danger=True 显示为危险按钮。
        params: [{"name": "lines", "label": "行数", "type": "number", "default": 50}]"""
        def deco(fn: Callable[..., Any]):
            self.actions[id] = {"id": id, "label": label, "confirm": confirm, "danger": danger,
                                "group": group, "params": params or [], "description": description}
            self.action_fns[id] = fn
            return fn
        return deco

    def add_action(self, id: str, fn: Callable[..., Any], **meta: Any) -> None:
        self.action(id, **meta)(fn)

    def emit(self, topic: str, data: Any = None) -> None:
        """向所有打开的控制台页面推送一条实时事件（线程安全、不阻塞）。
        前端：面板声明 refresh_on=["topic"] 会在收到事件时自动刷新；详情弹窗可订阅流式输出。"""
        try:
            self._events.put_nowait({"topic": topic, "data": data})
        except queue.Full:
            self._dropped += 1

    def update_manifest(self) -> None:
        """面板或动作的声明变了（例如表单默认值），马上把新清单推给中枢，控制台会重建这张卡片。"""
        self._manifest_dirty = True

    def check_token(self, request: Request) -> None:
        self._check(request)

    def manifest(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "host": self.host_label,
            "version": self.version,
            "description": self.description,
            "icon": self.icon,
            "order": self.order,
            "layout": self.layout,
            "section": self.section,
            **self.meta,
            "platform": f"{platform.system()} {platform.release()}",
            "panels": self.panels,
            "actions": list(self.actions.values()),
        }

    # ------------------------------------------------------------ HTTP 服务
    def _check(self, request: Request) -> None:
        if self.token and request.headers.get("x-cozy-token") != self.token:
            raise HTTPException(401, "token 无效")

    @staticmethod
    async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if inspect.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        return await run_in_threadpool(fn, *args, **kwargs)

    def build_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            for fn in self.on_start:
                await self._call(fn)
            task = asyncio.create_task(self._presence_loop())
            sender = asyncio.create_task(self._event_loop())
            yield
            task.cancel()
            sender.cancel()
            for fn in self.on_stop:
                try:
                    await self._call(fn)
                except Exception:
                    log.exception("on_stop 出错")
            await self._unregister()

        app = FastAPI(title=f"module {self.id}", lifespan=lifespan)

        @app.get("/health")
        async def health():
            return {"ok": True, "id": self.id, "ts": time.time()}

        @app.get("/manifest")
        async def manifest(request: Request):
            self._check(request)
            return self.manifest()

        @app.get("/data/{name}")
        async def data(name: str, request: Request):
            self._check(request)
            fn = self.sources.get(name)
            if fn is None:
                raise HTTPException(404, f"没有数据源 {name}")
            try:
                kwargs = dict(request.query_params) if inspect.signature(fn).parameters else {}
                return await self._call(fn, **kwargs)
            except Exception as exc:
                log.exception("数据源 %s 出错", name)
                return {"error": f"{type(exc).__name__}: {exc}"}

        @app.get("/files/{name}")
        async def files(name: str, request: Request):
            self._check(request)
            getter = self.files.get(name)
            path = getter() if getter else None
            if not path or not Path(path).is_file():
                raise HTTPException(404, f"没有文件 {name}")
            return FileResponse(path, headers={"cache-control": "private, max-age=3600"})

        @app.post("/action/{name}")
        async def action(name: str, request: Request):
            self._check(request)
            fn = self.action_fns.get(name)
            if fn is None:
                raise HTTPException(404, f"没有动作 {name}")
            try:
                params = await request.json()
            except Exception:
                params = {}
            try:
                result = await self._call(fn, **(params or {})) if inspect.signature(fn).parameters \
                    else await self._call(fn)
            except ValueError as exc:  # 参数校验失败：只回错误信息，不回堆栈
                return {"ok": False, "error": str(exc)}
            except Exception as exc:
                log.exception("动作 %s 出错", name)
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                        "detail": traceback.format_exc(limit=3)}
            if isinstance(result, dict):
                result.setdefault("ok", True)
                return result
            return {"ok": True, "result": result}

        app.include_router(self.router)
        return app

    # ------------------------------------------------------------ 注册 / 心跳
    def _headers(self) -> dict[str, str]:
        return {"x-cozy-token": self.token} if self.token else {}

    async def _register(self, client: httpx.AsyncClient) -> int:
        r = await client.post(f"{self.hub_url}/api/registry/register", headers=self._headers(),
                              json={"id": self.id, "base_url": self.base_url,
                                    "manifest": self.manifest(), "protocol": PROTOCOL_VERSION})
        r.raise_for_status()
        lease = int(r.json().get("lease_seconds", 15))
        log.info("已注册到中枢 %s（租约 %ss）", self.hub_url, lease)
        return lease

    async def _presence_loop(self) -> None:
        lease = 15
        registered = False
        async with httpx.AsyncClient(timeout=5) as client:
            while True:
                try:
                    if not registered or getattr(self, "_manifest_dirty", False):
                        self._manifest_dirty = False
                        lease = await self._register(client)
                        registered = True
                    else:
                        r = await client.post(f"{self.hub_url}/api/registry/heartbeat",
                                              headers=self._headers(), json={"id": self.id})
                        if r.status_code == 404:  # 中枢重启 / 被遗忘 → 重新注册
                            log.info("中枢不认识本模块，重新注册")
                            registered = False
                            continue
                        r.raise_for_status()
                    if not self.hub_reachable:
                        self.hub_reachable = True
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    reason = "口令(token)不对" if code == 401 else exc.response.text[:200]
                    log.warning("中枢拒绝注册（HTTP %s）：%s", code, reason)
                    self.hub_reachable = False
                    registered = False
                except Exception as exc:
                    if self.hub_reachable or not registered:
                        log.warning("连不上中枢 %s：%s（稍后重试）", self.hub_url, type(exc).__name__)
                    self.hub_reachable = False
                    registered = False
                for _ in range(int(max(1.0, lease / 3) / 0.5)):
                    if getattr(self, "_manifest_dirty", False):
                        break
                    await asyncio.sleep(0.5)

    async def _event_loop(self) -> None:
        """把 emit() 的事件批量转发给中枢，中枢再经 WebSocket 推给前端。中枢不在线就丢弃（事件只是提示刷新）。"""
        async with httpx.AsyncClient(timeout=5) as client:
            while True:
                await asyncio.sleep(0.3)
                batch = []
                while len(batch) < 200:
                    try:
                        batch.append(self._events.get_nowait())
                    except queue.Empty:
                        break
                if not batch or not self.hub_reachable:
                    continue
                try:
                    await client.post(f"{self.hub_url}/api/events", headers=self._headers(),
                                      json={"id": self.id, "events": batch})
                except Exception:
                    pass

    async def _unregister(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                await client.post(f"{self.hub_url}/api/registry/unregister",
                                  headers=self._headers(), json={"id": self.id})
            log.info("已从中枢注销（拔出）")
        except Exception:
            pass

    # ------------------------------------------------------------ 启动
    @staticmethod
    def _local_ip_towards(hub_url: str) -> str:
        host = urlparse(hub_url).hostname or "127.0.0.1"
        port = urlparse(hub_url).port or 80
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((host, port))  # UDP connect 不发包，只用来选路由
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"

    @staticmethod
    def _free_port() -> int:
        s = socket.socket()
        s.bind(("0.0.0.0", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def run(self, argv: list[str] | None = None) -> None:
        p = argparse.ArgumentParser(description=f"模块：{self.name}")
        p.add_argument("--hub", default=os.environ.get("COZY_HUB", "http://127.0.0.1:8700"),
                       help="中枢地址，默认取环境变量 COZY_HUB")
        p.add_argument("--token", default=os.environ.get("COZY_TOKEN", ""))
        p.add_argument("--port", type=int,
                       default=int(os.environ.get("COZY_MODULE_PORT", str(self.default_port))),
                       help="模块监听端口，0 = 自动选空闲端口")
        p.add_argument("--advertise", default=os.environ.get("COZY_ADVERTISE", ""),
                       help="告诉中枢用哪个 IP 访问本模块，默认自动探测")
        p.add_argument("--host-label", default=os.environ.get("COZY_HOST_LABEL", ""),
                       help="机器显示名，默认取主机名")
        p.add_argument("--bind", default="127.0.0.1")
        args = p.parse_args(argv)

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self.hub_url = args.hub.rstrip("/")
        self.token = args.token
        if args.host_label:
            self.host_label = args.host_label
        port = args.port or self._free_port()
        ip = args.advertise or self._local_ip_towards(self.hub_url)
        self.base_url = f"http://{ip}:{port}"
        log.info("模块 %s 启动：%s → 中枢 %s", self.id, self.base_url, self.hub_url)

        import uvicorn
        uvicorn.run(self.build_app(), host=args.bind, port=port, log_level="warning")
