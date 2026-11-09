# 生成四个住户的 3D 模型。用法：
#   blender -b -P tools/avatars/build.py -- [ac ag ayu ak] [--no-render]
# 不写名字就全部生成。输出 skin/models/<id>.glb，预览图在 tools/avatars/previews/。
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit  # noqa: E402
import rig  # noqa: E402
from kit import (HY, V, Atlas, Mesh, clamp, ellipse_mask, eye_upper, eye_lower, head_point, head_z, mix, norm, rot_x, rot_y,  # noqa: E402
                 rot_z, segment_mask, spline, EYE_X, EYE_Y, EYE_W)

ROOT = os.path.dirname(os.path.dirname(HERE))
TAU = 2 * math.pi


# ---------------------------------------------------------------- 配置
CHARS = {
    'ac': dict(skin='#fde8da', hair='#e8772e', hair_tip='#f29a4a', hair_dark='#b9551c', eye='#c9682a', lash='#5a2c16',
               length=0.14, spread=0.50, wave=0.012, locks=15, sox='#f7f1e6', shoe='#2b2226',
               build='ac'),
    'ag': dict(skin='#fdeee6', hair='#e6e6f0', hair_tip='#cfcde2', hair_dark='#b4b2cc', eye='#9c8fc9', lash='#6a6488',
               length=0.22, spread=0.48, wave=0.03, locks=15, sox='#f4f3fa', shoe='#f0eff7',
               build='ag'),
    'ayu': dict(skin='#fde8da', hair='#2e3f9e', hair_tip='#4c9be0', hair_dark='#1f2b73', eye='#3d7be0', lash='#1a2150',
                length=0.34, spread=0.46, wave=0.03, locks=14, sox='#f4f2ee', shoe='#1e2754',
                build='ayu'),
    'ak': dict(skin='#fdeae0', hair='#ecEaf4', hair_tip='#bcd0f0', hair_dark='#c2bcdc', eye='#8a7fc8', lash='#4a4470',
               length=0.14, spread=0.52, wave=0.04, locks=16, sox='#f4f3fa', shoe='#2b2f55',
               build='ak'),
}


# ---------------------------------------------------------------- 权重
def W(**k):
    return k


def hair_w(p):
    y, x = p[1], p[0]
    l = clamp((x - 0.06) / 0.16)
    r = clamp((-x - 0.06) / 0.16)
    c = 1 - l - r
    if y >= 0.95:
        return W(head=1)
    if y >= 0.70:
        u = (0.95 - y) / 0.25
        out = {'head': 1 - u, 'hair_C1': c * u, 'hair_L1': l * u, 'hair_R1': r * u}
    elif y >= 0.42:
        u = (0.70 - y) / 0.28
        out = {'hair_C1': c * (1 - u), 'hair_L1': l * (1 - u), 'hair_R1': r * (1 - u),
               'hair_C2': c * u, 'hair_L2': l * u, 'hair_R2': r * u}
    else:
        out = {'hair_C2': c, 'hair_L2': l, 'hair_R2': r}
    return {k: v for k, v in out.items() if v > 1e-3}


def skirt_w(p):
    a = math.atan2(p[0], p[2])
    ca, sa = math.cos(a), math.sin(a)
    out = {}
    if ca > 0:
        out['skirt_F'] = ca * ca
    else:
        out['skirt_B'] = ca * ca
    if sa > 0:
        out['skirt_L'] = sa * sa
    else:
        out['skirt_R'] = sa * sa
    return out


def arm_w(side):
    def f(p):
        s = 1 if side == 'L' else -1
        sh = V(s * 0.17, 0.84, 0)
        d = V(s * math.sin(0.18), -math.cos(0.18), 0)
        t = np.dot(p - sh, d)
        u = clamp((t - 0.11) / 0.08)
        return {f'arm_{side}': 1 - u, f'fore_{side}': u} if 0 < u < 1 else ({f'arm_{side}': 1} if u <= 0 else {f'fore_{side}': 1})
    return f


