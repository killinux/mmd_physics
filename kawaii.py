"""弹簧骨骼物理(KawaiiPhysics 同款):给导入 Blender 的 PMX 渲视频用。胸部、头发、裙子都能用。

算法照搬 KawaiiPhysics v1.13(pafuhana1213/KawaiiPhysics,MIT;Vindictus 预 alpha 包用的就是这一版的参数集),
在 Blender 里按 60 Hz 子步逐帧模拟,结果烘成骨骼的关键帧:

- 一条链 = 起点骨(位置随动画走)+ 它下面的骨;每根骨是一个点,按顺序(父在前)做:
  惯性(上一步的速度 ×(1-阻尼))→ 跟随角色整体移动(×(1-世界阻尼))→ 重力 → 按刚度拉回动画姿势
  → 碰撞(胶囊)→ 限角(相对动画姿势)→ 恢复骨长;
- 写回:只有一个子点的父骨转向子点,其余骨平移到模拟出的位置(和 KawaiiPhysics 一样);
- 末端补点(KawaiiPhysics 的 DummyBone):链末端的骨在骨尾方向上加一个虚点,这根骨也跟着转。
  只有一根骨的胸(乳奶模板)靠它才能动;头发、裙子默认补。

Vindictus 的参数(从游戏的动画蓝图字节码读出,ripper_tpose 仓库 reports/胸部控制方式全面调研_插件准备.md 第三节):
胸 刚度 0.05、阻尼 0.5、世界阻尼 0.8 / 0.8、限角 10.8°、碰撞半径 5 cm、不加重力、60 Hz;
碰撞体 DA_Breast:上臂、前臂前方 13 cm 各一根 22 cm × 半径 4 cm 的胶囊,手前方 6 cm 一根 10 cm × 半径 5 cm,
胶囊轴和骨头、和"前方"都垂直。游戏里的厘米按两肩距离换算到模型上(Fiona 0.08 导入时 1 cm = 0.01 m)。

和 MMD 刚体的区别:不加重力(胸停在模型本来的形状)、阻尼按步作用在相对动画的速度上、能抵消角色整体移动。

脚本接口(保持不变):roots_of(arm)、breast_bodies(arm)、bodies_follow_bones(arm)、clear(arm)、
bake(scene, arm, settings=None, frame_start=None, frame_end=None, capsules=True, carrier=None, log=None)。
多条链各用各的参数:simulate(scene, arm, specs, ...) + write_keys(arm, frames, bases)(效果面板用)。
"""

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

TAG = "mmd_physics_kawaii"                 # 烘焙出来的 F 曲线所在动作的自定义属性:烘了哪些骨
FIONA_SHOULDERS_M = 0.2698                 # Fiona 两肩关节距离(米,0.08 导入):游戏厘米 → 模型米的基准

VINDICTUS = dict(
    stiffness=0.05, damping=0.5, world_damping_location=0.8, world_damping_rotation=0.8,
    limit_angle=10.8, radius_cm=5.0, gravity_cm=(0.0, 0.0, 0.0), target_fps=60,
)

