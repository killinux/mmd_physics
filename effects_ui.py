"""「效果选择(渲染用)」面板:胸部 / 头发 / 裙子 / 其他衣物 各选方式和预设,一键模拟 / 烘焙,一键还原。流程在 effects.py。"""

import json

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty,
                       StringProperty)
from bpy.types import PropertyGroup

from . import chains, effects, kits, ops, outfit, presets

CATS = ("BUST", "HAIR", "SKIRT", "CLOTH")
ATTR = {"BUST": "bust", "HAIR": "hair", "SKIRT": "skirt", "CLOTH": "cloth"}
CAT_OF = {v: k for k, v in ATTR.items()}

# 面板属性名 ↔ 预设参数名。骨骼布料的参数名加 bc_ 前缀(damping / gravity / radius 和弹簧骨骼的重名)。
RIGID_KEYS = ("kind", "mass", "lin_damp", "ang_damp", "rot", "spring_rot", "sag", "twist_sag", "pitch_limit",
              "yaw_limit", "twist_limit", "hanging_scale", "damp_scale", "damp_min", "limit_scale", "kit", "kit_scale",
              "kit_limit", "kit_lift", "kit_mass", "kit_pair")
SPRING_KEYS = ("stiffness", "damping", "world_damping_location", "world_damping_rotation", "limit_angle", "radius_cm",
               "gravity_cm", "target_fps", "tip", "capsules", "colliders", "allow_legs", "carrier")
CLOTH_KEYS = ("gravity", "damping", "radius", "restore_stiffness", "restore_attenuation", "limit_root", "limit_tip",
              "inertia", "move_limit", "turn_limit", "particle_limit", "backstop", "backstop_radius",
              "backstop_distance", "max_distance_on", "max_distance", "collision_edge", "friction", "floor",
              "floor_height", "substeps", "iterations", "blend", "colliders", "allow_legs", "link", "link_stretch",
              "link_squash", "link_max")
KEYS = {"RIGID": [(k, k) for k in RIGID_KEYS], "SPRING": [(k, k) for k in SPRING_KEYS],
        "CLOTH": [("bc_" + k, k) for k in CLOTH_KEYS], "FOLLOW": []}

_CARRIERS = [
    ('NONE', "不设(全身动作都算)", "骨架对象当角色本体:PMX 跳舞时全身的移动、跳跃都按动画算,全部传给链"),
    ('下半身', "下半身", "把下半身(髋)的移动和转动当成角色整体移动,按「抵消整体移动 / 转动」只传一部分"),
    ('センター', "センター", "把センター当角色本体(动作的移动写在センター上时用)"),
    ('全ての親', "全ての親", "把全ての親当角色本体"),
]
_KINDS = [('model', "模型原样", "不改"), ('fixed', "固定值", "质量、阻尼、±限位、旋转弹簧直接给数"),
          ('sag', "按下垂角定弹簧", "按 MMD 重力 98 和静止下垂角算旋转弹簧"),
          ('scale', "按比例", "阻尼、关节限位在原值上按比例改"),
          ('kit', "整套换上", "换成社区的多段刚体套件(RGBA 式、Tda 式、欧美转换式、AH 式):原来的胸部刚体改成跟骨,"
                             "每条胸链另建一套刚体和关节;还原时删掉")]
_ALLOW_LEGS = ("静止时(弹簧骨骼:第一帧)就陷在腿碰撞体里的布骨也放过。关(默认):推出去,骨骼贴着腿走的外套会张开"
               "一些,但腿不会穿出来;开:保持原来的形状,腿一动就会从布里穿出来。陷在胯里的部分总是放过")
_items_cache = {}
_guard = [0]


def _cat_of(props):
    return CAT_OF[props.path_from_id().split(".")[-1]]


def _preset_items(self, context):
    key = (_cat_of(self), self.method)
    if key not in _items_cache:
        _items_cache[key] = presets.fx_items(*key) or [("none", "(没有预设)", "")]
    return _items_cache[key]


def fill(props, values):
    """预设参数填到面板上。"""
    _guard[0] += 1
    try:
        for attr, key in KEYS[props.method]:
            if key in values:
                v = values[key]
                if key == "gravity_cm" and isinstance(v, (tuple, list)):
                    v = -v[2]
                setattr(props, attr, v)
    finally:
        _guard[0] -= 1


