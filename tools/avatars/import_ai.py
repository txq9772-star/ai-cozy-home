# 把图生 3D 得到的高模 glb 处理成小窝能用的模型：对齐、减面、烘法线、绑骨骼、闭眼、动画。用法：
#   blender -b -P tools/avatars/import_ai.py -- ayu 源文件.glb
# 输出 skin/models/<id>.glb，预览图在 tools/avatars/previews/。
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build  # noqa: E402
import rig  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
HEIGHT = 1.55
TARGET_TRIS = 13800
TEX = 1024

# 关键位置。ayu 是缩放对齐后量的数值（three.js 坐标）；其余的写检查图上的像素（640x760 正面正交渲染），
# 由 resolve() 换算。fixed 里的手臂本来就是弯着的（抱书、抬手）或和宽袖连在一起，绑在胸口上不动。
HEAD_TOP = 1.37      # 头顶（不含角、呆毛、头饰）的高度，四个人统一
SPECS = {
    'ayu': dict(
        chin=0.73, waist=0.50, hip=0.30, hem=0.20,
        arms={'L': ((0.17, 0.665, 0.0), (0.26, 0.42, 0.0)), 'R': ((-0.17, 0.665, 0.0), (-0.26, 0.42, 0.0))},
        leg_x=0.08, skirt_hem=0.38,
        eyes=[(-0.137, 0.853, 0.083, 0.06), (0.137, 0.853, 0.083, 0.06)]),
    'ac': dict(px=dict(top=55, chin=318, waist=455, hip=580, hem=655, leg=37,
                       L=((395, 370), (455, 515)), R=((240, 370), (230, 460)),
                       eyes=[(262, 268, 38, 26), (375, 268, 38, 26)]),
               fixed=('R',), chest_box=(-0.42, -0.02), skirt_hem=0.42),
    'ag': dict(px=dict(top=85, chin=325, waist=470, hip=590, hem=715, leg=30, feet_side=390,
                       L=((375, 375), (440, 470)), R=((262, 375), (185, 470)),
                       eyes=[(278, 277, 36, 28), (355, 272, 36, 28)]),
               fixed=('L', 'R'), wing_dx=165, wing_py=495, skirt_hem=0.42),
    'ak': dict(px=dict(top=70, chin=322, waist=440, hip=570, hem=665, leg=38,
                       L=((400, 385), (465, 490)), R=((265, 375), (235, 300)),
                       eyes=[(283, 255, 36, 30), (375, 250, 36, 30)]),
               fixed=('R',), skirt_hem=0.42),
}


def resolve(sp, lo3, hi3):
    """把像素量的位置换算成对齐后的坐标，返回 (scale, 脚的 x, 脚的 y)，sp 就地补全。"""
    pxs = sp['px']
    size = hi3 - lo3
    u = float(size.max()) * 1.1 / 760
    c = (lo3 + hi3) / 2
    raw_z = lambda py: c[2] + (380 - py) * u
    scale = HEAD_TOP / (raw_z(pxs['top']) - lo3[2])
    fx = float(c[0])
    fy = None
    if 'feet_side' in pxs:
        fy = float(c[1]) - (pxs['feet_side'] - 320) * u
    ht = lambda py: (raw_z(py) - lo3[2]) * scale
    sx = lambda px: (c[0] + (px - 320) * u - fx) * scale
    for k in ('chin', 'waist', 'hip', 'hem'):
        sp[k] = float(ht(pxs[k]))
    sp['leg_x'] = float(pxs['leg'] * u * scale)
    sp['arms'] = {n: tuple((float(sx(a)), float(ht(b)), 0.0) for a, b in pxs[n]) for n in ('L', 'R')}
    sp['eyes'] = [(float(sx(a)), float(ht(b)), float(w * u * scale), float(h * u * scale)) for a, b, w, h in pxs['eyes']]
    if 'wing_dx' in sp:
        sp['wing_x'] = float(sp['wing_dx'] * u * scale)
        sp['wing_y'] = float(ht(sp['wing_py']))
    return scale, fx, fy


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- 导入和对齐
def load_high(path, sp):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    ob = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
    ob.data.transform(ob.matrix_world)
    ob.parent = None
    ob.matrix_world.identity()
    co = np.zeros(len(ob.data.vertices) * 3)
    ob.data.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    z0, z1 = co[:, 2].min(), co[:, 2].max()
    scale = HEIGHT / (z1 - z0)
    feet = co[co[:, 2] < z0 + (z1 - z0) * 0.06]
    cx, cy = (feet[:, 0].min() + feet[:, 0].max()) / 2, (feet[:, 1].min() + feet[:, 1].max()) / 2
    if 'px' in sp:
        scale, cx, fy = resolve(sp, co.min(axis=0), co.max(axis=0))
        cy = cy if fy is None else fy
    co = (co - np.array((cx, cy, z0))) * scale
    ob.data.vertices.foreach_set('co', co.ravel())
    ob.data.update()
    print(f'INFO scale={scale:.3f} feet_center=({cx:.3f},{cy:.3f}) top={(z1 - z0) * scale:.3f} chin={sp["chin"]:.3f} waist={sp["waist"]:.3f} hem={sp["hem"]:.3f}')
    return ob