# DA_Breast 的 6 个胶囊。每个:(骨, 定方向的子关节(候选名), 半径 cm, 长 cm, 偏移 cm,
#   游戏参考姿势下的 骨方向 / 偏移方向(骨的局部 +Y)/ 胶囊轴(骨的局部 Z)— Blender 方向,模型面朝 −Y)。
# 方向取自游戏骨架(UE Viewer 导出的 PSK,Y 轴已按引擎翻回);挂到 PMX 上时先把骨方向对齐(PMX 拉直过前臂)。
VINDICTUS_CAPSULES = (
    (("左腕", "upperarm_l"), ("左ひじ", "lowerarm_l"), 4.0, 22.0, 13.0,
     (0.6032, -0.0274, -0.7971), (0.0292, -0.998, 0.0564), (0.7971, 0.0573, 0.6012)),
    (("右腕", "upperarm_r"), ("右ひじ", "lowerarm_r"), 4.0, 22.0, 13.0,
     (-0.6032, -0.0274, -0.7971), (-0.0292, -0.998, 0.0564), (0.7971, -0.0573, -0.6012)),
    (("左ひじ", "lowerarm_l"), ("左手首", "hand_l"), 4.0, 22.0, 13.0,
     (0.501, -0.6184, -0.6054), (-0.3371, -0.7838, 0.5216), (0.7971, 0.0573, 0.6012)),
    (("右ひじ", "lowerarm_r"), ("右手首", "hand_r"), 4.0, 22.0, 13.0,
     (-0.501, -0.6184, -0.6054), (0.3371, -0.7838, 0.5216), (0.7971, -0.0573, -0.6012)),
    (("左手首", "hand_l"), ("middle_metacarpal_l", "左中指１", "左中指1"), 5.0, 10.0, 6.0,
     (0.4547, -0.7653, -0.4555), (0.7479, -0.2894, 0.5974), (0.5518, 0.7713, -0.3172)),
    (("右手首", "hand_r"), ("middle_metacarpal_r", "右中指１", "右中指1"), 5.0, 10.0, 6.0,
     (-0.4547, -0.7653, -0.4555), (-0.7479, -0.2894, 0.5974), (0.5518, -0.7713, 0.3172)),
)

BREAST_ROOTS = ("breast_physics_01_l", "breast_physics_01_r")


# -- 骨 ------------------------------------------------------------------------------------------------
def bone_by_jp(arm, name):
    """PMX 日文名 → pose bone(mmd_tools 导入后 Blender 名常是 腕.L 之类)。"""
    pb = arm.pose.bones.get(name)
    if pb is not None:
        return pb
    for pb in arm.pose.bones:
        if getattr(pb, "mmd_bone", None) is not None and pb.mmd_bone.name_j == name:
            return pb
    return None


def cm_to_m(arm):
    """游戏里的 1 cm 在这个模型上是多少米:按两肩关节(左腕 / 右腕)的距离和 Fiona 比。
    Fiona 的 PMX 按 0.08 导入时正好 1 cm = 0.01 m(两肩 26.98 cm)。"""
    a, b = bone_by_jp(arm, "左腕"), bone_by_jp(arm, "右腕")
    if a is None or b is None:
        return 0.01
    width = (a.bone.head_local - b.bone.head_local).length
    return 0.01 * width / FIONA_SHOULDERS_M if width > 0 else 0.01


class Chain:
    """一条链:起点骨 + 子孙骨,先序(父在前,子按骨骼顺序),和 KawaiiPhysics 的 ModifyBones 一样。

    members:只取这些骨(None = 全部子孙);tip:末端补点的长度,按那根骨自己的长度算(0 = 不补,1 = 骨尾)。"""

    def __init__(self, arm, root_name, members=None, tip=0.0):
        bones = arm.data.bones
        order = {b.name: i for i, b in enumerate(bones)}
        self.names, self.parent, self.dummy = [], [], []

        def add(bone, parent_index):
            index = len(self.names)
            self.names.append(bone.name)
            self.parent.append(parent_index)
            self.dummy.append(False)
            kids = [c for c in sorted(bone.children, key=lambda c: order[c.name])
                    if members is None or c.name in members]
            for child in kids:
                add(child, index)
            if not kids and tip > 0.0:
                self.names.append(bone.name)          # 虚点:名字记它挂的那根骨
                self.parent.append(index)
                self.dummy.append(True)

        add(bones[root_name], -1)
        self.tip = tip
        n = len(self.names)
        self.children = [0] * n
        for p in self.parent:
            if p >= 0:
                self.children[p] += 1
        self.length = [bones[name].length for name in self.names]
        self.loc = [Vector() for _ in range(n)]
        self.prev = [Vector() for _ in range(n)]
        self.pose_loc = [Vector() for _ in range(n)]
        self.pose_rot = [Quaternion() for _ in range(n)]
        self.started = False

    def bones(self):
        """链里真实的骨(不含虚点)。"""
        return [n for n, d in zip(self.names, self.dummy) if not d]

    def read_pose(self, arm, space_inv=None):
        """动画姿势(骨架空间,或乘上 space_inv 换到模拟空间)。"""
        for i, name in enumerate(self.names):
            m = arm.pose.bones[name].matrix
            if space_inv is not None:
                m = space_inv @ m
            if self.dummy[i]:
                self.pose_loc[i] = m @ Vector((0.0, self.length[i] * self.tip, 0.0))
            else:
                self.pose_loc[i] = m.translation.copy()
            self.pose_rot[i] = m.to_quaternion()
        if not self.started:
            for i in range(len(self.names)):
                self.loc[i] = self.pose_loc[i].copy()
                self.prev[i] = self.pose_loc[i].copy()
            self.started = True