def values_of(props):
    """面板上这一类的参数 → 预设参数格式(effects.apply 用)。"""
    return {key: getattr(props, attr) for attr, key in KEYS[props.method]}


def _preset_changed(self, context):
    if _guard[0] or self.preset == "none":
        return
    fill(self, presets.fx_values(_cat_of(self), self.method, self.preset))


def _method_changed(self, context):
    if _guard[0]:
        return
    items = presets.fx_items(_cat_of(self), self.method)
    if items:
        _guard[0] += 1
        try:
            self.preset = items[0][0]
        finally:
            _guard[0] -= 1
        fill(self, presets.fx_values(_cat_of(self), self.method, items[0][0]))


class MMDPhysFxCategory(PropertyGroup):
    method: EnumProperty(name="方式", items=presets.FX_METHODS, default="RIGID", update=_method_changed)
    preset: EnumProperty(name="预设", items=_preset_items, update=_preset_changed)
    show: BoolProperty(name="参数", default=False)
    # MMD 刚体
    kind: EnumProperty(name="写法", items=_KINDS, default='model')
    mass: FloatProperty(name="质量", min=0.001, soft_max=10.0, default=1.0)
    lin_damp: FloatProperty(name="移动衰减", min=0.0, max=1.0, default=0.5)
    ang_damp: FloatProperty(name="旋转衰减", min=0.0, max=1.0, default=0.5)
    rot: FloatProperty(name="旋转限制 ±°", min=0.0, max=180.0, default=10.0)
    spring_rot: FloatProperty(name="旋转弹簧", min=0.0, soft_max=2000.0, default=0.0, description="PMX 单位,0 = 没有弹簧")
    sag: FloatProperty(name="静止下垂°", min=0.1, max=60.0, default=8.0, description="按 MMD 重力 98 定上下弹簧")
    twist_sag: FloatProperty(name="扭转下垂°", min=0.1, max=60.0, default=4.0)
    pitch_limit: FloatProperty(name="上下限位 ±°", min=0.0, max=180.0, default=25.0)
    yaw_limit: FloatProperty(name="左右限位 ±°", min=0.0, max=180.0, default=15.0)
    twist_limit: FloatProperty(name="扭转限位 ±°", min=0.0, max=180.0, default=5.0)
    hanging_scale: FloatProperty(name="吊着的刚体减重", min=0.0, max=1.0, default=1.0,
                                 description="挂在胸上的摆动刚体(吊坠、衣片)的质量和弹簧先乘这个数;1 = 不变")
    damp_scale: FloatProperty(name="阻尼 ×", min=0.0, max=3.0, default=1.0)
    damp_min: FloatProperty(name="阻尼至少", min=0.0, max=1.0, default=0.0)
    limit_scale: FloatProperty(name="旋转限位 ×", min=0.0, max=3.0, default=1.0)
    kit: EnumProperty(name="套件", items=kits.items())
    kit_scale: FloatProperty(name="大小 ×", min=0.2, max=3.0, default=1.0,
                             description="套件按胸根到乳尖的距离自动缩放,再乘这个数")
    kit_limit: FloatProperty(name="幅度 ×", min=0.0, max=3.0, default=1.0,
                             description="主关节(锚 → 胸)的平移和旋转限位乘这个数(mmd_jiggle_bones 的「抖动强度」)")
    kit_lift: FloatProperty(name="托高", min=0.0, max=1.0, default=1.0,
                            description="平移上下限相等且不为 0 的关节(RGBA 把胸托高的两处)乘这个数。1 = 原版;"
                                        "Blender 的关节硬,原版在这里会把胸抬高、上翘约 16°")
    kit_mass: FloatProperty(name="质量 ×", min=0.1, max=20.0, default=1.0,
                            description="套件刚体的质量都乘这个数,关节弹簧不变:越重晃得越大、越慢。AH 式想更晃时"
                                        "社区的做法是 AH1 0.5 → 1.2、AH2 0.1 → 0.4(约 ×3)")
    kit_pair: BoolProperty(name="左右连着(着衣用)", default=False,
                           description="套件带左右之间的关节时(AH 式「着衣用」):左右两套锁在一起,两边一起晃,"
                                       "原版穿衣服时用;关 = 左右各晃各的")
    # 弹簧骨骼
    stiffness: FloatProperty(name="刚度", min=0.0, max=1.0, default=0.05, precision=3,
                             description="每步往动画姿势拉回的比例,越大越硬、晃得越小")
    damping: FloatProperty(name="阻尼", min=0.0, max=1.0, default=0.5, precision=3,
                           description="每步速度衰减,越大越快停、越不来回弹")
    world_damping_location: FloatProperty(name="抵消整体移动", min=0.0, max=1.0, default=0.8)
    world_damping_rotation: FloatProperty(name="抵消整体转动", min=0.0, max=1.0, default=0.8)
    limit_angle: FloatProperty(name="限角°", min=0.0, max=180.0, default=10.8, description="0 = 不限")
    radius_cm: FloatProperty(name="碰撞半径(cm)", min=0.0, soft_max=20.0, default=5.0)
    gravity_cm: FloatProperty(name="重力(cm/s²)", min=0.0, soft_max=2000.0, default=0.0,
                              description="游戏里是 0:形状保持动画姿势")
    target_fps: IntProperty(name="模拟频率", min=30, max=240, default=60)
    tip: FloatProperty(name="末端补点", min=0.0, max=2.0, default=0.0,
                       description="链末端的骨在骨尾方向加一个虚点(按骨长算),末端那根骨也跟着转;单根骨的胸自动补")
    capsules: BoolProperty(name="手臂碰撞(Vindictus 的 6 个胶囊)", default=False)
    colliders: BoolProperty(name="腿和胯的碰撞体", default=False)
    allow_legs: BoolProperty(name="腿里的重叠也放过", default=False, description=_ALLOW_LEGS)
    carrier: EnumProperty(name="角色本体", items=_CARRIERS, default='NONE')
    # 骨骼布料
    bc_gravity: FloatProperty(name="重力(m/s²)", min=0.0, soft_max=20.0, default=5.0)
    bc_damping: FloatProperty(name="阻尼", min=0.0, max=1.0, default=0.05, description="每 1/90 秒速度损失的比例")
    bc_radius: FloatProperty(name="质点半径(m)", min=0.0, soft_max=0.1, default=0.02, precision=3)
    bc_restore_stiffness: FloatProperty(name="角度恢复", min=0.0, max=1.0, default=0.2, precision=3)
    bc_restore_attenuation: FloatProperty(name="恢复速度衰减", min=0.0, max=1.0, default=0.8)
    bc_limit_root: FloatProperty(name="角度限制·根°", min=0.0, max=180.0, default=25.0)
    bc_limit_tip: FloatProperty(name="角度限制·梢°", min=0.0, max=180.0, default=60.0)
    bc_inertia: FloatProperty(name="惯性", min=0.0, max=1.0, default=0.4)
    bc_move_limit: FloatProperty(name="移动限速(m/s)", min=0.0, soft_max=20.0, default=3.0)
    bc_turn_limit: FloatProperty(name="转动限速(°/s)", min=0.0, soft_max=1440.0, default=360.0)
    bc_particle_limit: FloatProperty(name="质点限速(m/s)", min=0.1, soft_max=20.0, default=4.0)
    bc_backstop: BoolProperty(name="背挡", default=True)
    bc_backstop_radius: FloatProperty(name="背挡半径(m)", min=0.01, soft_max=20.0, default=10.0)
    bc_backstop_distance: FloatProperty(name="背挡距离(m)", min=0.0, soft_max=0.3, default=0.02)
    bc_max_distance_on: BoolProperty(name="最大距离", default=False)
    bc_max_distance: FloatProperty(name="距离(m)", min=0.0, soft_max=2.0, default=0.3)
    bc_collision_edge: BoolProperty(name="边碰撞", default=True)
    bc_friction: FloatProperty(name="摩擦", min=0.0, max=1.0, default=0.05)
    bc_floor: BoolProperty(name="地面", default=True)
    bc_floor_height: FloatProperty(name="地面高度(m)", soft_min=-2.0, soft_max=2.0, default=0.0)
    bc_substeps: IntProperty(name="子步数", min=1, max=16, default=3)
    bc_iterations: IntProperty(name="迭代", min=1, max=16, default=4)
    bc_blend: FloatProperty(name="混合", min=0.0, max=1.0, default=1.0)
    bc_colliders: BoolProperty(name="腿和胯的碰撞体", default=True)
    bc_allow_legs: BoolProperty(name="腿里的重叠也放过", default=False, description=_ALLOW_LEGS)
    bc_link: BoolProperty(name="相邻链连接", default=False,
                          description="同一层上离得近的两条链,骨尾间距只许在一定范围里变:环形裙子的裙片不会分开")
    bc_link_stretch: FloatProperty(name="可拉长", min=0.0, max=2.0, default=0.2, description="比第一帧的间距最多长多少")
    bc_link_squash: FloatProperty(name="可压短", min=0.0, max=1.0, default=0.5, description="比第一帧的间距最多短多少")
    bc_link_max: FloatProperty(name="只连近于(m)", min=0.0, soft_max=1.0, default=0.2)


