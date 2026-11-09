"""小窝的测试：房子布局、两种接入的解析、提示词、日常调度。全部离线，不调用任何模型。

运行：python -m unittest discover -s tests -v
"""
import json
import os
import sqlite3
import stat
import sys
import tempfile
import textwrap
import time
import unittest
from collections import Counter
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from home import days, drivers, living, prompts  # noqa: E402
from home import life as life_mod  # noqa: E402
from home.layout import LayoutError, bedroom_style, build_layout, load_templates, spots_index  # noqa: E402
from home.life import Life  # noqa: E402
from home.store import Store  # noqa: E402

CFG = yaml.safe_load((ROOT / "home.example.yaml").read_text(encoding="utf-8"))
ACTS = yaml.safe_load((ROOT / "activities.yaml").read_text(encoding="utf-8"))
TPL = load_templates(ROOT / "rooms")
ROOMS = [{"template": t} for t in ("living", "study", "play", "kitchen", "storage")]


def reachable(layout, room_id):
    rooms = {r["id"]: r for r in layout["rooms"]}
    seen = set()
    r = rooms[room_id]
    while r["id"] != layout["hall"]:
        if r["id"] in seen or "parent" not in r:
            return False
        seen.add(r["id"])
        r = rooms[r["parent"]]
    return True