class Capsule:
    """骨上的胶囊(KawaiiPhysics FCapsuleLimit):中心 = 关节 + 偏移方向 × offset,轴 = 胶囊轴;两个方向都存成
    PMX 骨的局部向量,随骨转动。游戏参考姿势和 PMX 静止姿势的骨方向不同时,先按最小旋转对齐骨方向。"""

    def __init__(self, bone, child, radius, length, offset, along_game, offset_dir_game, axis_game):
        self.bone = bone
        self.radius, self.length, self.offset = radius, length, offset
        along = (child.bone.head_local - bone.bone.head_local).normalized()
        fix = Vector(along_game).normalized().rotation_difference(along)
        rest_inv = bone.bone.matrix_local.to_3x3().inverted()
        self.dir_local = rest_inv @ (fix @ Vector(offset_dir_game)).normalized()
        self.axis_local = rest_inv @ (fix @ Vector(axis_game)).normalized()

    def segment(self):
        m = self.bone.matrix
        rot = m.to_3x3()
        centre = m.translation + (rot @ self.dir_local).normalized() * self.offset
        half = (rot @ self.axis_local).normalized() * (self.length * 0.5)
        return centre + half, centre - half


class ObjectCapsule:
    """场景里的胶囊物体(骨骼布料的腿部碰撞体:沿局部 Y 从 -len/2 到 +len/2),换到骨架空间。"""

    def __init__(self, arm, obj, moving=False):
        """moving:这个碰撞体在链底下动(腿),rest_allow 不放过第一帧陷进去的部分(除非参数 allow_legs)。"""
        self.arm, self.obj, self.moving = arm, obj, moving
        s = (obj.matrix_world.col[0].xyz.length + obj.matrix_world.col[2].xyz.length) / 2
        self.radius = max(float(obj.get("bc_r0", 0.05)), float(obj.get("bc_r1", obj.get("bc_r0", 0.05)))) * s

    def segment(self):
        inv = self.arm.matrix_world.inverted()
        half = float(self.obj.get("bc_len", 0.0)) / 2
        m = self.obj.matrix_world
        return inv @ (m @ Vector((0.0, -half, 0.0))), inv @ (m @ Vector((0.0, half, 0.0)))


def _first_bone(arm, names):
    for n in names:
        pb = bone_by_jp(arm, n)
        if pb is not None:
            return pb
    return None


def vindictus_capsules(arm, scale_m):
    """DA_Breast 的 6 个胶囊挂到 PMX 的手臂骨上(找不到骨的跳过)。"""
    out = []
    for names, child_names, r, length, off, along, offset_dir, axis in VINDICTUS_CAPSULES:
        bone, child = _first_bone(arm, names), _first_bone(arm, child_names)
        if bone is None or child is None:
            continue
        out.append(Capsule(bone, child, r * scale_m, length * scale_m, off * scale_m, along, offset_dir, axis))
    return out


# -- 模拟(KawaiiPhysics v1.13 SimulateModifyBones) ----------------------------------------------------
def _closest_on_segment(p, a, b):
    ab = b - a
    t = 0.0 if ab.length_squared == 0 else max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
    return a + ab * t