class MMDPhysFxGroup(PropertyGroup):
    category: EnumProperty(name="类别", items=[(k, label, "") for k, label in chains.CATEGORIES], default="CLOTH")
    bones: StringProperty()                 # JSON 列表
    roots: StringProperty()
    tip: BoolProperty()
    count: IntProperty()
    enabled: BoolProperty(name="参与", default=True)


class MMDPhysFx(PropertyGroup):
    groups: CollectionProperty(type=MMDPhysFxGroup)
    index: IntProperty()
    bust: PointerProperty(type=MMDPhysFxCategory)
    hair: PointerProperty(type=MMDPhysFxCategory)
    skirt: PointerProperty(type=MMDPhysFxCategory)
    cloth: PointerProperty(type=MMDPhysFxCategory)
    physics: EnumProperty(
        name="刚体怎么算",
        items=[('MMD', "MMD 同款", "关节按 MMD 的弹簧(无关节阻尼、旋转弹簧按缩放换算)、重力 98 单位/秒²、"
                                   "谁都不碰的刚体单独一层:效果和 MMD 里接近"),
               ('MMDTOOLS', "mmd_tools 原样", "不换算:mmd_tools 默认的关节(偏硬、带 0.5 关节阻尼)和场景原来的重力")],
        default='MMD')
    gravity_scale: FloatProperty(name="重力倍数", min=0.0, soft_max=3.0, default=1.0,
                                 description="MMD 同款时的重力 = 98 单位/秒² × 这个数")
    step: EnumProperty(
        name="物理步长",
        items=[('AUTO', "自动", "胸部用了要粗步长的套件(RGBA 式)就按 MMD 的 60 Hz,否则场景原样"),
               ('SCENE', "场景原样", "不改刚体世界的「每帧子步数」(Blender 默认 10,30 fps 时 300 Hz)"),
               ('60', "60 Hz(MMD)", "MMD 的物理最多每秒 60 步:关节「软」一些,RGBA 这类套件才晃"),
               ('120', "120 Hz", "MikuMikuPhysics、MMD4Mecanim 的默认"),
               ('300', "300 Hz", "Blender 默认(30 fps × 10)")],
        default='AUTO')
    status: StringProperty(default="")
    outfit: StringProperty(default="")      # 胸前穿的东西(outfit.py 的结论)
    inited: BoolProperty(default=False)


