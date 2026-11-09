# 建模工具：贴图集、网格拼装。坐标系跟 three.js 一样（x 右、y 上、z 朝前），写进 Blender 时再转换。
import math

import numpy as np

HY = 1.18            # 头中心高度，跟 web/js/avatar.js 的 HEAD_Y 一致
HEAD_A, HEAD_B, HEAD_C = 0.335, 0.32, 0.30
EYE_X, EYE_Y, EYE_W, EYE_H = 0.135, HY - 0.055, 0.092, 0.088
FACE_HALF = 0.36     # 脸部贴图覆盖的半宽


def V(*a):
    return np.array(a, dtype=float)


def hexrgb(h):
    h = h.lstrip('#')
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def mix(a, b, t):
    return np.asarray(a) * (1 - t) + np.asarray(b) * t


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


# ---------------------------------------------------------------- 头的形状
def taper(y):
    t = clamp((HY + 0.02 - y) / HEAD_B)
    return 1 - 0.30 * t * t


def head_point(lon, lat, grow=1.0):
    y = HY + HEAD_B * math.sin(lat) * grow
    t = clamp((HY + 0.02 - y) / HEAD_B)
    return V(HEAD_A * grow * math.cos(lat) * math.sin(lon) * taper(y), y,
             HEAD_C * grow * math.cos(lat) * math.cos(lon) * (1 - 0.12 * t * t))


def head_z(x, y):
    t = clamp((HY + 0.02 - y) / HEAD_B)
    X = x / (HEAD_A * taper(y))
    Y = (y - HY) / HEAD_B
    return HEAD_C * math.sqrt(max(0.0, 1 - X * X - Y * Y)) * (1 - 0.12 * t * t)


# 眼睛轮廓。du：-1 内眼角到 1 外眼角。返回相对眼睛中心的高度
def eye_upper(du):
    return EYE_H * (0.76 - (0.42 if du > 0 else 0.26) * du * du - 0.08 * du)


def eye_lower(du):
    return -EYE_H * (0.92 - 0.42 * du * du)


