"""住户刷到的内容。每个来源一个类，登记在 SOURCES 里；加新来源 = 写一个类 + 登记 + 在 home.yaml 的 sources 里开启。

来源只返回标题、作者/来源名、一小段简介和链接。这些都是网上的内容，交给模型时只当作资料。
"""
from __future__ import annotations

import html
import logging
import os
import random
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger("home.sources")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


@dataclass
class Item:
    key: str
    title: str
    site: str = ""        # 来源名：B站 / IT之家 / 书架
    by: str = ""          # UP 主 / 作者
    tag: str = ""         # 分区 / 栏目
    summary: str = ""
    url: str = ""


def clean(s: Any, n: int) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))
    s = "".join(ch for ch in s if ch.isprintable() or ch == " ")
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


class Source:
    name = ""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg or {}
        self.items: list[Item] = []
        self.updated = 0.0
        self.error = ""

    def interval(self) -> float:
        return float(self.cfg.get("refresh_minutes", 60)) * 60

    def fetch(self) -> list[Item]:
        return []

    def refresh(self) -> None:
        try:
            items = self.fetch()
            if items:
                self.items = items
                self.error = ""
            else:
                self.error = "没取到内容"
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            log.warning("内容来源 %s 刷新失败：%s", self.name, self.error)
        self.updated = time.time()


class Bilibili(Source):
    name = "bilibili"
    URL = "https://api.bilibili.com/x/web-interface/popular"

    def fetch(self):
        headers = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
        cookie = os.environ.get(self.cfg.get("cookie_env") or "BILI_COOKIE", "")
        if cookie:
            headers["Cookie"] = cookie
        r = httpx.get(self.URL, params={"ps": 40, "pn": 1}, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"B站返回 code={data.get('code')} {data.get('message', '')}")
        out = []
        for v in (data.get("data") or {}).get("list") or []:
            bvid = v.get("bvid") or str(v.get("aid", ""))
            out.append(Item(key=f"bili:{bvid}", title=clean(v.get("title"), 80), site="B站",
                            by=clean((v.get("owner") or {}).get("name"), 30), tag=clean(v.get("tname"), 20),
                            summary=clean(v.get("desc"), 120), url=f"https://www.bilibili.com/video/{bvid}"))
        return [i for i in out if i.title]


class Rss(Source):
    name = "rss"

    def fetch(self):
        out = []
        for feed in self.cfg.get("feeds") or []:
            try:
                r = httpx.get(feed["url"], headers={"User-Agent": UA}, timeout=15, follow_redirects=True)
                r.raise_for_status()
                root = ET.fromstring(r.content)
            except Exception as exc:
                log.warning("RSS %s 取不到：%s", feed.get("name"), type(exc).__name__)
                continue
            site = feed.get("name") or ""
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for it in root.iter("item"):
                title = clean(it.findtext("title"), 80)
                link = (it.findtext("link") or "").strip()
                if title:
                    out.append(Item(key=f"rss:{link or title}", title=title, site=site,
                                    summary=clean(it.findtext("description"), 120), url=link))
            for it in root.findall("a:entry", ns):
                title = clean(it.findtext("a:title", namespaces=ns), 80)
                le = it.find("a:link", ns)
                link = le.get("href", "") if le is not None else ""
                if title:
                    out.append(Item(key=f"rss:{link or title}", title=title, site=site,
                                    summary=clean(it.findtext("a:summary", namespaces=ns), 120), url=link))
        return out


class Shelf(Source):
    name = "shelf"

    def interval(self):
        return 10 ** 9

    def fetch(self):
        books = self.cfg if isinstance(self.cfg, list) else self.cfg.get("books") or []
        return [Item(key=f"book:{b.get('title')}", title=clean(b.get("title"), 60), site="书架", by=clean(b.get("by"), 30))
                for b in books if b.get("title")]


class Sample(Source):
    """模拟模式用的假内容，不联网。"""
    VIDEOS = ["蓝鲸的心脏到底有多大", "抹香鲸为什么竖着睡觉", "一百块在菜市场能做几道菜", "手搓一台迷你主机",
              "海边的雨季延时摄影", "从零开始养一缸水草", "老笔记本翻新全过程", "25 天做出一个小游戏",
              "深海里的发光生物", "一个人搬家的第一周", "给猫做一个纸箱城堡", "做了一个会说话的台灯"]
    POSTS = ["国产大模型这周又更新了什么", "家里的 NAS 该怎么备份", "迷你主机当服务器靠不靠谱", "怎么判断一条新闻的出处",
             "长期出差的人怎么整理照片", "开源项目的维护者都在想什么", "自建服务的内网穿透方案对比", "日常饮食怎么少油"]

    def __init__(self, kind: str):
        super().__init__({})
        self.kind = kind

    def interval(self):
        return 10 ** 9

    def fetch(self):
        if self.kind == "bilibili":
            return [Item(key=f"sample:v:{t}", title=t, site="B站", by="某个UP主", tag="生活") for t in self.VIDEOS]
        return [Item(key=f"sample:p:{t}", title=t, site="论坛") for t in self.POSTS]


SOURCES: dict[str, type[Source]] = {"bilibili": Bilibili, "rss": Rss, "shelf": Shelf}


class Sources:
    def __init__(self, cfg: dict[str, Any], mock: bool):
        self.sources: dict[str, Source] = {}
        for name, cls in SOURCES.items():
            sc = cfg.get(name)
            if sc is None:
                continue
            if isinstance(sc, dict) and sc.get("enabled") is False:
                continue
            if mock and name in ("bilibili", "rss"):
                self.sources[name] = Sample(name)
            else:
                self.sources[name] = cls(sc)
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="sources").start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            for s in self.sources.values():
                if now - s.updated >= s.interval():
                    s.refresh()
            self._stop.wait(20)

    def available(self, name: str) -> bool:
        s = self.sources.get(name)
        return bool(s and s.items)

    def pick(self, name: str, seen: Any) -> Item | None:
        s = self.sources.get(name)
        if not s or not s.items:
            return None
        fresh = [i for i in s.items if not seen(i.key)]
        return random.choice(fresh or s.items)

    def status(self) -> list[dict[str, Any]]:
        return [{"name": n, "items": len(s.items), "error": s.error, "updated": s.updated} for n, s in self.sources.items()]