def _root(context):
    return ops._root(context)


def init_categories(fx):
    for cat in CATS:
        props = getattr(fx, ATTR[cat])
        method, preset = presets.FX_DEFAULT[cat]
        _guard[0] += 1
        try:
            props.method = method
            props.preset = preset
        finally:
            _guard[0] -= 1
        fill(props, presets.fx_values(cat, method, preset))
    fx.inited = True


def plan_of(root):
    """面板 → effects.apply 的 plan。"""
    fx = root.mmd_physics_fx
    cats = {}
    for cat in CATS:
        props = getattr(fx, ATTR[cat])
        cats[cat] = {"method": props.method, "values": values_of(props)}
    groups = [{"name": g.name, "category": g.category, "bones": json.loads(g.bones), "roots": json.loads(g.roots),
               "tip": g.tip, "enabled": g.enabled} for g in fx.groups]
    return {"categories": cats, "groups": groups, "physics": fx.physics, "gravity_scale": fx.gravity_scale,
            "scale": root.mmd_physics.mmd_scale, "step": fx.step}


def fill_groups(fx, found):
    fx.groups.clear()
    for g in found:
        item = fx.groups.add()
        item.name, item.category = g["name"], g["category"]
        item.bones, item.roots = json.dumps(g["bones"], ensure_ascii=False), json.dumps(g["roots"], ensure_ascii=False)
        item.tip, item.count, item.enabled = g["tip"], len(g["bones"]), g.get("enabled", True)


