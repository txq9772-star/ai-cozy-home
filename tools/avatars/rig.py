# Blender 端：把 kit.Mesh 变成带骨骼、动画、形态键的对象，导出 glb，渲染预览。
import math
import os

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Quaternion, Vector

FPS = 24


def to_b(p):
    """three.js 坐标 -> Blender 坐标（面朝 +z 变成面朝 -y）。"""
    return (float(p[0]), float(-p[2]), float(p[1]))


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


# ---------------------------------------------------------------- 骨架定义
def bone_list(extra):
    S = {'L': 1, 'R': -1}
    b = [('root', None, (0, 0, 0), (0, 0.12, 0)),
         ('hips', 'root', (0, 0.30, 0), (0, 0.50, 0)),
         ('spine', 'hips', (0, 0.50, 0), (0, 0.70, 0)),
         ('chest', 'spine', (0, 0.70, 0), (0, 0.90, 0)),
         ('head', 'chest', (0, 0.90, 0), (0, 1.25, 0))]
    a = 0.18
    for n, s in S.items():
        sh = np.array((s * 0.17, 0.84, 0.0))
        d = np.array((s * math.sin(a), -math.cos(a), 0.0))
        el = sh + d * 0.15
        wr = sh + d * 0.30
        b.append((f'arm_{n}', 'chest', tuple(sh), tuple(el)))
        b.append((f'fore_{n}', f'arm_{n}', tuple(el), tuple(wr)))
        b.append((f'thigh_{n}', 'hips', (s * 0.08, 0.28, 0), (s * 0.08, 0.16, 0)))
        b.append((f'shin_{n}', f'thigh_{n}', (s * 0.08, 0.16, 0), (s * 0.08, 0.03, 0)))
    for n, d in (('F', (0, -0.3, 0.2)), ('B', (0, -0.3, -0.2)), ('L', (0.2, -0.3, 0)), ('R', (-0.2, -0.3, 0))):
        b.append((f'skirt_{n}', 'hips', (0, 0.62, 0), (d[0], 0.62 + d[1], d[2])))
    for n, x, z in (('C', 0.0, -0.30), ('L', 0.30, -0.12), ('R', -0.30, -0.12)):
        b.append((f'hair_{n}1', 'head', (x, 0.95, z), (x * 1.1, 0.70, z * 1.1)))
        b.append((f'hair_{n}2', f'hair_{n}1', (x * 1.1, 0.70, z * 1.1), (x * 1.2, 0.40, z * 1.2)))
    return b + list(extra)


