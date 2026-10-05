"""裙子:按配置串真正点一次「模拟 / 烘焙」,量每条裙链的链根偏离静止方向多少度(+ = 往外),和链根以下的骨陷进
腿胶囊多深(cm)。通过 = 后半段左右平均差 < MAX_SIDE、整段最大 < MAX_ANGLE、平均陷入 < MAX_POKE。

blender -b --factory-startup --python check_skirt.py -- PMX FRAMES CONFIG [MAX_ANGLE 45] [MAX_SIDE 5] [MAX_POKE 1]

由来(10-05):烘焙时腿的胶囊被一起藏起来、停在第一帧,PCF_005 的裙子右侧平均 +18°、最大 128° 卡住;修好后
左右 -1.7 / -1.7°、最大 7°。乳奶模板模型的外套骨贴着腿走,腿胶囊不留静止重叠以后,陷入 2.5 → 0.1 cm。
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender  # noqa: E402
from _blender import bpy, config  # noqa: E402

args = _blender.argv()
PMX, FRAMES, SPEC = args[0], int(args[1]), args[2]
MAX_ANGLE = float(args[3]) if len(args) > 3 else 45.0
MAX_SIDE = float(args[4]) if len(args) > 4 else 5.0
MAX_POKE = float(args[5]) if len(args) > 5 else 1.0
MARGIN = config.MARGIN

_blender.fresh()
from mmd_physics import bonecloth, chains  # noqa: E402

scene, root, arm = _blender.load(PMX, config.VMD, FRAMES)
bpy.ops.mmd_physics.fx_detect()
fx = root.mmd_physics_fx
_blender.configure(fx, SPEC)
bpy.ops.mmd_physics.fx_apply()
print("STATUS", fx.status[:400])
if scene.rigidbody_world is not None:
    scene.rigidbody_world.enabled = False          # 裙子已经是关键帧,不用再算刚体,逐帧快很多

skirt = [n for g in fx.groups if g.category == "SKIRT" and g.enabled for n in json.loads(g.bones)]
roots = chains.chain_roots(arm, skirt)
below = [n for n in skirt if n not in set(roots)]


def root_of(name):
    b = arm.data.bones[name]
    while b.parent is not None and b.parent.name in set(skirt):
        b = b.parent
    return b.name


chain_of = np.array([roots.index(root_of(n)) for n in below]) if below else np.zeros(0, int)
centre = next(b.name for b in arm.data.bones if "下半身" in chains.names_of(arm.pose.bones[b.name]))
legs = [o for o in bonecloth.collider_objects(arm) if "胯" not in o.name]
unit = bonecloth.metres_per_unit(arm)
print("SKIRT %d chains, %d bones below the roots, %d leg colliders" % (len(roots), len(below), len(legs)))

angles = {r: [] for r in roots}
poke = []                                            # per frame: per chain the deepest bone, cm
for f in range(MARGIN + 1, scene.frame_end + 1):
    scene.frame_set(f)
    c = arm.pose.bones[centre]
    ax = (c.tail - c.head).normalized()
    for r in roots:
        pb = arm.pose.bones[r]
        pp = pb.parent
        rest_local = pp.bone.matrix_local.inverted().to_3x3() @ (pb.bone.tail_local - pb.bone.head_local)
        rest_now = (pp.matrix.to_3x3() @ rest_local).normalized()
        now = (pb.tail - pb.head).normalized()
        rel = pb.head - c.head
        out = (rel - ax * rel.dot(ax)).normalized()
        a = math.degrees(rest_now.angle(now, 0.0))
        angles[r].append(a if now.dot(out) >= rest_now.dot(out) else -a)
    if legs and below:
        A = arm.matrix_world
        heads = np.array([tuple(A @ arm.pose.bones[n].head) for n in below])
        tails = np.array([tuple(A @ arm.pose.bones[n].tail) for n in below])
        pen = bonecloth._edge_pen(heads, tails, np.full(len(below), 0.02 / unit), bonecloth._capsules(legs))[0]
        deep = np.maximum(pen.max(axis=1), 0.0) * 100.0 * unit
        poke.append([deep[chain_of == k].max() if (chain_of == k).any() else 0.0 for k in range(len(roots))])

half = (scene.frame_end - MARGIN) // 2
print("  %-34s %7s %7s %7s %7s %7s" % ("root", "x", "front", "mean1", "mean2", "max"))
rows = []
for r in roots:
    v = angles[r]
    h = arm.data.bones[r].head_local
    rows.append((r, h.x, -h.y, sum(v[:half]) / max(1, half), sum(v[half:]) / max(1, len(v) - half),
                 max(v, key=abs)))
rows.sort(key=lambda t: math.atan2(t[1], t[2]))
for row in rows:
    print("  %-34s %7.3f %7.3f %7.1f %7.1f %7.1f" % row)
right = [t[4] for t in rows if t[1] < -0.01]
left = [t[4] for t in rows if t[1] > 0.01]
mr = sum(right) / max(1, len(right))
ml = sum(left) / max(1, len(left))
worst = max(abs(t[5]) for t in rows) if rows else 0.0
poke2 = float(np.mean(np.array(poke)[half:])) if poke else 0.0
ok = abs(mr - ml) < MAX_SIDE and worst < MAX_ANGLE and poke2 < MAX_POKE
_blender.result("skirt %s %s" % (os.path.basename(PMX), SPEC), ok,
                "second half right %.1f / left %.1f deg, max %.1f deg, legs inside the cloth %.2f cm "
                "(limits: side %.0f, max %.0f, poke %.1f)" % (mr, ml, worst, poke2, MAX_SIDE, MAX_ANGLE, MAX_POKE))