class MMDPHYS_OT_fx_detect(ops._ModelOp, bpy.types.Operator):
    """找出胸部、头发、裙子、其他衣物的物理骨链(按刚体和骨名),列在下面"""
    bl_idname = "mmd_physics.fx_detect"
    bl_label = "识别物理分组"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from mmd_tools.core.model import Model
        root = _root(context)
        fx = root.mmd_physics_fx
        arm = Model(root).armature()
        found = effects.detect_groups(arm)
        fill_groups(fx, found)
        result, worst = outfit.analyse(arm)
        fx.outfit = outfit.panel(result, worst) if result else ""
        if not fx.inited:
            init_categories(fx)
        counts = {}
        for g in found:
            counts[g["category"]] = counts.get(g["category"], 0) + 1
        fx.status = "识别到:" + ",".join("%s %d 组" % (chains.CATEGORY_LABEL[c], n) for c, n in counts.items()) \
            if counts else "没找到物理骨链(要用 mmd_tools 导入带物理的 PMX)"
        self.report({'INFO'}, fx.status)
        return {'FINISHED'}


class MMDPHYS_OT_fx_outfit(ops._ModelOp, bpy.types.Operator):
    """看胸前最外面那层网格跟不跟胸骨走,按结果给胸部选预设:衣服只跟一部分 → 收着晃(C 方案 / K1),
    挡着一层不跟胸的 → 小幅晃(紧实 / 稳一点);贴身、裸着或胸骨不带网格 → 不改"""
    bl_idname = "mmd_physics.fx_outfit"
    bl_label = "按衣服推荐"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from mmd_tools.core.model import Model
        root = _root(context)
        fx = root.mmd_physics_fx
        result, worst = outfit.analyse(Model(root).armature())
        fx.outfit = outfit.panel(result, worst) if result else "没找到胸链"
        detail = outfit.summary(result, worst) if result else "没找到胸链"
        props = fx.bust
        key = outfit.RECOMMEND.get(worst, {}).get(props.method)
        if key and key in [k for k, _l, _d in presets.fx_items("BUST", props.method)]:
            props.preset = key
            msg = "%s → 胸部预设改成「%s」| %s" % (outfit.LABELS[worst], dict(
                (k, label) for k, label, _d in presets.fx_items("BUST", props.method))[key], detail)
        else:
            msg = "%s,%s:预设不改 | %s" % (outfit.LABELS.get(worst, worst), outfit.ADVICE.get(worst, ""), detail)
        self.report({'INFO'}, msg)
        return {'FINISHED'}


def _selection(context):
    """活动对象和选中的对象(名字)。mmd_tools 建物理时把活动对象换成它最后建的不碰撞约束(ncc.N),清物理时又把它
    删掉:不放回去,用户选的东西就变了,还原后没有活动对象、面板的按钮全灰。"""
    a = context.view_layer.objects.active
    return (a.name if a else None, [o.name for o in context.selected_objects])


def _reselect(context, sel, root):
    """放回 _selection 记下的;原来的活动对象没了就用模型根。"""
    vl = context.view_layer
    active, selected = sel
    for o in context.selected_objects:
        o.select_set(False)
    for n in selected:
        o = vl.objects.get(n)
        if o is not None:
            o.select_set(True)
    o = vl.objects.get(active) if active else None
    try:
        vl.objects.active = o if o is not None else root
    except (RuntimeError, ReferenceError):
        pass


class MMDPHYS_OT_fx_apply(ops._ModelOp, bpy.types.Operator):
    """按每类选的方式算好:MMD 刚体改参数,弹簧骨骼 / 骨骼布料烘成关键帧(场景帧范围),跟随骨骼的刚体改成跟骨。
    每次都从第一次之前的原样重新来,可以随便换方式再点"""
    bl_idname = "mmd_physics.fx_apply"
    bl_label = "模拟 / 烘焙"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        root = _root(context)
        fx = root.mmd_physics_fx
        if not fx.groups:
            bpy.ops.mmd_physics.fx_detect()
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        lines = []
        sel = _selection(context)
        try:
            effects.apply(context.scene, root, plan_of(root), log=lines.append)
        except Exception as e:                      # noqa: BLE001 - 报给用户看
            self.report({'ERROR'}, "失败:%s" % e)
            raise
        finally:
            _reselect(context, sel, root)
        fx.status = " | ".join(lines)
        self.report({'INFO'}, lines[-1] if lines else "完成")
        return {'FINISHED'}


