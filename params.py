"""参数:界面上的一套刚体 + 关节参数,以及它和模型里刚体/关节对象之间的读写。

轴向:关节的 X/Y/Z 按 MMD(X 左右、Y 上下、Z 前后),与 PMXEditor 一致。mmd_tools 在 Blender 里存的是
Blender 轴(Y/Z 对调,旋转限制还差一个负号),读写时照 mmd_tools 导出器的规则换算。
长度(刚体尺寸、移动限制)是 Blender 里的长度,导出 PMX 时再乘导出缩放(常用 12.5)。
碰撞组按 PMXEditor 编号 1~16 显示(mmd_tools 内部 0~15)。
"""

import json
import math

import bpy
from bpy.props import (BoolProperty, BoolVectorProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, IntProperty, PointerProperty, StringProperty)
from bpy.types import PropertyGroup

from . import groups, presets

FIELDS = ("mode", "shape", "size", "mass", "lin_damp", "ang_damp", "bounce", "friction", "group",
          "nocollide", "rot_min", "rot_max", "loc_min", "loc_max", "spring_rot", "spring_loc")
_ANGLES = ("rot_min", "rot_max")
_guard = [0]


class guard:
    """批量改值(读取模型、套预设、左右同步)期间不触发自动应用。"""

    def __enter__(self):
        _guard[0] += 1
        return self

    def __exit__(self, *exc):
        _guard[0] -= 1
        return False


def _owner(params):
    """params 所在的 (root, 组名, 'left'/'right');路径形如 mmd_physics.breast.left"""
    parts = params.path_from_id().split(".")
    return params.id_data, parts[1], parts[2]


def _group_owner(gs):
    return gs.id_data, gs.path_from_id().split(".")[1]


def _changed(self, context):
    if _guard[0]:
        return
    root, key, side = _owner(self)
    st = root.mmd_physics
    gs = getattr(st, key)
    if gs.link:
        with guard():
            copy_params(self, gs.right if side == "left" else gs.left)
    if st.live:
        apply_group(root, key)


def _changed_rot(self, context):
    if not _guard[0]:
        root, key, _side = _owner(self)
        if getattr(root.mmd_physics, key).sym_rot:
            with guard():
                self.rot_min = [-v for v in self.rot_max]
    _changed(self, context)


def _changed_loc(self, context):
    if not _guard[0]:
        root, key, _side = _owner(self)
        if getattr(root.mmd_physics, key).sym_loc:
            with guard():
                self.loc_min = [-v for v in self.loc_max]
    _changed(self, context)


def _link_changed(self, context):
    if _guard[0] or not self.link:
        return
    with guard():
        copy_params(self.left, self.right)
    root, key = _group_owner(self)
    if root.mmd_physics.live:
        apply_group(root, key)


def _sym_changed(self, context):
    if _guard[0]:
        return
    with guard():
        for p in (self.left, self.right):
            if self.sym_rot:
                p.rot_min = [-v for v in p.rot_max]
            if self.sym_loc:
                p.loc_min = [-v for v in p.loc_max]
    root, key = _group_owner(self)
    if root.mmd_physics.live:
        apply_group(root, key)


_MODES = [
    ('1', "物理演算", "骨头完全由刚体带动(MMD「物理演算」)"),
    ('2', "物理+骨位置", "刚体只带旋转,位置跟父骨,不容易被拉长(MMD「物理+ボーン位置合わせ」)"),
    ('0', "跟骨(关闭物理)", "刚体跟着骨头走,不晃(MMD「ボーン追従」)"),
]
_SHAPES = [('SPHERE', "球", ""), ('BOX', "箱", ""), ('CAPSULE', "胶囊", "")]
_preset_cache = {}


def _preset_items(self, context):
    key = self.path_from_id().split(".")[1]
    if key not in _preset_cache:            # Blender 要求 items 回调返回的字符串一直有人引用
        _preset_cache[key] = presets.items(key)
    return _preset_cache[key]


