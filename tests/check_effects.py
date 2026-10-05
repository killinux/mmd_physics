"""效果选择整条流程:识别 → 几种方式 / 预设各算一遍(算完播放、量各类的摆幅)→ 还原。
通过 = 还原后刚体、关节、动作、重力和第一次用之前逐项一样,没有残留(原类型标记、工作动作、碰撞体)。

blender -b --factory-startup --python check_effects.py -- PMX FRAMES CONFIG [CONFIG ...]
CONFIG 见 _blender.configure,例如 "BUST=SPRING:k1,HAIR=CLOTH:hair,SKIRT=RIGID:model,CLOTH=FOLLOW"
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender  # noqa: E402
from _blender import bpy, config  # noqa: E402

args = _blender.argv()
PMX, FRAMES, CONFIGS = args[0], int(args[1]), args[2:]
MARGIN = config.MARGIN

_blender.fresh()
from mmd_physics import bonecloth, chains, effects  # noqa: E402

t0 = time.time()
scene, root, arm = _blender.load(PMX, config.VMD, FRAMES, morphs=True)
print("LOADED %.1f s, action %s, frames %d-%d" % (time.time() - t0, arm.animation_data.action.name,
                                                   scene.frame_start, scene.frame_end))
bpy.ops.mmd_physics.fx_detect()
fx = root.mmd_physics_fx
print("STATUS", fx.status)
groups = {}
for g in fx.groups:
    groups.setdefault(g.category, []).append(json.loads(g.bones))


def snapshot():
    """刚体 / 关节的值、动作、重力:还原后拿来比。"""
    m = effects._model(root)
    return ({o.name: effects._body_rec(o) for o in m.rigidBodies()},
            {j.name: effects._joint_rec(j) for j in m.joints() if j.rigid_body_constraint is not None},
            arm.animation_data.action.name, tuple(scene.gravity))


def first_moving(bones):
    """每条链量摆幅的骨:链根和它下面第一根,各配它的父骨。"""
    out = []
    s = set(bones)
    for r in chains.chain_roots(arm, bones):
        b = arm.data.bones[r]
        if b.parent is not None:
            out.append((r, b.parent.name))
        for c in b.children:
            if c.name in s:
                out.append((c.name, r))
                break
    return out


def measure():
    """带物理播放;每类:骨在父骨坐标里的方向和第一帧比转了多少度,所有链所有帧的 平均 / p90 / 最大。"""
    pairs = {cat: [p for bones in lists for p in first_moving(bones)] for cat, lists in groups.items()}
    first, angles = {}, {cat: [] for cat in pairs}
    for f in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(f)
        for cat, ps in pairs.items():
            for bone, parent in ps:
                pb, pp = arm.pose.bones[bone], arm.pose.bones[parent]
                d = (pp.matrix.to_3x3().inverted() @ (pb.tail - pb.head)).normalized()
                if f <= MARGIN + 1:
                    first[(bone, parent)] = d
                    continue
                angles[cat].append(math.degrees(first[(bone, parent)].angle(d, 0.0)))
    out = {}
    for cat, a in angles.items():
        if a:
            a = sorted(a)
            out[cat] = "mean %.1f p90 %.1f max %.1f (n %d)" % (sum(a) / len(a), a[int(0.9 * (len(a) - 1))], a[-1],
                                                              len(a))
    return out


before = snapshot()
for spec in CONFIGS:
    _blender.configure(fx, spec)
    t = time.time()
    res = bpy.ops.mmd_physics.fx_apply()
    t_apply = time.time() - t
    t = time.time()
    stats = measure()
    print("CONFIG %s | apply %.1f s, play %.1f s | %s" % (spec, t_apply, time.time() - t, res))
    for line in fx.status.split(" | "):
        print("   ", line)
    for cat, s in stats.items():
        print("    swing %-6s %s" % (cat, s))
    _blender.result("apply %s" % spec, res == {"FINISHED"}, "%.1f s" % t_apply)

bpy.ops.mmd_physics.fx_restore()
after = snapshot()
bad = []
for k in before[0]:
    if before[0][k] != after[0].get(k):
        bad.append(("body", k))
for k in before[1]:
    a, b = before[1][k], after[1].get(k)
    if b is None or any(abs(x - y) > 1e-6 for x, y in zip(
            [a[x] for x in effects.LIMITS] + a["damp"] + a["k_lin"] + a["k_ang"],
            [b[x] for x in effects.LIMITS] + b["damp"] + b["k_lin"] + b["k_ang"])) \
            or a["spring_type"] != b["spring_type"] or a["use"] != b["use"]:
        bad.append(("joint", k))
left = [o.name for o in bpy.data.objects if chains.ORIG_TYPE in o]
works = [a.name for a in bpy.data.actions if a.get(effects.WORK)]
cols = bonecloth.collider_objects(arm)
ok = not bad and not left and not works and not cols and before[2:] == after[2:]
_blender.result("restore %s" % os.path.basename(PMX), ok,
                "%d differences %s | action %s -> %s | gravity %s -> %s | left: orig-type %d, work actions %s, "
                "colliders %d" % (len(bad), bad[:3], before[2], after[2], before[3], after[3], len(left), works,
                                  len(cols)))