def step(chain, s, dt, dt_old, radius, capsules, gravity, move=None, move_rot=None, allow=None):
    exponent = s["target_fps"] * dt
    pull = 1.0 - (1.0 - s["stiffness"]) ** exponent
    keep = 1.0 - s["damping"]
    follow_loc = 1.0 - s["world_damping_location"]
    follow_rot = 1.0 - s["world_damping_rotation"]
    limit = s["limit_angle"]
    loc, prev = chain.loc, chain.prev
    for i, p in enumerate(chain.parent):
        if p < 0:
            prev[i] = loc[i].copy()
            loc[i] = chain.pose_loc[i].copy()
            continue
        velocity = (loc[i] - prev[i]) / dt_old
        prev[i] = loc[i].copy()
        loc[i] = loc[i] + velocity * keep * dt
        if move is not None:
            loc[i] += move * follow_loc
        if move_rot is not None:
            loc[i] += (move_rot @ prev[i] - prev[i]) * follow_rot
        if gravity is not None:
            loc[i] += gravity * (0.5 * dt * dt)
        base = loc[p] + (chain.pose_loc[i] - chain.pose_loc[p])
        loc[i] += (base - loc[i]) * pull
        for ci, (a, b, r) in enumerate(capsules):
            reach = radius + r - (allow[i][ci] if allow is not None else 0.0)
            closest = _closest_on_segment(loc[i], a, b)
            d = loc[i] - closest
            if reach > 0.0 and d.length_squared < reach * reach:
                loc[i] = closest + (d.normalized() if d.length_squared > 0 else Vector((0, -1, 0))) * reach
        if limit > 0.0:
            bone_dir = (loc[i] - loc[p])
            pose_dir = (chain.pose_loc[i] - chain.pose_loc[p]).normalized()
            if bone_dir.length_squared > 0 and pose_dir.length_squared > 0:
                length = bone_dir.length
                bone_dir.normalize()
                axis = pose_dir.cross(bone_dir)
                angle = math.degrees(math.atan2(axis.length, pose_dir.dot(bone_dir)))
                if angle - limit > 0.0 and axis.length_squared > 0:
                    bone_dir = Quaternion(axis.normalized(), -math.radians(angle - limit)) @ bone_dir
                    loc[i] = bone_dir * length + loc[p]
        rest_len = (chain.pose_loc[i] - chain.pose_loc[p]).length
        d = loc[i] - loc[p]
        if d.length_squared > 0:
            loc[i] = loc[p] + d.normalized() * rest_len


def result_matrices(chain):
    """KawaiiPhysics ApplySimulateResult:骨架空间的矩阵(位置 = 模拟点,旋转 = 动画 / 转向唯一子点)。"""
    rot = [q.copy() for q in chain.pose_rot]
    for i, p in enumerate(chain.parent):
        if p < 0 or chain.children[p] > 1:
            continue
        pose_vec = chain.pose_loc[i] - chain.pose_loc[p]
        sim_vec = chain.loc[i] - chain.loc[p]
        if pose_vec.length_squared == 0 or sim_vec.length_squared == 0:
            continue
        rot[p] = pose_vec.rotation_difference(sim_vec) @ chain.pose_rot[p]
    return [Matrix.Translation(chain.loc[i]) @ rot[i].to_matrix().to_4x4() for i in range(len(chain.names))]


# -- 链的识别 -----------------------------------------------------------------------------------------
def _bust(arm):
    from . import chains
    return chains.bust_chains(arm)


def roots_of(arm):
    """两侧胸链的起点骨。Vindictus(UE 骨架)是 breast_physics_01_l / _r;别的骨架按刚体和名字识别(chains.py)。"""
    ue = [r for r in BREAST_ROOTS if r in arm.data.bones]
    if ue:
        return ue
    return [c.root for c in _bust(arm)]


