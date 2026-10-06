"""胸部「整套换上」的套件:每个套件经面板算一遍(识别 → 选预设 → 模拟 / 烘焙),带物理播放,量主胸骨。
通过 = 每条胸链都建了一套(刚体、关节数对,左右连着时加上左右之间的关节),物理步长按套件要的设了,主胸骨在动、
没炸(没有 NaN,偏转不过 MAX 度);左右连着时两侧主胸骨每帧偏转差不过 PAIR_DEG 度(锁住了);
还原后套件的刚体 / 关节一个不剩、步长回到原来的。

blender -b --factory-startup --python check_kits.py -- PMX FRAMES [PRESET ...]     (不写 = rgba tda western ah ah_clothed)
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender  # noqa: E402
from _blender import bpy, config  # noqa: E402
from mathutils import Vector  # noqa: E402

args = _blender.argv()
PMX, FRAMES = args[0], int(args[1])
PRESETS = args[2:] or ["rgba", "tda", "western", "ah", "ah_clothed"]
MAX_DEG = 60.0                      # 主胸骨相对父骨偏离静止的上限
MIN_MOVE = 0.3                      # 常见摆幅(10-90 %)至少这么多度,否则算没在动
PAIR_DEG = 1.0                      # 左右连着:两侧主胸骨偏转之差(逐帧,90 %)不过这么多度

_blender.fresh()
from mmd_physics import chains, effects, kits  # noqa: E402
from mmd_tools.core.model import Model  # noqa: E402

t0 = time.time()
scene, root, arm = _blender.load(PMX, config.VMD, FRAMES)
m = Model(root)
bpy.ops.mmd_physics.fx_detect()
fx = root.mmd_physics_fx
bust = chains.bust_chains(arm)
mains = [kits.main_bone(arm, c) for c in bust]
side_mains = {s: [b for c, b in zip(bust, mains) if c.side == s] for s in ("L", "R")}
n_pairs = min(len(side_mains["L"]), len(side_mains["R"]))       # 左右连着时连几对(同序号的链)
world0 = scene.rigidbody_world
steps0 = world0.substeps_per_frame if world0 is not None else 0
print("LOADED %.1f s, %d bust chains, main bones %s, substeps %d" % (time.time() - t0, len(bust), mains, steps0))


def rel(pb):
    """(偏离静止的角度°, 骨尾位移 cm),相对父骨。"""
    r = pb.parent.matrix.inverted() @ pb.matrix
    r0 = pb.parent.bone.matrix_local.inverted() @ pb.bone.matrix_local
    tail = Vector((0.0, pb.bone.length, 0.0, 1.0))
    return math.degrees((r0.inverted() @ r).to_quaternion().angle), ((r @ tail) - (r0 @ tail)).length * 100.0


def pct(v, q):
    return v[int(q * (len(v) - 1))]


for preset in PRESETS:
    _blender.configure(fx, "BUST=RIGID:" + preset)
    t = time.time()
    res = bpy.ops.mmd_physics.fx_apply()
    t_apply = time.time() - t
    key = fx.bust.kit
    kit = kits.KITS[key]
    made_b = [o for o in m.rigidBodies() if o.get(kits.TAG)]
    made_j = [o for o in m.joints() if o.get(kits.TAG)]
    paired = fx.bust.kit_pair and kits.has_pairs(key)
    want_b = len(kit["bodies"]) * len(bust)
    want_j = len(kit["joints"]) * len(bust) + (len(kit["pairs"]) * n_pairs if paired else 0)
    world = scene.rigidbody_world
    fps = scene.render.fps / scene.render.fps_base
    hz = round(fps * world.substeps_per_frame)
    want_hz = kits.step_hz(key) or round(fps * steps0)
    trace = {b: [] for b in mains}
    for f in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(f)
        for b in mains:
            trace[b].append(rel(arm.pose.bones[b]))
    lines, ok = [], res == {"FINISHED"} and len(made_b) == want_b and len(made_j) == want_j and hz == want_hz
    for b, tr in trace.items():
        a = sorted(x[0] for x in tr[config.MARGIN:])
        cm = sorted(x[1] for x in tr[config.MARGIN:])
        nan = any(math.isnan(x) for x in a + cm)
        move = pct(a, 0.9) - pct(a, 0.1)
        good = not nan and a[-1] < MAX_DEG and move > MIN_MOVE
        ok = ok and good
        lines.append("%s %s median %.1f p10-p90 %.1f-%.1f max %.1f deg, tail %.1f cm (max %.1f)" % (
            "ok" if good else "BAD", b, pct(a, 0.5), pct(a, 0.1), pct(a, 0.9), a[-1], pct(cm, 0.5), cm[-1]))
    if paired:
        for bl, br in zip(side_mains["L"], side_mains["R"]):
            d = sorted(abs(x[0] - y[0]) for x, y in zip(trace[bl][config.MARGIN:], trace[br][config.MARGIN:]))
            good = pct(d, 0.9) < PAIR_DEG
            ok = ok and good
            lines.append("%s together %s / %s: |L - R| p90 %.2f max %.2f deg" % (
                "ok" if good else "BAD", bl, br, pct(d, 0.9), d[-1]))
    print("KIT %s | apply %.1f s | %s" % (preset, t_apply, fx.status))
    for ln in lines:
        print("    " + ln)
    _blender.result("kit %s %s" % (preset, os.path.basename(PMX)), ok,
                    "bodies %d/%d joints %d/%d, %d Hz (want %d) | %s" % (len(made_b), want_b, len(made_j), want_j, hz,
                                                                         want_hz, " | ".join(lines)))

bpy.ops.mmd_physics.fx_restore()
left = [o.name for o in bpy.data.objects if o.get(kits.TAG)]
world = scene.rigidbody_world
steps = world.substeps_per_frame if world is not None else 0
orig = [o.name for o in bpy.data.objects if chains.ORIG_TYPE in o]
_blender.result("kits restore %s" % os.path.basename(PMX), not left and not orig and steps == steps0,
                "kit objects left %d %s, orig-type marks %d, substeps %d -> %d" % (len(left), left[:3], len(orig),
                                                                                  steps0, steps))