class LayoutTests(unittest.TestCase):
    def test_default_house(self):
        L = build_layout(CFG["residents"], ROOMS, TPL)
        ids = [r["id"] for r in L["rooms"]]
        self.assertEqual(ids[:4], ["ac", "ag", "ayu", "ak"])
        self.assertIn("hall", ids)
        for r in L["rooms"]:
            if r["kind"] == "hall":
                continue
            self.assertIn("door", r, r["id"])
            self.assertTrue(reachable(L, r["id"]), f"{r['id']} 走不到走廊")
        living = next(r for r in L["rooms"] if r["id"] == "living")
        self.assertEqual(living["entrance"]["wall"], "s")

    def test_playground_is_outside_the_front_door(self):
        L = build_layout(CFG["residents"], ROOMS, TPL, [{"template": "playground"}])
        yard = next(r for r in L["rooms"] if r["kind"] == "outdoor")
        living = next(r for r in L["rooms"] if r["id"] == "living")
        self.assertEqual(yard["parent"], "living")
        self.assertEqual(yard["door"], {"wall": "n", "at": living["entrance"]["at"]})
        self.assertEqual(yard["rect"][1], L["house"][3])
        self.assertTrue(reachable(L, yard["id"]))
        self.assertGreater(L["island"][3], yard["rect"][3])
        rides = {f["ride"] for f in yard["furniture"] if f.get("ride")}
        for sid, s in yard["spots"].items():
            if s.get("ride"):
                self.assertIn(s["ride"], rides, sid)

    def test_right_side_is_mirrored(self):
        L = build_layout(CFG["residents"], ROOMS, TPL)
        rooms = {r["id"]: r for r in L["rooms"]}
        self.assertEqual(rooms["kitchen"]["door"]["wall"], "e")      # 左边：门朝东开向客厅
        self.assertEqual(rooms["storage"]["door"]["wall"], "w")      # 右边：镜像后门朝西
        self.assertEqual(rooms["kitchen"]["parent"], "living")
        play = rooms["play"]
        self.assertLess(play["door"]["at"], (play["rect"][0] + play["rect"][2]) / 2)   # 镜像后门靠近客厅一侧

    def test_add_resident_and_room(self):
        residents = CFG["residents"] + [{"id": "x", "name": "阿X", "color": "#0a0"}]
        L = build_layout(residents, ROOMS + [{"template": "study", "name": "书房二"}], TPL)
        names = [r["name"] for r in L["rooms"]]
        self.assertIn("阿X的卧室", names)
        self.assertIn("书房二", names)
        xs = [r for r in L["rooms"] if r.get("owner") == "x"]
        self.assertEqual(len(xs), 1)
        for r in L["rooms"]:
            if r["kind"] != "hall":
                self.assertTrue(reachable(L, r["id"]))
        # 前后两排一样宽
        hall = next(r for r in L["rooms"] if r["kind"] == "hall")
        front = [r for r in L["rooms"] if r["rect"][1] >= hall["rect"][3] - 1e-6]
        self.assertAlmostEqual(min(r["rect"][0] for r in front), hall["rect"][0])
        self.assertAlmostEqual(max(r["rect"][2] for r in front), hall["rect"][2])

    def test_bedroom_spots_belong_to_owner(self):
        L = build_layout(CFG["residents"], ROOMS, TPL)
        beds = [s for s in spots_index(L) if "bed" in s["tags"]]
        self.assertEqual({s["owner"] for s in beds}, {"ac", "ag", "ayu", "ak"})

    def test_vacant_rooms(self):
        rooms = ROOMS + [{"template": "lounge"}, {"template": "library"}]
        L = build_layout(CFG["residents"], rooms, TPL, None, 8)
        empty = [r for r in L["rooms"] if r.get("vacant")]
        self.assertEqual(len(empty), 4)
        self.assertEqual(L["style"], "courtyard")
        self.assertEqual(L["house"][2] - L["house"][0], 42)
        for r in empty:
            self.assertFalse(r["spots"])
            self.assertNotIn("owner", r)
            self.assertTrue(reachable(L, r["id"]))
        self.assertFalse([s for s in spots_index(L) if s["room"] in {r["id"] for r in empty}])
        for r in L["rooms"]:
            if r["kind"] != "hall":
                self.assertTrue(reachable(L, r["id"]), r["id"])

    def test_moving_in_keeps_the_house(self):
        rooms = ROOMS + [{"template": "lounge"}, {"template": "library"}]
        before = build_layout(CFG["residents"], rooms, TPL, None, 8)
        L = build_layout(CFG["residents"] + [{"id": "glm", "name": "阿智"}], rooms, TPL, None, 8)
        after = {r["id"]: r for r in L["rooms"]}
        self.assertEqual(L["house"], before["house"])
        self.assertEqual(sum(1 for r in L["rooms"] if r.get("vacant")), 3)
        old_first_empty = next(r for r in before["rooms"] if r.get("vacant"))
        self.assertEqual(after["glm"]["rect"], old_first_empty["rect"])
        for r in before["rooms"]:
            if not r.get("vacant"):
                self.assertEqual(after[r["id"]]["rect"], r["rect"], r["id"])

    def test_courtyard_shape(self):
        rooms = ROOMS + [{"template": "lounge"}, {"template": "library"}]
        L = build_layout(CFG["residents"], rooms, TPL, [{"template": "playground"}, {"template": "lake"}], 8)
        by = {r["id"]: r for r in L["rooms"]}
        court = by["courtyard"]
        self.assertEqual(court["kind"], "court")
        self.assertTrue(all(s["outdoor"] for s in spots_index(L) if s["room"] == "courtyard"))
        self.assertEqual(len(by["hall"]["parts"]), 4)
        beds = [r for r in L["rooms"] if r.get("template") == "bedroom"]
        self.assertEqual(len(beds), 8)
        self.assertEqual(sum(1 for r in beds if r.get("flip")), 2)
        for r in beds:
            if r.get("flip"):
                self.assertEqual(r["door"]["wall"], "n")
        indoor = [r for r in L["rooms"] if r["kind"] not in ("hall", "outdoor")]
        for i, a in enumerate(indoor):                # 房间互不重叠
            for b in indoor[i + 1:]:
                ax0, az0, ax1, az1 = a["rect"]
                bx0, bz0, bx1, bz1 = b["rect"]
                self.assertFalse(ax0 < bx1 - 1e-6 and bx0 < ax1 - 1e-6 and az0 < bz1 - 1e-6 and bz0 < az1 - 1e-6, (a["id"], b["id"]))

    def test_bedroom_style_follows_persona_and_setting(self):
        bed = TPL["bedroom"]
        self.assertEqual(bedroom_style({"persona": "喜欢海洋和鲸鱼"}, bed)["floor"], bed["styles"]["ocean"]["floor"])
        chosen = bedroom_style({"persona": "喜欢海洋", "room_style": "books"}, bed)
        self.assertEqual(chosen["floor"], bed["styles"]["books"]["floor"])
        self.assertTrue(any(f["type"] == "bookshelf" for f in chosen["furniture"]))
        self.assertEqual(len(bedroom_style({}, bed)["spots"]), len(bed["spots"]))

    def test_few_bedrooms_keep_straight_row(self):
        rooms = ROOMS + [{"template": "lounge"}, {"template": "library"}]
        self.assertNotEqual(build_layout(CFG["residents"], rooms, TPL).get("style"), "courtyard")

    def test_flipped_bedroom_mirrors_furniture(self):
        rooms = ROOMS + [{"template": "lounge"}, {"template": "library"}]
        L = build_layout(CFG["residents"], rooms, TPL, None, 8)
        r = next(x for x in L["rooms"] if x.get("flip"))
        bed = next(f for f in r["furniture"] if f["type"] == "bed")
        self.assertGreater(bed["z"], (r["rect"][1] + r["rect"][3]) / 2)
        self.assertEqual(bed["face"], "n")

    def test_more_residents_than_bedrooms(self):
        many = [{"id": f"r{i}", "name": f"r{i}"} for i in range(9)]
        L = build_layout(many, ROOMS, TPL, None, 8)
        self.assertFalse([r for r in L["rooms"] if r.get("vacant")])
        self.assertEqual(sum(1 for r in L["rooms"] if r.get("owner")), 9)

    def test_bad_bedrooms(self):
        with self.assertRaises(LayoutError):
            build_layout(CFG["residents"], ROOMS, TPL, None, "很多")

    def test_bad_template(self):
        with self.assertRaises(LayoutError):
            build_layout(CFG["residents"], [{"template": "spaceship"}], TPL)


