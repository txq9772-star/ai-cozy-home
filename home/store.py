"""小窝的存档：动态、群聊、住户记忆、每日调用次数、住户位置。SQLite 一个文件，data/home.db。"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS feed(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, resident TEXT, kind TEXT,
  room TEXT, spot TEXT, text TEXT, detail TEXT DEFAULT '', title TEXT DEFAULT '', url TEXT DEFAULT '',
  seen INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS chat(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, sender TEXT, text TEXT, depth INTEGER DEFAULT 0, reply_to INTEGER);
CREATE TABLE IF NOT EXISTS memory(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, resident TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS usage(day TEXT, resident TEXT, calls INTEGER DEFAULT 0, fails INTEGER DEFAULT 0,
  PRIMARY KEY(day, resident));
CREATE TABLE IF NOT EXISTS state(resident TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS seen_items(resident TEXT, key TEXT, ts REAL, PRIMARY KEY(resident, key));
CREATE TABLE IF NOT EXISTS relation(resident TEXT, other TEXT, score REAL DEFAULT 10, times INTEGER DEFAULT 0,
  last_ts REAL DEFAULT 0, note TEXT DEFAULT '', PRIMARY KEY(resident, other));
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, sender TEXT, recipient TEXT, text TEXT,
  read_at REAL DEFAULT 0, reply_to INTEGER);
CREATE TABLE IF NOT EXISTS trace(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, resident TEXT, room TEXT, spot TEXT,
  status TEXT, activity TEXT);
CREATE INDEX IF NOT EXISTS feed_ts ON feed(ts);
CREATE INDEX IF NOT EXISTS chat_ts ON chat(ts);
CREATE INDEX IF NOT EXISTS trace_ts ON trace(ts);
"""
MEMORY_KEEP = 60
MEMORY_TEXT_MAX = 200
MEMORY_COLUMNS = {"kind": "TEXT DEFAULT 'auto'", "importance": "INTEGER DEFAULT 1", "pinned": "INTEGER DEFAULT 0",
                  "hits": "INTEGER DEFAULT 1", "last_used": "REAL DEFAULT 0", "merged": "INTEGER DEFAULT 0"}
USAGE_COLUMNS = {"input_tokens": "INTEGER DEFAULT 0", "output_tokens": "INTEGER DEFAULT 0", "seconds": "REAL DEFAULT 0"}
RELATION_START, RELATION_MAX = 10.0, 100.0
RELATION_HALF_DAYS = 30.0     # 这么久没来往，亲近程度掉一半（不低于初始值）
TRACE_KEEP_DAYS = 14
NOTE_TEXT_MAX = 300


def relation_label(score: float) -> str:
    return "最亲近" if score >= 65 else "挺要好" if score >= 35 else "还算熟" if score >= 15 else "刚认识"


def _grams(text: str) -> set[str]:
    """按相邻两个字切开，中文不用分词也能比相似。"""
    t = re.sub(r"[\s，。！？、,.!?：:；;“”\"'（）()…~-]+", "", str(text or "").lower())
    return {t[i:i + 2] for i in range(len(t) - 1)} or ({t} if t else set())


def _same_memory(a: str, b: str) -> bool:
    ga, gb = _grams(a), _grams(b)
    return bool(ga and gb) and len(ga & gb) / len(ga | gb) >= 0.75


