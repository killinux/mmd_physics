"""「MMD 刚体」方式的预设怎么写进模型(效果烘焙每次先还原原值,所以都是在原值上改)。

- 胸部 kind = "fixed":固定值(乳奶模板、柔软、Q弹、PmxTailor……):摆动刚体的质量 / 阻尼,挂它的关节 ±限位
  (扭转可以单给 twist_limit)、旋转弹簧,平移锁死。
- 胸部 kind = "kit":整套换上(kits.py,effects.apply 里处理,不经过这里)。
- 胸部 kind = "sag":按 MMD 重力(98 单位/秒²)和「静止时下垂几度」定旋转弹簧(ripper_tpose 仓库
  scripts/vindictus/bust_physics.py 的算法):弹簧 = 重力力矩 / 下垂角 + 重力刚度;力矩算上挂在胸上的所有摆动刚体
  (吊坠、衣片),它们的质量和弹簧可以先按 hanging_scale 减轻。上下 / 左右 / 扭转限位分开给,阻尼写在摆动刚体上。
- 头发 / 裙子 / 衣物 kind = "scale":阻尼 ×damp_scale、再不低于 damp_min;关节旋转限位 ×limit_scale。
- kind = "model":不改。

关节轴按 PMX(pitch = 左右轴,上下摆;yaw = 竖轴;twist = 前后轴),Blender 里是 x / z / y。
"""

import math

from mathutils import Vector

from . import chains

GRAVITY_PMX = 98.0                           # MMD 的重力,PMX 单位/秒²(three.js MMDPhysics / saba / MMDAgent-EX)


def _mode(o):
    return int(chains.body_type(o))


# -- 关节 -------------------------------------------------------------------------------------------------
def hanging_joints(joints, bones):
    """把挂在 bones 上的摆动刚体吊在跟骨刚体上的关节:[(joint, 摆动刚体)]。"""
    out = []
    for j in joints:
        c = j.rigid_body_constraint
        if c is None or c.object1 is None or c.object2 is None:
            continue
        for src, dst in ((c.object1, c.object2), (c.object2, c.object1)):
            if _mode(src) == 0 and _mode(dst) in (1, 2) and dst.mmd_rigid.bone in bones:
                out.append((j, dst))
                break
    return out


def joints_on(joints, bodies):
    """吊着这些刚体的关节(PMX 关节 src → dest,mmd_tools 的 object2 = dest)。"""
    s = set(bodies)
    return [j for j in joints if j.rigid_body_constraint is not None and j.rigid_body_constraint.object2 in s]


def hung_on(joints, ball):
    """吊在 ball 上的摆动刚体(经关节,任意深度)和那些关节。"""
    by_src = {}
    for j in joints:
        c = j.rigid_body_constraint
        if c is None or c.object1 is None or c.object2 is None:
            continue
        by_src.setdefault(c.object1, []).append((j, c.object2))
        by_src.setdefault(c.object2, []).append((j, c.object1))
    found, links, stack, seen = [], [], [ball], {ball}
    while stack:
        current = stack.pop()
        for j, other in by_src.get(current, []):
            if other in seen or _mode(other) == 0:
                continue
            seen.add(other)
            found.append(other)
            links.append(j)
            stack.append(other)
    return found, links


def _set_ang_limits(c, pitch, twist, yaw):
    """Blender 轴 x = pitch、y = twist、z = yaw,±对称。"""
    for axis, v in (("x", pitch), ("y", twist), ("z", yaw)):
        setattr(c, "limit_ang_%s_lower" % axis, -v)
        setattr(c, "limit_ang_%s_upper" % axis, v)


def _lock_lin(c):
    for axis in "xyz":
        setattr(c, "limit_lin_%s_lower" % axis, 0.0)
        setattr(c, "limit_lin_%s_upper" % axis, 0.0)


# -- 按下垂角定弹簧(bust_physics.py) ---------------------------------------------------------------------
def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def own_inertia(shape, size, mass):
    """刚体绕自身中心的转动惯量(PMX 形状 0 球 / 1 箱 / 2 胶囊,PMX 尺寸)。"""
    if shape == 0:
        return (0.4 * mass * size[0] ** 2,) * 3
    if shape == 1:
        x, y, z = (2 * s for s in size[:3])
        return (mass * (y * y + z * z) / 12, mass * (x * x + z * z) / 12, mass * (x * x + y * y) / 12)
    r, h = size[0], size[1]
    return (mass * (3 * r * r + h * h) / 12, 0.4 * mass * r * r, mass * (3 * r * r + h * h) / 12)


def size_joint(bodies, down, sag, twist_sag, yaw_scale=1.0, gravity=GRAVITY_PMX):
    """一个胸部关节的旋转弹簧(pitch, yaw, twist),PMX 单位。bodies:(质量, 力臂, 自身惯量),力臂 = 刚体中心 - 关节,
    关节轴、PMX 单位;down:关节轴下的重力方向。弹簧 = |力矩| / 下垂角 + 重力刚度,不小于 |力矩| / 下垂角 的一半。"""
    torque, stiff = [0.0] * 3, [0.0] * 3
    for mass, arm, _own in bodies:
        w = [mass * gravity * c for c in down]
        t = _cross(arm, w)
        aw = _dot(arm, w)
        for k in range(3):
            torque[k] += t[k]
            stiff[k] += arm[k] * w[k] - aw

    def spring(k, sag_deg, at_least=0.0):
        plain = abs(torque[k]) / math.radians(max(sag_deg, 0.1))
        return max(plain + stiff[k], 0.5 * plain, at_least, 1.0)

    pitch = spring(0, sag)
    yaw = spring(1, sag, pitch * yaw_scale)
    twist = spring(2, twist_sag, pitch)
    return pitch, yaw, twist