def fake_cli(folder: Path, name: str, body: str) -> Path:
    p = folder / name
    p.write_text("#!" + sys.executable + "\n" + textwrap.dedent(body), encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


@unittest.skipIf(os.name == "nt", "假 CLI 用 shebang，只在 Linux / macOS 上测")
class CliDriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_claude_ok_and_flags(self):
        exe = fake_cli(self.dir, "claude", f"""
            import json, sys
            args = sys.argv[1:]
            sp = args[args.index('--system-prompt-file') + 1]
            json.dump({{'args': args, 'system': open(sp, encoding='utf-8').read(), 'stdin': sys.stdin.read()}},
                      open({str(self.dir / 'call.json')!r}, 'w', encoding='utf-8'), ensure_ascii=False)
            print(json.dumps({{'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '好的',
                              'usage': {{'input_tokens': 2, 'cache_creation_input_tokens': 100, 'output_tokens': 3}}}}))
        """)
        d = drivers.make_driver({"type": "claude_cli", "command": str(exe), "model": "sonnet"}, self.dir / "sb", 20)
        self.assertEqual(d.access, "subscription")
        g = d.generate("你是阿C", "说一句话")
        self.assertTrue(g.ok, g.error)
        self.assertEqual(g.text, "好的")
        self.assertEqual(g.meta["input_tokens"], 102)
        call = json.loads((self.dir / "call.json").read_text(encoding="utf-8"))
        args = call["args"]
        self.assertEqual(args[args.index("--tools") + 1], "")          # 不给任何工具
        self.assertIn("--no-chrome", args)
        self.assertIn("--no-session-persistence", args)
        self.assertEqual(args[args.index("--model") + 1], "sonnet")
        self.assertEqual(call["system"], "你是阿C")
        self.assertEqual(call["stdin"], "说一句话")
        self.assertEqual(list((self.dir / "sb").glob("persona-*")), [])  # 临时人设文件删掉了

    def test_claude_not_logged_in(self):
        exe = fake_cli(self.dir, "claude", """
            import json
            print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': True, 'result': 'Not logged in · Please run /login'}))
        """)
        g = drivers.make_driver({"type": "claude_cli", "command": str(exe)}, self.dir / "sb", 20).generate("s", "p")
        self.assertFalse(g.ok)
        self.assertEqual(g.kind, "auth")

    def test_codex_jsonl(self):
        exe = fake_cli(self.dir, "codex", f"""
            import json, sys
            open({str(self.dir / 'argv.json')!r}, 'w').write(json.dumps(sys.argv[1:]))
            sys.stdin.read()
            for o in [{{'type': 'thread.started', 'thread_id': 't1'}},
                      {{'type': 'error', 'message': 'Reconnecting... 1/5'}},
                      {{'type': 'item.completed', 'item': {{'type': 'agent_message', 'text': '收到'}}}},
                      {{'type': 'turn.completed', 'usage': {{'input_tokens': 50, 'output_tokens': 4}}}}]:
                print(json.dumps(o))
        """)
        d = drivers.make_driver({"type": "codex_cli", "command": str(exe), "reasoning_effort": "low"}, self.dir / "sb", 20)
        g = d.generate("你是阿G", "说一句")
        self.assertTrue(g.ok, g.error)
        self.assertEqual(g.text, "收到")
        argv = json.loads((self.dir / "argv.json").read_text())
        self.assertIn("read-only", argv)
        self.assertIn("shell_tool", argv)
        self.assertIn("model_reasoning_effort=low", argv)
        self.assertEqual(argv[-1], "-")

    def test_codex_failure(self):
        exe = fake_cli(self.dir, "codex", """
            import json, sys
            print(json.dumps({'type': 'turn.failed', 'error': {'message': 'You have hit your usage limit'}}))
            sys.exit(1)
        """)
        g = drivers.make_driver({"type": "codex_cli", "command": str(exe)}, self.dir / "sb", 20).generate("s", "p")
        self.assertFalse(g.ok)
        self.assertEqual(g.kind, "limit")

    def test_missing_cli(self):
        d = drivers.make_driver({"type": "claude_cli", "command": "/nope/claude"}, self.dir / "sb", 20)
        ok, info = d.check()
        self.assertFalse(ok)
        self.assertIn("找不到命令", info)


class FakeResp:
    def __init__(self, code, data):
        self.status_code, self._d = code, data
        self.text = json.dumps(data)

    def json(self):
        return self._d


class ApiDriverTests(unittest.TestCase):
    def test_openai_compat(self):
        with patch.dict(os.environ, {"TEST_KEY": "sk-x"}):
            d = drivers.make_driver({"type": "openai_api", "base_url": "https://api.deepseek.com", "model": "m",
                                     "api_key_env": "TEST_KEY"}, Path("."), 10)
        self.assertEqual(d.product, "DeepSeek")
        self.assertTrue(d.check()[0])
        with patch("home.drivers.httpx.post", return_value=FakeResp(200, {"choices": [{"message": {"content": "嗯"}}],
                                                                        "usage": {"prompt_tokens": 9}})) as post:
            g = d.generate("sys", "hi")
        self.assertTrue(g.ok)
        self.assertEqual(g.text, "嗯")
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["messages"][0], {"role": "system", "content": "sys"})
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer sk-x")

    def test_openai_errors(self):
        with patch.dict(os.environ, {"TEST_KEY": "sk-x"}):
            d = drivers.make_driver({"type": "openai_api", "model": "m", "api_key_env": "TEST_KEY"}, Path("."), 10)
        with patch("home.drivers.httpx.post", return_value=FakeResp(401, {"error": "bad key"})):
            self.assertEqual(d.generate("s", "p").kind, "auth")
        with patch("home.drivers.httpx.post", return_value=FakeResp(402, {"error": "Insufficient Balance"})):
            self.assertEqual(d.generate("s", "p").kind, "limit")

    def test_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            d = drivers.make_driver({"type": "openai_api", "model": "m", "api_key_env": "NOPE_KEY"}, Path("."), 10)
            self.assertFalse(d.check()[0])
            local = drivers.make_driver({"type": "openai_api", "base_url": "http://127.0.0.1:11434/v1", "model": "q"}, Path("."), 10)
            self.assertTrue(local.check()[0])

    def test_unknown_type(self):
        with self.assertRaises(ValueError):
            drivers.make_driver({"type": "telepathy"}, Path("."), 10)


