# 把图生 3D 的源 glb 渲成检查图（正面 640x760 正交，和 import_ai.resolve 的像素换算一致；另有侧面图），画 50px 网格，用来量 SPECS 里的像素。
# 用法：blender -b -P tools/avatars/check_render.py -- 输出目录 id=源文件.glb [id2=...]
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
out_dir = argv[0]
W, H = 640, 760


def grid(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.zeros(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    # 图像坐标 y 向下；blender 像素第 0 行在底部
    for x in range(0, w, 50):
        c = (1, 0.2, 0.2, 1) if x % 100 == 0 else (0.3, 0.3, 1, 1)
        px[:, x, :] = np.where(px[:, x, 3:4] > 0, 0.5 * px[:, x, :] + 0.5 * np.array(c), np.array(c) * [1, 1, 1, 0.35])
    for y in range(0, h, 50):
        r = h - 1 - y
        c = (1, 0.2, 0.2, 1) if y % 100 == 0 else (0.3, 0.3, 1, 1)
        px[r, :, :] = np.where(px[r, :, 3:4] > 0, 0.5 * px[r, :, :] + 0.5 * np.array(c), np.array(c) * [1, 1, 1, 0.35])
    # 背景填白，看得清
    a = px[:, :, 3:4]
    px[:, :, :3] = px[:, :, :3] * a + (1 - a)
    px[:, :, 3] = 1
    img.pixels.foreach_set(px.ravel())
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()


def render(cid, src):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    for ob in meshes:
        ob.data.transform(ob.matrix_world)
        ob.parent = None
        ob.matrix_world.identity()
    ob = meshes[0]
    co = np.zeros(len(ob.data.vertices) * 3)
    ob.data.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    lo3, hi3 = co.min(axis=0), co.max(axis=0)
    size = hi3 - lo3
    c = (lo3 + hi3) / 2
    u = float(size.max()) * 1.1 / 760
    imgs = []
    for m in ob.data.materials:
        if m and m.use_nodes:
            imgs += [n.image.name + str(tuple(n.image.size)) for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image]
    print(f'[{cid}] meshes={len(meshes)} verts={len(ob.data.vertices)} polys={len(ob.data.polygons)} size={np.round(size, 3).tolist()} '
          f'center={np.round(c, 3).tolist()} min={np.round(lo3, 3).tolist()} u={u:.5f} mats={[m.name for m in ob.data.materials]} imgs={imgs}')
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'FLAT'
    scene.display.shading.color_type = 'TEXTURE'
    scene.render.film_transparent = True
    scene.render.resolution_x, scene.render.resolution_y = W, H
    scene.render.resolution_percentage = 100
    cam_data = bpy.data.cameras.new('cam')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = float(size.max()) * 1.1
    cam_data.clip_end = 100
    cam = bpy.data.objects.new('cam', cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    views = {'front': (Vector((c[0], c[1] - 10, c[2])), Vector((0, 1, 0))),
             'side': (Vector((c[0] - 10, c[1], c[2])), Vector((1, 0, 0)))}
    for name, (pos, fwd) in views.items():
        cam.location = pos
        cam.rotation_euler = fwd.to_track_quat('-Z', 'Y').to_euler()
        path = os.path.join(out_dir, f'{cid}-{name}.png')
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        grid(path)


for a in argv[1:]:
    cid, src = a.split('=', 1)
    render(cid, src)
print('DONE')