def breast_chains(arm):
    """[Chain],两侧胸。UE 骨架:起点骨 + 全部子孙(和游戏一样);别的骨架:chains.py 的胸链(单根骨的末端补点)。"""
    ue = [r for r in BREAST_ROOTS if r in arm.data.bones]
    if ue:
        return [Chain(arm, r) for r in ue]
    return [Chain(arm, c.root, members=set(c.bones), tip=1.0 if c.tip else 0.0) for c in _bust(arm)]


def _mmd_root(obj):
    while obj is not None and getattr(obj, "mmd_type", "") != "ROOT":
        obj = obj.parent
    return obj


def breast_bodies(arm):
    """这个模型挂在胸链上的刚体(mmd_tools)。场景里有别的同骨架模型时,只认和骨架同一个 MMD 根的。"""
    names = set()
    ue = [r for r in BREAST_ROOTS if r in arm.data.bones]
    if ue:
        for r in ue:
            b = arm.data.bones[r]
            names.update([r] + [c.name for c in b.children_recursive])
    else:
        for c in _bust(arm):
            names.update(c.bones)
    jp = {arm.pose.bones[n].mmd_bone.name_j for n in names if getattr(arm.pose.bones[n], "mmd_bone", None)}
    root = _mmd_root(arm)
    out = []
    for o in bpy.data.objects:
        if getattr(o, "mmd_type", "") == "RIGID_BODY" and (o.mmd_rigid.bone in names or o.mmd_rigid.bone in jp) \
                and (root is None or _mmd_root(o) is root):
            out.append(o)
    return out


def bodies_follow_bones(arm):
    """胸部刚体改成「跟骨」,让关键帧来驱动胸骨(物理要在这之后 Build)。返回改动前的类型。
    改之前的类型也记在刚体上(chains.ORIG_TYPE),之后还认得哪些是胸部的摆动刚体。"""
    from . import chains
    before = {}
    for o in breast_bodies(arm):
        before[o.name] = o.mmd_rigid.type
        if chains.ORIG_TYPE not in o:
            o[chains.ORIG_TYPE] = o.mmd_rigid.type
        o.mmd_rigid.type = '0'
    return before


# -- 烘焙 --------------------------------------------------------------------------------------------
def clear(arm):
    """删掉本模块烘出来的 F 曲线(bake() 写的)。"""
    action = arm.animation_data.action if arm.animation_data else None
    if action is None:
        return 0
    names = set(action.get(TAG, "").split("|")) - {""}
    removed = 0
    for fc in list(action.fcurves):
        if fc.data_path.startswith('pose.bones["'):
            bone = fc.data_path.split('"')[1]
            if bone in names:
                action.fcurves.remove(fc)
                removed += 1
    if TAG in action:
        del action[TAG]
    for n in names:
        pb = arm.pose.bones.get(n)
        if pb is not None:
            pb.matrix_basis = Matrix.Identity(4)
    return removed


def write_keys(arm, frames, bases, tag=True):
    """bases[bone] = [(loc, quat), ...] 按 frames;直接写 F 曲线(比 keyframe_insert 快得多),覆盖这些骨原有的曲线。"""
    if arm.animation_data is None:
        arm.animation_data_create()
    action = arm.animation_data.action
    if action is None:
        action = arm.animation_data.action = bpy.data.actions.new(arm.name + "_kawaii")
    n = len(frames)
    for bone, values in bases.items():
        arm.pose.bones[bone].rotation_mode = 'QUATERNION'
        for path, size, getter in (("location", 3, lambda v, k: v[0][k]),
                                   ("rotation_quaternion", 4, lambda v, k: v[1][k])):
            dp = 'pose.bones["%s"].%s' % (bone, path)
            for k in range(size):
                fc = action.fcurves.find(dp, index=k)
                if fc is not None:
                    action.fcurves.remove(fc)
                fc = action.fcurves.new(dp, index=k, action_group=bone)
                fc.keyframe_points.add(n)
                co = []
                for f, v in zip(frames, values):
                    co += [float(f), getter(v, k)]
                fc.keyframe_points.foreach_set("co", co)
                fc.keyframe_points.foreach_set("interpolation", [1] * n)    # LINEAR
                fc.update()
    if tag:
        action[TAG] = "|".join(bases)


