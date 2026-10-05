"""调裙子参数用:动画只采样一次,然后直接调 bonecloth.simulate 换参数跑好几遍(每遍十几秒),比较每条链的
链根偏角(+ = 往外)、末端往外移多少、碰撞体推了多少、链根以下的骨陷进腿胶囊多深。不写关键帧,不改模型。

blender -b --factory-startup --python skirt_solver_variants.py -- PMX FRAMES [CAT SKIRT] [PRESET skirt] [VARIANTS]
VARIANTS:";" 隔开,每个 "名字" 或 "名字:参数=值,参数=值";参数是 bonecloth.DEFAULTS 里的键
(allow_legs=1、link=0、restore_stiffness=0.04 ……),另外 rest=FIRST(静止重叠按第一帧量)/ NONE(不放过任何重叠)、
colliders=0(不碰撞)。基准(不写参数)和「模拟 / 烘焙」一样:静止重叠在胯里放过、在腿里不放过。
"""
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender  # noqa: E402
from _blender import bpy, config  # noqa: E402

args = _blender.argv()
PMX, FRAMES = args[0], int(args[1])
CAT = args[2] if len(args) > 2 else "SKIRT"
PRESET = args[3] if len(args) > 3 else "skirt"
VARIANTS = args[4] if len(args) > 4 else ("base;allow_legs:allow_legs=1;nolink:link=0;noback:backstop=0;"
                                          "point:collision_edge=0;first:rest=FIRST;norest:rest=NONE;"
                                          "nocoll:colliders=0")
MARGIN = config.MARGIN

_blender.fresh()
from mmd_physics import bonecloth, effects, effects_ui  # noqa: E402

scene, root, arm = _blender.load(PMX, config.VMD, FRAMES)
bpy.ops.mmd_physics.fx_detect()
fx = root.mmd_physics_fx
# 全部跟骨:每条链的动画姿势 = 它挂在跳舞的身体上的静止形状
_blender.configure(fx, ",".join("%s=FOLLOW" % c for c in effects_ui.CATS))
bpy.ops.mmd_physics.fx_apply()
p = getattr(fx, effects_ui.ATTR[CAT])
p.method, p.preset = "CLOTH", PRESET
plan = effects_ui.plan_of(root)
values = plan["categories"][CAT]["values"]
units = effects._units(arm, plan["groups"], {CAT: plan["categories"][CAT]})
cloths = effects._batch_cloth(arm, units)
colliders = bonecloth.collider_objects(arm) or bonecloth.add_body_colliders(arm)
print("COLLIDERS", [(o.name, round(o["bc_r0"], 3), round(o["bc_r1"], 3), round(o["bc_len"], 3)) for o in colliders])
scene.rigidbody_world.enabled = False
frames = list(range(scene.frame_start, scene.frame_end + 1))
t = time.time()
rests = {id(u): bonecloth.rest_pose(scene, arm, bonecloth.chain_set(arm, u.bones).names, colliders) for u in cloths}
data = effects._sample(scene, arm, cloths, frames, colliders)
for u in cloths:
    rests[id(u)]["moving"] = [o.parent_bone != data[id(u)]["centre"] for o in colliders]
print("SAMPLED %d frames, %d batches in %.0f s" % (len(frames), len(cloths), time.time() - t))

# 碰撞体推了多少:包一层碰撞函数记下每次的位移(simulate 调用时按名字找,换掉就能记)
LOG = {"calls": [], "on": False}
_pe, _pp = bonecloth._push_edges, bonecloth._push_points


def pe(head, tail, r, caps, allow=None):
    nt, hit = _pe(head, tail, r, caps, allow)
    if LOG["on"]:
        LOG["calls"].append(np.linalg.norm(nt - tail, axis=1))
    return nt, hit


def pp(pts, r, caps, allow=None):
    out, hit = _pp(pts, r, caps, allow)
    if LOG["on"]:
        LOG["calls"].append(np.linalg.norm(out - pts, axis=1))
    return out, hit


bonecloth._push_edges, bonecloth._push_points = pe, pp


def root_of(cs, j):
    while cs.parent[j] >= 0:
        j = cs.parent[j]
    return j


