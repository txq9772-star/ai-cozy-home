"""房子布局：按住户和 rooms 列表，用 rooms/ 里的模板拼出整座房子的坐标。

排法：
  后排  每个住户一间卧室，从左到右按 residents 的顺序。
  走廊  后排和前排之间一条，所有房间都能走到。
  前排  rooms 列表里的公共房间。第一个整高房间（kind: tall，比如客厅）放正中，大门开在它南墙；
        其余房间左右交替往外排：半高房间（kind: half）两个叠成一列，上半格的门开向走廊，
        下半格挨着中间房间就开门进中间房间，不挨着就开门进同一列的上半格。
  两排宽度不一样时，窄的那排把房间拉宽补齐（家具按贴墙坐标跟着走）。

模板按「放在中间房间左边」的朝向写，放到右边时左右镜像。
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

HALL_DEPTH = 2.0
FRONT_DEPTH = 11.0
DOOR_WIDTH = 1.6
_ANCHOR = re.compile(r"^\s*([nsew])\s*([+-]\s*[\d.]+)?\s*$")


class LayoutError(ValueError):
    pass


def load_templates(folder: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in sorted(folder.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        data.setdefault("kind", "half")
        out[f.stem] = data
    if "bedroom" not in out:
        raise LayoutError(f"{folder} 里缺少 bedroom.yaml（卧室模板）")
    return out


def _coord(v: Any, axis: str, rect: tuple[float, float, float, float], mirror: bool) -> float:
    """把模板坐标换成绝对坐标。axis: x 或 z。"""
    x0, z0, x1, z1 = rect
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    if isinstance(v, (int, float)):
        off = float(v)
        if axis == "x":
            return cx - off if mirror else cx + off
        return cz + off
    m = _ANCHOR.match(str(v))
    if not m:
        raise LayoutError(f"看不懂的坐标：{v!r}（写数字，或 n+0.5 / s-1 / w+0.3 / e-0.3）")
    wall, off = m.group(1), float((m.group(2) or "0").replace(" ", ""))
    if axis == "x" and mirror and wall in "we":
        wall, off = ("e" if wall == "w" else "w"), -off
    base = {"n": z0, "s": z1, "w": x0, "e": x1}[wall]
    if axis == "x" and wall in "ns" or axis == "z" and wall in "we":
        raise LayoutError(f"坐标 {v!r} 用错了方向：x 只能贴 w/e 墙，z 只能贴 n/s 墙")
    return base + off


def _face(face: str | None, mirror: bool) -> str | None:
    if mirror and face in ("e", "w"):
        return "w" if face == "e" else "e"
    return face


def _fill(v: Any, ctx: dict[str, str]) -> Any:
    if isinstance(v, str):
        for k, val in ctx.items():
            v = v.replace("{" + k + "}", val)
    return v


def _place(tpl: dict[str, Any], room_id: str, rect: tuple[float, float, float, float], mirror: bool,
           ctx: dict[str, str], extra: dict[str, Any]) -> dict[str, Any]:
    room: dict[str, Any] = {
        "id": room_id, "template": extra.get("template"),
        "name": extra.get("name") or _fill(tpl.get("name", room_id), ctx),
        "kind": tpl.get("kind"), "icon": tpl.get("icon", ""), "floor": tpl.get("floor", "wood"),
        "rect": [round(c, 3) for c in rect], "mirror": mirror,
        "furniture": [], "spots": {},
    }
    if extra.get("owner"):
        room["owner"] = extra["owner"]
    lab = tpl.get("label") or [0, 0]
    room["label"] = [round(_coord(lab[0], "x", rect, mirror), 3), round(_coord(lab[1], "z", rect, mirror), 3)]
    for item in tpl.get("furniture") or []:
        f = {k: _fill(v, ctx) for k, v in item.items()}
        f["x"] = round(_coord(item.get("x", 0), "x", rect, mirror), 3)
        f["z"] = round(_coord(item.get("z", 0), "z", rect, mirror), 3)
        if "face" in f:
            f["face"] = _face(f["face"], mirror)
        if mirror and f.get("rot"):
            f["rot"] = -float(f["rot"])
        if mirror and "stove_at" in f:
            f["stove_at"] = -float(f["stove_at"])
        room["furniture"].append(f)
    for sid, s in (tpl.get("spots") or {}).items():
        spot = dict(s)
        spot["x"] = round(_coord(s.get("x", 0), "x", rect, mirror), 3)
        spot["z"] = round(_coord(s.get("z", 0), "z", rect, mirror), 3)
        spot["face"] = _face(s.get("face", "s"), mirror)
        spot.setdefault("tags", [])
        spot.setdefault("pose", "stand")
        room["spots"][sid] = spot
    return room


def _door(tpl: dict[str, Any], want: list[str], mirror: bool) -> tuple[str, float] | None:
    """在模板允许的墙里按 want 的顺序挑门。want 用的是「实际」方向，模板写的是镜像前的方向。"""
    doors = tpl.get("doors") or {}
    for wall in want:
        tw = wall
        if mirror and wall in "ew":
            tw = "w" if wall == "e" else "e"
        if tw in doors:
            off = float(doors[tw])
            return wall, (-off if mirror and wall in "ns" else off)
    return None


def build_layout(residents: list[dict[str, Any]], rooms: list[dict[str, Any]], templates: dict[str, dict[str, Any]],
                 outdoors: list[dict[str, Any]] | None = None, bedrooms: int = 0) -> dict[str, Any]:
    """bedrooms 是卧室总数，住户比它少时多出来的就是空房，住户多了卧室跟着加。"""
    if not residents:
        raise LayoutError("至少要有一个住户")
    try:
        slots = max(len(residents), int(bedrooms or 0))
    except (TypeError, ValueError):
        raise LayoutError(f"bedrooms 要写数字，现在是 {bedrooms!r}") from None
    bed_tpl = templates["bedroom"]
    bed_w = float((bed_tpl.get("size") or [7, 7])[0])
    bed_d = float((bed_tpl.get("size") or [7, 7])[1])

    # ---------- 前排：排列
    entries = []
    for i, r in enumerate(rooms):
        name = r.get("template")
        if name not in templates:
            raise LayoutError(f"rooms 第 {i + 1} 项：找不到房间模板 {name!r}（rooms/ 下应有 {name}.yaml）")
        if name == "bedroom":
            raise LayoutError("卧室按住户自动生成，rooms 里不要写 bedroom")
        tpl = templates[name]
        entries.append({"cfg": r, "tpl": tpl, "tall": tpl.get("kind") == "tall",
                        "w": float(r.get("width") or (tpl.get("size") or [9, 5.5])[0])})
    # 中间房间：第一个整高房间；没有整高房间就让第一个房间占中间（拉成整高）
    center = next((e for e in entries if e["tall"]), None) or (entries[0] if entries else None)
    cols: dict[str, list[dict[str, Any]]] = {"L": [], "R": []}
    side_i = 0
    for e in entries:
        if e is center:
            continue
        side = "LR"[side_i % 2]
        side_i += 1
        lst = cols[side]
        if not e["tall"] and lst and not lst[-1]["tall"] and len(lst[-1]["rooms"]) == 1:
            lst[-1]["rooms"].append(e)
            lst[-1]["w"] = max(lst[-1]["w"], e["w"])
        else:
            lst.append({"tall": e["tall"], "rooms": [e], "w": e["w"]})

    # 房子左右对称：两边取较宽的一边为准，窄的一边把最外一列拉宽；某一边没有房间就让中间房间往那边伸
    cw = center["w"] if center else 0.0
    side_w = {s: sum(c["w"] for c in cols[s]) for s in "LR"}
    half = max(cw / 2 + side_w["L"], cw / 2 + side_w["R"], bed_w * slots / 2, bed_w / 2)
    width = 2 * half
    bed_w = width / slots
    center_ext = {"L": 0.0, "R": 0.0}
    for s in "LR":
        extra = half - (cw / 2 + side_w[s])
        if extra > 1e-9:
            if cols[s]:
                cols[s][-1]["w"] += extra
            elif center:
                center_ext[s] = extra
    x_min, x_max = -half, half

    z_hall0 = 0.0 - HALL_DEPTH / 2 - 1.0      # 走廊北墙
    z_hall1 = z_hall0 + HALL_DEPTH            # 走廊南墙
    z_back0 = z_hall0 - bed_d
    z_front1 = z_hall1 + (FRONT_DEPTH if entries else 0.0)
    z_mid = z_hall1 + FRONT_DEPTH / 2

    out_rooms: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    def new_id(base: str) -> str:
        rid, n = base, 2
        while rid in used_ids:
            rid, n = f"{base}{n}", n + 1
        used_ids.add(rid)
        return rid

    # ---------- 卧室
    for i, r in enumerate(residents):
        rect = (x_min + i * bed_w, z_back0, x_min + (i + 1) * bed_w, z_hall0)
        rid = new_id(str(r["id"]))
        room = _place(bed_tpl, rid, rect, False, {"owner": str(r.get("name", r["id"])), "color": str(r.get("color", "#aaaaaa"))},
                      {"owner": r["id"], "template": "bedroom"})
        d = _door(bed_tpl, ["s"], False)
        room["door"] = {"wall": "s", "at": round((rect[0] + rect[2]) / 2 + (d[1] if d else 0), 3)}
        room["parent"] = "hall"
        out_rooms.append(room)

    # ---------- 空房：只有床和书桌，没有 spot，住户不会进去
    empty_tpl = {**bed_tpl, "spots": {}, "furniture": [f for f in bed_tpl.get("furniture") or [] if f.get("type") in ("bed", "desk", "chair")]}
    for i in range(len(residents), slots):
        rect = (x_min + i * bed_w, z_back0, x_min + (i + 1) * bed_w, z_hall0)
        room = _place(empty_tpl, new_id(f"vacant{i + 1}"), rect, False, {"owner": "", "color": "#cfc8bb"}, {"name": "空房", "template": "bedroom"})
        d = _door(bed_tpl, ["s"], False)
        room["door"] = {"wall": "s", "at": round((rect[0] + rect[2]) / 2 + (d[1] if d else 0), 3)}
        room["parent"] = "hall"
        room["vacant"] = True
        out_rooms.append(room)

    # ---------- 走廊
    hall = {"id": new_id("hall"), "name": "走廊", "kind": "hall", "icon": "", "floor": "tile",
            "rect": [x_min, z_hall0, x_max, z_hall1], "furniture": [
                {"type": "plant", "x": x_min + 0.6, "z": (z_hall0 + z_hall1) / 2},
                {"type": "plant", "x": x_max - 0.6, "z": (z_hall0 + z_hall1) / 2}],
            "spots": {}, "label": None}
    out_rooms.append(hall)

    # ---------- 前排
    def place_front(e: dict[str, Any], rect: tuple[float, float, float, float], mirror: bool) -> dict[str, Any]:
        cfg = e["cfg"]
        rid = new_id(str(cfg.get("id") or cfg["template"]))
        return _place(e["tpl"], rid, rect, mirror, {}, {"name": cfg.get("name"), "template": cfg["template"]})

    def set_door(room, tpl, want, parent, rect):
        d = _door(tpl, want, room["mirror"])
        if d is None:
            d = (want[0], 0.0)
        wall, off = d
        if wall in "ns":
            at = (rect[0] + rect[2]) / 2 + off
        else:
            at = (rect[1] + rect[3]) / 2 + off
        room["door"] = {"wall": wall, "at": round(at, 3)}
        room["parent"] = parent

    center_room = None
    if center:
        rect = (-cw / 2 - center_ext["L"], z_hall1, cw / 2 + center_ext["R"], z_front1)
        center_room = place_front(center, rect, False)
        set_door(center_room, center["tpl"], ["n"], hall["id"], rect)
        ent = center["tpl"].get("entrance")
        center_room["entrance"] = {"wall": "s", "at": round(float(ent if ent is not None else 0), 3)}
        if center_room["kind"] != "tall":
            center_room["kind"] = "tall"
        out_rooms.append(center_room)
    for side in "LR":
        mirror = side == "R"
        edge = -cw / 2 if side == "L" else cw / 2
        for ci, col in enumerate(cols[side]):
            w = col["w"]
            x0, x1 = (edge - w, edge) if side == "L" else (edge, edge + w)
            edge = x0 if side == "L" else x1
            adjacent = ci == 0 and center_room is not None
            toward_center = "e" if side == "L" else "w"
            rooms_in = col["rooms"]
            if col["tall"] or len(rooms_in) == 1:
                e = rooms_in[0]
                rect = (x0, z_hall1, x1, z_front1)
                room = place_front(e, rect, mirror)
                set_door(room, e["tpl"], ["n"], hall["id"], rect)
                out_rooms.append(room)
                continue
            top_e, bot_e = rooms_in
            rect_t = (x0, z_hall1, x1, z_mid)
            top = place_front(top_e, rect_t, mirror)
            set_door(top, top_e["tpl"], ["n"], hall["id"], rect_t)
            out_rooms.append(top)
            rect_b = (x0, z_mid, x1, z_front1)
            bot = place_front(bot_e, rect_b, mirror)
            if adjacent:
                set_door(bot, bot_e["tpl"], [toward_center, "n"], center_room["id"], rect_b)
                if bot["door"]["wall"] == "n":
                    bot["parent"] = top["id"]
            else:
                set_door(bot, bot_e["tpl"], ["n", toward_center], top["id"], rect_b)
                if bot["door"]["wall"] != "n":
                    bot["door"] = {"wall": "n", "at": round((x0 + x1) / 2, 3)}
            out_rooms.append(bot)

    if center_room is None:
        # 没有整高房间：大门开在最靠中间的前排房间南墙
        front = [r for r in out_rooms if r["rect"][3] == z_front1]
        if front:
            mid = min(front, key=lambda r: abs((r["rect"][0] + r["rect"][2]) / 2))
            mid["entrance"] = {"wall": "s", "at": 0.0}
    for r in out_rooms:
        if r.get("entrance"):
            ent = r["entrance"]
            ent["at"] = round((r["rect"][0] + r["rect"][2]) / 2 + float(ent["at"]), 3)

    # ---------- 户外：大门外往南一块接一块，从大门（或上一块场地的南边）走过去
    door_room = next((r for r in out_rooms if r.get("entrance")), None)
    z_end, x_low, x_high = z_front1, x_min, x_max
    if door_room is not None:
        parent, at = door_room["id"], door_room["entrance"]["at"]
        for i, o in enumerate(outdoors or []):
            name = o.get("template")
            if name not in templates:
                raise LayoutError(f"outdoors 第 {i + 1} 项：找不到模板 {name!r}（rooms/ 下应有 {name}.yaml）")
            tpl = templates[name]
            if tpl.get("kind") != "outdoor":
                raise LayoutError(f"outdoors 第 {i + 1} 项：模板 {name!r} 要写 kind: outdoor")
            w, d = (float(v) for v in (tpl.get("size") or [24, 16])[:2])
            rect = (-w / 2, z_end, w / 2, z_end + d)
            yard = _place(tpl, new_id(str(o.get("id") or name)), rect, False, {}, {"name": o.get("name"), "template": name})
            yard["door"] = {"wall": "n", "at": round(max(rect[0] + 1, min(rect[2] - 1, at)), 3)}
            yard["parent"] = parent
            out_rooms.append(yard)
            parent, at, z_end = yard["id"], 0.0, rect[3]
            x_low, x_high = min(x_low, rect[0]), max(x_high, rect[2])

    house = [x_min, z_back0, x_max, z_front1]
    return {
        "version": 2,
        "house": [round(v, 3) for v in house],
        "wall_height": 2.5,
        "door_width": DOOR_WIDTH,
        "hall": hall["id"],
        "hall_z": (z_hall0 + z_hall1) / 2,
        "rooms": out_rooms,
        "island": [round(x_low - 5, 3), round(z_back0 - 5, 3), round(x_high + 5, 3), round(z_end + 5, 3)],
    }


def spots_index(layout: dict[str, Any]) -> list[dict[str, Any]]:
    """所有可去的位置：[{room, room_name, spot, label, tags, owner}]。"""
    out = []
    for r in layout["rooms"]:
        for sid, s in (r.get("spots") or {}).items():
            out.append({"room": r["id"], "room_name": r["name"], "spot": sid, "label": s.get("label", sid),
                        "tags": list(s.get("tags") or []), "owner": r.get("owner"), "pose": s.get("pose", "stand"),
                        "ride": s.get("ride", ""), "outdoor": r.get("kind") == "outdoor"})
    return out


def describe(layout: dict[str, Any]) -> str:
    lines = []
    for r in layout["rooms"]:
        d = r.get("door") or {}
        lines.append(f"{r['id']:<10} {r['name']:<8} rect={r['rect']} door={d.get('wall', '-')}@{d.get('at', '-')} "
                     f"parent={r.get('parent', '-')} spots={list((r.get('spots') or {}).keys())}")
    return "\n".join(lines)


def deep(obj: Any) -> Any:
    return copy.deepcopy(obj)
