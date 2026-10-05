"""弹簧骨骼回归:新版 kawaii.bake() 和 0.2.0 版(kawaii_v020_reference.py)在 Vindictus 模型上烘出的关键帧要一样
(vindictus 那边的脚本还在用 bake / roots_of / breast_bodies / bodies_follow_bones);再在别的骨架上烘一遍看能不能动。

blender -b --factory-startup --python check_kawaii.py -- VINDICTUS_PMX [OTHER_PMX ...]
"""
import importlib.util
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender  # noqa: E402
from _blender import bpy, config  # noqa: E402

_blender.fresh(("mmd_tools",))
from mmd_physics import kawaii as new  # noqa: E402

spec = importlib.util.spec_from_file_location("kawaii_v020", os.path.join(_blender.HERE, "kawaii_v020_reference.py"))
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)

args = _blender.argv()
UE, OTHERS = args[0], args[1:]
FRAMES = (1, 90)


def load(path):
    _blender.fresh(("mmd_tools",))
    scene, root, arm = _blender.load(path, config.VMD, margin=0)
    scene.frame_start, scene.frame_end = FRAMES
    if scene.rigidbody_world:
        scene.rigidbody_world.enabled = False
    for o in bpy.data.objects:
        if o.type == "MESH" and getattr(o, "mmd_type", "") == "NONE":
            o.hide_viewport = True
    return scene, arm


def snapshot(arm):
    act = arm.animation_data.action
    names = set(act.get(new.TAG, "").split("|")) - {""}
    out = {}
    for fc in act.fcurves:
        if fc.data_path.startswith('pose.bones["') and fc.data_path.split('"')[1] in names:
            out[(fc.data_path, fc.array_index)] = [kp.co[1] for kp in fc.keyframe_points]
    return out


def diff(a, b):
    if set(a) != set(b):
        return None, "different curves: %d vs %d" % (len(a), len(b))
    worst = 0.0
    for k in a:
        if len(a[k]) != len(b[k]):
            return None, "different key counts on %s" % (k,)
        worst = max(worst, max(abs(x - y) for x, y in zip(a[k], b[k])))
    return worst, "max |old - new| = %.3g over %d curves" % (worst, len(a))


scene, arm = load(UE)
new.bodies_follow_bones(arm)
for label, kw in (("default", dict(capsules=False, carrier=None)),
                  ("capsules + 下半身", dict(capsules=True, carrier="下半身"))):
    t = time.time()
    old.bake(scene, arm, None, capsules=kw["capsules"], carrier=kw["carrier"])
    a = snapshot(arm)
    t_old = time.time() - t
    old.clear(arm)
    t = time.time()
    st = new.bake(scene, arm, None, capsules=kw["capsules"], carrier=kw["carrier"])
    b = snapshot(arm)
    t_new = time.time() - t
    new.clear(arm)
    worst, text = diff(a, b)
    _blender.result("kawaii regression %s" % label, worst is not None and worst < 1e-6 and len(a) > 0,
                    "%s | old %.1f s, new %.1f s | %s" % (text, t_old, t_new, st))

for path in OTHERS:
    scene, arm = load(path)
    found = new.breast_chains(arm)
    new.bodies_follow_bones(arm)
    st = new.bake(scene, arm, None, capsules=False)
    act = arm.animation_data.action
    moved = 0.0
    for c in found:
        for n in c.bones():
            for fc in act.fcurves:
                if fc.data_path == 'pose.bones["%s"].rotation_quaternion' % n:
                    vals = [kp.co[1] for kp in fc.keyframe_points]
                    moved = max(moved, max(vals) - min(vals))
    _blender.result("kawaii other skeleton %s" % os.path.basename(path), len(found) >= 2 and moved > 1e-4,
                    "chains %s | %s | rotation keys span %.4f" % ([(c.names[0], len(c.bones()), c.tip) for c in found],
                                                                  st, moved))