def decimate(hi):
    me = hi.data.copy()
    lo = bpy.data.objects.new('lo', me)
    bpy.context.scene.collection.objects.link(lo)
    # glTF 在贴图接缝处把顶点拆开了，先缝上，减面时才不会裂开
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.to_mesh(me)
    bm.free()
    mod = lo.modifiers.new('d', 'DECIMATE')
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    mod.ratio = TARGET_TRIS / tris
    dg = bpy.context.evaluated_depsgraph_get()
    new = bpy.data.meshes.new_from_object(lo.evaluated_get(dg))
    lo.modifiers.clear()
    lo.data = new
    new.shade_smooth()
    return lo


def base_image(ob):
    mat = ob.data.materials[0]
    p = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    n = p.inputs['Base Color'].links[0].from_node
    while n.type != 'TEX_IMAGE':
        n = n.inputs[0].links[0].from_node
    return n.image


def bake_normal(hi, lo, name, tex_dir):
    img = bpy.data.images.new(name + '_n', TEX, TEX, alpha=False, float_buffer=False)
    img.colorspace_settings.name = 'Non-Color'
    mat = bpy.data.materials.new('bake')
    mat.use_nodes = True
    t = mat.node_tree.nodes.new('ShaderNodeTexImage')
    t.image = img
    mat.node_tree.nodes.active = t
    lo.data.materials.clear()
    lo.data.materials.append(mat)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 1
    for o in scene.objects:
        o.select_set(False)
    hi.select_set(True)
    lo.select_set(True)
    bpy.context.view_layer.objects.active = lo
    bpy.ops.object.bake(type='NORMAL', use_selected_to_active=True, cage_extrusion=0.02, max_ray_distance=0.06,
                        normal_space='TANGENT', margin=6)
    os.makedirs(tex_dir, exist_ok=True)
    img.filepath_raw = os.path.join(tex_dir, name + '_n.png')
    img.file_format = 'PNG'
    img.save()
    return img


def final_material(lo, base, normal, name):
    mat = bpy.data.materials.new(name + '_mat')
    mat.use_nodes = True
    mat.use_backface_culling = False
    nt = mat.node_tree
    p = nt.nodes['Principled BSDF']
    t = nt.nodes.new('ShaderNodeTexImage')
    t.image = base
    nt.links.new(t.outputs['Color'], p.inputs['Base Color'])
    nt.links.new(t.outputs['Color'], p.inputs['Emission Color'])
    p.inputs['Emission Strength'].default_value = 0.2
    p.inputs['Roughness'].default_value = 0.6
    p.inputs['Metallic'].default_value = 0.0
    n = nt.nodes.new('ShaderNodeTexImage')
    n.image = normal
    nm = nt.nodes.new('ShaderNodeNormalMap')
    nt.links.new(n.outputs['Color'], nm.inputs['Color'])
    nt.links.new(nm.outputs['Normal'], p.inputs['Normal'])
    lo.data.materials.clear()
    lo.data.materials.append(mat)