class MMDPHYS_OT_fx_restore(ops._ModelOp, bpy.types.Operator):
    """回到第一次用「模拟 / 烘焙」之前:刚体、关节、动作、重力都还原,本插件加的碰撞体删掉"""
    bl_idname = "mmd_physics.fx_restore"
    bl_label = "还原"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        root = _root(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        sel = _selection(context)
        try:
            done = effects.restore(context.scene, root)
        finally:
            _reselect(context, sel, root)
        root.mmd_physics_fx.status = "已还原" if done else "还没用过,不用还原"
        self.report({'INFO'}, root.mmd_physics_fx.status)
        return {'FINISHED'}


class MMDPHYS_OT_fx_bake_cache(ops._ModelOp, bpy.types.Operator):
    """渲染前把刚体物理烘成缓存(场景帧范围);不烘的话渲染时每帧现算,结果可能和播放时不同"""
    bl_idname = "mmd_physics.fx_bake_cache"
    bl_label = "烘焙刚体缓存(渲染前)"
    bl_options = {'REGISTER'}

    def execute(self, context):
        ok = effects.bake_cache(context.scene)
        self.report({'INFO'} if ok else {'WARNING'}, "刚体缓存已烘焙" if ok else "场景里没有刚体世界")
        return {'FINISHED'}


class MMDPHYS_UL_fx_groups(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text="%s(%d 根)" % (item.name, item.count))
        row.prop(item, "category", text="")


def _draw_params(layout, cat, props):
    m = props.method
    col = layout.column(align=True)
    if m == "RIGID":
        col.prop(props, "kind")
        if props.kind == "fixed":
            for k in ("mass", "lin_damp", "ang_damp", "rot", "twist_limit", "spring_rot"):
                col.prop(props, k)
        elif props.kind == "kit":
            for k in ("kit", "kit_scale", "kit_limit", "kit_lift", "kit_mass"):
                col.prop(props, k)
            if kits.has_pairs(props.kit):
                col.prop(props, "kit_pair")
            if kits.step_hz(props.kit):
                col.label(text="自动步长 = %d Hz" % kits.step_hz(props.kit), icon='INFO')
        elif props.kind == "sag":
            for k in ("sag", "twist_sag", "pitch_limit", "yaw_limit", "twist_limit", "lin_damp", "ang_damp",
                      "hanging_scale"):
                col.prop(props, k)
        elif props.kind == "scale":
            for k in ("damp_scale", "damp_min", "limit_scale"):
                col.prop(props, k)
        else:
            col.label(text="用 PMX 自带的数值")
    elif m == "SPRING":
        for k in ("stiffness", "damping", "limit_angle", "gravity_cm", "radius_cm", "tip"):
            col.prop(props, k)
        box = layout.box()
        box.prop(props, "carrier")
        if props.carrier != 'NONE':
            sub = box.column(align=True)
            sub.prop(props, "world_damping_location")
            sub.prop(props, "world_damping_rotation")
        if cat == "BUST":
            layout.prop(props, "capsules")
        col = layout.column(align=True)
        col.prop(props, "colliders")
        sub = col.row(align=True)
        sub.active = props.colliders
        sub.prop(props, "allow_legs")
        layout.prop(props, "target_fps")
    elif m == "CLOTH":
        for k in ("bc_restore_stiffness", "bc_restore_attenuation", "bc_limit_root", "bc_limit_tip"):
            col.prop(props, k)
        col = layout.column(align=True)
        for k in ("bc_gravity", "bc_damping", "bc_inertia", "bc_move_limit", "bc_turn_limit", "bc_particle_limit"):
            col.prop(props, k)
        col = layout.column(align=True)
        col.prop(props, "bc_backstop")
        sub = col.column(align=True)
        sub.active = props.bc_backstop
        sub.prop(props, "bc_backstop_radius")
        sub.prop(props, "bc_backstop_distance")
        row = col.row(align=True)
        row.prop(props, "bc_max_distance_on")
        r = row.row(align=True)
        r.active = props.bc_max_distance_on
        r.prop(props, "bc_max_distance")
        col = layout.column(align=True)
        col.prop(props, "bc_link")
        sub = col.column(align=True)
        sub.active = props.bc_link
        for k in ("bc_link_stretch", "bc_link_squash", "bc_link_max"):
            sub.prop(props, k)
        col = layout.column(align=True)
        col.prop(props, "bc_colliders")
        sub = col.row(align=True)
        sub.active = props.bc_colliders
        sub.prop(props, "bc_allow_legs")
        for k in ("bc_collision_edge", "bc_radius", "bc_friction"):
            col.prop(props, k)
        row = col.row(align=True)
        row.prop(props, "bc_floor")
        r = row.row(align=True)
        r.active = props.bc_floor
        r.prop(props, "bc_floor_height")
        col = layout.column(align=True)
        for k in ("bc_substeps", "bc_iterations", "bc_blend"):
            col.prop(props, k)
    else:
        col.label(text="刚体改成跟骨;动作里有这些骨的关键帧就照关键帧走")


class MMDPHYS_PT_fx(bpy.types.Panel):
    bl_label = "效果选择(渲染用)"
    bl_idname = "MMDPHYS_PT_fx"
    bl_order = 0
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MMD物理"
    bl_parent_id = "MMDPHYS_PT_main"

    @classmethod
    def poll(cls, context):
        return hasattr(bpy.types.Object, "mmd_type") and _root(context) is not None

    def draw(self, context):
        layout = self.layout
        root = _root(context)
        fx = root.mmd_physics_fx
        layout.label(text="胸部、头发、裙子、衣物各选一种方式,点「模拟 / 烘焙」", icon='INFO')
        layout.operator("mmd_physics.fx_detect", icon='VIEWZOOM')
        if not fx.groups:
            return
        present = {g.category for g in fx.groups if g.enabled}
        for cat in CATS:
            if cat not in present:
                continue
            props = getattr(fx, ATTR[cat])
            n = sum(1 for g in fx.groups if g.enabled and g.category == cat)
            box = layout.box()
            row = box.row()
            row.label(text="%s(%d 组)" % (chains.CATEGORY_LABEL[cat], n),
                      icon={'BUST': 'MOD_CLOTH', 'HAIR': 'CURVES', 'SKIRT': 'MOD_CLOTH', 'CLOTH': 'MOD_CLOTH'}
                      .get(cat, 'MOD_CLOTH'))
            box.prop(props, "method")
            if props.method != "FOLLOW":
                box.prop(props, "preset")
            if cat == "BUST":
                box.operator("mmd_physics.fx_outfit", icon='MATCLOTH')
                for i, line in enumerate(fx.outfit.split(" | ") if fx.outfit else []):
                    box.label(text=line, icon='INFO' if i == 0 else 'BLANK1')
            box.prop(props, "show", icon='TRIA_DOWN' if props.show else 'TRIA_RIGHT', emboss=False)
            if props.show:
                _draw_params(box, cat, props)
        col = layout.column(align=True)
        col.prop(fx, "physics")
        if fx.physics == 'MMD':
            col.prop(fx, "gravity_scale")
        col.prop(fx, "step")
        layout.label(text="范围:场景帧 %d–%d" % (context.scene.frame_start, context.scene.frame_end))
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("mmd_physics.fx_apply", icon='PHYSICS')
        row.operator("mmd_physics.fx_restore", icon='LOOP_BACK')
        layout.operator("mmd_physics.fx_bake_cache", icon='REC')
        if fx.status:
            for line in fx.status.split(" | ")[:8]:
                layout.label(text=line)
        layout.label(text="分组(可改类别、取消参与):")
        layout.template_list("MMDPHYS_UL_fx_groups", "", fx, "groups", fx, "index", rows=4)


_CLASSES = (MMDPhysFxCategory, MMDPhysFxGroup, MMDPhysFx, MMDPHYS_OT_fx_detect, MMDPHYS_OT_fx_outfit, MMDPHYS_OT_fx_apply,
            MMDPHYS_OT_fx_restore, MMDPHYS_OT_fx_bake_cache, MMDPHYS_UL_fx_groups, MMDPHYS_PT_fx)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Object.mmd_physics_fx = PointerProperty(type=MMDPhysFx)


def unregister():
    del bpy.types.Object.mmd_physics_fx
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
