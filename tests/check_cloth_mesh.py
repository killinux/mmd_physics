"""裙子的布面:按配置串点一次「模拟 / 烘焙」,量两条相邻链之间那块布(四边形)陷进腿多深、横向拉长多少。

blender -b --factory-startup --python check_cloth_mesh.py -- PMX FRAMES CONFIG [VMD] [MAX_IN 2] [MAX_STRETCH 1.6]

- 布:裙链按绕下半身轴的角度排一圈,相邻两条(链根骨尾离得近于 25 cm)第 k 节的头、尾围成一个四边形,每块取
  3×3 个点(bonecloth.mesh_pairs 同样的连法,和解算有没有开布面无关)。
- 陷进腿:每个点在腿胶囊(大腿、小腿;胯不算)里多深,减去静止时就陷着的(裙子贴腿的模型),cm。逐帧取最深的,
  报整段最大和平均;骨段本身陷进去多少另报(check_skirt.py 的量法)。
- 拉长:同一层两条相邻链的骨尾间距 ÷ 静止时的(模型做出来的样子),逐帧取最大的,报整段最大和 p90。
通过 = 布最深陷入 < MAX_IN cm、拉长 < MAX_STRETCH。VMD 不写 = config.VMD(手势舞);腿动得大的用 config.VMD_LEGS。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender  # noqa: E402
from _blender import bpy, config  # noqa: E402

args = _blender.argv()
PMX, FRAMES, SPEC = args[0], int(args[1]), args[2]
VMD = args[3] if len(args) > 3 and args[3] else config.VMD
MAX_IN = float(args[4]) if len(args) > 4 else 2.0
MAX_STRETCH = float(args[5]) if len(args) > 5 else 1.6
MARGIN = config.MARGIN
NAME = "mesh %s %s [%s]" % (os.path.splitext(os.path.basename(PMX))[0], os.path.splitext(os.path.basename(VMD))[0],
                           SPEC)

_blender.fresh()
from mmd_physics import bonecloth, chains  # noqa: E402

scene, root, arm = _blender.load(PMX, VMD, FRAMES)
bpy.ops.mmd_physics.fx_detect()
fx = root.mmd_physics_fx
_blender.configure(fx, SPEC)
bpy.ops.mmd_physics.fx_apply()
print("STATUS", fx.status[:500])
if scene.rigidbody_world is not None and "RIGID" not in SPEC:
    scene.rigidbody_world.enabled = False          # 裙子已经是关键帧

import json  # noqa: E402

skirt = [n for g in fx.groups if g.category == "SKIRT" and g.enabled for n in json.loads(g.bones)]
cs = bonecloth.chain_set(arm, skirt)
legs = [o for o in bonecloth.collider_objects(arm) if "胯" not in o.name]
made_legs = False
if not legs:                                       # 刚体方式不建碰撞体:量的时候临时建,量完删掉
    legs = [o for o in bonecloth.add_body_colliders(arm, log=lambda s: None) if "胯" not in o.name]
    made_legs = True
unit = bonecloth.metres_per_unit(arm)
centre = next(b.name for b in arm.data.bones if "下半身" in chains.names_of(arm.pose.bones[b.name]))
A = arm.matrix_world
names = cs.names


def pose():
    head = np.array([tuple(A @ arm.pose.bones[n].head) for n in names])
    tail = np.array([tuple(A @ arm.pose.bones[n].tail) for n in names])
    return head, tail


# 静止姿势:四边形怎么连、静止时布和骨就陷进腿多深(裙子贴腿的模型)、横边多长
was = arm.data.pose_position
arm.data.pose_position = "REST"
scene.frame_set(scene.frame_start)
hr, tr = pose()
hor = bonecloth.mesh_pairs(cs, tr, np.array(A @ arm.pose.bones[centre].matrix), 0.25 / unit)
quads = []                                         # (a, b):两条相邻链同一层的骨
for k, (i, j, _r) in hor.items():
    quads += list(zip(i.tolist(), j.tolist()))
uv = [(u, v) for u in (0.2, 0.5, 0.8) for v in (0.2, 0.5, 0.8)]
print("SKIRT %d bones, %d chains, %d quads, %d leg colliders" % (len(names), sum(1 for p in cs.parent if p < 0),
                                                                len(quads), len(legs)))


def samples(head, tail):
    out = []
    for a, b in quads:
        for u, v in uv:                            # u 沿链(头 → 尾),v 横向(a → b)
            pa = head[a] + (tail[a] - head[a]) * u
            pb = head[b] + (tail[b] - head[b]) * u
            out.append(pa + (pb - pa) * v)
    return np.array(out) if out else np.zeros((0, 3))


def depth(points, caps):
    if not len(points) or caps is None:
        return np.zeros((len(points), 0))
    return np.maximum(bonecloth._point_pen(points, np.zeros(len(points)), caps)[0], 0.0)


rest_in = depth(samples(hr, tr), bonecloth._capsules(legs))
rest_seg = np.maximum(bonecloth._edge_pen(hr, tr, np.zeros(len(names)), bonecloth._capsules(legs))[0], 0.0)
arm.data.pose_position = was
scene.frame_set(scene.frame_start)

fabric, seg, stretch = [], [], []
for f in range(scene.frame_start, scene.frame_end + 1):
    scene.frame_set(f)
    if f <= MARGIN:
        continue
    head, tail = pose()
    caps = bonecloth._capsules(legs)
    fabric.append(float((np.maximum(depth(samples(head, tail), caps) - rest_in, 0.0)).max(initial=0.0)) * 100 * unit)
    sp = np.maximum(bonecloth._edge_pen(head, tail, np.zeros(len(names)), caps)[0] - rest_seg, 0.0)
    seg.append(float(sp.max(initial=0.0)) * 100 * unit)
    st = [np.linalg.norm(tail[i] - tail[j], axis=1) / np.maximum(r, 1e-9) for i, j, r in hor.values()]
    stretch.append(float(np.concatenate(st).max()) if st else 1.0)
if made_legs:
    for o in legs:
        bpy.data.objects.remove(o, do_unlink=True)
F, Sg, St = np.array(fabric), np.array(seg), np.array(stretch)
print("FABRIC in legs cm: max %.2f mean %.2f p90 %.2f | bones in legs cm: max %.2f mean %.2f | stretch max %.2f p90 %.2f"
      % (F.max(), F.mean(), np.percentile(F, 90), Sg.max(), Sg.mean(), St.max(), np.percentile(St, 90)))
ok = F.max() < MAX_IN and St.max() < MAX_STRETCH
_blender.result(NAME, ok, "fabric max %.2f mean %.2f cm, bones max %.2f cm, stretch max %.2f p90 %.2f (limits %.1f cm, %.2f)"
                % (F.max(), F.mean(), Sg.max(), St.max(), np.percentile(St, 90), MAX_IN, MAX_STRETCH))