def joint_frame(rx, ry, rz):
    """PMX 关节(PMX 里写的旋转)的三个轴,PMX 坐标;旋转 0 时是单位阵。"""
    def rot(axis, angle):
        c, s = math.cos(angle), math.sin(angle)
        return {"x": [[1, 0, 0], [0, c, -s], [0, s, c]], "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
                "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]

    def mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    swap = [[1, 0, 0], [0, 0, 1], [0, 1, 0]]
    return mul(mul(swap, mul(mul(rot("z", -ry), rot("x", -rx)), rot("y", -rz))), swap)


def to_frame(frame, v):
    return tuple(sum(frame[r][c] * v[r] for r in range(3)) for c in range(3))


def _pmx_point(obj, scale):
    return Vector(obj.matrix_world.translation).xzy * scale


def _pmx_shape_size(obj, scale):
    size = Vector(obj.mmd_rigid.size) * (sum(obj.matrix_world.to_scale()) / 3) * scale
    shape = {"SPHERE": 0, "BOX": 1, "CAPSULE": 2}[obj.mmd_rigid.shape]
    return shape, (size.xzy if shape == 1 else size)


# -- 写进模型 ---------------------------------------------------------------------------------------------
def apply_bust(model, bust_bones, v, scale=12.5):
    """胸部的「MMD 刚体」预设。bust_bones:胸链的骨;v:预设参数;scale:Blender → PMX。返回说明(每个关节一行)。"""
    kind = v.get("kind", "model")
    if kind == "model":
        return []
    joints = list(model.joints())
    pairs = hanging_joints(joints, set(bust_bones))
    lines = []
    if kind == "fixed":
        r = math.radians(v["rot"])
        tw = v.get("twist_limit", v["rot"])
        for j, ball in pairs:
            rb = ball.rigid_body
            rb.mass = v["mass"]
            rb.linear_damping, rb.angular_damping = v["lin_damp"], v["ang_damp"]
            c = j.rigid_body_constraint
            _set_ang_limits(c, r, math.radians(tw), r)
            _lock_lin(c)
            j.mmd_joint.spring_angular = (v["spring_rot"],) * 3
            j.mmd_joint.spring_linear = (0.0, 0.0, 0.0)
            lines.append("%s: ±%g°(扭转 ±%g°), 弹簧 %g, 阻尼 %g/%g" % (j.name, v["rot"], tw, v["spring_rot"],
                                                                   v["lin_damp"], v["ang_damp"]))
        return lines
    if kind != "sag":
        raise ValueError(kind)
    scaled = set()
    for j, ball in pairs:
        extra, links = hung_on(joints, ball)
        hs = v.get("hanging_scale", 1.0)
        if hs != 1.0:
            for o in extra:
                if o not in scaled:
                    o.rigid_body.mass *= hs
                    scaled.add(o)
            for lj in links:
                if lj not in scaled:
                    mj = lj.mmd_joint
                    mj.spring_linear = tuple(x * hs for x in mj.spring_linear)
                    mj.spring_angular = tuple(x * hs for x in mj.spring_angular)
                    scaled.add(lj)
        rotation = Vector(j.matrix_world.to_euler("YXZ")).xzy * -1
        frame = joint_frame(*rotation)
        down = to_frame(frame, (0.0, -1.0, 0.0))
        origin = _pmx_point(j, scale)
        bodies = []
        for o in [ball] + extra:
            shape, size = _pmx_shape_size(o, scale)
            arm = to_frame(frame, tuple(_pmx_point(o, scale) - origin))
            bodies.append((o.rigid_body.mass, arm, own_inertia(shape, size, o.rigid_body.mass)))
        pitch, yaw, twist = size_joint(bodies, down, v["sag"], v["twist_sag"], v.get("yaw_scale", 1.0))
        j.mmd_joint.spring_angular = (pitch, twist, yaw)          # Blender 轴序 x, y, z
        c = j.rigid_body_constraint
        _set_ang_limits(c, math.radians(v["pitch_limit"]), math.radians(v["twist_limit"]),
                        math.radians(v["yaw_limit"]))
        rb = ball.rigid_body
        rb.linear_damping, rb.angular_damping = v["lin_damp"], v["ang_damp"]
        lines.append("%s: 弹簧 %.0f/%.0f/%.0f(上下/左右/扭转),限位 ±%g/%g/%g°,阻尼 %g,吊着 %d 个刚体" % (
            j.name, pitch, yaw, twist, v["pitch_limit"], v["yaw_limit"], v["twist_limit"], v["lin_damp"], len(extra)))
    return lines


def apply_chains(model, bones, v):
    """头发 / 裙子 / 衣物的「MMD 刚体」预设:按比例改这些骨上摆动刚体的阻尼和挂它们的关节的旋转限位。"""
    kind = v.get("kind", "model")
    if kind == "model":
        return 0
    if kind != "scale":
        raise ValueError(kind)
    bones = set(bones)
    bodies = [o for o in model.rigidBodies() if o.mmd_rigid.bone in bones and _mode(o) in (1, 2) and o.rigid_body]
    for o in bodies:
        rb = o.rigid_body
        for attr in ("linear_damping", "angular_damping"):
            d = getattr(rb, attr) * v.get("damp_scale", 1.0)
            setattr(rb, attr, min(1.0, max(v.get("damp_min", 0.0), d)))
    ls = v.get("limit_scale", 1.0)
    for j in joints_on(list(model.joints()), bodies):
        c = j.rigid_body_constraint
        for axis in "xyz":
            for end in ("lower", "upper"):
                attr = "limit_ang_%s_%s" % (axis, end)
                setattr(c, attr, max(-math.pi, min(math.pi, getattr(c, attr) * ls)))
    return len(bodies)