class MMDPhysParams(PropertyGroup):
    mode: EnumProperty(name="物理类型", items=_MODES, default='1', update=_changed)
    shape: EnumProperty(name="形状", items=_SHAPES, default='SPHERE', update=_changed)
    size: FloatVectorProperty(name="尺寸", size=3, subtype='XYZ', unit='LENGTH', min=0.0, precision=4,
                              step=0.1, update=_changed)
    mass: FloatProperty(name="质量", min=0.001, soft_max=10.0, default=1.0, precision=3, update=_changed)
    lin_damp: FloatProperty(name="移动衰减", description="越大平移越快停下", min=0.0, max=1.0, default=0.5,
                            update=_changed)
    ang_damp: FloatProperty(name="旋转衰减", description="越大晃动越快停下", min=0.0, max=1.0, default=0.5,
                            update=_changed)
    bounce: FloatProperty(name="反弹", min=0.0, soft_max=1.0, default=0.0, update=_changed)
    friction: FloatProperty(name="摩擦", min=0.0, soft_max=1.0, default=0.5, update=_changed)
    group: IntProperty(name="碰撞组", description="PMXEditor 编号 1~16", min=1, max=16, default=16,
                       update=_changed)
    nocollide: BoolVectorProperty(name="不碰撞的组", description="勾上 = 不和这个组碰撞", size=16,
                                  update=_changed)
    rot_min: FloatVectorProperty(name="旋转下限", size=3, subtype='EULER', unit='ROTATION', update=_changed)
    rot_max: FloatVectorProperty(name="旋转上限", size=3, subtype='EULER', unit='ROTATION',
                                 update=_changed_rot)
    loc_min: FloatVectorProperty(name="移动下限", size=3, subtype='XYZ', unit='LENGTH', precision=4,
                                 update=_changed)
    loc_max: FloatVectorProperty(name="移动上限", size=3, subtype='XYZ', unit='LENGTH', precision=4,
                                 update=_changed_loc)
    spring_rot: FloatVectorProperty(name="旋转弹簧", description="回弹力,0 = 没有弹簧", size=3, subtype='XYZ',
                                    min=0.0, soft_max=1000.0, update=_changed)
    spring_loc: FloatVectorProperty(name="移动弹簧", size=3, subtype='XYZ', min=0.0, soft_max=1000.0,
                                    update=_changed)


class MMDPhysGroup(PropertyGroup):
    left: PointerProperty(type=MMDPhysParams)
    right: PointerProperty(type=MMDPhysParams)
    link: BoolProperty(name="左右联动", description="左右用同一套参数", default=True, update=_link_changed)
    side: EnumProperty(name="编辑", items=[('left', "左", ""), ('right', "右", "")], default='left')
    sym_rot: BoolProperty(name="旋转对称", description="旋转限制取 ±同一个值", default=True,
                          update=_sym_changed)
    sym_loc: BoolProperty(name="移动对称", description="移动限制取 ±同一个值", default=True,
                          update=_sym_changed)
    preset: EnumProperty(name="预设", items=_preset_items)
    inited: BoolProperty(default=False)
    original: StringProperty(default="")        # 第一次读取时的参数(JSON),「恢复初始」用


class MMDPhysBreastNew(PropertyGroup):
    """「新建胸部物理」的参数(算法见 create_breast.py);×身高的都按模型身高换算。"""
    depth: FloatProperty(name="骨头深度", description="胸骨骨头(关节)在乳尖后方多深,×身高", default=0.058,
                         min=0.01, max=0.2, precision=3)
    sigma: FloatProperty(name="权重范围", description="胸骨带动的范围(高斯 σ),×身高;越大带动的胸部越大",
                         default=0.052, min=0.01, max=0.2, precision=3)
    radius: FloatProperty(name="刚体半径", description="球形刚体半径,×身高", default=0.029, min=0.005, max=0.1,
                          precision=3)
    preset: EnumProperty(name="初始手感", description="建完套用的预设,之后可以随便调",
                         items=presets.items("breast"), default="bouncy")
    apex_l: FloatVectorProperty(name="左乳尖", size=3, subtype='TRANSLATION', unit='LENGTH')
    apex_r: FloatVectorProperty(name="右乳尖", size=3, subtype='TRANSLATION', unit='LENGTH')
    manual_l: BoolProperty(name="左乳尖手动指定", default=False)
    manual_r: BoolProperty(name="右乳尖手动指定", default=False)
    found_l: BoolProperty(default=False)        # 检测/指定过,有位置可显示
    found_r: BoolProperty(default=False)


class MMDPhysSettings(PropertyGroup):
    live: BoolProperty(name="实时应用", description="改参数立即写进模型的刚体/关节", default=True)
    mmd_scale: FloatProperty(
        name="PMX 缩放",
        description="Blender → PMX 的缩放(导出 Scale)。预览按它把重力、旋转弹簧换成 MMD 里的比例,"
                    "导出默认也用它",
        default=12.5, min=0.001, soft_max=100.0)
    breast: PointerProperty(type=MMDPhysGroup)
    breast_new: PointerProperty(type=MMDPhysBreastNew)
    preview_motion: EnumProperty(
        name="预览动作",
        items=[('TEST', "内置测试动作", "上下颠、扭腰、前后倾,约 5 秒"),
               ('SCENE', "场景现有动作", "用已经导入的 VMD 等动作")],
        default='TEST')
    pv_active: BoolProperty(default=False)
    pv_state: StringProperty(default="")        # 预览前的场景状态(JSON),停止时还原