# ---------------------------------------------------------------- 贴图集
class Atlas:
    """1024 见方。左上 512 脸，右上纯色格，右下渐变条，左下贴花。"""
    S = 1024
    CELL = 32

    def __init__(self):
        self.px = np.ones((self.S, self.S, 3))
        self.colors = {}
        self.nramp = 0
        self.decal_x = 0
        self.decal_y = 512

    def _uv(self, x, y):
        return (x / self.S, 1 - y / self.S)

    def color(self, h):
        h = h.lower()
        if h not in self.colors:
            i = len(self.colors)
            col, row = i % 16, i // 16
            if row >= 16:
                raise RuntimeError('纯色格用完了')
            x, y = 512 + col * self.CELL, row * self.CELL
            self.px[y:y + self.CELL, x:x + self.CELL] = hexrgb(h)
            self.colors[h] = self._uv(x + self.CELL / 2, y + self.CELL / 2)
        return self.colors[h]

    def ramp(self, stops):
        """沿 t 0→1 的竖向渐变，stops = [(t, '#hex'), ...]，返回 t -> uv。"""
        k = self.nramp
        self.nramp += 1
        x = 512 + k * self.CELL
        H = 512
        ts = np.linspace(0, 1, H)
        cols = np.stack([np.interp(ts, [s[0] for s in stops], [hexrgb(s[1])[c] for s in stops]) for c in range(3)], axis=1)
        self.px[512:512 + H, x:x + self.CELL] = cols[:, None, :]
        cx = x + self.CELL / 2

        def f(t):
            return self._uv(cx, 512 + clamp(t) * (H - 1) + 0.5)
        return f

    def decal(self, size):
        """分配一块 size 见方的区域，返回 (x, y)。"""
        if self.decal_x + size > 512:
            self.decal_x = 0
            self.decal_y += size
        at = (self.decal_x, self.decal_y)
        self.decal_x += size
        return at

    def decal_uv(self, at, size, s, t):
        """s, t 为 0-1，t=0 在贴花底部。内缩 2 像素防止取到邻格。"""
        x = at[0] + 2 + s * (size - 4)
        y = at[1] + 2 + (1 - t) * (size - 4)
        return self._uv(x, y)

    def face_uv(self, x, y):
        return ((x + FACE_HALF) / (2 * FACE_HALF) * 0.5,
                1 - (HY + FACE_HALF - y) / (2 * FACE_HALF) * 0.5)

    # ------------------------------------------------------------ 脸
    def paint_face(self, skin, eye, lash, blush='#f3a3a0'):
        N = 1536
        xs = (np.arange(N) + 0.5) / N * 2 * FACE_HALF - FACE_HALF
        ys = HY + FACE_HALF - (np.arange(N) + 0.5) / N * 2 * FACE_HALF
        X, Y = np.meshgrid(xs, ys)
        img = np.ones((N, N, 3)) * hexrgb(skin)

        def over(mask, col):
            nonlocal img
            m = np.clip(mask, 0, 1)[..., None]
            img = img * (1 - m) + np.asarray(col) * m

        def ellipse(cx, cy, rx, ry):
            d = np.sqrt(((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2)
            return np.clip((1 - d) * min(rx, ry) * 700 + 0.5, 0, 1)

        e = hexrgb(eye)
        L = hexrgb(lash)
        for side in (-1, 1):
            cx, cy = side * EYE_X, EYE_Y
            du = side * (X - cx) / EYE_W
            up = cy + EYE_H * (0.76 - np.where(du > 0, 0.42, 0.26) * du * du - 0.08 * du)
            lo = cy + eye_lower(du)
            soft = 700
            sclera = np.clip((up - Y) * soft + 0.5, 0, 1) * np.clip((Y - lo) * soft + 0.5, 0, 1) * (np.abs(du) < 1)
            layer = np.ones((N, N, 3)) * hexrgb('#fbfaff')
            # 上眼睑投下的影子
            sh = np.clip((Y - (up - 0.03)) / 0.03, 0, 1)[..., None] * 0.35
            layer = layer * (1 - sh) + mix(e, [0.3, 0.3, 0.45], 0.5) * sh
            # 虹膜：上深下亮
            icx, icy, irx, iry = cx, cy - 0.006, 0.076, 0.092
            iris = ellipse(icx, icy, irx, iry)
            g = np.clip((Y - (icy - iry)) / (2 * iry), 0, 1)[..., None]
            col = (e * 1.35).clip(0, 1) * (1 - g) + e * 0.32 * g
            m = iris[..., None]
            layer = layer * (1 - m) + col * m
            # 虹膜外圈
            ring = np.clip(iris - ellipse(icx, icy, irx - 0.008, iry - 0.008), 0, 1)[..., None]
            layer = layer * (1 - ring) + e * 0.22 * ring
            # 瞳孔
            m = ellipse(cx, cy + 0.004, 0.034, 0.05)[..., None]
            layer = layer * (1 - m) + e * 0.14 * m
            # 下半的亮斑
            m = (ellipse(cx, cy - 0.052, 0.042, 0.024) * 0.75)[..., None]
            layer = layer * (1 - m) + mix(e * 1.4, [1, 1, 1], 0.45).clip(0, 1) * m
            # 高光
            m = ellipse(cx - 0.024, cy + 0.04, 0.026, 0.03)[..., None]
            layer = layer * (1 - m) + np.ones(3) * m
            m = ellipse(cx + 0.03, cy - 0.03, 0.011, 0.011)[..., None]
            layer = layer * (1 - m) + np.ones(3) * m
            m = sclera[..., None]
            img = img * (1 - m) + layer * m
            # 上睫毛线
            t = 0.026 * (1 - 0.25 * du * du)
            lashm = np.clip((Y - up) * soft + 0.5, 0, 1) * np.clip((up + t - Y) * soft + 0.5, 0, 1) * (du > -0.92) * (du < 1.14)
            over(lashm, L)
            # 外眼角上翘一笔
            tip_x = side * (EYE_X + EYE_W * 1.02)
            over(ellipse(tip_x, cy + eye_upper(1.0) - 0.006, 0.016, 0.009), L)
            # 下睫毛
            lm = np.clip((lo - Y) * soft + 0.5, 0, 1) * np.clip((Y - lo + 0.0045) * soft + 0.5, 0, 1) * (du > 0.15) * (du < 0.98)
            over(lm, mix(L, hexrgb(skin), 0.25))
            # 腮红
            bcx, bcy = side * 0.215, HY - 0.15
            over(0.5 * np.exp(-(((X - bcx) / 0.062) ** 2 + ((Y - bcy) / 0.03) ** 2)), hexrgb(blush))
        # 鼻子、嘴
        over(ellipse(0.0, HY - 0.16, 0.006, 0.0045) * 0.6, mix(hexrgb(skin), hexrgb('#b5544a'), 0.6))
        my = HY - 0.21
        mm = np.clip((0.0042 - np.abs(Y - (my - 28 * X * X * 0.15))) * 700 + 0.5, 0, 1) * (np.abs(X) < 0.019)
        over(mm, hexrgb('#a34a42'))
        self.px[0:512, 0:512] = img.reshape(512, 3, 512, 3, 3).mean(axis=(1, 3))

    # ------------------------------------------------------------ 贴花
    def paint(self, size, fn, bg):
        """fn(X, Y, over)：在 0-1 坐标（Y 向上）里画。返回贴花位置。"""
        at = self.decal(size)
        N = size * 3
        c = (np.arange(N) + 0.5) / N
        X, Y = np.meshgrid(c, 1 - c)
        state = {'img': np.ones((N, N, 3)) * hexrgb(bg)}

        def over(mask, col):
            m = np.clip(mask, 0, 1)[..., None]
            state['img'] = state['img'] * (1 - m) + hexrgb(col) * m
        fn(X, Y, over, N)
        small = state['img'].reshape(size, 3, size, 3, 3).mean(axis=(1, 3))
        self.px[at[1]:at[1] + size, at[0]:at[0] + size] = small
        return at


def segment_mask(X, Y, a, b, r, N):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = np.clip(((X - ax) * dx + (Y - ay) * dy) / (dx * dx + dy * dy), 0, 1)
    d = np.hypot(X - ax - t * dx, Y - ay - t * dy)
    return np.clip((r - d) * N + 0.5, 0, 1)


def ellipse_mask(X, Y, cx, cy, rx, ry, N):
    d = np.sqrt(((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2)
    return np.clip((1 - d) * min(rx, ry) * N + 0.5, 0, 1)


# ---------------------------------------------------------------- 曲线
def spline(pts, n):
    """Catmull-Rom，过所有控制点，返回 n+1 个点。"""
    P = [np.asarray(p, dtype=float) for p in pts]
    P = [2 * P[0] - P[1]] + P + [2 * P[-1] - P[-2]]
    out = []
    segs = len(P) - 3
    for k in range(n + 1):
        u = k / n * segs
        i = min(int(u), segs - 1)
        t = u - i
        p0, p1, p2, p3 = P[i], P[i + 1], P[i + 2], P[i + 3]
        out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (3 * p1 - p0 - 3 * p2 + p3) * t * t * t))
    return out


def norm(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def rot_y(p, a):
    c, s = math.cos(a), math.sin(a)
    return V(p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c)


def rot_x(p, a):
    c, s = math.cos(a), math.sin(a)
    return V(p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c)


def rot_z(p, a):
    c, s = math.cos(a), math.sin(a)
    return V(p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2])


# ---------------------------------------------------------------- 网格
def _val(f, *a):
    return f(*a) if callable(f) else f


class Mesh:
    def __init__(self):
        self.v, self.uv, self.w, self.f = [], [], [], []
        self.key = {}          # 顶点下标 -> 闭眼时的位置

    def add(self, p, uv, w):
        self.v.append(np.asarray(p, dtype=float))
        self.uv.append(uv)
        self.w.append(w)
        return len(self.v) - 1

    def grid(self, rings, uv, w, wrap=True, cap0=False, cap1=False, skip=None):
        base = len(self.v)
        n = len(rings[0])
        for i, r in enumerate(rings):
            for j, p in enumerate(r):
                self.add(p, _val(uv, i, j, p), _val(w, p))
        def at(i, j):
            return base + i * n + (j % n)
        cols = n if wrap else n - 1
        for i in range(len(rings) - 1):
            for j in range(cols):
                if skip and skip(i, j):
                    continue
                self.f.append((at(i, j), at(i, j + 1), at(i + 1, j + 1), at(i + 1, j)))
        def cap(i, flip):
            c = sum(rings[i]) / n
            k = self.add(c, _val(uv, i, 0, c), _val(w, c))
            for j in range(cols):
                self.f.append((k, at(i, j + 1), at(i, j)) if flip else (k, at(i, j), at(i, j + 1)))
        if cap0:
            cap(0, False)
        if cap1:
            cap(len(rings) - 1, True)
        return base

    def ellipsoid(self, c, r, uv, w, seg=10, rings=7, xf=None):
        out = []
        for i in range(rings + 1):
            lat = -math.pi / 2 * 0.94 + math.pi * 0.94 * i / rings
            ring = []
            for j in range(seg):
                lon = 2 * math.pi * j / seg
                p = V(r[0] * math.cos(lat) * math.sin(lon), r[1] * math.sin(lat), r[2] * math.cos(lat) * math.cos(lon))
                if xf:
                    p = xf(p)
                ring.append(p + np.asarray(c, dtype=float))
            out.append(ring)
        self.grid(out, uv, w, cap0=True, cap1=True)

    def lathe(self, prof, uv, w, seg=16, arc=None, center=(0, 0, 0), zs=1.0, deform=None, cap0=False, cap1=False):
        """prof = [(r, y), ...]。arc = (起始角, 结束角)，角度 0 朝 +z、π/2 朝 +x。"""
        a0, a1 = arc if arc else (0, 2 * math.pi)
        n = seg if not arc else seg + 1
        out = []
        for i, (r, y) in enumerate(prof):
            ring = []
            for j in range(n):
                a = a0 + (a1 - a0) * j / seg
                rr = deform(r, i, a) if deform else r
                ring.append(V(center[0] + rr * math.sin(a), y, center[2] + rr * math.cos(a) * zs))
            out.append(ring)
        self.grid(out, uv, w, wrap=not arc, cap0=cap0, cap1=cap1)

    def tube(self, path, width, thick=None, sides=6, uv=None, w=None, radial=None, cap0=True, cap1=True):
        """沿路径的管子。width、thick 可以是 t -> 半径。radial(p) 给定厚度方向，用来让发束贴着头。"""
        n = len(path)
        thick = width if thick is None else thick
        rings = []
        prevN = None
        ts = []
        for i, p in enumerate(path):
            t = i / (n - 1)
            ts.append(t)
            T = norm(path[min(i + 1, n - 1)] - path[max(i - 1, 0)])
            if radial is not None:
                N = np.asarray(radial(p), dtype=float)
            elif prevN is not None:
                N = prevN
            else:
                N = V(1, 0, 0) if abs(T[0]) < 0.9 else V(0, 1, 0)
            N = norm(N - T * np.dot(N, T))
            prevN = N
            B = norm(np.cross(T, N))
            wd, th = _val(width, t), _val(thick, t)
            ring = []
            for k in range(sides):
                a = 2 * math.pi * k / sides
                ring.append(p + B * math.cos(a) * max(wd, 0.0008) + N * math.sin(a) * max(th, 0.0008))
            rings.append(ring)
        self.grid(rings, (lambda i, j, p: uv(ts[i])), (lambda p: w(p)) if callable(w) else w, cap0=cap0, cap1=cap1)

    def sheet(self, outline_a, outline_b, n, uv, w):
        """两条边界线之间铺一张面。"""
        rings = [[mix(a, b, j / n) for j in range(n + 1)] for a, b in zip(outline_a, outline_b)]
        self.grid(rings, uv, w, wrap=False)

    def fan(self, center, rim, uv, w):
        """单面的扇形（翅膀膜之类）。"""
        c = self.add(center, _val(uv, center), _val(w, center))
        ids = [self.add(p, _val(uv, p), _val(w, p)) for p in rim]
        for a, b in zip(ids, ids[1:]):
            self.f.append((c, a, b))

    def quad_decal(self, c, right, up, at, size, atlas, w, normal_lift=0.0, grid=1):
        c = np.asarray(c, dtype=float)
        n = norm(np.cross(right, up))
        rings = []
        for i in range(grid + 1):
            t = i / grid
            rings.append([c + (right * (2 * j / grid - 1)) + (up * (2 * t - 1)) + n * normal_lift for j in range(grid + 1)])
        self.grid(rings, lambda i, j, p: atlas.decal_uv(at, size, j / grid, i / grid), w, wrap=False)