# ---------------------------------------------------------------- 身体
class Build:
    def __init__(self, cid, cfg):
        self.id = cid
        self.c = cfg
        self.a = Atlas()
        self.m = Mesh()
        self.extra = []

    def col(self, h):
        return self.a.color(h)

    # ------------------------------------------------------------ 腿和鞋
    def legs(self, socks=None, boot=False):
        m, c = self.m, self.c
        for side, s in (('L', 1), ('R', -1)):
            x = s * 0.08
            def lw(p):
                u = clamp((0.20 - p[1]) / 0.08)
                return {f'thigh_{side}': 1 - u, f'shin_{side}': u} if 0 < u < 1 else ({f'thigh_{side}': 1} if u <= 0 else {f'shin_{side}': 1})
            m.lathe([(0.052, 0.34), (0.052, 0.22), (0.046, 0.12), (0.044, 0.06)], self.col(socks or c['skin']), lw, seg=8, center=(x, 0, 0), cap1=True)
            if socks and not boot:
                m.lathe([(0.066, 0.15), (0.062, 0.115), (0.066, 0.09)], self.col('#fffaf2'), lw, seg=10, center=(x, 0, 0))
            shoe = self.col(c['shoe'])
            sw = {f'shin_{side}': 1}
            if boot:
                m.lathe([(0.058, 0.20), (0.056, 0.10), (0.058, 0.04)], shoe, sw, seg=8, center=(x, 0, 0), cap0=True)
            m.ellipsoid((x, 0.05, 0.03), (0.066, 0.06, 0.105), shoe, sw, seg=12, rings=7,
                        xf=lambda p: V(p[0], max(p[1], -0.05), p[2]))

    # ------------------------------------------------------------ 躯干
    def torso(self, color, prof=None):
        m = self.m
        spine = lambda p: W(spine=clamp((0.74 - p[1]) / 0.08), chest=1 - clamp((0.74 - p[1]) / 0.08))
        prof = prof or [(0.118, 0.58), (0.122, 0.64), (0.142, 0.74), (0.15, 0.81), (0.125, 0.87), (0.05, 0.905)]
        m.lathe(prof, self.col(color), spine, seg=14, zs=0.78, cap1=True)

    def neck(self):
        self.m.lathe([(0.047, 0.86), (0.045, 0.96)], self.col(self.c['skin']), W(head=1), seg=8)

    # ------------------------------------------------------------ 手臂：cuff 袖口颜色，puff 泡泡袖半径
    def arm(self, side, color, cuff=None, puff=0.09, wide=False, bare_hand=True):
        m = self.m
        s = 1 if side == 'L' else -1
        sh = V(s * 0.17, 0.84, 0)
        d = V(s * math.sin(0.18), -math.cos(0.18), 0)
        w = arm_w(side)
        uvc = self.col(color)
        if wide:
            pts = [sh + d * (0.12 + (i / 8) * 0.22) for i in range(9)]
            m.tube(pts, lambda t: 0.052 + 0.115 * t ** 1.4, sides=10, uv=lambda t: uvc, w=w, cap0=False, cap1=False)
            skinuv = self.col(self.c['skin'])
            up = [sh + d * (i / 6) * 0.30 for i in range(7)]
            m.tube(up, lambda t: 0.05 - 0.008 * t, sides=7, uv=lambda t: skinuv, w=w)
        else:
            pts = [sh + d * (i / 12) * 0.28 for i in range(13)]
            def rad(t):
                bulge = math.exp(-((t - 0.28) / 0.28) ** 2)
                return 0.046 + (puff - 0.046) * bulge
            m.tube(pts, rad, sides=9, uv=lambda t: uvc, w=w)
        hand = sh + d * 0.32
        m.ellipsoid(hand, (0.04, 0.05, 0.04), self.col(self.c['skin']), {f'fore_{side}': 1}, seg=8, rings=5)
        if cuff:
            pos = sh + d * 0.27
            cc = self.col(cuff)
            ring = []
            for r, off in ((0.05, -0.03), (0.082, 0.02)):
                rr = []
                for j in range(14):
                    a = TAU * j / 14
                    u = norm(np.cross(d, V(0, 0, 1)))
                    v = V(0, 0, 1)
                    rad = r * (1 + (0.12 if off > 0 else 0) * math.sin(a * 7 / 1))
                    rr.append(pos + d * off + (u * math.cos(a) + v * math.sin(a)) * rad)
                ring.append(rr)
            m.grid(ring, cc, {f'fore_{side}': 1})

    # ------------------------------------------------------------ 头和脸
    def head(self):
        m, a, c = self.m, self.a, self.c
        a.paint_face(c['skin'], c['eye'], c['lash'])
        rings = []
        nlat, nlon = 18, 30
        for i in range(nlat + 1):
            lat = -math.pi / 2 * 0.96 + math.pi * 0.96 * i / nlat
            rings.append([head_point(TAU * j / nlon, lat) for j in range(nlon)])
        m.grid(rings, lambda i, j, p: a.face_uv(p[0], p[1]), W(head=1), cap0=True, cap1=True)
        self.eyelids()

    def eyelids(self):
        m, c = self.m, self.c
        cols = 11
        for s in (-1, 1):
            def pos(du, y, lift):
                x = s * EYE_X + s * du * EYE_W
                return V(x, y, head_z(x, y) + lift)
            # 眼皮：睁眼时压成一条，藏在肌肤色区域里；闭眼时往下盖住整只眼
            ids = []
            skin = self.col(c['skin'])
            for i in range(3):
                row = []
                for j in range(cols):
                    du = -1.2 + 2.4 * j / (cols - 1)
                    top = EYE_Y + eye_upper(du) + 0.032
                    closed = EYE_Y + eye_lower(du) - 0.006
                    u = i / 2
                    open_y = top - 0.0015 * u
                    close_y = top * (1 - u) + closed * u
                    v = m.add(pos(du, open_y, 0.0035), skin, W(head=1))
                    m.key[v] = pos(du, close_y, 0.0035)
                    row.append(v)
                ids.append(row)
            for i in range(2):
                for j in range(cols - 1):
                    m.f.append((ids[i][j], ids[i + 1][j], ids[i + 1][j + 1], ids[i][j + 1]))
            # 睫毛：睁眼时贴着画好的睫毛线，闭眼时落到下面成一道弧
            lash = self.col(c['lash'])
            rows = []
            for i in range(2):
                row = []
                for j in range(cols):
                    du = -0.9 + 1.98 * j / (cols - 1)
                    t = 0.0075 * (1 - 0.5 * du * du)
                    sign = 1 if i == 0 else -1
                    up_y = EYE_Y + eye_upper(du) + 0.013 + sign * t
                    closed = EYE_Y + eye_lower(du) - 0.004 + sign * t
                    v = m.add(pos(du, up_y, 0.002), lash, W(head=1))
                    m.key[v] = pos(du, closed, 0.0048)
                    row.append(v)
                rows.append(row)
            for j in range(cols - 1):
                m.f.append((rows[0][j], rows[1][j], rows[1][j + 1], rows[0][j + 1]))

    # ------------------------------------------------------------ 头发
    def hair(self, bang_tips=None, side_len=0.72):
        m, a, c = self.m, self.a, self.c
        base = a.ramp([(0, c['hair']), (0.55, c['hair']), (1, c['hair_tip'])])
        lit = mix(kit.hexrgb(c['hair']), [1, 1, 1], 0.32)
        lit_hex = '#%02x%02x%02x' % tuple(int(v * 255) for v in lit)
        bang = a.ramp([(0, c['hair']), (0.24, c['hair']), (0.32, lit_hex), (0.42, lit_hex), (0.52, c['hair']), (1, c['hair'])])
        under = a.ramp([(0, c['hair_dark']), (1, mix_hex(c['hair_dark'], c['hair_tip'], 0.8))])
        # 头顶
        nlat, nlon = 12, 28
        rings = []
        lats = []
        for i in range(nlat + 1):
            lat = math.radians(-58) + math.radians(150) * i / nlat
            lats.append(lat)
            rings.append([head_point(TAU * j / nlon, lat, 1.075) for j in range(nlon)])
        def skip(i, j):
            lon = (TAU * (j + 0.5) / nlon + math.pi) % TAU - math.pi
            lat = (lats[i] + lats[i + 1]) / 2
            return abs(lon) < math.radians(92) and lat < math.radians(18 + 18 * math.cos(lon))
        cap_uv = base(0.02)
        m.grid(rings, cap_uv, W(head=1), cap1=True, skip=skip)

        def lock(pts, width, thick=0.016, ramp=base, n=9, sides=5, w=hair_w):
            path = spline(pts, n)
            radial = lambda p: V(p[0], (p[1] - HY) if p[1] > HY else 0.15 * (p[1] - HY), p[2] + 0.001)
            m.tube(path, (lambda t: width * (1 - t ** 4) * min(1.0, 0.4 + t * 3)) if not callable(width) else width,
                   thick=lambda t: thick * (1 - 0.6 * t), sides=sides, uv=lambda t: ramp(t), w=w, radial=radial)

        # 刘海，lon 从脸中间往两边
        tips = bang_tips or [(-1.16, 18), (-0.86, 12), (-0.56, 4), (-0.30, -1), (-0.05, -9), (0.20, 1), (0.48, 7), (0.78, 14), (1.08, 20)]
        for lon, tip in tips:
            p0 = head_point(lon * 0.3, math.radians(70), 1.085)
            p1 = head_point(lon * 0.62, math.radians(52), 1.115)
            p2 = head_point(lon * 0.86, math.radians(30), 1.12)
            p3 = head_point(lon * 0.98, math.radians(tip), 1.10)
            lock([p0, p1, p2, p3], 0.075, ramp=bang, n=8, thick=0.014, w=W(head=1))
        # 鬓发，从耳前垂下
        for s in (-1, 1):
            for i, (lon, ln, wd) in enumerate(((1.38, side_len, 0.06), (1.58, side_len - 0.08, 0.07))):
                p0 = head_point(s * 1.25, math.radians(48), 1.09)
                p1 = head_point(s * lon, math.radians(16), 1.12)
                p2 = head_point(s * lon, math.radians(-30), 1.15)
                p3 = V(s * (0.335 + 0.012 * i), 0.88, 0.09 - 0.05 * i)
                p4 = V(s * (0.31 + 0.02 * i), ln, 0.10 - 0.05 * i)
                lock([p0, p1, p2, p3, p4], wd, n=11)
        # 后面的长发：内层深色、外层本色
        ln = c['length']
        spread = c['spread']
        wave = c['wave']
        rand = np.random.RandomState(sum(ord(x) for x in self.id))
        def back_path(lon, end_y, R, drift):
            P = [head_point(lon, math.radians(62), 1.085)]
            P.append(head_point(lon, math.radians(30), 1.12))
            P.append(head_point(lon, math.radians(-20), 1.16))
            steps = 4
            y0 = HY - 0.32
            for k in range(1, steps + 1):
                u = k / steps
                y = y0 + (end_y - y0) * u
                r = 0.36 + (R - 0.36) * u ** 0.8
                wob = math.sin(u * 8 + lon * 3) * wave * (0.4 + u)
                a = lon + drift * u
                P.append(V(math.sin(a) * r + wob, y, math.cos(a) * r * 0.86))
            return P
        n = c['locks']
        for i in range(n):
            lon = math.radians(100) + math.radians(160) * (i + 0.5) / n
            lon = (lon + math.pi) % TAU - math.pi
            end = ln + rand.uniform(0.0, 0.12)
            lock(back_path(lon, end, spread - 0.03, 0.0), 0.13, thick=0.016, ramp=under, n=12, sides=4)
        for i in range(n + 3):
            lon = math.radians(96) + math.radians(168) * (i + 0.5) / (n + 3)
            lon = (lon + math.pi) % TAU - math.pi
            end = ln + rand.uniform(-0.04, 0.10)
            lock(back_path(lon, end, spread + rand.uniform(0, 0.03), rand.uniform(-0.05, 0.05)), 0.105, thick=0.018, n=12)

    def ahoge(self, big=False):
        c = self.c
        u = self.a.ramp([(0, c['hair']), (1, c['hair_tip'])])
        k = 0.1 if not big else 0.14
        pts = spline([V(0, HY + 0.34, 0.02), V(0.01, HY + 0.34 + k, -0.03), V(-0.055, HY + 0.36 + k * 1.2, 0.0), V(-0.09, HY + 0.33 + k * 0.5, 0.03)], 8)
        self.m.tube(pts, lambda t: 0.013 * (1 - t ** 3), thick=lambda t: 0.009 * (1 - t ** 3), sides=4, uv=u, w=W(head=1))

    # ------------------------------------------------------------ 裙子
    def skirt(self, y0, y1, r0, r1, color, arc=None, amp=0.03, folds=9, seg=40, rings=6):
        m = self.m
        uv = self.col(color)
        prof = []
        for i in range(rings + 1):
            u = i / rings
            prof.append((r0 + (r1 - r0) * u ** 0.85, y0 + (y1 - y0) * u))
        def deform(r, i, a):
            return r * (1 + amp * (i / rings) * math.sin(a * folds))
        m.lathe(prof, uv, skirt_w, seg=seg, arc=arc, deform=deform)

    def frill(self, y, r, h, color, amp=0.035, folds=14, seg=56, arc=None, flare=0.05):
        def deform(rr, i, a):
            return rr * (1 + amp * (i / 2) * math.sin(a * folds))
        self.m.lathe([(r, y), (r + flare * 0.6, y - h * 0.5), (r + flare, y - h)], self.col(color), skirt_w, seg=seg, arc=arc, deform=deform)

    def collar(self, color, r=0.08, y=0.905):
        self.m.lathe([(0.05, y + 0.012), (r, y - 0.012), (r + 0.016, y - 0.03)], self.col(color), W(chest=1), seg=14,
                     deform=lambda rr, i, a: rr * (1 + 0.06 * (i / 2) * math.sin(a * 8)))

    # ------------------------------------------------------------ 配件
    def bow(self, c, color, scale=1.0, w=W(head=1), tails=True, tail_color=None, xf=None):
        m = self.m
        uv = self.col(color)
        X = xf or (lambda p: p)
        c = np.asarray(c, dtype=float)
        for s in (-1, 1):
            def tr(p):
                q = rot_z(V(p[0], p[1], p[2]), s * 0.2)
                return X(q * scale)
            m.ellipsoid(c + X(V(s * 0.085, 0.006, 0) * scale), (0.085 * scale, 0.055 * scale, 0.022 * scale), uv, w, seg=8, rings=4,
                        xf=lambda p: X(rot_z(p, s * 0.22)))
            if tails:
                tc = self.col(tail_color or color)
                pts = [c + X(V(s * (0.012 + 0.04 * t), -0.14 * t, 0) * scale) for t in (0, 0.25, 0.5, 0.75, 1)]
                m.tube(pts, lambda t: 0.02 * scale * (1 + 0.5 * t), thick=0.004, sides=4, uv=lambda t: tc, w=w, radial=lambda p: X(V(0, 0, 1)))
        m.ellipsoid(c, (0.024 * scale, 0.026 * scale, 0.022 * scale), uv, w, seg=6, rings=4)

    def flower(self, c, color, center, r=0.08, petals=10, w=W(head=1), xf=None):
        X = xf or (lambda p: p)
        c = np.asarray(c, dtype=float)
        uv = self.col(color)
        for i in range(petals):
            a = TAU * i / petals
            d = V(math.cos(a), math.sin(a), 0)
            def tr(p):
                q = V(p[0], p[1], p[2])
                ang = a - math.pi / 2
                return X(rot_z(q, ang))
            self.m.ellipsoid(c + X(d * r * 0.62), (r * 0.26, r * 0.5, r * 0.09), uv, w, seg=6, rings=3, xf=tr)
        self.m.ellipsoid(c + X(V(0, 0, r * 0.1)), (r * 0.26, r * 0.26, r * 0.14), self.col(center), w, seg=8, rings=4, xf=X)

    def face_xf(self, side, lift=-0.2):
        """头侧配件朝向：把 +z 转到朝外偏前。"""
        def xf(p):
            return rot_y(rot_x(p, lift), side * 0.75)
        return xf

    def headband(self, color='#ffffff', inner='#e8e4f4'):
        m = self.m
        uv = self.col(color)
        n = 72
        for layer, (grow, wd, hue) in enumerate(((1.20, 0.05, inner), (1.25, 0.075, color))):
            outer, inr = [], []
            for j in range(n + 1):
                a = -1.72 + 3.44 * j / n
                ang = a
                p = head_point(ang, math.radians(52) * math.cos(a * 0.42), grow - 0.06)
                up = norm(p - V(0, HY, 0))
                ruffle = 0.72 + 0.5 * abs(math.sin(j * math.pi / 6))
                outer.append(p + up * wd * ruffle)
                inr.append(p - up * 0.012)
            m.sheet(outer, inr, 2, self.col(hue), W(head=1))
        # 布带
        pts = [head_point(-1.72 + 3.44 * j / 20, math.radians(52) * math.cos((-1.72 + 3.44 * j / 20) * 0.42), 1.16) for j in range(21)]
        m.tube(pts, 0.016, thick=0.012, sides=5, uv=lambda t: uv, w=W(head=1))

    def book(self):
        m = self.m
        red, paper, gold = self.col('#7b2428'), self.col('#f3ead8'), self.col('#e8a23a')
        c = V(-0.115, 0.68, 0.21)
        xf = lambda p: rot_z(rot_y(rot_x(p, -0.1), -0.2), 0.16)
        def box(cc, r, uv):
            # 用 4 边管子代替立方体：角更利落
            pts = [c + xf(V(cc[0], cc[1] - r[1], cc[2])), c + xf(V(cc[0], cc[1] + r[1], cc[2]))]
            rings = []
            for p in pts:
                ring = [p + xf(V(sx * r[0], 0, sz * r[2])) for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                rings.append(ring)
            m.grid(rings, uv, W(chest=1), cap0=True, cap1=True)
        box((0, 0, 0), (0.092, 0.122, 0.028), red)
        box((0.006, 0, 0), (0.092, 0.112, 0.0288), paper)
        box((0, 0, 0.022), (0.094, 0.124, 0.008), red)
        self.flower(c + xf(V(0, 0, 0.034)), '#e8892e', '#c0601c', r=0.045, petals=8, w=W(chest=1), xf=lambda p: xf(p))
        box((0, 0.098, 0.031), (0.07, 0.004, 0.001), gold)
        box((0, -0.098, 0.031), (0.07, 0.004, 0.001), gold)

    def button(self, p, color, r=0.012, w=W(spine=1)):
        self.m.ellipsoid(p, (r, r, r * 0.6), self.col(color), w, seg=6, rings=3)

    # ------------------------------------------------------------ 四个人
    def build(self):
        getattr(self, 'make_' + self.c['build'])()
        return self

    def base(self, socks=None, boot=False):
        self.legs(socks=socks, boot=boot)
        self.neck()
        self.head()

    def make_ac(self):
        c = self.c
        self.base(socks=c['sox'])
        self.torso('#f6efe0')
        # 高腰胸衣、裙子
        self.m.lathe([(0.128, 0.60), (0.136, 0.655), (0.150, 0.745), (0.154, 0.76)], self.col('#26212b'), W(spine=1), seg=14, zs=0.82)
        for sx in (-1, 1):
            self.button(V(sx * 0.03, 0.70, 0.123), '#d9a24a')
        self.skirt(0.62, 0.24, 0.13, 0.35, '#f5ebd8', amp=0.05, folds=10)
        self.frill(0.26, 0.35, 0.07, '#fbf4e7', folds=14)
        self.frill(0.2, 0.38, 0.075, '#f5ebd8', folds=16)
        # 黑色外裙（前面开口），一侧露出橙色内摆
        self.skirt(0.625, 0.235, 0.138, 0.385, '#26212b', arc=(0.42, TAU - 0.42), amp=0.06, folds=11, seg=36)
        self.skirt(0.62, 0.25, 0.137, 0.37, '#d9702a', arc=(0.10, 0.82), amp=0.05, folds=5, seg=8)
        # 袖子、领口
        self.arm('L', '#f6efe0', cuff='#fbf4e7')
        self.arm('R', '#f6efe0', cuff='#fbf4e7')
        self.collar('#fbf4e7')
        self.bow(V(0, 0.835, 0.125), '#26212b', scale=0.7, w=W(chest=1))
        self.flower(V(0, 0.835, 0.15), '#e8892e', '#c0601c', r=0.04, petals=8, w=W(chest=1))
        self.book()
        self.hair()
        # 头侧：花和黑色蝴蝶结
        xf = self.face_xf(1)
        p = head_point(0.92, math.radians(46), 1.19)
        self.flower(p, '#e8772e', '#f2b24e', r=0.092, petals=12, xf=xf)
        pb = head_point(1.10, math.radians(24), 1.22)
        self.bow(pb, '#26212b', scale=0.82, tail_color='#f3ead8', xf=lambda q: rot_y(q, 1.0))

    # ------------------------------------------------------------ 阿G
    def knot(self, p, r, color, w=W(head=1), xf=None):
        """编绳结：几个小环。"""
        X = xf or (lambda q: q)
        p = np.asarray(p, dtype=float)
        uv = self.col(color)
        for k in range(4):
            a = TAU * k / 4 + 0.4
            c = p + X(V(math.cos(a), math.sin(a), 0) * r * 0.62)
            pts = [c + X(V(math.cos(t * TAU) * r * 0.55, math.sin(t * TAU) * r * 0.55, 0)) for t in [i / 10 for i in range(11)]]
            self.m.tube(pts, r * 0.15, sides=4, uv=lambda t: uv, w=w, cap0=False, cap1=False)
        self.m.ellipsoid(p, (r * 0.28, r * 0.28, r * 0.2), uv, w, seg=6, rings=3, xf=X)

    def horns(self):
        ramp = self.a.ramp([(0, '#d6d5e2'), (0.5, '#f4f3fa'), (1, '#ffffff')])
        for s in (-1, 1):
            pts = spline([V(s * 0.17, HY + 0.25, -0.03), V(s * 0.32, HY + 0.36, -0.07), V(s * 0.39, HY + 0.50, -0.09),
                          V(s * 0.34, HY + 0.63, -0.09), V(s * 0.22, HY + 0.68, -0.07)], 22)
            self.m.tube(pts, lambda t: (0.075 * (1 - t) ** 0.8 + 0.008) * (1 + 0.09 * math.sin(t * 46)), sides=7, uv=lambda t: ramp(t), w=W(head=1))

    def elf_ears(self):
        uv = self.col(self.c['skin'])
        for s in (-1, 1):
            pts = spline([V(s * 0.30, HY + 0.0, 0.0), V(s * 0.41, HY + 0.04, -0.015), V(s * 0.53, HY + 0.13, -0.03)], 6)
            self.m.tube(pts, lambda t: 0.055 * (1 - t) ** 0.9 + 0.002, thick=lambda t: 0.012, sides=5, uv=lambda t: uv, w=W(head=1), radial=lambda p: V(0, 0, 1))

    def wings(self):
        uv, rib = self.col('#e2e1ee'), self.col('#ffffff')
        for side, s in (('L', 1), ('R', -1)):
            w = {f'wing_{side}': 1}
            J = V(s * 0.12, 0.86, -0.38)
            E = V(s * 0.44, 1.14, -0.5)
            T = V(s * 0.88, 0.74, -0.58)
            ribs = [V(s * 0.70, 0.46, -0.54), V(s * 0.46, 0.42, -0.48), V(s * 0.24, 0.52, -0.44)]
            arc = [E + (T - E) * u + V(0, 0.09 * math.sin(u * math.pi), 0) for u in [i / 6 for i in range(7)]]
            rim = list(arc)
            prev = T
            for r in ribs + [J]:
                for u in (0.2, 0.4, 0.6, 0.8):
                    mid = prev + (r - prev) * u
                    pull = 0.16 * math.sin(u * math.pi)
                    rim.append(mid + (E - mid) * pull)
                rim.append(r)
                prev = r
            self.m.fan(E, rim, uv, w)
            self.m.fan(E, [J, E + (J - E) * 0.5 + V(0, 0.05, 0), E], uv, w)
            bone = lambda a, b, r0, r1, bend=0.03: self.m.tube(
                spline([a, (a + b) / 2 + V(0, bend, 0), b], 6), lambda t: r0 + (r1 - r0) * t, sides=5, uv=lambda t: rib, w=w)
            bone(J, E, 0.03, 0.022)
            bone(E, T, 0.022, 0.006, 0.09)
            for r in ribs:
                bone(E, r, 0.014, 0.005, 0.0)

    def tail(self):
        ramp = self.a.ramp([(0, '#f4f3fa'), (0.7, '#e6e4f2'), (1, '#c9c6e0')])
        ctrl = [V(0, 0.42, -0.30), V(-0.12, 0.22, -0.54), V(-0.42, 0.11, -0.62), V(-0.68, 0.17, -0.48), V(-0.82, 0.31, -0.32)]
        path = spline(ctrl, 22)
        def w(p):
            # 按离各段中点的距离分权重
            d1 = np.linalg.norm(p - ctrl[1])
            d2 = np.linalg.norm(p - ctrl[2])
            d3 = np.linalg.norm(p - (ctrl[3] + ctrl[4]) / 2)
            a = np.array([1 / (d1 + 0.02) ** 3, 1 / (d2 + 0.02) ** 3, 1 / (d3 + 0.02) ** 3])
            a /= a.sum()
            return {'tail1': float(a[0]), 'tail2': float(a[1]), 'tail3': float(a[2])}
        self.m.tube(path, lambda t: 0.105 * (1 - t) ** 0.7 + 0.012, sides=9, uv=lambda t: ramp(t), w=w)
        spike = self.col('#ffffff')
        for k in range(2, 21, 2):
            t = k / 22
            p = path[k]
            r = 0.105 * (1 - t) ** 0.7 + 0.012
            T = norm(path[k + 1] - path[k - 1])
            up = norm(V(0, 1, 0) - T * T[1])
            pts = [p + up * r * 0.8, p + up * (r + 0.05 * (1 - t) + 0.015) + T * 0.03]
            self.m.tube(pts, lambda u: 0.03 * (1 - u) * (1 - t * 0.6) + 0.001, thick=lambda u: 0.009 * (1 - u) + 0.001, sides=4, uv=lambda u: spike, w=w, radial=lambda q: T)

    def make_ag(self):
        c = self.c
        self.extra = [
            ('wing_L', 'chest', (0.12, 0.86, -0.38), (0.44, 1.14, -0.5)), ('wing_R', 'chest', (-0.12, 0.86, -0.38), (-0.44, 1.14, -0.5)),
            ('tail1', 'hips', (0, 0.42, -0.30), (-0.12, 0.22, -0.54)), ('tail2', 'tail1', (-0.12, 0.22, -0.54), (-0.42, 0.11, -0.62)),
            ('tail3', 'tail2', (-0.42, 0.11, -0.62), (-0.82, 0.31, -0.32))]
        self.base(socks=c['sox'], boot=True)
        # 上身：露肩，胸前有布
        self.m.lathe([(0.12, 0.79), (0.15, 0.815), (0.125, 0.87), (0.05, 0.905)], self.col(c['skin']), W(chest=1), seg=14, zs=0.78, cap1=True)
        self.torso('#fbfaff', prof=[(0.118, 0.58), (0.122, 0.64), (0.142, 0.74), (0.155, 0.80), (0.125, 0.825)])
        self.collar('#fbfaff', r=0.058, y=0.895)
        # 长裙，前面偏一侧开衩
        self.skirt(0.62, 0.05, 0.13, 0.44, '#e9e8f2', arc=(0.08, TAU - 0.46), amp=0.055, folds=12, seg=46)
        self.skirt(0.62, 0.22, 0.128, 0.30, '#e6e4f1', arc=(-0.5, 0.14), amp=0.03, folds=4, seg=8)
        self.frill(0.11, 0.42, 0.09, '#f0eff7', folds=16, arc=(0.08, TAU - 0.46), seg=46, flare=0.06)
        # 腰链和结
        pts = [V(math.sin(a) * 0.145, 0.60 - 0.012 * math.cos(a * 2), math.cos(a) * 0.145 * 1.02) for a in [-1.3 + 2.6 * i / 14 for i in range(15)]]
        chain = self.col('#7f7d92')
        self.m.tube(pts, 0.006, sides=4, uv=lambda t: chain, w=W(spine=1))
        for x, y in ((-0.11, 0.6), (0.11, 0.6)):
            self.knot(V(x, y, 0.155), 0.04, '#3f3d52', w=W(spine=1))
            tassel = [V(x, y - 0.03, 0.17), V(x, y - 0.14, 0.2)]
            self.m.tube(tassel, 0.008, sides=4, uv=lambda t: chain, w=skirt_w)
        self.arm('L', '#e9e8f2', cuff=None, wide=True)
        self.arm('R', '#e9e8f2', cuff=None, wide=True)
        self.hair()
        self.ahoge(big=True)
        self.horns()
        self.elf_ears()
        self.knot(head_point(0.95, math.radians(38), 1.2), 0.062, '#3f3d52', xf=self.face_xf(1))
        self.wings()
        self.tail()

    # ------------------------------------------------------------ 阿鱼
    def fins(self):
        top, lo = self.a.ramp([(0, '#2b3a90'), (1, '#4661c4')]), self.col('#f1f5fb')
        for s in (-1, 1):
            base = V(s * 0.33, HY + 0.0, -0.01)
            def outline(k):
                pts = []
                for i in range(9):
                    u = i / 8
                    x = base[0] + s * 0.22 * u
                    h = 0.075 * math.sin(math.pi * min(1.0, u * 1.02)) ** 0.7
                    pts.append(V(x, base[1] + 0.03 - 0.075 * u * u + k * h, base[2] - 0.02 * u))
                return pts
            self.m.sheet(outline(1), outline(0), 2, lambda i, j, p: top(i / 8), W(head=1))
            self.m.sheet(outline(0), outline(-0.72), 2, lo, W(head=1))

    def whale_tail(self):
        ramp = self.a.ramp([(0, '#2e3f9e'), (1, '#4cb4e0')])
        w = W(hair_L2=1)
        stem = spline([V(0.36, 0.42, -0.2), V(0.44, 0.34, -0.2), V(0.52, 0.30, -0.18)], 6)
        self.m.tube(stem, lambda t: 0.034 - 0.018 * t, thick=0.018, sides=6, uv=lambda t: ramp(0.1 + t * 0.3), w=w)
        c = stem[-1]
        for k in (-1, 1):
            up, lo = [], []
            for i in range(9):
                u = i / 8
                # k=1 向上，k=-1 向外下，形成鲸尾两片
                d = V(0.15 * u + (0.02 if k > 0 else 0.1 * u), k * 0.16 * u, 0)
                hw = 0.055 * math.sin(math.pi * min(1, u)) ** 0.7
                n = norm(V(-d[1], d[0], 0) + V(1e-4, 0, 0))
                up.append(c + d + n * hw + V(0, 0, 0.005))
                lo.append(c + d - n * hw)
            self.m.sheet(up, lo, 2, lambda i, j, p: ramp(0.4 + 0.6 * i / 8), w)

    def paint_whale(self, navy):
        def fn(X, Y, over, N):
            body = ellipse_mask(X, Y, 0.46, 0.42, 0.34, 0.25, N)
            over(body, '#3f67b8')
            over(ellipse_mask(X, Y, 0.46, 0.27, 0.32, 0.14, N) * body, '#d8e6f5')
            for sgn in (-1, 1):
                over(segment_mask(X, Y, (0.76, 0.47), (0.89, 0.56 + sgn * 0.13), 0.055, N), '#3f67b8')
            over(ellipse_mask(X, Y, 0.27, 0.45, 0.025, 0.03, N), '#1b2453')
            over(segment_mask(X, Y, (0.47, 0.63), (0.47, 0.76), 0.012, N), '#6eb4e8')
            for sgn in (-1, 1):
                over(segment_mask(X, Y, (0.47, 0.76), (0.47 + sgn * 0.09, 0.84), 0.012, N), '#6eb4e8')
        return self.a.paint(128, fn, '#fbfaf5')

    def make_ayu(self):
        c = self.c
        self.base(socks=c['sox'])
        navy, white, gold = '#1e2754', '#fbf9f4', '#d9b25a'
        self.torso(navy)
        self.skirt(0.62, 0.22, 0.13, 0.36, navy, amp=0.05, folds=10)
        self.m.lathe([(0.348, 0.262), (0.366, 0.235)], self.col(gold), skirt_w, seg=40, deform=lambda r, i, a: r * (1 + 0.04 * math.sin(a * 10)) + 0.006)
        self.frill(0.245, 0.36, 0.075, white, folds=16, flare=0.05)
        # 围裙
        self.skirt(0.625, 0.285, 0.14, 0.36, white, arc=(-0.72, 0.72), amp=0.02, folds=6, seg=16, rings=4)
        self.frill(0.295, 0.356, 0.05, white, folds=12, arc=(-0.76, 0.76), seg=22, flare=0.035)
        at = self.paint_whale(navy)
        y = 0.43
        r = 0.14 + (0.36 - 0.14) * ((0.625 - y) / (0.625 - 0.285)) ** 0.85
        slope = (0.36 - 0.14) / (0.625 - 0.285)
        self.m.quad_decal(V(0, y, r + 0.006), V(0.115, 0, 0), norm(V(0, 1, -slope)) * 0.115, at, 128, self.a, W(skirt_F=1), grid=1)
        # 胸前的围裙片和肩带
        wh = self.col(white)
        rows = []
        for y, half in ((0.63, 0.078), (0.70, 0.075), (0.77, 0.085)):
            rows.append([V(half * (2 * j / 6 - 1), y, 0.126 + 0.008 * (y - 0.63) / 0.14 - 0.14 * (half * (2 * j / 6 - 1)) ** 2 + 0.016) for j in range(7)])
        self.m.grid(rows, wh, W(chest=1), wrap=False)
        for s in (-1, 1):
            p = [V(s * 0.078, 0.77, 0.14), V(s * 0.1, 0.86, 0.09), V(s * 0.1, 0.89, -0.02), V(s * 0.085, 0.72, -0.13)]
            self.m.tube(spline(p, 8), 0.016, thick=0.005, sides=4, uv=lambda t: wh, w=W(chest=1))
        self.arm('L', navy, cuff=white)
        self.arm('R', navy, cuff=white)
        self.collar(white)
        self.bow(V(0, 0.835, 0.125), navy, scale=0.75, w=W(chest=1))
        self.button(V(0, 0.835, 0.15), '#6eb4e8', r=0.018, w=W(chest=1))
        self.hair()
        self.ahoge(big=True)
        self.headband()
        self.fins()
        self.bow(head_point(1.05, math.radians(32), 1.2), '#5aa6e6', scale=0.72, xf=lambda q: rot_y(q, 1.0))
        self.whale_tail()

    # ------------------------------------------------------------ 阿K
    def paint_k(self, frame):
        def fn(X, Y, over, N):
            s = 0.055
            over(segment_mask(X, Y, (0.32, 0.2), (0.32, 0.8), s, N), '#ffffff')
            over(segment_mask(X, Y, (0.32, 0.47), (0.7, 0.8), s, N), '#ffffff')
            over(segment_mask(X, Y, (0.4, 0.53), (0.72, 0.2), s, N), '#ffffff')
        return self.a.paint(96, fn, frame)

    def k_plate(self, center, hw, xf, w):
        at = self.paint_k('#2b2f55')
        frame = self.col('#d9d6f0')
        right, up = xf(V(hw, 0, 0)), xf(V(0, hw * 1.15, 0))
        n = xf(V(0, 0, 1))
        c = np.asarray(center, dtype=float)
        ring = [c + (right * sx + up * sy) * 1.14 for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        back = [p - n * 0.008 for p in ring]
        self.m.grid([back, ring], frame, w, cap0=True, cap1=True)
        self.m.quad_decal(c + n * 0.0015, right, up, at, 96, self.a, w)

    def moon(self, c, xf):
        uv = self.col('#b9bccd')
        c = np.asarray(c, dtype=float)
        pts = [c + xf(V(math.cos(a) * 0.075, math.sin(a) * 0.075, 0)) for a in [0.6 + 4.4 * i / 14 for i in range(15)]]
        self.m.tube(pts, lambda t: 0.024 * math.sin(math.pi * t) ** 0.8 + 0.002, thick=0.009, sides=5, uv=lambda t: uv, w=W(head=1), radial=lambda p: xf(V(0, 0, 1)))

    def make_ak(self):
        c = self.c
        self.base(socks=c['sox'])
        navy, white, lav = '#2b2f55', '#f8f7fc', '#8e86c2'
        self.torso(white)
        self.m.lathe([(0.128, 0.60), (0.136, 0.655), (0.150, 0.745), (0.154, 0.765)], self.col(navy), W(spine=1), seg=14, zs=0.82)
        for y in (0.64, 0.68, 0.72):
            self.button(V(0, y, 0.122), '#d9d6f0', r=0.009)
        self.skirt(0.62, 0.24, 0.13, 0.35, white, amp=0.05, folds=12)
        self.frill(0.26, 0.35, 0.07, '#fdfcff', folds=16)
        self.frill(0.205, 0.38, 0.07, lav, folds=18)
        self.skirt(0.625, 0.235, 0.138, 0.385, lav, arc=(0.32, 3.75), amp=0.06, folds=10, seg=26)
        self.skirt(0.627, 0.215, 0.14, 0.39, navy, arc=(3.7, TAU - 0.32), amp=0.06, folds=9, seg=20)
        self.arm('L', white, cuff='#fdfcff')
        self.arm('R', white, cuff='#fdfcff')
        self.collar('#fdfcff')
        self.bow(V(0, 0.835, 0.125), navy, scale=0.75, w=W(chest=1))
        self.k_plate(V(0.16, 0.5, 0.33), 0.036, lambda p: rot_x(rot_y(p, 0.45), -0.45), skirt_w)
        self.hair()
        self.headband()
        xf = self.face_xf(1)
        self.bow(head_point(0.92, math.radians(44), 1.22), navy, scale=0.86, xf=lambda q: rot_y(q, 0.8))
        self.k_plate(head_point(1.02, math.radians(23), 1.25), 0.052, xf, W(head=1))
        self.moon(head_point(0.98, math.radians(50), 1.3), xf)


def mix_hex(a, b, t):
    v = mix(kit.hexrgb(a), kit.hexrgb(b), t)
    return '#%02x%02x%02x' % tuple(int(x * 255) for x in v)


# ---------------------------------------------------------------- 动画
CLIPS = {'idle': 72, 'walk': 16, 'sit': 72, 'sit_floor': 72, 'lie': 72}


def posefn(cid):
    holds_book = cid == 'ac'
    has_wings = cid == 'ag'
    has_tail = cid == 'ag'

    def pose(name, t):
        P = {}
        ph = TAU * t
        s, c2 = math.sin(ph), math.sin(ph * 2)
        rootloc = [0, 0, 0]
        if name == 'walk':
            P['thigh_R'] = (s * 0.6, 0, 0)
            P['thigh_L'] = (-s * 0.6, 0, 0)
            P['shin_R'] = (max(0, s) * 0.45, 0, 0)
            P['shin_L'] = (max(0, -s) * 0.45, 0, 0)
            P['arm_R'] = (-s * 0.5, 0, 0)
            P['arm_L'] = (s * 0.5, 0, 0)
            rootloc[1] = abs(s) * 0.04
            P['head'] = (0, 0, s * 0.03)
            P['skirt_F'] = (-abs(s) * 0.12, 0, 0)
            P['skirt_B'] = (abs(s) * 0.10, 0, 0)
            for k in ('C', 'L', 'R'):
                P[f'hair_{k}1'] = (0.05 + c2 * 0.03, 0, 0)
                P[f'hair_{k}2'] = (0.06 + math.sin(ph * 2 - 0.8) * 0.05, 0, 0)
        else:
            breathe = s * 0.012
            P['chest'] = (breathe, 0, 0)
            P['spine'] = (-breathe * 0.5, 0, 0)
            P['arm_R'] = (math.sin(ph + 1) * 0.03, 0, 0)
            P['arm_L'] = (math.sin(ph) * 0.03, 0, 0)
            P['head'] = (0, 0, s * 0.03)
            for k in ('C', 'L', 'R'):
                P[f'hair_{k}2'] = (math.sin(ph + 0.6) * 0.012, 0, 0)
            if name == 'idle':
                rootloc[1] = s * 0.006
            elif name in ('sit', 'sit_floor'):
                y = 0.2 if name == 'sit' else -0.2
                rootloc[1] = y + s * 0.006
                thigh, shin, arm = (-1.34, 0.42, -0.55) if name == 'sit' else (-1.5, 0.05, -0.2)
                P['thigh_R'] = P['thigh_L'] = (thigh, 0, 0)
                P['shin_R'] = P['shin_L'] = (shin, 0, 0)
                P['arm_R'] = (arm + math.sin(ph + 1) * 0.03, 0, 0)
                P['arm_L'] = (arm + math.sin(ph) * 0.03, 0, 0)
                # 椅子上裙摆基本垂着；坐地上要多张开一点，不然穿进地板
                long_skirt = cid == 'ag'
                spread = 0.16 if name == 'sit' else (0.62 if long_skirt else 0.42)
                P['skirt_F'] = (-0.62 if name == 'sit' else -0.72, 0, 0)
                P['skirt_B'] = (spread, 0, 0)
                P['skirt_L'] = (0, 0, spread)
                P['skirt_R'] = (0, 0, -spread)
                for k in ('C', 'L', 'R'):
                    P[f'hair_{k}1'] = (0.28, 0, 0)
            elif name == 'lie':
                P['#rootrot'] = (-math.pi / 2, 0, 0)
                rootloc = [0, 0.9, 0.72]
                P['chest'] = (s * 0.02, 0, 0)
                # 裙摆往身上收，不捅穿被子
                P['skirt_F'] = (1.2, 0, 0)
                P['skirt_L'] = (0, 0, -0.34)
                P['skirt_R'] = (0, 0, 0.34)
        if holds_book:
            P['arm_R'] = (-0.42 if name != 'lie' else -0.3, -0.25, 0.2)
            P['fore_R'] = (-1.72, 0.55, 0)
        if has_wings:
            f = 8 if name == 'walk' else 1
            flap = math.sin(ph * (2 if name == 'walk' else 1)) * 0.12 + 0 * f
            fold = -1.1 if name == 'lie' else 0
            P['wing_L'] = (0, flap, fold * 1)
            P['wing_R'] = (0, -flap, -fold)
        if has_tail:
            lift = 0.55 if name == 'sit_floor' else 0.18 if name == 'sit' else 0
            sway = math.sin(ph * (2 if name == 'walk' else 1)) * 0.05
            P['tail1'] = (lift, sway, 0)
            P['tail2'] = (0, sway, 0)
            P['tail3'] = (0, sway * 1.4, 0)
        P['#root'] = (tuple(rootloc), None)
        if '#rootrot' in P:
            P['root'] = P.pop('#rootrot')
        return P
    return pose


# ---------------------------------------------------------------- 入口
def make(cid, render=True, samples=40):
    rig.clear_scene()
    bd = Build(cid, CHARS[cid]).build()
    arm, ob = rig.build_object(cid, bd.m, bd.a, bd.extra, os.path.join(os.environ.get('TEMP', '/tmp'), 'avatar_tex'))
    fn = posefn(cid)
    rig.make_actions(arm, CLIPS, fn)
    ob.data.shape_keys.key_blocks['eyes_closed'].value = 0
    out = os.path.join(ROOT, 'skin', 'models', cid + '.glb')
    rig.export_glb(out)
    ob.data.calc_loop_triangles()
    print(f'[{cid}] tris={len(ob.data.loop_triangles)} verts={len(ob.data.vertices)} size={os.path.getsize(out) / 1024:.0f}KB')
    if render:
        rig.render_views(arm, ob, cid, os.path.join(HERE, 'previews'), fn, samples=samples)


if __name__ == '__main__':
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    render = '--no-render' not in argv
    ids = [a for a in argv if a in CHARS] or list(CHARS)
    for cid in ids:
        make(cid, render=render)