# -- 模型 ↔ 参数 --------------------------------------------------------------------------
def rigid_size(o):
    """刚体当前尺寸,直接从碰撞网格顶点算。mmd_tools 的 size 读的是包围盒,刚改完网格
    还没刷新时是旧值,连续写两次会误判「没变」而漏写。"""
    vs = o.data.vertices if o.data else ()
    if not vs:
        return tuple(o.mmd_rigid.size)
    shape = o.mmd_rigid.shape
    if shape == 'SPHERE':
        return (max(v.co.length for v in vs), 0.0, 0.0)
    xs, ys, zs = ([v.co[i] for v in vs] for i in range(3))
    if shape == 'BOX':
        return ((max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2, (max(zs) - min(zs)) / 2)
    r = (max(xs) - min(xs)) / 2
    return (r, abs((max(zs) - min(zs)) - 2 * r), 0.0)


def read_rigid(o, p):
    rb, mr = o.rigid_body, o.mmd_rigid
    p.mode = mr.type
    p.shape = mr.shape
    p.size = rigid_size(o)
    if rb is not None:
        p.mass = rb.mass
        p.lin_damp = rb.linear_damping
        p.ang_damp = rb.angular_damping
        p.bounce = rb.restitution
        p.friction = rb.friction
    p.group = mr.collision_group_number + 1
    p.nocollide = tuple(mr.collision_group_mask)


def read_joint(j, p):
    c = j.rigid_body_constraint
    if c is None:
        return
    # PMX 旋转下限 = -(Blender 上限),上限 = -(Blender 下限);轴序 PMX(x,y,z) = Blender(x,z,y)
    p.rot_min = (-c.limit_ang_x_upper, -c.limit_ang_z_upper, -c.limit_ang_y_upper)
    p.rot_max = (-c.limit_ang_x_lower, -c.limit_ang_z_lower, -c.limit_ang_y_lower)
    p.loc_min = (c.limit_lin_x_lower, c.limit_lin_z_lower, c.limit_lin_y_lower)
    p.loc_max = (c.limit_lin_x_upper, c.limit_lin_z_upper, c.limit_lin_y_upper)
    s = j.mmd_joint.spring_angular
    p.spring_rot = (s[0], s[2], s[1])
    s = j.mmd_joint.spring_linear
    p.spring_loc = (s[0], s[2], s[1])


def _differs(a, b, tol=1e-7):
    if isinstance(b, (tuple, list)):
        return any(abs(x - y) > tol for x, y in zip(a, b))
    if isinstance(b, float):
        return abs(a - b) > tol
    return a != b


def _put(obj, attr, value):
    if _differs(getattr(obj, attr), value):
        setattr(obj, attr, value)


def write_rigid(o, p):
    rb, mr = o.rigid_body, o.mmd_rigid
    _put(mr, "shape", p.shape)
    size = tuple(p.size)
    used = {'SPHERE': 1, 'CAPSULE': 2}.get(p.shape, 3)     # 球只看半径,胶囊看半径+高
    if _differs(rigid_size(o)[:used], size[:used], 1e-6):
        mr.size = size                      # mmd_tools 会按新尺寸重建碰撞网格
    _put(mr, "type", p.mode)
    _put(mr, "collision_group_number", p.group - 1)
    mask = tuple(bool(x) for x in p.nocollide)
    if tuple(mr.collision_group_mask) != mask:
        mr.collision_group_mask = mask
    if rb is not None:
        _put(rb, "mass", p.mass)
        _put(rb, "linear_damping", p.lin_damp)
        _put(rb, "angular_damping", p.ang_damp)
        _put(rb, "restitution", p.bounce)
        _put(rb, "friction", p.friction)


_AXES = ("x", "y", "z", "ang_x", "ang_y", "ang_z")
PREVIEW_ZETA = 0.1          # 预览弹簧的阻尼比(临界阻尼的 10%):能晃几下再停


def _body_inertia(j):
    """关节带动的那个刚体(object2,是跟骨的就取 object1):(质量, 绕关节的转动惯量),近似成球。"""
    c = j.rigid_body_constraint
    b = c.object2
    if b is None or b.rigid_body is None or b.rigid_body.kinematic:
        b = c.object1
    if b is None or b.rigid_body is None:
        return 1.0, 1.0
    m = b.rigid_body.mass
    r = max(rigid_size(b))
    d = (b.matrix_world.translation - j.matrix_world.translation).length
    return m, m * (0.4 * r * r + d * d)


def joint_backup(j):
    c = j.rigid_body_constraint
    if c is None:
        return None
    return [c.spring_type, [getattr(c, "spring_damping_" + a) for a in _AXES],
            [getattr(c, "use_spring_" + a) for a in _AXES]]


def preview_joint(j, s2, backup=None):
    """预览时让关节约束接近 MMD;s2 = None 时按 backup 还原(没有 backup 用 mmd_tools 的默认)。

    - mmd_tools 建的约束六轴弹簧全开、阻尼 0.5,弹簧常数为 0 也照样阻尼,关节像泡在蜂蜜里(下坠 4 秒、
      几乎不晃)。MMD 只在弹簧常数非 0 的轴上开弹簧 → 常数为 0 的轴关掉弹簧;非 0 的轴阻尼取临界阻尼的
      PREVIEW_ZETA(SPRING2 的阻尼是绝对量,固定一个数对小刚体过阻尼、对大刚体又不够)。
      (MMD 的老版 6DofSpring 对应 Blender 的 SPRING1,但它在 Blender 里撞到多轴限位后会锁死不动,
      所以用 SPRING2。)
    - 旋转弹簧的量纲带长度²,模型在 Blender 里是 PMX 的 1/scale,同一个数在 Blender 里硬 scale² 倍:
      乘 s2 = (1/scale)²。线性弹簧与尺度无关。
    """
    c = j.rigid_body_constraint
    if c is None or not hasattr(c, "spring_stiffness_ang_x"):
        return
    ka = j.mmd_joint.spring_angular
    kl = j.mmd_joint.spring_linear
    if s2 is None:
        kind, damp, use = backup if backup else ('SPRING2', [0.5] * 6, [True] * 6)
        c.spring_type = kind
        for a, d, u in zip(_AXES, damp, use):
            setattr(c, "spring_damping_" + a, d)
            setattr(c, "use_spring_" + a, u)
        f = 1.0
    else:
        c.spring_type = 'SPRING2'
        m, inertia = _body_inertia(j)
        for i, a in enumerate(_AXES):
            k = kl[i] if i < 3 else ka[i - 3] * s2          # Blender 里实际的刚度
            setattr(c, "use_spring_" + a, abs(k) > 1e-12)
            crit = 2.0 * math.sqrt(max(k, 0.0) * (m if i < 3 else inertia))
            setattr(c, "spring_damping_" + a, PREVIEW_ZETA * crit)
        f = s2
    c.spring_stiffness_ang_x, c.spring_stiffness_ang_y, c.spring_stiffness_ang_z = ka[0] * f, ka[1] * f, ka[2] * f


def write_joint(j, p, s2=None):
    c = j.rigid_body_constraint
    if c is None:
        return
    _put(c, "limit_ang_x_lower", -p.rot_max[0])
    _put(c, "limit_ang_x_upper", -p.rot_min[0])
    _put(c, "limit_ang_z_lower", -p.rot_max[1])
    _put(c, "limit_ang_z_upper", -p.rot_min[1])
    _put(c, "limit_ang_y_lower", -p.rot_max[2])
    _put(c, "limit_ang_y_upper", -p.rot_min[2])
    _put(c, "limit_lin_x_lower", p.loc_min[0])
    _put(c, "limit_lin_x_upper", p.loc_max[0])
    _put(c, "limit_lin_z_lower", p.loc_min[1])
    _put(c, "limit_lin_z_upper", p.loc_max[1])
    _put(c, "limit_lin_y_lower", p.loc_min[2])
    _put(c, "limit_lin_y_upper", p.loc_max[2])
    _put(j.mmd_joint, "spring_angular", (p.spring_rot[0], p.spring_rot[2], p.spring_rot[1]))
    _put(j.mmd_joint, "spring_linear", (p.spring_loc[0], p.spring_loc[2], p.spring_loc[1]))
    if s2 is not None:                      # 预览中:mmd_tools 刚按原值写了约束,换回 MMD 比例
        preview_joint(j, s2)


def copy_params(src, dst):
    for f in FIELDS:
        v = getattr(src, f)
        setattr(dst, f, v if isinstance(v, (str, int, float, bool)) else tuple(v))


def params_equal(a, b, tol=1e-5):
    for f in FIELDS:
        x, y = getattr(a, f), getattr(b, f)
        if isinstance(x, (str, bool, int)) and not isinstance(x, float):
            if x != y:
                return False
        elif isinstance(x, float):
            if abs(x - y) > tol:
                return False
        elif any((abs(u - v) > tol) if isinstance(u, float) else u != v for u, v in zip(x, y)):
            return False
    return True


def _model(root):
    from mmd_tools.core.model import Model
    return Model(root)


def apply_group(root, key):
    """把参数写进模型;左右联动时两侧都用左侧那套。返回 Group。"""
    g = groups.find(key, _model(root))
    st = root.mmd_physics
    gs = getattr(st, key)
    s2 = (1.0 / st.mmd_scale) ** 2 if st.pv_active else None
    for side, p in (("L", gs.left), ("R", gs.left if gs.link else gs.right)):
        for o in g.rigids[side]:
            if o.get(groups.TAG) != key:
                o[groups.TAG] = key         # 改成「跟骨」后也还认得
            write_rigid(o, p)
        for j in g.joints[side]:
            write_joint(j, p, s2)
    return g


def sync_group(root, key):
    """从模型读参数(每侧取第一个刚体/关节);第一次读时顺便记下「初始值」。"""
    g = groups.find(key, _model(root))
    if g.empty():
        return g
    gs = getattr(root.mmd_physics, key)
    with guard():
        for side, p in (("L", gs.left), ("R", gs.right)):
            other = "R" if side == "L" else "L"
            rs = g.rigids[side] or g.rigids[other]
            js = g.joints[side] or g.joints[other]
            read_rigid(rs[0], p)
            if js:
                read_joint(js[0], p)
        gs.link = params_equal(gs.left, gs.right)
        both = (gs.left, gs.right)
        gs.sym_rot = all(abs(a + b) < 1e-5 for p in both for a, b in zip(p.rot_min, p.rot_max))
        gs.sym_loc = all(abs(a + b) < 1e-7 for p in both for a, b in zip(p.loc_min, p.loc_max))
        if not gs.inited:
            gs.original = json.dumps(to_dict(gs), ensure_ascii=False)
            gs.inited = True
    return g


# -- 预设 / JSON -------------------------------------------------------------------------
def apply_preset(root, key, preset):
    v = presets.values(key, preset)
    gs = getattr(root.mmd_physics, key)
    with guard():
        for p in (gs.left, gs.right):
            if "mode" in v:
                p.mode = v["mode"]
            for f in ("mass", "lin_damp", "ang_damp", "bounce", "friction"):
                if f in v:
                    setattr(p, f, v[f])
            if "rot" in v:
                r = math.radians(v["rot"])
                p.rot_max, p.rot_min = (r, r, r), (-r, -r, -r)
            if "loc" in v:
                d = v["loc"]
                p.loc_max, p.loc_min = (d, d, d), (-d, -d, -d)
            if "spring_rot" in v:
                p.spring_rot = (v["spring_rot"],) * 3
            if "spring_loc" in v:
                p.spring_loc = (v["spring_loc"],) * 3
        if "rot" in v:
            gs.sym_rot = True
        if "loc" in v:
            gs.sym_loc = True
        gs.link = params_equal(gs.left, gs.right)
    return apply_group(root, key)


def _params_dict(p):
    d = {}
    for f in FIELDS:
        v = getattr(p, f)
        if f in _ANGLES:
            v = [round(math.degrees(x), 6) for x in v]      # JSON 里角度用度,方便手改
        elif not isinstance(v, (str, int, float, bool)):
            v = list(v)
        d[f] = v
    return d


def to_dict(gs):
    return {"link": gs.link, "sym_rot": gs.sym_rot, "sym_loc": gs.sym_loc,
            "left": _params_dict(gs.left), "right": _params_dict(gs.right)}


def from_dict(gs, d):
    with guard():
        for side in ("left", "right"):
            p, src = getattr(gs, side), d.get(side, {})
            for f in FIELDS:
                if f not in src:
                    continue
                v = src[f]
                if f in _ANGLES:
                    v = [math.radians(x) for x in v]
                setattr(p, f, tuple(v) if isinstance(v, list) else v)
        for f in ("link", "sym_rot", "sym_loc"):
            if f in d:
                setattr(gs, f, bool(d[f]))


_CLASSES = (MMDPhysParams, MMDPhysGroup, MMDPhysBreastNew, MMDPhysSettings)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.mmd_physics = PointerProperty(type=MMDPhysSettings)


def unregister():
    del bpy.types.Object.mmd_physics
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