_write_keys = write_keys                   # 旧名字


TELEPORT_CM = 300.0                        # KawaiiPhysics v1.13 默认:一步移动超过 300 cm / 转超过 10° 当瞬移,不跟随
TELEPORT_DEG = 10.0


def spec(chain, settings=None, carrier=None, capsules=(), rest_allow=False):
    """simulate() 的一条:链 + 参数(VINDICTUS 的键)+ 当作角色本体的骨(日文名或 Blender 名,None = 骨架对象)
    + 碰撞胶囊(有 .segment() 和 .radius 的对象,骨架空间)。
    rest_allow:第一帧时点已经陷在胶囊里多深,之后就允许多深(裙根本来就在胯部胶囊里,不放过会被推得翻起来);
    bake() 不用它(和以前一样)。"""
    s = dict(VINDICTUS)
    s.update(settings or {})
    return {"chain": chain, "settings": s, "carrier": carrier, "capsules": list(capsules), "rest_allow": rest_allow}


def simulate(scene, arm, specs, frame_start=None, frame_end=None, log=None):
    """从 frame_start 到 frame_end 逐帧(子步)模拟 specs 里的每条链,返回 (frames, bases):bases[骨] = [(loc, quat)]。

    所有链在同一个帧循环里算(读姿势只要一次 frame_set)。carrier:当作"角色本体"的骨,它的移动和转动就是游戏里的
    角色整体移动,按世界阻尼只传一部分给链(Vindictus 0.8 = 只传 20%);None = 骨架对象本身(PMX 跳舞时骨架对象
    不动,全身的移动都算作动画,全部传给链)。
    要求:链上的骨不被物理带动(刚体先改成跟骨),模拟期间只读骨架姿势。"""
    if not specs:
        return [], {}
    scale_m = cm_to_m(arm)
    for sp in specs:
        s = sp["settings"]
        name = sp["carrier"]
        sp["_carrier"] = bone_by_jp(arm, name) if name else None
        if name and sp["_carrier"] is None:
            raise RuntimeError("没找到当作角色本体的骨:%s" % name)
        sp["_radius"] = s["radius_cm"] * scale_m
        g = Vector(s["gravity_cm"]) * scale_m
        sp["_gravity"] = None if g.length_squared == 0 else g
        sp["_dt_old"] = 1.0 / s["target_fps"]
        sp["_prev"] = None
        sp["_space"] = Matrix.Identity(4)
        sp["_allow"] = None
    fps = scene.render.fps / scene.render.fps_base
    sub = max(1, int(round(max(sp["settings"]["target_fps"] for sp in specs) / fps)))
    dt = 1.0 / (fps * sub)
    f0 = scene.frame_start if frame_start is None else frame_start
    f1 = scene.frame_end if frame_end is None else frame_end
    frames = list(range(f0, f1 + 1))
    bases = {}
    rest = {}
    parent_of = {}
    for sp in specs:
        for n in sp["chain"].bones():
            bases[n] = []
            rest[n] = arm.data.bones[n].matrix_local
            parent_of[n] = arm.data.bones[n].parent
    teleport_m = TELEPORT_CM * scale_m
    for f in frames:
        for k in range(sub):
            frac = (k + 1) / sub - 1.0                      # 子步落在 (f-1, f]
            if frac < -1e-6:
                scene.frame_set(f - 1, subframe=1.0 + frac)
            else:
                scene.frame_set(f)
            spaces = {}
            for sp in specs:
                carrier_pb = sp["_carrier"]
                key = carrier_pb.name if carrier_pb is not None else None
                if key not in spaces:
                    spaces[key] = carrier_pb.matrix.copy() if carrier_pb is not None else Matrix.Identity(4)
                space = spaces[key]
                space_inv = space.inverted()
                move = move_rot = None
                prev_space = sp["_prev"]
                if prev_space is not None and carrier_pb is not None:
                    # KawaiiPhysics UpdateSkelCompMove:上一步本体位置 / 朝向换到这一步的本体空间
                    move = space_inv @ prev_space.translation
                    if move.length > teleport_m:
                        move = Vector()
                    move_rot = space_inv.to_quaternion() @ prev_space.to_quaternion()
                    if math.degrees(move_rot.angle) > TELEPORT_DEG:
                        move_rot = Quaternion()
                sp["_prev"] = space
                sp["_space"] = space
                segs = [(space_inv @ a, space_inv @ b, c.radius) for c in sp["capsules"] for a, b in [c.segment()]]
                chain = sp["chain"]
                chain.read_pose(arm, space_inv if carrier_pb is not None else None)
                if f == f0 and k == 0:
                    if sp.get("rest_allow") and segs:
                        # 腿这种在链底下动的胶囊不放过:骨贴着腿走的外套,放过了腿就整个穿出来
                        free = [not getattr(c, "moving", False) or sp["settings"].get("allow_legs", False)
                                for c in sp["capsules"]]
                        sp["_allow"] = [[max(0.0, sp["_radius"] + r - (p - _closest_on_segment(p, a, b)).length)
                                         if ok else 0.0 for (a, b, r), ok in zip(segs, free)]
                                        for p in chain.pose_loc]
                    continue
                step(chain, sp["settings"], dt, sp["_dt_old"], sp["_radius"], segs, sp["_gravity"], move, move_rot,
                     sp["_allow"])
                sp["_dt_old"] = dt
        # 这一帧的结果 → 每根骨的 matrix_basis(父在前,父用模拟后的矩阵)
        for sp in specs:
            chain = sp["chain"]
            space = sp["_space"]
            final = {}
            for name, dummy, m in zip(chain.names, chain.dummy, result_matrices(chain)):
                if dummy:
                    continue
                m = space @ m
                final[name] = m
                parent = parent_of[name]
                if parent is None:
                    pm, prest = Matrix.Identity(4), Matrix.Identity(4)
                else:
                    pm = final.get(parent.name)
                    if pm is None:
                        pm = arm.pose.bones[parent.name].matrix.copy()
                    prest = parent.matrix_local
                basis = (pm @ prest.inverted() @ rest[name]).inverted() @ m
                loc, quat, _scale = basis.decompose()
                bases[name].append((loc, quat))
        if log and f % 60 == 0:
            log("kawaii frame %d / %d" % (f, f1))
    return frames, bases