def build_object(name, m, atlas, extra_bones, tex_dir):
    arm_data = bpy.data.armatures.new(name + '_rig')
    arm = bpy.data.objects.new(name + '_rig', arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bones = bone_list(extra_bones)
    eb = {}
    for n, parent, head, tail in bones:
        e = arm_data.edit_bones.new(n)
        e.head = to_b(head)
        e.tail = to_b(tail)
        e.roll = 0
        e.use_deform = True
        eb[n] = e
    for n, parent, head, tail in bones:
        if parent:
            eb[n].parent = eb[parent]
    bpy.ops.object.mode_set(mode='OBJECT')

    me = bpy.data.meshes.new(name)
    me.from_pydata([to_b(p) for p in m.v], [], m.f)
    me.update()
    uvl = me.uv_layers.new(name='UV')
    for lp in me.loops:
        uvl.data[lp.index].uv = m.uv[lp.vertex_index]
    # 统一法线朝向（recalc 不动顶点顺序）
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.shade_smooth()

    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    groups = {n: ob.vertex_groups.new(name=n) for n, *_ in bones}
    for i, w in enumerate(m.w):
        total = sum(w.values())
        for bn, val in w.items():
            if val > 1e-4:
                groups[bn].add([i], val / total, 'REPLACE')

    ob.shape_key_add(name='Basis', from_mix=False)
    k = ob.shape_key_add(name='eyes_closed', from_mix=False)
    for i, p in m.key.items():
        k.data[i].co = to_b(p)
    k.value = 0

    # 贴图和材质
    S = atlas.S
    img = bpy.data.images.new(name + '_atlas', S, S, alpha=False)
    rgba = np.ones((S, S, 4))
    rgba[..., :3] = np.flipud(np.clip(atlas.px, 0, 1))
    img.pixels.foreach_set(rgba.ravel().astype(np.float32))
    os.makedirs(tex_dir, exist_ok=True)
    path = os.path.join(tex_dir, name + '_atlas.png')
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()

    mat = bpy.data.materials.new(name + '_mat')
    mat.use_nodes = True
    mat.use_backface_culling = False
    nt = mat.node_tree
    p = nt.nodes['Principled BSDF']
    t = nt.nodes.new('ShaderNodeTexImage')
    t.image = img
    nt.links.new(t.outputs['Color'], p.inputs['Base Color'])
    nt.links.new(t.outputs['Color'], p.inputs['Emission Color'])
    p.inputs['Emission Strength'].default_value = 0.2
    p.inputs['Roughness'].default_value = 0.75
    p.inputs['Metallic'].default_value = 0.0
    me.materials.append(mat)

    ob.parent = arm
    mod = ob.modifiers.new('Armature', 'ARMATURE')
    mod.object = arm
    return arm, ob


# ---------------------------------------------------------------- 动画
def q_three(rx=0.0, ry=0.0, rz=0.0):
    """按 three.js 轴写的欧拉角 -> Blender 轴的四元数。"""
    q = Euler((rx, ry, rz), 'XYZ').to_quaternion()
    return Quaternion((q.w, q.x, -q.z, q.y))


def apply_pose(arm, pose):
    for pb in arm.pose.bones:
        R = pb.bone.matrix_local.to_quaternion()
        rot = pose.get(pb.name)
        q = q_three(*rot) if rot else Quaternion()
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = R.inverted() @ q @ R
        pb.location = (0, 0, 0)
    root = arm.pose.bones['root']
    loc, rot = pose.get('#root', ((0, 0, 0), None))
    R = root.bone.matrix_local.to_quaternion()
    root.location = R.inverted() @ Vector(to_b(loc))


def make_actions(arm, clips, pose_fn):
    """clips = {名字: 帧数}。pose_fn(名字, t∈[0,1)) -> {骨骼: (rx,ry,rz), '#root': ((x,y,z), None)}。"""
    arm.animation_data_create()
    made = []
    for name, frames in clips.items():
        act = bpy.data.actions.new(name)
        act.use_fake_user = True
        arm.animation_data.action = act
        step = 2
        for f in list(range(0, frames, step)) + [frames]:
            apply_pose(arm, pose_fn(name, (f % frames) / frames))
            for pb in arm.pose.bones:
                pb.keyframe_insert('rotation_quaternion', frame=f)
                if pb.name == 'root':
                    pb.keyframe_insert('location', frame=f)
        made.append(act)
    arm.animation_data.action = None
    return made


def export_glb(path, image_format='AUTO'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=path, export_format='GLB', export_yup=True, use_selection=False,
        export_animations=True, export_animation_mode='ACTIONS', export_skins=True,
        export_morph=True, export_morph_normal=False, export_force_sampling=True,
        export_bake_animation=False, export_frame_range=False,
        export_image_format=image_format, export_jpeg_quality=86, export_materials='EXPORT', export_tangents=False,
        export_all_influences=False, export_lights=False, export_cameras=False)


# ---------------------------------------------------------------- 预览
def render_views(arm, ob, name, out_dir, pose_fn, res=(560, 720), samples=40):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'

    world = bpy.data.worlds.new('w')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0.86, 0.87, 0.92, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = 0.62
    scene.world = world

    sun = bpy.data.lights.new('sun', 'SUN')
    sun.energy = 1.3
    sun_ob = bpy.data.objects.new('sun', sun)
    scene.collection.objects.link(sun_ob)
    sun_ob.rotation_euler = (math.radians(55), 0, math.radians(-25))

    cam = bpy.data.cameras.new('c')
    cam.lens = 85
    cam_ob = bpy.data.objects.new('c', cam)
    scene.collection.objects.link(cam_ob)
    scene.camera = cam_ob

    apply_pose(arm, pose_fn('idle', 0.0))
    bpy.context.view_layer.update()

    D = 6.2
    tgt = Vector((0, 0, 0.82))
    os.makedirs(out_dir, exist_ok=True)
    for view, pos in (('front', (0, -D, 0.82)), ('side', (-D, 0, 0.82)), ('back', (0, D, 0.82))):
        cam_ob.location = pos
        cam_ob.rotation_euler = (tgt - Vector(pos)).to_track_quat('-Z', 'Y').to_euler()
        sun_ob.rotation_euler = (math.radians(55), 0, {'front': math.radians(-25), 'side': math.radians(-100), 'back': math.radians(155)}[view])
        scene.render.filepath = os.path.join(out_dir, f'{name}-{view}.png')
        bpy.ops.render.render(write_still=True)