def run(over):
    params = {k: v for k, v in values.items() if k != "colliders"}
    params["unit"] = bonecloth.metres_per_unit(arm)
    rest_mode = over.pop("rest", "REST")
    use_coll = bool(int(over.pop("colliders", 1)))
    for k, v in over.items():
        old = params.get(k, bonecloth.DEFAULTS.get(k))
        params[k] = (v not in ("0", "false")) if isinstance(old, bool) else type(old)(float(v))
    rows = []
    for u in cloths:
        d = data[id(u)]
        cs, base, cen = d["cs"], d["base"], d["cen"]
        caps = d["caps"] if use_coll else None
        rest = rests[id(u)] if use_coll else None
        if rest is not None and rest_mode == "FIRST":
            rest = dict(rest, head=base[0]["head"], tail=base[0]["tail"], caps=caps[0])
        elif rest_mode == "NONE":
            rest = None
        LOG["calls"], LOG["on"] = [], True
        sim = bonecloth.simulate(cs, base, cen, caps, 30.0, params, rest=rest)
        LOG["on"] = False
        per = int(params.get("substeps", 3)) * int(params.get("iterations", 4))
        push = np.zeros((len(frames), len(cs.names)))
        if LOG["calls"]:
            k = 0
            for f in range(len(frames)):
                for _s in range(per):
                    for lv in cs.levels:
                        push[f, lv] += LOG["calls"][k]
                        k += 1
        roots = [i for i in range(len(cs.names)) if cs.parent[i] < 0]
        members = {i: [j for j in range(len(cs.names)) if root_of(cs, j) == i] for i in roots}
        legs = [j for j, o in enumerate(colliders) if "胯" not in o.name]
        rad = np.full(len(cs.names), values.get("radius", 0.02) / params["unit"])
        poke = np.zeros((len(frames), len(cs.names)))
        for f in range(len(frames)):
            rot, head = sim[f]
            tail = head + rot[:, :, 1] * cs.length[:, None]
            c = d["caps"][f]
            if c is not None:
                pen = bonecloth._edge_pen(head, tail, rad, tuple(x[legs] for x in c))[0]
                poke[f] = np.maximum(pen.max(axis=1), 0.0) * 100.0 * params["unit"]
        poke[:, cs.parent < 0] = 0.0
        half = MARGIN + FRAMES // 2
        for i in roots:
            angs, tips = [], []
            for f in range(len(frames)):
                rot, head = sim[f]
                b = base[f]
                anim = (b["tail"][i] - b["head"][i]) / np.linalg.norm(b["tail"][i] - b["head"][i])
                simd = rot[i][:, 1]
                C = cen[f]
                ax = C[:3, 1] / np.linalg.norm(C[:3, 1])
                rel = b["head"][i] - C[:3, 3]
                out = rel - ax * (rel @ ax)
                out /= max(np.linalg.norm(out), 1e-9)
                ang = math.degrees(math.acos(np.clip(anim @ simd, -1, 1)))
                angs.append(ang if simd @ out >= anim @ out else -ang)
                j = members[i][-1]
                tips.append(float((head[j] + rot[j][:, 1] * cs.length[j] - b["tail"][j]) @ out) * 100.0 * params["unit"])
            h0 = rests[id(u)]["head"][i]                # rest pose, world: the model faces -Y; x < 0 = her right
            rows.append((cs.names[i], float(h0[0]), float(-h0[1]), np.mean(angs[MARGIN:half]), np.mean(angs[half:]),
                         np.mean(tips[half:]), max(angs, key=abs), 1 + int(np.argmax(np.abs(angs))),
                         float(push[half:, members[i]].sum(axis=1).mean()) * 100.0 * params["unit"],
                         float(poke[half:, members[i]].max(axis=1).mean()), float(poke[:, members[i]].max())))
    return rows


summary = []
for spec in VARIANTS.split(";"):
    name, _, kv = spec.partition(":")
    over = dict(x.split("=") for x in kv.split(",") if x)
    t = time.time()
    rows = run(dict(over))
    print("VARIANT %s %s (%.0f s)" % (name, over, time.time() - t))
    rows.sort(key=lambda r: math.atan2(r[1], r[2]))
    print("  %-34s %7s %7s %7s %7s %7s %7s %6s %7s %6s %6s" % ("root", "x", "front", "ang1", "ang2", "tip2cm", "max",
                                                               "frame", "push", "poke2", "pokeM"))
    for r in rows:
        print("  %-34s %7.3f %7.3f %7.1f %7.1f %7.1f %7.1f %6d %7.2f %6.1f %6.1f" % r)
    R = [r for r in rows if r[1] < -0.02]
    L = [r for r in rows if r[1] > 0.02]
    summary.append((name, np.mean([r[4] for r in R]) if R else 0.0, np.mean([r[4] for r in L]) if L else 0.0,
                    np.mean([r[5] for r in R]) if R else 0.0, np.mean([r[5] for r in L]) if L else 0.0,
                    max(abs(r[6]) for r in rows), np.mean([r[9] for r in rows]), max(r[10] for r in rows)))
print("SUMMARY (second half: mean root angle right / left, mean tip outward cm right / left, max angle; "
      "poke = cm the bones below the roots sink into the leg capsules: second-half mean, worst)")
for s in summary:
    print("  %-12s ang R %6.1f  L %6.1f   tip R %6.1f  L %6.1f   max %6.1f   poke %5.1f  worst %5.1f" % s)