def bake(scene, arm, settings=None, frame_start=None, frame_end=None, capsules=True, carrier=None, log=None):
    """从 frame_start 到 frame_end 逐帧(60 Hz 子步)模拟两侧胸链,烘成关键帧。返回统计。

    carrier:当作"角色本体"的骨(日文名或 Blender 名,例如 下半身 / センター);None = 骨架对象本身。
    要求:胸骨不被物理带动(先 bodies_follow_bones + 重新 Build,或根本没 Build);模拟期间只读骨架姿势。"""
    s = dict(VINDICTUS)
    s.update(settings or {})
    clear(arm)
    chain_list = breast_chains(arm)
    if not chain_list:
        raise RuntimeError("没找到胸骨链(%s,或挂着摆动刚体、名字像胸的骨)" % ", ".join(BREAST_ROOTS))
    scale_m = cm_to_m(arm)
    caps = vindictus_capsules(arm, scale_m) if capsules else []
    specs = [spec(c, s, carrier, caps) for c in chain_list]
    frames, bases = simulate(scene, arm, specs, frame_start, frame_end, log)
    write_keys(arm, frames, bases)
    scene.frame_set(frames[0])
    carrier_pb = specs[0]["_carrier"]
    return {"bones": len(bases), "frames": len(frames), "substeps": max(1, int(round(
        s["target_fps"] / (scene.render.fps / scene.render.fps_base)))), "capsules": len(caps),
        "carrier": carrier_pb.name if carrier_pb is not None else None, "cm_to_m": round(scale_m, 6)}
