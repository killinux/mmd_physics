"""对比视频的一格:PMX + VMD,按配置串用「效果选择」算好,渲成 mp4(或几帧 PNG)。demo_videos.py 一格调一次。

blender -b --factory-startup --python render_tile.py -- --pmx P --out O.mp4 [--vmd V] [--wav W] [--frames N]
        [--view chest[:yaw] | full[:yaw]] [--config "BUST=SPRING:k1,HAIR=CLOTH:hair"] [--still F ...] [--size S]
外观同 ripper_tpose 的 render_pmx_dance.py:灰色背景、两盏平行光、地面、Eevee 16 采样。
"""
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender  # noqa: E402
from _blender import bpy, config  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--pmx", required=True)
ap.add_argument("--vmd", default=config.VMD)
ap.add_argument("--out", required=True)
ap.add_argument("--wav", default="")
ap.add_argument("--frames", type=int, default=0, help="舞蹈帧数(不含开头过渡),0 = 整段")
ap.add_argument("--view", default="chest", help="chest = 胸部特写(跟着上半身),full = 全身;冒号后是绕 Z 转的角度")
ap.add_argument("--config", default="", help="各类的方式和预设,见 _blender.configure")
ap.add_argument("--still", type=int, nargs="*", default=[], help="只渲这些帧(PNG)")
ap.add_argument("--size", type=int, default=0, help="宽度(胸部特写是正方形,全身 2:3)")
a = ap.parse_args(_blender.argv())
t0 = time.time()

_blender.fresh()
from mmd_physics import effects  # noqa: E402

scene, root, arm = _blender.load(a.pmx, a.vmd, a.frames, morphs=True)
from mmd_tools.core.model import Model  # noqa: E402
rig = Model(root)
rig.morph_slider.create()
rig.morph_slider.bind()
bpy.context.view_layer.objects.active = root

bpy.ops.mmd_physics.fx_detect()
fx = root.mmd_physics_fx
_blender.configure(fx, a.config)
bpy.ops.mmd_physics.fx_apply()
print("FX", fx.status)
t_apply = time.time() - t0
effects.bake_cache(scene)
print("BAKED cache %d-%d (%.0f s so far)" % (scene.frame_start, scene.frame_end, time.time() - t0))

# -- 外观 ------------------------------------------------------------------------------------------------------
scene.render.engine = "BLENDER_EEVEE"
scene.view_settings.view_transform = "Standard"
world = bpy.data.worlds.new("fx_world")
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs[0].default_value = (0.34, 0.34, 0.37, 1.0)
bg.inputs[1].default_value = 1.35
scene.world = world
for name, energy, rotation in (("key", 3.2, (0.95, 0.0, 0.65)), ("fill", 1.1, (1.15, 0.0, -2.2))):
    data = bpy.data.lights.new(name, type="SUN")
    data.energy = energy
    lamp = bpy.data.objects.new(name, data)
    scene.collection.objects.link(lamp)
    lamp.rotation_euler = rotation
floor_mesh = bpy.data.meshes.new("floor")
floor_mesh.from_pydata([(-4, -4, 0), (4, -4, 0), (4, 4, 0), (-4, 4, 0)], [], [(0, 1, 2, 3)])
floor = bpy.data.objects.new("floor", floor_mesh)
scene.collection.objects.link(floor)
mat = bpy.data.materials.new("floor")
mat.diffuse_color = (0.28, 0.28, 0.30, 1.0)
floor_mesh.materials.append(mat)


def bone(name_j):
    for pb in arm.pose.bones:
        if pb.name == name_j or (getattr(pb, "mmd_bone", None) and pb.mmd_bone.name_j == name_j):
            return pb
    return None


view, _, yaw_s = a.view.partition(":")
yaw = math.radians(float(yaw_s) if yaw_s else (28.0 if view == "chest" else 20.0))
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 50
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
scene.frame_set(scene.frame_start)
if view == "chest":
    anchor = bone("上半身3") or bone("上半身2")
    heads = [arm.matrix_world @ b.head for b in (bone("左胸"), bone("右胸")) if b is not None]
    if not heads:
        heads = [arm.matrix_world @ arm.pose.bones[n].head for n in ("breast_physics_02_l", "breast_physics_02_r")
                 if n in arm.pose.bones]
    target = (sum(heads, Vector()) / len(heads)) if heads else arm.matrix_world @ anchor.head
    target = target + Vector((0.0, -0.08, -0.02))
    offset = Matrix.Rotation(yaw, 3, "Z") @ Vector((0.0, -0.62, 0.06))
    cam.matrix_world = Matrix.Translation(target + offset) @ (-offset).to_track_quat("-Z", "Y").to_matrix().to_4x4()
    w = cam.matrix_world.copy()
    cam.parent, cam.parent_type, cam.parent_bone = arm, "BONE", anchor.name
    cam.matrix_world = w
    size = (a.size or 720, a.size or 720)
else:
    target = Vector((0.0, 0.0, 0.95))
    offset = Matrix.Rotation(yaw, 3, "Z") @ Vector((0.0, -4.2, 0.0))
    cam.matrix_world = Matrix.Translation(target + offset) @ (-offset).to_track_quat("-Z", "Y").to_matrix().to_4x4()
    size = (a.size or 720, int((a.size or 720) * 1.5))
scene.render.resolution_x, scene.render.resolution_y = size
scene.render.resolution_percentage = 100
scene.eevee.taa_render_samples = 16
if a.wav and os.path.isfile(a.wav):
    scene.sequence_editor_create()
    scene.sequence_editor.sequences.new_sound("BGM", a.wav, 1, config.MARGIN + 1)
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
if a.still:
    scene.render.image_settings.file_format = "PNG"
    for f in a.still:
        scene.frame_set(f)
        scene.render.filepath = os.path.splitext(a.out)[0] + "_f%04d.png" % f
        bpy.ops.render.render(write_still=True)
else:
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.audio_codec = "AAC"
    scene.render.filepath = a.out
    bpy.ops.render.render(animation=True)
print("FX_RENDER_DONE %s apply %.0f s total %.0f s" % (a.out, t_apply, time.time() - t0))
