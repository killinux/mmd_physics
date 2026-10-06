"""「MMD 刚体」方式下,给原来不动的骨链(chains.still_groups:没有刚体,或只有跟骨刚体)临时建一套刚体和关节。
效果烘焙用:每次烘焙前、还原时删掉重建(remove)。

- 每根骨一个胶囊刚体(物理),沿骨,长 = 骨长,半径 = 骨长 × radius;质量从链根到梢减到一半。
- 每根骨的头上一个关节,轴 = 骨的静止朝向(Y 沿骨 = 扭转,X / Z = 摆动),平移锁死,摆动 ±rot、扭转 ±twist_limit。
- 旋转弹簧按「静止时下垂几度」(sag,整条链):关节以下的刚体在 MMD 重力(98)下对关节的力矩和重力刚度
  (rigidfx.size_joint 的思路),再加一份「整条链平伸时力矩的 20%」÷ 这个关节分到的下垂角 —— 垂着的链弹簧很小、
  按重力自然摆,平伸、朝上的链(刘海、兔耳)撑得住。n 节的链每个关节分到 2·sag / (n + 1)(每节都垂 θ 时整条链
  弦的方向垂 θ·(n + 1) / 2),所以平伸的链整条最多垂 sag 左右。PMX 单位;「MMD 同款」再按缩放换算(effects.mmd_like)。
- 链根挂在锚刚体上:挂点骨上新建一个跟骨的小球。不连模型原有的刚体:Blender 退出时按名字顺序释放对象,本插件的
  刚体(0chb_…)要排在关节(J.0chb_…)和 mmd_tools 的不碰撞约束(ncc)前面才不会崩(同 kits.build 的说明)。
- 新建的刚体谁都不碰(建物理以后清掉碰撞层,同套件):不会撞头、撞身体炸开,但也挡不住腿 —— 裙子要防穿腿用骨骼布料。
"""

import math

from mathutils import Matrix, Vector

TAG = "mmd_physics_chainbody"               # 新建的刚体 / 关节上(chains.MADE_TAGS 里也有)
GRAVITY_PMX = 98.0
_Z_TO_Y = Matrix.Rotation(-math.pi / 2, 4, "X")   # mmd_tools 的胶囊沿物体 Z 轴,骨沿 Y 轴
MIN_LEN = 1e-4                              # 比这短的骨不建刚体(子骨挂到上面最近的刚体)
DEFAULTS = dict(mass=0.5, lin_damp=0.8, ang_damp=0.9, rot=30.0, twist_limit=5.0, sag=10.0, radius=0.2)


def _loc_rot(W):
    loc, rot, _s = W.decompose()
    return loc, rot.to_euler("YXZ")


def _frame(arm, b):
    """骨的静止朝向(世界,去掉缩放):Y 沿骨。"""
    return (arm.matrix_world.to_3x3() @ b.matrix_local.to_3x3()).normalized()


def _depths(arm, names):
    """每根骨在自己那条链上的位置(0 = 链根 … 1 = 最深的梢)和那条链有几节:({骨: 位置}, {骨: 节数})。
    names:父在前。"""
    s = set(names)
    level = {}
    for n in names:
        p = arm.data.bones[n].parent
        level[n] = level[p.name] + 1 if p is not None and p.name in s else 0
    deepest = dict(level)
    for n in reversed(names):
        p = arm.data.bones[n].parent
        if p is not None and p.name in s:
            deepest[p.name] = max(deepest[p.name], deepest[n])
    top = {}
    for n in names:
        p = arm.data.bones[n].parent
        top[n] = top[p.name] if p is not None and p.name in s else deepest[n]
    return {n: level[n] / top[n] if top[n] else 0.0 for n in names}, {n: top[n] + 1 for n in names}


def joint_springs(axes, pivot, bodies, sag_deg, scale):
    """一个关节的旋转弹簧,关节三个轴各一个(PMX 单位)。axes:三个轴(世界单位向量);pivot:关节位置(世界);
    bodies:关节以下的刚体 [(质量, 中心世界坐标)];scale:世界 → PMX 单位。
    = 重力刚度 + (静止时的重力力矩 + 0.2 × Σ m·g·|r|) / 下垂角,不小于 0。"""
    th = math.radians(max(sag_deg, 0.5))
    out = []
    for a in axes:
        tau = stiff = moment = 0.0
        for m, c in bodies:
            r = (c - pivot) * scale
            w = Vector((0.0, 0.0, -m * GRAVITY_PMX))
            tau += a.dot(r.cross(w))
            stiff += a.dot(r) * a.dot(w) - r.dot(w)
            moment += m * GRAVITY_PMX * r.length
        out.append(max(stiff + (abs(tau) + 0.2 * moment) / th, 0.0))
    return out


