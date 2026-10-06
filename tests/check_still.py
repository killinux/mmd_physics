"""原来不动的链(没有刚体 / 只有跟骨刚体):识别出来、按配置串真正点一次「模拟 / 烘焙」,量每条链整体(链根的头 →
最深的骨尾)偏离静止方向多少度,再还原、查有没有剩下新建的刚体。

blender -b --factory-startup --python check_still.py -- PMX FRAMES CONFIG [MIN_GROUPS 1] [MOVE 1] [MAX 90] [STRIP]

- MIN_GROUPS:至少识别出几组原来不动的链(参与的)。
- MOVE:1 = 应该晃起来(中位数 > 1°、最大 < MAX 不炸开);0 = 应该照旧不动(最大 < 0.5°,「模型原样」时)。
- STRIP:正则;导入后先删掉骨名匹配的刚体和连着它们的关节,当作转换来的模型没有这部分物理(例:PCF_005 的
  裙子 "skirt" —— 要跳得动的 MMD 骨架,XPS 骨名的模型套不上舞蹈动作)。
CONFIG 为空 = 各类「MMD 刚体 · 模型原样」。
"""
import re
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender  # noqa: E402
from _blender import bpy, config  # noqa: E402

args = _blender.argv()
PMX, FRAMES, SPEC = args[0], int(args[1]), args[2] if len(args) > 2 else ""
MIN_GROUPS = int(args[3]) if len(args) > 3 else 1
MOVE = (args[4] if len(args) > 4 else "1") == "1"
MAX_ANGLE = float(args[5]) if len(args) > 5 else 90.0
STRIP = args[6] if len(args) > 6 else ""
MARGIN = config.MARGIN
NAME = "still %s%s [%s]" % (os.path.splitext(os.path.basename(PMX))[0], " -" + STRIP if STRIP else "", SPEC or "model")

_blender.fresh()
from mmd_physics import chains  # noqa: E402

scene, root, arm = _blender.load(PMX, config.VMD, FRAMES)
if STRIP:
    rx = re.compile(STRIP, re.I)
    gone = {o for o in bpy.data.objects if getattr(o, "mmd_type", "") == "RIGID_BODY" and rx.search(o.mmd_rigid.bone)}
    joints = [o for o in bpy.data.objects if getattr(o, "mmd_type", "") == "JOINT" and o.rigid_body_constraint
              and (o.rigid_body_constraint.object1 in gone or o.rigid_body_constraint.object2 in gone)]
    for o in list(gone) + joints:
        bpy.data.objects.remove(o, do_unlink=True)
    print("STRIP %d bodies, %d joints on bones matching %r" % (len(gone), len(joints), STRIP))
n_bodies = sum(1 for o in bpy.data.objects if getattr(o, "mmd_type", "") == "RIGID_BODY")
n_joints = sum(1 for o in bpy.data.objects if getattr(o, "mmd_type", "") == "JOINT")
bpy.ops.mmd_physics.fx_detect()
fx = root.mmd_physics_fx
print("DETECT", fx.status)
for g in fx.groups:
    print("  GROUP %-6s %-8s %-3s %3d bones  %s" % (g.category, g.still or "-", "on" if g.enabled else "off", g.count,
                                                    g.name))
still = [g for g in fx.groups if g.still and g.enabled]
_blender.configure(fx, SPEC)
bpy.ops.mmd_physics.fx_apply()
print("STATUS", fx.status[:600])
made = [o.name for o in bpy.data.objects if chains.made_by_us(o)]
print("MADE %d objects" % len(made))

# 每条链:链根、最深的骨、挂点骨;静止时(挂点骨坐标系里)链根头 → 梢的骨尾的方向
chains_ = []
for g in still:
    bones = json.loads(g.bones)
    s = set(bones)
    for r in chains.chain_roots(arm, bones):
        b = arm.data.bones[r]
        if b.parent is None:
            continue
        tip, best = r, 0
        for c in b.children_recursive:
            if c.name in s:
                d, p = 0, c
                while p.name != r:
                    d, p = d + 1, p.parent
                if d > best:
                    tip, best = c.name, d
        a = b.parent
        rest = a.matrix_local.inverted().to_3x3() @ (arm.data.bones[tip].tail_local - b.head_local)
        chains_.append((g.name, r, tip, a.name, rest))
print("CHAINS %d (%s)" % (len(chains_), ", ".join("%s→%s" % (r, t) for _g, r, t, _a, _v in chains_[:6])))

angles = []
for f in range(scene.frame_start, scene.frame_end + 1):    # 刚体要从头一帧一帧往前走才会算
    scene.frame_set(f)
    if f <= MARGIN:
        continue
    row = []
    for _g, r, tip, a, rest in chains_:
        pa = arm.pose.bones[a]
        want = (pa.matrix.to_3x3() @ rest)
        now = arm.pose.bones[tip].tail - arm.pose.bones[r].head
        row.append(np.degrees(want.angle(now, 0.0)))
    angles.append(row)
A = np.array(angles) if angles else np.zeros((0, 0))
if A.size:
    per = np.median(A, axis=0)
    med, p90, mx = float(np.median(A)), float(np.percentile(A, 90)), float(A.max())
    worst = chains_[int(np.argmax(A.max(axis=0)))][1]
    print("ANGLE median %.2f  p90 %.2f  max %.2f (worst chain %s); per-chain medians %s" % (
        med, p90, mx, worst, " ".join("%.1f" % x for x in per[:12])))
else:
    med = p90 = mx = 0.0

bpy.ops.mmd_physics.fx_restore()
left = [o.name for o in bpy.data.objects if chains.made_by_us(o)]
nb2 = sum(1 for o in bpy.data.objects if getattr(o, "mmd_type", "") == "RIGID_BODY")
nj2 = sum(1 for o in bpy.data.objects if getattr(o, "mmd_type", "") == "JOINT")
print("RESTORE left %d made objects; bodies %d -> %d, joints %d -> %d" % (len(left), n_bodies, nb2, n_joints, nj2))

ok = len(still) >= MIN_GROUPS and not left and nb2 == n_bodies and nj2 == n_joints and bool(chains_)
if MOVE:
    ok = ok and med > 1.0 and mx < MAX_ANGLE
else:
    ok = ok and mx < 0.5
_blender.result(NAME, ok, "groups %d chains %d median %.1f p90 %.1f max %.1f made %d left %d" % (
    len(still), len(chains_), med, p90, mx, len(made), len(left)))