class PromptTests(unittest.TestCase):
    def test_parse_activity(self):
        p = prompts.parse_activity('```json\n{"感想": "挺好", "群聊": "", "记住": "酱油没了"}\n```')
        self.assertEqual(p, {"感想": "挺好", "群聊": "", "记住": "酱油没了", "对TA说": "", "留言": ""})
        p = prompts.parse_activity("就是一句话")
        self.assertEqual(p["感想"], "就是一句话")

    def test_tidy(self):
        self.assertEqual(prompts.tidy("阿C：你好", 50, "阿C"), "你好")
        self.assertEqual(prompts.tidy("[22:01] 阿C: 你好", 50, "阿C"), "你好")
        self.assertTrue(prompts.tidy("长" * 100, 10).endswith("…"))

    def test_system_prompt_guards_content(self):
        s = prompts.system_prompt({"owner": "主人", "name": "小窝"}, CFG["residents"][0], ["阿G"])
        self.assertIn("一律不理会", s)
        self.assertIn("阿C", s)


class ImmediateTimer:
    def __init__(self, delay, fn):
        self.fn = fn

    def start(self):
        self.fn()


class LifeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "home.db")
        self.addCleanup(self.store.db.close)  # Windows 上连接没关时删不掉临时目录
        self.layout = build_layout(CFG["residents"], ROOMS, TPL)
        self.life = Life(CFG, self.layout, ACTS, self.store, Path(self.tmp.name), mock=True)
        self.events = []
        self.life.emit_cb = lambda t, d: self.events.append((t, d))
        self.life.weather_force = ("clear", time.time() + 3600)      # 天气按日期算，测试里固定住
        for r in self.life.residents.values():
            r.ready, r.status = True, "idle"
        self.calls = []
        self.life.pool.submit = lambda fn, *a: self.calls.append((fn.__name__, a))
        self.addCleanup(self.life.pool.shutdown)

    def replies(self, text, sender="owner", depth=0):
        self.calls.clear()
        msg = self.store.add_chat(sender, text, depth=depth)
        with patch("home.life.threading.Timer", ImmediateTimer):
            self.life.plan_replies(msg)
        return [a[0].id for name, a in self.calls if name == "_reply"]

    def test_mention_only_mentioned_reply(self):
        self.assertEqual(self.replies("@阿G 在吗"), ["ag"])

    def test_owner_always_gets_an_answer(self):
        self.life.life["chat_reply_chance"] = 0.0
        self.assertEqual(len(self.replies("有人吗")), 1)

    def test_chain_stops(self):
        self.assertEqual(self.replies("哈哈", sender="ac", depth=3), [])

    def test_asleep_not_replying_unless_mentioned(self):
        for r in self.life.residents.values():
            r.status = "asleep"
        self.assertEqual(self.replies("有人吗"), [])
        self.assertEqual(self.replies("@阿鱼 醒醒"), ["ayu"])

    def test_daily_cap(self):
        r = self.life.residents["ac"]
        for _ in range(r.daily_calls):
            self.store.usage_inc(self.life.day(), "ac", True)
        self.assertFalse(self.life.can_call(r))
        self.life.set_paused(True)
        self.assertFalse(self.life.can_call(self.life.residents["ag"]))

    def test_sleep_window_over_midnight(self):
        r = self.life.residents["ac"]       # 01:30–08:30（每天前后浮动最多 15 分钟）
        tz = self.life.tz
        self.assertTrue(self.life.in_sleep(r, datetime(2026, 11, 8, 4, 0, tzinfo=tz)))
        self.assertFalse(self.life.in_sleep(r, datetime(2026, 11, 8, 14, 0, tzinfo=tz)))
        r.cfg = {**r.cfg, "sleep": ["23:30", "07:00"]}
        self.assertTrue(self.life.in_sleep(r, datetime(2026, 11, 8, 0, 30, tzinfo=tz)))
        self.assertFalse(self.life.in_sleep(r, datetime(2026, 11, 8, 20, 0, tzinfo=tz)))

    def test_activity_uses_own_bedroom_only(self):
        self.life.sources.sources["shelf"].refresh()
        for _ in range(30):
            r = self.life.residents["ac"]
            r.status = "idle"
            with patch("home.life.threading.Timer", ImmediateTimer):
                self.life.start_activity(r)
            owner = self.life._spot(r.room, r.spot)["owner"]
            if r.last_act != "visit":        # 串门是唯一会进别人房间的事
                self.assertIn(owner, (None, "ac"))

    def test_think_activity_writes_feed_and_memory(self):
        self.life.sources.sources["shelf"].refresh()
        r = self.life.residents["ak"]
        with patch("home.drivers.Mock.generate", return_value=drivers.Gen(True, text=json.dumps(
                {"感想": "好看", "群聊": "大家看过这本吗", "记住": "书架第二层"}, ensure_ascii=False))):
            self.life._think(r, ACTS["read"], "书房的书架边", "在书房的书架边翻了几页《三体》", None)
        feed = self.store.list_feed(5)[0]
        self.assertEqual(feed["detail"], "好看")
        self.assertIn("在群里提了一句", feed["text"])
        self.assertEqual(self.store.recent_memory("ak"), ["书架第二层"])
        self.assertEqual(self.store.list_chat(5)[-1]["text"], "大家看过这本吗")

    def test_memory_dedupes_and_keeps_pinned(self):
        first = self.store.add_memory("ac", "厨房的酱油快用完了")
        again = self.store.add_memory("ac", "厨房的酱油快用完了。")
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(again["hits"], 2)
        self.store.update_memory(first["id"], pinned=True)
        for i in range(80):
            self.store.add_memory("ac", f"第{i}件完全不同的小事编号{i * 7919}")
        rows = self.store.list_memory("ac")
        self.assertLessEqual(len(rows), 61)
        self.assertTrue(any(m["id"] == first["id"] for m in rows))

    def test_recall_prefers_related_and_pinned(self):
        pin = self.store.add_memory("ak", "主人不吃香菜")
        self.store.update_memory(pin["id"], pinned=True)
        self.store.add_memory("ak", "秋千的绳子有点松")
        for i in range(10):
            self.store.add_memory("ak", f"无关的流水账{i * 104729}号")
        got = self.store.recall_memory("ak", "去荡秋千，绳子", 3)
        self.assertIn("主人不吃香菜", got)
        self.assertIn("秋千的绳子有点松", got)

    def test_old_memory_table_upgrades(self):
        path = Path(self.tmp.name) / "old.db"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE memory(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, resident TEXT, text TEXT)")
        db.execute("INSERT INTO memory(ts,resident,text) VALUES(1,'ac','旧记忆')")
        db.commit(); db.close()
        s = Store(path)
        self.addCleanup(s.db.close)
        self.assertEqual(s.recent_memory("ac"), ["旧记忆"])

    def test_reflect_merges_only_on_success(self):
        r = self.life.residents["ac"]
        rows = [self.store.add_memory("ac", f"今天的零碎事情第{i * 7919}个") for i in range(4)]
        with patch("home.drivers.Mock.generate", return_value=drivers.Gen(False, error="x", kind="other")):
            self.life._reflect(r, rows)
        self.assertEqual(sum(m["merged"] for m in self.store.list_memory("ac")), 0)
        with patch("home.drivers.Mock.generate", return_value=drivers.Gen(True, text='{"记住": "今天过得挺满"}')):
            self.life._reflect(r, rows)
        mems = self.store.list_memory("ac")
        self.assertEqual(sum(m["merged"] for m in mems), 4)
        self.assertEqual(self.store.recent_memory("ac"), ["今天过得挺满"])

    def test_together_moves_both_to_one_ride(self):
        layout = build_layout(CFG["residents"], ROOMS, TPL, [{"template": "playground"}])
        self.life.apply(CFG, layout, ACTS)
        for r in self.life.residents.values():
            r.ready, r.status = True, "idle"
        a = self.life.residents["ac"]
        with patch("home.life.threading.Timer", ImmediateTimer), patch.object(self.life, "is_day", return_value=True), \
                patch("home.life.random.random", return_value=0.99):
            self.life.start_activity(a, "seesaw")
        partner = next(r for r in self.life.residents.values() if r is not a and r.spot.startswith("seesaw"))
        self.assertTrue(a.spot.startswith("seesaw"))
        self.assertNotEqual(a.spot, partner.spot)
        self.assertEqual(self.store.list_feed(1)[0]["kind"], "together")

    def test_no_playground_at_night(self):
        layout = build_layout(CFG["residents"], ROOMS, TPL, [{"template": "playground"}])
        self.life.apply(CFG, layout, ACTS)
        with patch.object(self.life, "is_day", return_value=False):
            ids = [aid for aid, _, _ in self.life._choices(self.life.residents["ac"])]
            self.assertNotIn("swing", ids)
            self.assertIn("天黑", self.life.go_play("ac"))

    def test_interact_bubbles_without_model(self):
        with patch("home.drivers.Mock.generate", side_effect=AssertionError("不该调用模型")):
            self.life.interact("ayu", "pat")
        self.assertTrue(any(t == "bubble" and d["id"] == "ayu" for t, d in self.events))
        self.assertEqual(self.store.list_feed(1)[0]["kind"], "interact")
        with self.assertRaises(ValueError):
            self.life.interact("ayu", "explode")

    def outdoors(self):
        layout = build_layout(CFG["residents"], ROOMS, TPL, [{"template": "playground"}])
        self.life.apply(CFG, layout, ACTS)
        for r in self.life.residents.values():
            r.ready, r.status = True, "idle"

    def test_relation_grows_decays_and_stays_directed(self):
        self.store.bump_relation("ac", "ag", 40, "上次一起荡秋千")
        self.assertEqual(self.store.relations("ac")[0]["label"], "挺要好")
        self.assertEqual(self.store.relations("ag"), [])
        self.store._x("UPDATE relation SET last_ts=? WHERE resident='ac'", (time.time() - 30 * 86400,))
        self.assertAlmostEqual(self.store.relation_score("ac", "ag"), 30.0, delta=0.5)
        self.store._x("UPDATE relation SET last_ts=? WHERE resident='ac'", (time.time() - 3650 * 86400,))
        self.assertGreaterEqual(self.store.relation_score("ac", "ag"), 10.0)

    def test_together_builds_relation_and_reaches_prompt(self):
        a, b = self.life.residents["ac"], self.life.residents["ag"]
        self.life._finish_together(a, b, "和阿G坐着聊了会儿", "和阿C聊过", "你昨天说的鲸鱼呢", "还在查")
        self.assertIn("鲸鱼", self.store.relations("ac")[0]["note"])
        self.assertIn("鲸鱼", self.store.relations("ag")[0]["note"])
        self.assertIn("鲸鱼", self.life._system(a))

    def test_rain_keeps_everyone_inside(self):
        self.outdoors()
        self.life.weather_force = ("rain", time.time() + 3600)
        with patch.object(self.life, "is_day", return_value=True):
            ids = [aid for aid, _, _ in self.life._choices(self.life.residents["ac"])]
            self.assertNotIn("swing", ids)
            self.assertIn("下雨", self.life.go_play("ac"))
            r = self.life.residents["ac"]
            r.room, r.spot = "playground", "bench_a"
            self.assertTrue(self.life._caught_in_rain(r))

    def test_weather_is_stable_and_festival_known(self):
        when = datetime(2026, 7, 3, 10, tzinfo=self.life.tz)
        self.assertEqual({drivers_w for drivers_w in (days.weather_at(when, "x") for _ in range(5))}, {days.weather_at(when, "x")})
        self.assertEqual(days.weather_at(when, "x", {"rain": 1.0}), "rain")
        self.assertEqual(days.festival_on(datetime(2027, 2, 6)), "春节")
        self.assertEqual(days.festival_on(datetime(2026, 3, 14), [{"date": "03-14", "name": "生日"}]), "生日")
        self.assertEqual(days.festival_on(datetime(2026, 3, 15)), "")

    def test_festival_activity_only_on_festival(self):
        ids = lambda: [a for a, _, _ in self.life._choices(self.life.residents["ac"], "decorate")]
        with patch.object(self.life, "festival", return_value=""):
            self.assertEqual(ids(), [])
        with patch.object(self.life, "festival", return_value="春节"):
            self.assertEqual(ids(), ["decorate"])

    def test_visit_greets_once_per_gap(self):
        with patch("home.life.threading.Timer", ImmediateTimer):
            self.life.owner_online(1)
            self.life.owner_online(0)
            self.life.owner_online(1)
        visits = [f for f in self.store.list_feed(20) if f["kind"] == "visit"]
        self.assertEqual(len(visits), 1)
        self.assertEqual(self.life.visits, 1)
        self.assertGreater(self.store.relation_score("ac", "owner"), 10)

    def test_owner_note_gets_reply_and_keeps_when_failed(self):
        r = self.life.residents["ak"]
        note = self.life.post_note("ak", "记得吃药")
        with patch("home.drivers.Mock.generate", return_value=drivers.Gen(False, error="x", kind="other")):
            self.life._read_note(r, note, False)
        self.assertEqual(len(self.store.unread_notes("ak")), 1)
        r.backoff_until = 0
        with patch("home.drivers.Mock.generate", return_value=drivers.Gen(True, text="好，吃了")):
            self.life._read_note(r, note, False)
        self.assertEqual(self.store.unread_notes("ak"), [])
        self.assertEqual(self.store.unread_notes("owner")[0]["text"], "好，吃了")
        self.assertTrue(any("记得吃药" in m for m in self.store.recent_memory("ak")))

    def test_no_quota_note_does_not_call_model(self):
        r = self.life.residents["ak"]
        note = self.life.post_note("ak", "在吗")
        with patch("home.drivers.Mock.generate", side_effect=AssertionError("不该调用模型")):
            self.life._read_note(r, note, True)
        self.assertEqual(self.store.unread_notes("owner")[0]["text"], life_mod.NOTE_NO_QUOTA)

    def test_note_to_unknown_resident_rejected(self):
        with self.assertRaises(ValueError):
            self.life.post_note("nobody", "hi")

    def test_owner_away_lowers_think_chance(self):
        r = self.life.residents["ac"]
        self.life.online, self.life.last_seen = 1, time.time()
        self.assertFalse(self.life.owner_away())
        with patch("home.life.random.random", return_value=0.5):
            self.assertTrue(self.life._think_now(r))
            self.life.online, self.life.last_seen = 0, time.time() - 7200
            self.assertTrue(self.life.owner_away())
            self.assertFalse(self.life._think_now(r))

    def test_usage_tokens_and_cost(self):
        self.store.usage_inc(self.life.day(), "ac", True, {"input_tokens": 1000, "output_tokens": None, "seconds": 2})
        self.life.residents["ac"].cfg = {**self.life.residents["ac"].cfg,
                                         "driver": {"type": "mock", "price": {"input": 2, "output": 1, "currency": "元"}}}
        row = next(x for x in self.life.usage_report()["residents"] if x["id"] == "ac")
        self.assertEqual((row["calls"], row["input_tokens"], row["today_tokens"]), (1, 1000, 1000))
        self.assertEqual(row["cost"], 0.002)
        self.assertIsNone(next(x for x in self.life.usage_report()["residents"] if x["id"] == "ag")["cost"])

    def test_old_usage_table_upgrades(self):
        path = Path(self.tmp.name) / "old_use.db"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE usage(day TEXT, resident TEXT, calls INTEGER DEFAULT 0, fails INTEGER DEFAULT 0, PRIMARY KEY(day, resident))")
        db.execute("INSERT INTO usage VALUES('2026-01-01','ac',5,1)")
        db.commit(); db.close()
        s = Store(path)
        self.addCleanup(s.db.close)
        self.assertEqual(s.usage("2026-01-01", "ac"), {"calls": 5, "fails": 1})
        s.usage_inc("2026-01-01", "ac", True, {"input_tokens": 3})
        self.assertEqual(s.usage_since("2026-01-01")[0]["input_tokens"], 3)

    def test_daily_and_replay(self):
        a, b = self.life.residents["ac"], self.life.residents["ag"]
        a.room, a.spot, a.activity = "living", "sofa_a", "在看电视"
        self.life.changed(a)
        self.life.changed(a)                # 没变化不重复记
        self.life._finish_together(a, b, "和阿G在客厅窝着聊了会儿", "和阿C窝着聊天过", "嗨", "嗯")
        self.store.add_chat("ac", "有人吗")
        report = self.life.daily()
        self.assertFalse(report["empty"])
        by = {p["id"]: p for p in report["residents"]}
        self.assertEqual(by["ac"]["with"], ["阿G"])
        self.assertEqual(by["ag"]["with"], ["阿C"])
        self.assertEqual(by["ac"]["chats"], 1)
        rep = self.life.replay()
        self.assertEqual([x["id"] for x in rep["trace"]], ["ac"])
        self.assertEqual(len(rep["weather"]), 4)
        with self.assertRaises(ValueError):
            self.life.daily("昨天")

    def test_auth_failure_takes_resident_offline(self):
        r = self.life.residents["ac"]
        with patch("home.drivers.Mock.generate", return_value=drivers.Gen(False, error="Not logged in", kind="auth")):
            self.life._call(r, "s", "p", "line")
        self.assertFalse(r.ready)
        self.assertGreater(r.next_check, time.time())


class LivingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "home.db")
        self.addCleanup(self.store.db.close)
        rooms = ROOMS + [{"template": "lounge"}, {"template": "library"}]
        self.layout = build_layout(CFG["residents"], rooms, TPL, [{"template": "playground"}, {"template": "lake"}], 8)
        cfg = {**CFG, "life": dict(CFG["life"])}
        self.life = Life(cfg, self.layout, ACTS, self.store, Path(self.tmp.name), mock=True)
        self.events = []
        self.life.emit_cb = lambda t, d: self.events.append((t, d))
        self.life.weather_force = ("clear", time.time() + 3600)
        for r in self.life.residents.values():
            r.ready, r.status = True, "idle"
        self.life.pool.submit = lambda fn, *a: None
        self.addCleanup(self.life.pool.shutdown)
        self.ac = self.life.residents["ac"]

    def kinds(self, typ):
        return [d for t, d in self.events if t == typ]

    def test_templates_reachable_and_every_activity_has_a_place(self):
        tags = {t for s in spots_index(self.layout) for t in s["tags"]}
        for aid, act in ACTS.items():
            if not act.get("visit"):
                self.assertTrue(set(act["spots"]) & tags, aid)
        for r in self.layout["rooms"]:
            if r["kind"] != "hall":
                self.assertTrue(reachable(self.layout, r["id"]), r["id"])

    def test_mood_follows_needs(self):
        needs = living.clean_needs(None)
        needs["hunger"] = 5
        self.assertEqual(living.mood(needs)["key"], "hungry")
        needs = {k: 90.0 for k in living.NEEDS}
        self.assertEqual(living.mood(needs)["key"], "happy")

    def test_hungry_prefers_food(self):
        full, empty = {k: 90.0 for k in living.NEEDS}, {**{k: 90.0 for k in living.NEEDS}, "hunger": 0.0}
        gives = ACTS["cook"]["gives"]
        self.assertGreater(living.need_factor(empty, gives), living.need_factor(full, gives))

    def test_sleep_restores_energy(self):
        needs = {k: 50.0 for k in living.NEEDS}
        living.drain(needs, 1, asleep=True)
        self.assertGreater(needs["energy"], 50)
        self.assertLess(needs["hunger"], 50)

    def test_activity_sets_action_and_public_has_mood(self):
        with patch("home.life.threading.Timer", ImmediateTimer):
            self.life.start_activity(self.ac, "stretch")
        pub = self.life.public(self.ac)
        self.assertEqual(pub["anim"], "stretch")
        self.assertTrue(pub["emote"])
        self.assertIn("label", pub["mood"])

    def test_state_survives_restart(self):
        self.ac.needs["fun"] = 12.0
        self.ac.decor = ["flower"]
        self.life.save(self.ac)
        again = Life(self.life.cfg, self.layout, ACTS, self.store, Path(self.tmp.name), mock=True)
        self.addCleanup(again.pool.shutdown)
        self.assertEqual(again.residents["ac"].needs["fun"], 12.0)
        self.assertEqual(again.residents["ac"].decor, ["flower"])

    def test_goal_done_adds_decor_and_feed(self):
        self.ac.goal = {"act": "water", "label": "把一盆花养开", "need": 2, "done": 1}
        self.life._progress(self.ac, "water")
        self.assertIn("flower", self.ac.decor)
        self.assertEqual(self.store.list_feed(5)[0]["kind"], "goal")
        self.assertNotEqual((self.ac.goal or {}).get("act"), "water")

    def test_visit_goes_to_someone_elses_room(self):
        ag = self.life.residents["ag"]
        ag.room, ag.spot = ag.bedroom, "desk"
        for o in self.life.residents.values():
            if o is not ag and o is not self.ac:
                o.room, o.spot = "living", "sofa_a"
        with patch("home.life.threading.Timer", ImmediateTimer):
            self.life.start_activity(self.ac, "visit")
        self.assertEqual(self.ac.room, ag.bedroom)
        self.assertGreater(self.store.relation_score("ac", "ag"), 10)

    def test_nobody_goes_in_vacant_room(self):
        vacant = {r["id"] for r in self.layout["rooms"] if r.get("vacant")}
        for _ in range(60):
            self.ac.status = "idle"
            with patch("home.life.threading.Timer", ImmediateTimer):
                self.life.start_activity(self.ac)
            self.assertNotIn(self.ac.room, vacant)

    def test_party_gathers_in_one_room(self):
        with patch("home.life.threading.Timer", ImmediateTimer):
            self.life.party()
        rooms = {r.room for r in self.life.residents.values() if r.activity.startswith("在") and r.anim or r.emote}
        self.assertEqual(len(rooms), 1)
        self.assertEqual(self.store.list_feed(1)[0]["kind"], "party")

    def test_party_stays_inside_when_raining(self):
        self.life.weather_force = ("rain", time.time() + 3600)
        with patch("home.life.threading.Timer", ImmediateTimer):
            for _ in range(20):
                for r in self.life.residents.values():
                    r.status = "idle"
                self.life.party()
                for r in self.life.residents.values():
                    self.assertFalse((self.life._spot(r.room, r.spot) or {}).get("outdoor"))

    def test_quiet_person_gets_picked_more(self):
        for _ in range(6):
            self.store.add_chat("ac", "我又说了一句")
        msg = self.store.add_chat("owner", "随便聊聊")
        pool = list(self.life.residents.values())
        got = Counter(self.life._pick_speakers(pool, msg, 1)[0].id for _ in range(400))
        self.assertLess(got["ac"], got["ag"])

    def test_chat_crowded_stops_auto_replies_but_not_mentions(self):
        self.life.life["max_chat_per_minute"] = 2
        self.life.life["chat_reply_chance"] = 1.0
        for who in ("ac", "ag", "ayu"):
            self.store.add_chat(who, "嗯")
        self.assertTrue(self.life._chat_crowded())

    def test_budget_keeps_owner_replies(self):
        self.life.life["budget"] = {"calls": 2}
        self.store.usage_inc(self.life.day(), "ag", True)
        self.store.usage_inc(self.life.day(), "ag", True)
        self.assertEqual(self.life.budget_state(), "out")
        self.assertFalse(self.life.can_call(self.ac))
        self.assertTrue(self.life.can_call(self.ac, for_owner=True))

    def test_no_budget_means_no_limit(self):
        self.store.usage_inc(self.life.day(), "ag", True)
        self.assertEqual(self.life.budget_state(), "ok")

    def test_touch(self):
        self.ac.room = "living"
        self.life.touch("living", "cat")
        self.assertTrue(self.kinds("bubble"))
        with self.assertRaises(ValueError):
            self.life.touch("living", "nuke")

    def test_weekly(self):
        self.store.add_feed("ac", "activity", "在书房看书", room="study")
        w = self.life.weekly()
        self.assertFalse(w["empty"])
        row = next(p for p in w["residents"] if p["id"] == "ac")
        self.assertEqual(row["things"], 1)

    def test_night_sends_people_inside(self):
        self.ac.room, self.ac.spot = "lake", "feed_a"
        with patch.object(self.life, "is_day", return_value=False):
            self.assertTrue(self.life._must_come_in(self.ac))
        with patch.object(self.life, "is_day", return_value=True):
            self.assertFalse(self.life._must_come_in(self.ac))
            self.ac.room, self.ac.spot = "living", "sofa_a"
            self.assertFalse(self.life._must_come_in(self.ac))

    def test_daily_shows_goals_and_parties(self):
        self.store.add_feed("ac", "goal", "读完一本厚书")
        self.store.add_feed("", "party", "大家一起吃了顿饭")
        texts = [m["text"] for m in self.life.daily()["moments"]]
        self.assertIn("读完一本厚书", texts)
        self.assertIn("大家一起吃了顿饭", texts)

    def test_replay_brings_back_actions(self):
        self.ac.room, self.ac.spot = "library", "arm_a"
        self.ac.status, self.ac.activity = "idle", "在看书"
        self.life.changed(self.ac)
        row = next(x for x in self.life.replay()["trace"] if x["id"] == "ac")
        self.assertEqual((row["anim"], row["prop"]), ("read", "book"))
        self.assertEqual(self.life._act_look("和阿G下棋", "idle")["anim"], "chess")
        self.assertEqual(self.life._act_look("睡觉", "asleep")["anim"], "")

    def test_backup_keeps_recent_copies(self):
        self.store.add_feed("ac", "activity", "备份要带上这条")
        self.life.life["backup_keep"] = 2
        for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
            self.life._backup(day)
        files = sorted(p.name for p in (Path(self.tmp.name) / "backups").glob("*.db"))
        self.assertEqual(files, ["home-2026-01-02.db", "home-2026-01-03.db"])
        copy = sqlite3.connect(Path(self.tmp.name) / "backups" / files[-1])
        self.addCleanup(copy.close)
        self.assertEqual(copy.execute("SELECT COUNT(*) FROM feed").fetchone()[0], 1)

    def test_new_resident_gets_move_in_feed(self):
        cfg = {**self.life.cfg, "residents": [*CFG["residents"], {"id": "glm", "name": "阿智", "color": "#00aa88"}]}
        layout = build_layout(cfg["residents"], ROOMS, TPL, None, 8)
        self.life.apply(cfg, layout, ACTS)
        self.assertIn("glm", self.life.residents)
        self.assertEqual(self.store.list_feed(1)[0]["kind"], "movein")


if __name__ == "__main__":
    unittest.main()