def _row(cur: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    return {d[0]: row[i] for i, d in enumerate(cur.description)}


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = _row
        self.lock = threading.RLock()
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
            for table, columns in (("memory", MEMORY_COLUMNS), ("usage", USAGE_COLUMNS)):   # 旧存档升级：原有数据都保留
                have = {c["name"] for c in self.db.execute(f"PRAGMA table_info({table})").fetchall()}
                for col, decl in columns.items():
                    if col not in have:
                        self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    def _q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            cur = self.db.execute(sql, args)
            return cur.lastrowid

    def backup(self, dest: Path) -> None:
        """在线备份整个存档，写到 dest。"""
        dest.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(dest))
        try:
            with self.lock:
                self.db.backup(target)
        finally:
            target.close()

    # ------------------------------------------------------------ 动态
    def add_feed(self, resident: str, kind: str, text: str, room: str = "", spot: str = "", detail: str = "",
                 title: str = "", url: str = "") -> dict[str, Any]:
        ts = time.time()
        fid = self._x("INSERT INTO feed(ts,resident,kind,room,spot,text,detail,title,url) VALUES(?,?,?,?,?,?,?,?,?)",
                      (ts, resident, kind, room, spot, text, detail, title, url))
        return self.get_feed(fid)

    def get_feed(self, fid: int) -> dict[str, Any]:
        rows = self._q("SELECT * FROM feed WHERE id=?", (fid,))
        return rows[0] if rows else {}

    def update_feed(self, fid: int, **fields: Any) -> dict[str, Any]:
        if fields:
            cols = ",".join(f"{k}=?" for k in fields)
            self._x(f"UPDATE feed SET {cols} WHERE id=?", (*fields.values(), fid))
        return self.get_feed(fid)

    def list_feed(self, limit: int = 40, before: int | None = None) -> list[dict[str, Any]]:
        if before:
            return self._q("SELECT * FROM feed WHERE id<? ORDER BY id DESC LIMIT ?", (before, limit))
        return self._q("SELECT * FROM feed ORDER BY id DESC LIMIT ?", (limit,))

    def mark_seen(self, fid: int) -> dict[str, Any]:
        self._x("UPDATE feed SET seen=1 WHERE id=?", (fid,))
        return self.get_feed(fid)

    def feed_count_today(self, day_start: float) -> int:
        return self._q("SELECT COUNT(*) AS n FROM feed WHERE ts>=? AND kind!='system'", (day_start,))[0]["n"]

    def last_feed_of(self, resident: str, n: int = 3) -> list[dict[str, Any]]:
        return self._q("SELECT * FROM feed WHERE resident=? AND kind='activity' ORDER BY id DESC LIMIT ?", (resident, n))

    # ------------------------------------------------------------ 群聊
    def add_chat(self, sender: str, text: str, depth: int = 0, reply_to: int | None = None) -> dict[str, Any]:
        cid = self._x("INSERT INTO chat(ts,sender,text,depth,reply_to) VALUES(?,?,?,?,?)",
                      (time.time(), sender, text, depth, reply_to))
        return self._q("SELECT * FROM chat WHERE id=?", (cid,))[0]

    def list_chat(self, limit: int = 60, before: int | None = None) -> list[dict[str, Any]]:
        if before:
            rows = self._q("SELECT * FROM chat WHERE id<? ORDER BY id DESC LIMIT ?", (before, limit))
        else:
            rows = self._q("SELECT * FROM chat ORDER BY id DESC LIMIT ?", (limit,))
        return list(reversed(rows))

    def last_chat_ts(self) -> float:
        rows = self._q("SELECT MAX(ts) AS t FROM chat")
        return rows[0]["t"] or 0.0

    # ------------------------------------------------------------ 记忆（只在小窝里用，不连任何外部记忆）
    # kind：auto 住户自己记的 / owner 主人教的 / together 和别人一起的事 / summary 睡前整理的
    # merged=1 表示已经被整理进一条 summary，不再进提示词，满了先删它们
    def add_memory(self, resident: str, text: str, kind: str = "auto", importance: int = 1) -> dict[str, Any]:
        text = " ".join(str(text or "").split())[:MEMORY_TEXT_MAX]
        if not text:
            raise ValueError("记忆不能是空的")
        now = time.time()
        for row in self._q("SELECT * FROM memory WHERE resident=? AND merged=0", (resident,)):
            if _same_memory(row["text"], text):      # 同一件事不存两遍，只提高分量
                self._x("UPDATE memory SET ts=?, hits=hits+1, importance=? WHERE id=?",
                        (now, max(row["importance"], importance), row["id"]))
                return self.get_memory(row["id"])
        mid = self._x("INSERT INTO memory(ts,resident,text,kind,importance) VALUES(?,?,?,?,?)",
                      (now, resident, text, kind, importance))
        self._x("DELETE FROM memory WHERE resident=? AND pinned=0 AND id NOT IN (SELECT id FROM memory WHERE resident=? "
                "ORDER BY pinned DESC, merged ASC, importance DESC, id DESC LIMIT ?)", (resident, resident, MEMORY_KEEP))
        return self.get_memory(mid)

    def get_memory(self, mid: int) -> dict[str, Any]:
        rows = self._q("SELECT * FROM memory WHERE id=?", (mid,))
        return rows[0] if rows else {}

    def update_memory(self, mid: int, text: str | None = None, pinned: bool | None = None,
                      importance: int | None = None) -> dict[str, Any]:
        if text is not None:
            text = " ".join(str(text).split())[:MEMORY_TEXT_MAX]
            if not text:
                raise ValueError("记忆不能是空的")
            self._x("UPDATE memory SET text=? WHERE id=?", (text, mid))
        if pinned is not None:
            self._x("UPDATE memory SET pinned=? WHERE id=?", (1 if pinned else 0, mid))
        if importance is not None:
            self._x("UPDATE memory SET importance=? WHERE id=?", (max(1, min(3, int(importance))), mid))
        return self.get_memory(mid)

    def delete_memory(self, mid: int) -> None:
        self._x("DELETE FROM memory WHERE id=?", (mid,))

    def recent_memory(self, resident: str, n: int = 5) -> list[str]:
        rows = self._q("SELECT text FROM memory WHERE resident=? AND merged=0 ORDER BY id DESC LIMIT ?", (resident, n))
        return [r["text"] for r in reversed(rows)]

    def recall_memory(self, resident: str, query: str = "", n: int = 5) -> list[str]:
        """挑这次最该想起来的几条：置顶的一定在，其余按相关、分量和新旧打分。"""
        rows = self._q("SELECT * FROM memory WHERE resident=? AND merged=0", (resident,))
        if not rows:
            return []
        now, q = time.time(), _grams(query)

        def score(m: dict[str, Any]) -> float:
            g = _grams(m["text"])
            related = len(g & q) / max(len(g), 1)
            fresh = math.exp(-max(now - m["ts"], 0) / (14 * 86400))
            return related * 3 + m["importance"] * 0.5 + fresh + min(m["hits"], 3) * 0.1

        pinned = sorted((m for m in rows if m["pinned"]), key=score, reverse=True)[:max(1, n // 2)]
        rest = sorted((m for m in rows if not m["pinned"]), key=score, reverse=True)
        picked = pinned + rest[:max(n - len(pinned), 0)]
        with self.lock:
            for m in picked:
                self.db.execute("UPDATE memory SET last_used=? WHERE id=?", (now, m["id"]))
        return [m["text"] for m in sorted(picked, key=lambda m: m["id"])]

    def list_memory(self, resident: str) -> list[dict[str, Any]]:
        return self._q("SELECT * FROM memory WHERE resident=? ORDER BY pinned DESC, merged ASC, id DESC", (resident,))

    def memory_to_reflect(self, resident: str, since: float) -> list[dict[str, Any]]:
        return self._q("SELECT * FROM memory WHERE resident=? AND merged=0 AND pinned=0 AND kind IN ('auto','together','chat') "
                       "AND ts>=? ORDER BY id", (resident, since))

    def mark_merged(self, ids: list[int]) -> None:
        with self.lock:
            for mid in ids:
                self.db.execute("UPDATE memory SET merged=1 WHERE id=?", (mid,))

    # ------------------------------------------------------------ 用量
    def usage_inc(self, day: str, resident: str, ok: bool, meta: dict[str, Any] | None = None) -> None:
        m = meta or {}
        self._x("INSERT INTO usage(day,resident,calls,fails,input_tokens,output_tokens,seconds) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(day,resident) DO UPDATE SET calls=calls+excluded.calls, fails=fails+excluded.fails, "
                "input_tokens=input_tokens+excluded.input_tokens, output_tokens=output_tokens+excluded.output_tokens, "
                "seconds=seconds+excluded.seconds",
                (day, resident, 1, 0 if ok else 1, int(m.get("input_tokens") or 0), int(m.get("output_tokens") or 0),
                 float(m.get("seconds") or 0)))

    def usage(self, day: str, resident: str) -> dict[str, int]:
        rows = self._q("SELECT calls, fails FROM usage WHERE day=? AND resident=?", (day, resident))
        return rows[0] if rows else {"calls": 0, "fails": 0}

    def usage_since(self, day: str) -> list[dict[str, Any]]:
        return self._q("SELECT * FROM usage WHERE day>=? ORDER BY day", (day,))

    # ------------------------------------------------------------ 关系（A 对 B 的印象，other 可以是 owner）
    @staticmethod
    def _decayed(row: dict[str, Any], now: float) -> float:
        idle = max(now - row["last_ts"], 0) / 86400 if row["last_ts"] else 0
        extra = max(row["score"] - RELATION_START, 0) * 0.5 ** (idle / RELATION_HALF_DAYS)
        return min(row["score"], RELATION_START + extra)

    def bump_relation(self, resident: str, other: str, amount: float, note: str = "") -> None:
        now = time.time()
        with self.lock:
            rows = self._q("SELECT * FROM relation WHERE resident=? AND other=?", (resident, other))
            score = self._decayed(rows[0], now) if rows else RELATION_START
            score = min(score + amount, RELATION_MAX)
            keep = " ".join(str(note).split())[:120] or (rows[0]["note"] if rows else "")
            self._x("INSERT INTO relation(resident,other,score,times,last_ts,note) VALUES(?,?,?,1,?,?) "
                    "ON CONFLICT(resident,other) DO UPDATE SET score=excluded.score, times=times+1, "
                    "last_ts=excluded.last_ts, note=excluded.note", (resident, other, score, now, keep))

    def relations(self, resident: str) -> list[dict[str, Any]]:
        now = time.time()
        out = []
        for row in self._q("SELECT * FROM relation WHERE resident=?", (resident,)):
            score = round(self._decayed(row, now), 1)
            out.append({**row, "score": score, "label": relation_label(score)})
        return sorted(out, key=lambda r: r["score"], reverse=True)

    def relation_score(self, resident: str, other: str) -> float:
        rows = self._q("SELECT * FROM relation WHERE resident=? AND other=?", (resident, other))
        return self._decayed(rows[0], time.time()) if rows else RELATION_START

    # ------------------------------------------------------------ 留言（主人和住户之间）
    def add_note(self, sender: str, recipient: str, text: str, reply_to: int | None = None) -> dict[str, Any]:
        text = " ".join(str(text or "").split())[:NOTE_TEXT_MAX]
        if not text:
            raise ValueError("留言不能是空的")
        nid = self._x("INSERT INTO notes(ts,sender,recipient,text,reply_to) VALUES(?,?,?,?,?)",
                      (time.time(), sender, recipient, text, reply_to))
        return self._q("SELECT * FROM notes WHERE id=?", (nid,))[0]

    def list_notes(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._q("SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,))

    def unread_notes(self, recipient: str) -> list[dict[str, Any]]:
        return self._q("SELECT * FROM notes WHERE recipient=? AND read_at=0 ORDER BY id", (recipient,))

    def unread_from(self, sender: str, recipient: str) -> int:
        return self._q("SELECT COUNT(*) AS n FROM notes WHERE sender=? AND recipient=? AND read_at=0",
                       (sender, recipient))[0]["n"]

    def mark_note_read(self, nid: int) -> None:
        self._x("UPDATE notes SET read_at=? WHERE id=?", (time.time(), nid))

    def mark_notes_read(self, recipient: str) -> None:
        self._x("UPDATE notes SET read_at=? WHERE recipient=? AND read_at=0", (time.time(), recipient))

    # ------------------------------------------------------------ 足迹（回放用）
    def add_trace(self, resident: str, room: str, spot: str, status: str, activity: str) -> None:
        self._x("INSERT INTO trace(ts,resident,room,spot,status,activity) VALUES(?,?,?,?,?,?)",
                (time.time(), resident, room, spot, status, activity))

    def prune_trace(self) -> None:
        self._x("DELETE FROM trace WHERE ts<?", (time.time() - TRACE_KEEP_DAYS * 86400,))

    def trace_between(self, start: float, end: float) -> list[dict[str, Any]]:
        return self._q("SELECT * FROM trace WHERE ts>=? AND ts<? ORDER BY id", (start, end))

    def trace_before(self, ts: float) -> list[dict[str, Any]]:
        return self._q("SELECT t.* FROM trace t JOIN (SELECT resident, MAX(id) AS id FROM trace WHERE ts<? GROUP BY resident) m "
                       "ON t.id=m.id", (ts,))

    # ------------------------------------------------------------ 按天查（日报、回放）
    def feed_between(self, start: float, end: float) -> list[dict[str, Any]]:
        return self._q("SELECT * FROM feed WHERE ts>=? AND ts<? ORDER BY id", (start, end))

    def chat_between(self, start: float, end: float) -> list[dict[str, Any]]:
        return self._q("SELECT * FROM chat WHERE ts>=? AND ts<? ORDER BY id", (start, end))

    def notes_between(self, start: float, end: float) -> list[dict[str, Any]]:
        return self._q("SELECT * FROM notes WHERE ts>=? AND ts<? ORDER BY id", (start, end))

    # ------------------------------------------------------------ 住户位置（重启后接着来）
    def save_state(self, resident: str, data: dict[str, Any]) -> None:
        self._x("INSERT INTO state(resident,data) VALUES(?,?) ON CONFLICT(resident) DO UPDATE SET data=excluded.data",
                (resident, json.dumps(data, ensure_ascii=False)))

    def load_state(self, resident: str) -> dict[str, Any]:
        rows = self._q("SELECT data FROM state WHERE resident=?", (resident,))
        try:
            return json.loads(rows[0]["data"]) if rows else {}
        except ValueError:
            return {}

    # ------------------------------------------------------------ 刷过的内容（不重复刷同一条）
    def item_seen(self, resident: str, key: str) -> bool:
        return bool(self._q("SELECT 1 FROM seen_items WHERE resident=? AND key=?", (resident, key)))

    def mark_item(self, resident: str, key: str) -> None:
        self._x("INSERT OR REPLACE INTO seen_items(resident,key,ts) VALUES(?,?,?)", (resident, key, time.time()))
        self._x("DELETE FROM seen_items WHERE ts<?", (time.time() - 14 * 86400,))