# ---------------------------------------------------------------- 闭眼：藏在脸里的眼皮，闭眼时推到脸外面
class Face:
    def __init__(self, lo, img, chin):
        self.me = lo.data
        self.bvh = BVHTree.FromPolygons([v.co.copy() for v in self.me.vertices], [tuple(p.vertices) for p in self.me.polygons])
        self.uvl = self.me.uv_layers.active.data
        self.w, self.h = img.size
        # 下巴上方没有刘海，第一层就是脸，往前留一点余量作为刘海和脸的分界
        self.front = self.first(0.0, chin + 0.06, -9.0)[0].y - 0.06
        px = np.zeros(self.w * self.h * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        self.px = px.reshape(self.h, self.w, 4)

    def hit(self, x, y):
        """跳过脸前面的刘海，取脸平面之后的第一层表面。"""
        return self.first(x, y, self.front)

    def first(self, x, y, limit):
        pos = Vector((x, -2.0, y))
        d = Vector((0, 1, 0))
        for _ in range(12):
            loc, _n, idx, _d = self.bvh.ray_cast(pos, d, 4.0)
            if loc is None:
                return None, None
            if loc.y >= limit:
                return loc, idx
            pos = loc + d * 1e-4
        return None, None

    def uv_at(self, loc, idx):
        p = self.me.polygons[idx]
        best = min(p.loop_indices, key=lambda li: (self.me.vertices[self.me.loops[li].vertex_index].co - loc).length)
        return tuple(self.uvl[best].uv)

    def lum(self, uv):
        c = self.px[int(uv[1] * (self.h - 1)), int(uv[0] * (self.w - 1))]
        return float(0.3 * c[0] + 0.6 * c[1] + 0.1 * c[2])


def add_eyelids(lo, img, sp):
    face = Face(lo, img, sp['chin'])
    bm = bmesh.new()
    bm.from_mesh(lo.data)
    uvl = bm.loops.layers.uv.active
    bm.verts.ensure_lookup_table()
    first = len(bm.verts)
    closed = {}
    for cx, ey, ew, eh in sp['eyes']:
        # 肤色取眼睛下方，线条色取眼睛范围里最暗的一点
        cheeks = []
        for u in np.linspace(-0.7, 0.7, 7):
            for v in np.linspace(1.3, 2.1, 5):
                loc, idx = face.hit(cx + u * ew, ey - v * eh)
                if loc:
                    cheeks.append(face.uv_at(loc, idx))
        cheeks.sort(key=face.lum)
        skin_uv = cheeks[len(cheeks) * 3 // 4]      # 偏亮一侧的中间值，避开发丝和饰物
        samples = []
        for u in np.linspace(-0.8, 0.8, 9):
            for v in np.linspace(0.2, 1.0, 5):
                loc, idx = face.hit(cx + u * ew, ey + v * eh)
                if loc:
                    samples.append(face.uv_at(loc, idx))
        lash_uv = min(samples, key=face.lum)

        # 脸可能被发丝、手挡着，逐点探测不稳定，用二次曲面拟合脸在这只眼附近的深度
        pts = []
        for u in np.linspace(-1.3, 1.3, 15):
            for v in np.linspace(-1.5, 1.5, 11):
                loc, _ = face.hit(cx + u * ew, ey + v * eh)
                if loc:
                    pts.append((loc.x - cx, loc.z - ey, loc.y))
        pts = np.array(pts)

        def basis(a, b):
            return np.stack((np.ones_like(a), a, b, a * a, a * b, b * b), axis=-1)
        keep = np.abs(pts[:, 2] - np.median(pts[:, 2])) < 0.04
        for _ in range(4):
            coef = np.linalg.lstsq(basis(pts[keep, 0], pts[keep, 1]), pts[keep, 2], rcond=None)[0]
            res = np.abs(basis(pts[:, 0], pts[:, 1]) @ coef - pts[:, 2])
            keep = res < max(0.008, float(np.median(res)) * 2.5)

        def place(x, y, lift):
            depth = float(basis(np.array(x - cx), np.array(y - ey)) @ coef)
            return Vector((x, depth - lift, y))

        def strip(rows, uv):
            ids = []
            for row in rows:
                line = []
                for x, y, lift in row:
                    v = bm.verts.new(place(x, y, -0.05))
                    closed[v] = place(x, y, lift)
                    line.append(v)
                ids.append(line)
            for a, b in zip(ids, ids[1:]):
                for j in range(len(a) - 1):
                    f = bm.faces.new((a[j], b[j], b[j + 1], a[j + 1]))
                    f.smooth = True
                    # 贴图坐标留一点差：坐标完全相同时法线贴图算不出方向，会出现杂点
                    for lp, (du, dv) in zip(f.loops, ((0, 0), (0, 1), (1, 1), (1, 0))):
                        lp[uvl].uv = (uv[0] + (j + du) * 3e-4, uv[1] + dv * 1.5e-3)

        cols, rows_n = 11, 7
        rows = []
        for i in range(rows_n):
            v = 1 - 2 * i / (rows_n - 1)
            row = []
            for j in range(cols):
                u = -1.1 + 2.2 * j / (cols - 1)
                span = math.sqrt(max(0.02, 1 - (u / 1.2) ** 2))
                row.append((cx + u * ew, ey + v * eh * 1.2 * span, 0.01))
            rows.append(row)
        strip(rows, skin_uv)
        line_rows = []
        for sign in (1, -1):
            row = []
            for j in range(cols):
                u = -0.88 + 1.76 * j / (cols - 1)
                y = ey - eh * (0.45 - 0.38 * u * u) + sign * 0.0048 * (1 - 0.7 * u * u)
                row.append((cx + u * ew, y, 0.015))
            line_rows.append(row)
        strip(line_rows, lash_uv)
    bm.verts.index_update()
    closed_by_index = {v.index: co for v, co in closed.items()}
    bm.to_mesh(lo.data)
    bm.free()
    return first, closed_by_index


# ---------------------------------------------------------------- 骨骼
def bones_for(sp):
    b = [('root', None, (0, 0, 0), (0, 0.12, 0)),
         ('hips', 'root', (0, sp['hip'], 0), (0, sp['waist'] - 0.04, 0)),
         ('spine', 'hips', (0, sp['waist'] - 0.04, 0), (0, sp['waist'] + 0.07, 0)),
         ('chest', 'spine', (0, sp['waist'] + 0.07, 0), (0, sp['chin'] - 0.03, 0)),
         ('head', 'chest', (0, sp['chin'] - 0.03, 0), (0, 1.3, 0))]
    knee = sp['hem'] * 0.85
    for n, s in (('L', 1), ('R', -1)):
        sh, wr = (np.array(v) for v in sp['arms'][n])
        el = (sh + wr) / 2
        b.append((f'arm_{n}', 'chest', tuple(sh), tuple(el)))
        b.append((f'fore_{n}', f'arm_{n}', tuple(el), tuple(wr)))
        x = s * sp['leg_x']
        b.append((f'thigh_{n}', 'hips', (x, sp['hip'], 0), (x, knee, 0)))
        b.append((f'shin_{n}', f'thigh_{n}', (x, knee, 0), (x, 0.03, 0)))
    y = sp['waist']
    for n, d in (('F', (0, -0.3, 0.2)), ('B', (0, -0.3, -0.2)), ('L', (0.2, -0.3, 0)), ('R', (-0.2, -0.3, 0))):
        b.append((f'skirt_{n}', 'hips', (0, y, 0), (d[0], y + d[1], d[2])))
    for n, x, z in (('C', 0.0, -0.30), ('L', 0.30, -0.12), ('R', -0.30, -0.12)):
        c = sp['chin']
        b.append((f'hair_{n}1', 'head', (x, c + 0.02, z), (x * 1.1, c - 0.18, z * 1.1)))
        b.append((f'hair_{n}2', f'hair_{n}1', (x * 1.1, c - 0.18, z * 1.1), (x * 1.2, c - 0.43, z * 1.2)))
    return b


def compute_weights(lo, sp, bones, first_lid):
    me = lo.data
    n = len(me.vertices)
    co = np.zeros(n * 3)
    me.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    X, Y, Z = co[:, 0], co[:, 2], -co[:, 1]
    names = [b[0] for b in bones]
    idx = {b: i for i, b in enumerate(names)}
    W = np.zeros((n, len(names)))
    rem = np.ones(n)

    def take(part, targets):
        """part：这部分占多少（0-1）；targets：{骨骼: 权重数组}，和为 1。"""
        nonlocal rem
        amt = rem * part
        for b, v in targets.items():
            W[:, idx[b]] += amt * v
        rem = rem - amt

    chin, waist, hem, hip = sp['chin'], sp['waist'], sp['hem'], sp['hip']
    take(smooth(chin - 0.03, chin + 0.03, Y), {'head': np.ones(n)})

    fixed = sp.get('fixed', ())
    for name in ('L', 'R'):
        a, b = (np.array(v) for v in sp['arms'][name])
        ab = b - a
        P = np.stack((X, Y, Z), axis=1)
        t = np.clip(((P - a) @ ab) / (ab @ ab), -0.1, 1.25)
        d = np.linalg.norm(P - (a + t[:, None] * ab), axis=1)
        inside = 1 - smooth(0.085, 0.115, d)
        u = smooth(0.42, 0.58, t)
        if name in fixed:
            take(inside, {'chest': np.ones(n)})
        else:
            take(inside, {f'arm_{name}': 1 - u, f'fore_{name}': u})

    if 'chest_box' in sp:          # 抱在胸前的书和手
        x0, x1 = sp['chest_box']
        box = smooth(x0 - 0.02, x0, X) * (1 - smooth(x1, x1 + 0.02, X)) * smooth(waist - 0.03, waist, Y) * smooth(0.04, 0.08, Z)
        take(box, {'chest': np.ones(n)})

    if 'wing_x' in sp:             # 翅膀不单独动，跟着胸口
        wing = smooth(sp['wing_x'] - 0.02, sp['wing_x'] + 0.02, np.abs(X)) * smooth(sp['wing_y'] - 0.02, sp['wing_y'] + 0.02, Y)
        take(wing, {'chest': np.ones(n)})

    side = smooth(-0.02, 0.02, X)
    legs = (1 - smooth(hem - 0.03, hem + 0.02, Y)) * (1 - smooth(0.17, 0.21, np.abs(X))) * smooth(-0.17, -0.12, Z)
    knee = hem * 0.85
    leg_u = smooth(knee - 0.03, knee + 0.03, Y)
    take(legs * side, {'thigh_L': leg_u, 'shin_L': 1 - leg_u})
    take(legs * (1 - side) / np.clip(1 - legs * side, 1e-3, 1), {'thigh_R': leg_u, 'shin_R': 1 - leg_u})

    drop = np.clip((waist - Y) / (waist - hem), 0, 1.1)
    Rx = 0.17 + (sp['skirt_hem'] - 0.17) * drop ** 0.7
    Rz = np.where(Z > 0, Rx * 0.95, Rx * 0.72)
    r = np.sqrt((X / Rx) ** 2 + (Z / Rz) ** 2)
    skirt = (1 - smooth(1.0, 1.15, r)) * smooth(hem - 0.06, hem - 0.02, Y) * (1 - smooth(waist, waist + 0.02, Y))
    ang = np.arctan2(X, Z)
    ca, sa = np.cos(ang), np.sin(ang)
    take(skirt, {'skirt_F': np.where(ca > 0, ca * ca, 0), 'skirt_B': np.where(ca <= 0, ca * ca, 0),
                 'skirt_L': np.where(sa > 0, sa * sa, 0), 'skirt_R': np.where(sa <= 0, sa * sa, 0)})

    r = np.sqrt((X / 0.2) ** 2 + (Z / 0.17) ** 2)
    torso = (1 - smooth(1.0, 1.2, r)) * smooth(waist - 0.06, waist - 0.02, Y)
    u = smooth(waist + 0.04, waist + 0.1, Y)
    take(torso, {'chest': u, 'spine': 1 - u})

    # 剩下的都是头发
    l = smooth(0.06, 0.2, X)
    rr = smooth(0.06, 0.2, -X)
    c = 1 - l - rr
    top = smooth(chin - 0.01, chin + 0.07, Y)
    low = 1 - smooth(chin - 0.39, chin - 0.21, Y)
    mid = 1 - top
    W[:, idx['head']] += rem * top
    for k, f in (('C', c), ('L', l), ('R', rr)):
        W[:, idx[f'hair_{k}1']] += rem * mid * (1 - low) * f
        W[:, idx[f'hair_{k}2']] += rem * mid * low * f

    # 沿边平滑，一整块模型不这样关节处会撕裂
    e = np.zeros(len(me.edges) * 2, dtype=np.int32)
    me.edges.foreach_get('vertices', e)
    e = e.reshape(-1, 2)
    for _ in range(6):
        total = np.zeros_like(W)
        cnt = np.zeros(n)
        np.add.at(total, e[:, 0], W[e[:, 1]])
        np.add.at(total, e[:, 1], W[e[:, 0]])
        np.add.at(cnt, e[:, 0], 1)
        np.add.at(cnt, e[:, 1], 1)
        mask = cnt > 0
        W[mask] = 0.5 * W[mask] + 0.5 * total[mask] / cnt[mask, None]
    W[first_lid:] = 0
    W[first_lid:, idx['head']] = 1

    W[W < 0.02] = 0
    W /= np.clip(W.sum(axis=1, keepdims=True), 1e-6, None)
    groups = [lo.vertex_groups.new(name=b) for b in names]
    for j, g in enumerate(groups):
        for i in np.nonzero(W[:, j])[0]:
            g.add([int(i)], float(W[i, j]), 'REPLACE')


def make_armature(bones, name):
    data = bpy.data.armatures.new(name + '_rig')
    arm = bpy.data.objects.new(name + '_rig', data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb = {}
    for n, parent, head, tail in bones:
        e = data.edit_bones.new(n)
        e.head, e.tail, e.roll = rig.to_b(head), rig.to_b(tail), 0
        eb[n] = e
    for n, parent, head, tail in bones:
        if parent:
            eb[n].parent = eb[parent]
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def main():
    argv = sys.argv[sys.argv.index('--') + 1:]
    cid, src = argv[0], argv[1]
    render = '--no-render' not in argv
    sp = SPECS[cid]
    tex_dir = os.path.join(os.environ.get('TEMP', '/tmp'), 'avatar_tex')
    hi = load_high(src, sp)
    lo = decimate(hi)
    normal = bake_normal(hi, lo, cid, tex_dir)
    base = base_image(hi)
    first, closed = add_eyelids(lo, base, sp)
    bpy.data.objects.remove(hi)
    base.scale(TEX, TEX)
    final_material(lo, base, normal, cid)
    lo.name = cid
    lo.data.name = cid
    bones = bones_for(sp)
    compute_weights(lo, sp, bones, first)
    lo.shape_key_add(name='Basis', from_mix=False)
    k = lo.shape_key_add(name='eyes_closed', from_mix=False)
    for i, co in closed.items():
        k.data[i].co = co
    k.value = 0
    arm = make_armature(bones, cid)
    lo.parent = arm
    lo.modifiers.new('Armature', 'ARMATURE').object = arm
    fn = build.posefn(cid)
    rig.make_actions(arm, build.CLIPS, fn)
    out = os.path.join(ROOT, 'skin', 'models', cid + '.glb')
    rig.export_glb(out, image_format='JPEG')
    lo.data.calc_loop_triangles()
    print(f'[{cid}] tris={len(lo.data.loop_triangles)} verts={len(lo.data.vertices)} size={os.path.getsize(out) / 1024:.0f}KB')
    if render:
        rig.render_views(arm, lo, cid, os.path.join(HERE, 'previews'), fn)


if __name__ == '__main__':
    main()