def build(model, arm, groups, v, pmx_scale=12.5, key="chain"):
    """在每组骨(groups:[[骨名, …], …])上建刚体和关节。v:预设参数(DEFAULTS 的键);pmx_scale:世界 → PMX 单位。
    返回 (刚体数, 关节数)。"""
    p = dict(DEFAULTS)
    p.update({k: v[k] for k in DEFAULTS if k in v})
    A = arm.matrix_world
    gw = model.rigidGroupObject().matrix_world.inverted()
    jw = model.jointGroupObject().matrix_world.inverted()
    swing, twist = math.radians(p["rot"]), math.radians(p["twist_limit"])
    nb = nj = 0
    for gi, bones in enumerate(groups):
        names = [b.name for b in arm.data.bones if b.name in set(bones)]
        depth, count = _depths(arm, names)
        made, centre, mass, anchors = {}, {}, {}, {}

        def body(name, loc, rot, size, shape, mode, m, bone):
            o = model.createRigidBody(
                shape_type=shape, location=loc, rotation=rot, size=size, dynamics_type=mode,
                collision_group_number=15, collision_group_mask=[True] * 16, name=name, bone=bone, mass=m,
                friction=0.5, linear_damping=p["lin_damp"], angular_damping=p["ang_damp"], bounce=0.0)
            o[TAG] = key
            return o

        for n in names:
            b = arm.data.bones[n]
            head, tail = A @ b.head_local, A @ b.tail_local
            length = (tail - head).length
            if length < MIN_LEN:
                continue
            W = Matrix.Translation((head + tail) / 2) @ _frame(arm, b).to_4x4() @ _Z_TO_Y
            loc, rot = _loc_rot(gw @ W)
            m = p["mass"] * (1.0 - 0.5 * depth[n])
            made[n] = body("0chb_%d.%s" % (gi, n), loc, rot, (max(length * p["radius"], 1e-3), length, 0.0), 2, 1, m, n)
            centre[n], mass[n] = (head + tail) / 2, m
            nb += 1
        for n in names:
            if n not in made:
                continue
            b = arm.data.bones[n]
            up = b.parent
            while up is not None and up.name in set(names) and up.name not in made:
                up = up.parent                          # 太短没建刚体的父骨:挂到再上面
            pivot = A @ b.head_local
            if up is not None and up.name in made:
                a_obj = made[up.name]
            elif up is not None:
                if up.name not in anchors:              # 挂点骨上的锚:跟骨的小球,放在链根的头上
                    loc, rot = _loc_rot(gw @ Matrix.Translation(pivot))
                    anchors[up.name] = body("0chb_%d.%s.锚" % (gi, up.name), loc, rot,
                                            (max((A @ b.tail_local - pivot).length * 0.1, 1e-3), 0.0, 0.0), 0, 0, 1.0,
                                            up.name)
                    nb += 1
                a_obj = anchors[up.name]
            else:                                       # 没有父骨可挂:这根骨的刚体跟骨,不晃
                made[n].mmd_rigid.type = "0"
                continue
            below = {n} | {c.name for c in b.children_recursive if c.name in made}
            R = _frame(arm, b)
            k = joint_springs([R.col[0], R.col[1], R.col[2]], pivot, [(mass[x], centre[x]) for x in below],
                              2.0 * p["sag"] / (count[n] + 1), pmx_scale)
            loc, rot = _loc_rot(jw @ (Matrix.Translation(pivot) @ R.to_4x4()))
            o = model.createJoint(
                location=loc, rotation=rot, rigid_a=a_obj, rigid_b=made[n],
                maximum_location=Vector(), minimum_location=Vector(),
                maximum_rotation=Vector((swing, twist, swing)), minimum_rotation=Vector((-swing, -twist, -swing)),
                spring_linear=Vector(), spring_angular=Vector(k), name="0chb_%d.%s" % (gi, n))
            o[TAG] = key
            nj += 1
    return nb, nj


def no_collisions(model):
    """建物理以后:新建的刚体谁都不碰(不在任何碰撞层)。返回个数。"""
    n = 0
    for o in model.rigidBodies():
        if o.get(TAG) and o.rigid_body is not None:
            o.rigid_body.collision_collections = [False] * 20
            n += 1
    return n


def remove(model):
    """删掉新建的刚体和关节:先删刚体,再删关节(同 kits.remove)。返回个数。"""
    import bpy
    objs = [o for o in model.rigidBodies() if o.get(TAG)] + [o for o in model.joints() if o.get(TAG)]
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    return len(objs)
