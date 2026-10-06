"""内置预设。只改「手感」参数(物理类型、质量、衰减、反弹、摩擦、限位、弹簧),
不改刚体大小/碰撞组——那些跟模型尺寸和结构有关。

rot = 旋转限制 ±度(三轴相同),loc = 移动限制 ±(Blender 长度),spring_* 三轴相同(MMD 数值)。
胸部各档在插件预览(Fiona,内置测试动作)里的实测:最大摆角 / 静止下垂 / 动作停后余晃
  参考默认 17° / 14°(垂在限位上) / 4°    柔软 25° / 4° / 11°    Q弹 19° / 2° / 5°
  紧实 7° / 1° / 0.5°    夸张 41° / 晃个不停 / 18°    关闭物理 0
静止下垂 ≈ 质量×重力×(球心到关节距离)/旋转弹簧,没有弹簧就垂到限位。手感最终以 MMD 实测为准。
"""

BREAST = [
    ("reference", "参考默认",
     "Convert_to_MMD5 的默认值(同系列 11 个参考 PMX 实测):质量 1、衰减 0.5、±10°、无弹簧;"
     "没有弹簧托着,静止时会垂在限位上",
     dict(mode='1', mass=1.0, lin_damp=0.5, ang_damp=0.5, bounce=0.0, friction=0.5,
          rot=10.0, loc=0.0, spring_rot=0.0, spring_loc=0.0)),
    ("soft", "柔软",
     "弹簧弱、晃得慢而大,静止时略垂",
     dict(mode='1', mass=1.0, lin_damp=0.5, ang_damp=0.6, bounce=0.0, friction=0.5,
          rot=20.0, loc=0.0, spring_rot=60.0, spring_loc=0.0)),
    ("bouncy", "Q弹",
     "衰减小、带回弹,晃得欢",
     dict(mode='1', mass=1.0, lin_damp=0.3, ang_damp=0.3, bounce=0.0, friction=0.5,
          rot=15.0, loc=0.0, spring_rot=150.0, spring_loc=0.0)),
    ("firm", "紧实",
     "幅度小、很快停,像穿了运动内衣",
     dict(mode='1', mass=1.0, lin_damp=0.7, ang_damp=0.85, bounce=0.0, friction=0.5,
          rot=6.0, loc=0.0, spring_rot=300.0, spring_loc=0.0)),
    ("big", "夸张",
     "更重、衰减很小、幅度大,动漫式大幅甩动",
     dict(mode='1', mass=1.5, lin_damp=0.2, ang_damp=0.2, bounce=0.0, friction=0.5,
          rot=25.0, loc=0.0, spring_rot=60.0, spring_loc=0.0)),
    ("off", "关闭物理",
     "刚体改为跟骨,胸部跟着身体走、完全不晃",
     dict(mode='0')),
]

PRESETS = {"breast": BREAST}

# 弹簧骨骼(kawaii.py)的预设:KawaiiPhysics 的参数。数值取自游戏文件(reports/胸部控制方式全面调研_插件准备.md 第三节)。
KAWAII = [
    ("vindictus", "Vindictus 原版(身体)",
     "游戏身体动画蓝图里两侧胸部的参数:刚度 0.05、阻尼 0.5、世界阻尼 0.8、限角 10.8°、碰撞半径 5 cm、无重力",
     dict(stiffness=0.05, damping=0.5, world_damping_location=0.8, world_damping_rotation=0.8,
          limit_angle=10.8, radius_cm=5.0, gravity_cm=0.0)),
    ("vindictus_cloth", "Vindictus 衣服跟胸",
     "连衣裙 PCF_003、西装 PCF_009 里衣服跟着胸动的那对节点:阻尼 0.4,其余同身体(比身体稍弹)",
     dict(stiffness=0.05, damping=0.4, world_damping_location=0.8, world_damping_rotation=0.8,
          limit_angle=10.8, radius_cm=5.0, gravity_cm=0.0)),
]


def kawaii_items():
    return [(k, label, desc) for k, label, desc, _v in KAWAII]


def kawaii_values(preset):
    for k, _label, _desc, v in KAWAII:
        if k == preset:
            return v
    raise KeyError(preset)


# == 效果选择(渲染用) ======================================================================================
# 每类物理(BUST 胸部 / HAIR 头发 / SKIRT 裙子 / CLOTH 其他衣物)选一种方式,每种方式一组预设:
# (键, 名字, 说明, 参数)。参数只是默认值,面板上都能改。
FX_METHODS = (
    ("RIGID", "MMD 刚体", "PMX 自带的刚体 + 关节,按 MMD 的方式算(播放时实时算,渲染前烘焙物理缓存)"),
    ("SPRING", "弹簧骨骼", "KawaiiPhysics 同款(Vindictus 用的):骨链往动画姿势拉回,不加重力也保持形状;烘成关键帧"),
    ("CLOTH", "骨骼布料", "Magica Cloth 2 风格(ROE 游戏用的):角度恢复、角度限制、碰撞体、背挡;烘成关键帧"),
    ("FOLLOW", "跟随骨骼", "不模拟:刚体改成跟骨。动作里有这些骨的关键帧(游戏导出的动作)就照关键帧走,没有就跟着身体"),
)

AH_MASS = 3.0                                # AH 式的质量倍数:原版(1)在 Blender 里几乎不动
AH_CLOTHED_MASS = 10.0                       # AH 式「着衣用」(左右锁在一起)的质量倍数
RGBA_LIFT = 0.0                              # RGBA 的托高:Blender 里关节硬,原版的托高(1)会把胸抬高上翘 16°

_K = dict(stiffness=0.05, damping=0.5, world_damping_location=0.8, world_damping_rotation=0.8, limit_angle=10.8,
          radius_cm=5.0, gravity_cm=0.0, target_fps=60, tip=0.0, capsules=False, colliders=False, allow_legs=False,
          carrier="NONE")


def _k(**kw):
    d = dict(_K)
    d.update(kw)
    return d


# 骨骼布料的三组(和 ripper_tpose 的骨骼布料插件一样),colliders = 自动加腿和胯的胶囊碰撞体
_BC_SKIRT = dict(gravity=5.0, damping=0.05, radius=0.02, restore_stiffness=0.2, restore_attenuation=0.8,
                 limit_root=25.0, limit_tip=60.0, inertia=0.4, move_limit=3.0, turn_limit=360.0, particle_limit=4.0,
                 backstop=True, backstop_radius=10.0, backstop_distance=0.02, max_distance_on=False, max_distance=0.3,
                 collision_edge=True, friction=0.05, floor=True, floor_height=0.0, substeps=3, iterations=4, blend=1.0,
                 colliders=True, allow_legs=False, link=True, link_stretch=0.2, link_squash=0.5, link_max=0.2)
_BC_HAIR = dict(_BC_SKIRT, radius=0.015, restore_stiffness=0.3, limit_root=15.0, limit_tip=50.0, inertia=0.3,
                move_limit=2.0, particle_limit=3.0, backstop_distance=0.01, collision_edge=False, colliders=False,
                link=False)
_BC_GAME = dict(_BC_SKIRT, radius=0.015, limit_root=0.0, limit_tip=90.0, inertia=0.0, move_limit=5.0, turn_limit=720.0,
                particle_limit=1.0, backstop=False, backstop_distance=0.0, collision_edge=False, colliders=False,
                link=False)
# ROE 高级 H 场景胸部的 Magica 参数(游戏数据)。Magica 的阻尼、角度恢复实际只用设置值的 20%,这里已经换算好。
_BC_ROE_TOUCH = dict(_BC_HAIR, gravity=0.0, damping=0.0, radius=0.003, restore_stiffness=0.03, restore_attenuation=0.0,
                     limit_root=35.0, limit_tip=0.0, inertia=1.0, move_limit=5.0, turn_limit=720.0, particle_limit=4.0,
                     backstop=False, floor=False)
_BC_ROE_REST = dict(_BC_ROE_TOUCH, damping=0.2, restore_stiffness=0.0, limit_root=33.5)


def _fixed(v):
    """旧的胸部预设(柔软、Q弹……)换成效果用的「固定值」参数(扭转限位和摆动一样)。"""
    return dict(kind="fixed", mass=v["mass"], lin_damp=v["lin_damp"], ang_damp=v["ang_damp"], rot=v["rot"],
                twist_limit=v["rot"], spring_rot=v["spring_rot"])


def _kit(key, lift=1.0, pair=False, mass=1.0):
    """整套换上的套件(kits.py):缩放、幅度、托高、质量都先 1(托高按套件给);pair = 左右连着(AH 式「着衣用」)。"""
    return dict(kind="kit", kit=key, kit_scale=1.0, kit_limit=1.0, kit_lift=lift, kit_mass=mass, kit_pair=pair)


def _old(key):
    return next(v for k, _l, _d, v in BREAST if k == key)


_CHAIN_RIGID = [
    ("model", "模型原样", "PMX 自带的刚体和关节,不改", dict(kind="model")),
    ("calm", "稳一点", "阻尼至少 0.9、关节旋转限位收到 70%:晃得小、停得快",
     dict(kind="scale", damp_scale=1.0, damp_min=0.9, limit_scale=0.7)),
    ("lively", "飘一点", "阻尼 ×0.6、关节旋转限位放宽到 130%:晃得大、停得慢",
     dict(kind="scale", damp_scale=0.6, damp_min=0.0, limit_scale=1.3)),
]

FX = {
    ("BUST", "RIGID"): [
        ("model", "模型原样", "PMX 自带的胸部刚体和关节,不改", dict(kind="model")),
        ("template", "乳奶模板(无弹簧 ±10°)",
         "本机 89% 的 MMD 模型用的:没有弹簧、三轴 ±10°、阻尼 0.5,静止时垂在限位上",
         dict(kind="fixed", mass=1.0, lin_damp=0.5, ang_damp=0.5, rot=10.0, twist_limit=10.0, spring_rot=0.0)),
        ("rgba", "RGBA 式 1.5β(整套换上)",
         "中文圈最常移植的胸部刚体:每侧 6 个刚体、9 个关节、没有弹簧,靠 MMD 关节的「软」晃(ボヨヨン)。"
         "Blender 的关节硬,物理步长自动用 MMD 的 60 Hz,原版把胸托高的两处偏移默认不用(托高 %g)" % RGBA_LIFT,
         _kit("rgba", RGBA_LIFT)),
        ("tda", "Tda 式(整套换上)",
         "Tda式ミク 一系的 胸上 / 胸上2 / 胸下:旋转弹簧 100、尖端能前后颠(平移弹簧 200)、阻尼 0.99。"
         "原版也只有尖端「胸上2」带权重,这里它驱动模型自己的胸骨", _kit("tda")),
        ("western", "欧美 XPS 转换式(整套换上)",
         "Leberx44qa 一系 XPS 转 PMX 的 Boob 三段:质量 0.8、阻尼 0.9999、旋转弹簧 150 / 400、"
         "能平移几毫米(平移弹簧 400 / 150)、只往下摆 20°", _kit("western")),
        ("ah", "AH 式(整套换上,质量 ×%g)" % AH_MASS,
         "AH式(アローヘッド):锁成一整块的「接続 + AH1 + AH2」挂在一个硬弹簧关节上(旋转 2500 / 500、阻尼 0.9999),"
         "只能往上颠、上下 ±20°、左右 ±10°:幅度小、来得快(プリン);左右各晃各的。原版质量在 Blender 里几乎不动"
         "(关节硬,ROE 上 0.35°),按社区想更晃时的做法质量 ×%g(AH1 0.5 → 1.2、AH2 0.1 → 0.4)" % AH_MASS,
         _kit("ah", mass=AH_MASS)),
        ("ah_clothed", "AH 式 着衣用(左右连着,质量 ×%g)" % AH_CLOTHED_MASS,
         "AH 式加原版的「着衣用」关节:左右两块锁在一起,两边一起晃,穿衣服时不会把两胸之间的布扯开。锁在一起比"
         "单边更硬,质量 ×%g 才有 2° 左右的小晃" % AH_CLOTHED_MASS,
         _kit("ah", pair=True, mass=AH_CLOTHED_MASS)),
        ("pmxtailor_s", "PmxTailor 胸(小)",
         "PmxTailor / VRoid2Pmx 的「胸(小)」(按它的源码算):质量 4、阻尼 0.9999、摆动 ±12.5°、扭转 ±25°、"
         "旋转弹簧 187。按 MMD 重力会垂在限位上",
         dict(kind="fixed", mass=4.0, lin_damp=0.9999, ang_damp=0.9999, rot=12.5, twist_limit=25.2, spring_rot=187.2)),
        ("pmxtailor_l", "PmxTailor 胸(大)",
         "PmxTailor「胸(大)」:质量 6.2、阻尼 0.9999、摆动 ±13.5°、扭转 ±27°、旋转弹簧 251",
         dict(kind="fixed", mass=6.2, lin_damp=0.9999, ang_damp=0.9999, rot=13.5, twist_limit=27.4, spring_rot=251.5)),
        ("roe_bustb", "ROE 跳舞(bustB)",
         "ROE 跳舞视频用的:按 MMD 重力 98 定弹簧,静止下垂 15°,上下 / 左右 / 扭转 ±25 / 20 / 5°,阻尼 0.95",
         dict(kind="sag", sag=15.0, twist_sag=4.0, pitch_limit=25.0, yaw_limit=20.0, twist_limit=5.0,
              lin_damp=0.95, ang_damp=0.95, hanging_scale=1.0)),
        ("vdf_b", "Vindictus 归档(B,大摆幅)",
         "15 套 Vindictus PMX 现在的设置:静止下垂 8°、上下 ±25°、阻尼 0.5,摆得大",
         dict(kind="sag", sag=8.0, twist_sag=4.0, pitch_limit=25.0, yaw_limit=15.0, twist_limit=5.0,
              lin_damp=0.5, ang_damp=0.5, hanging_scale=1.0)),
        ("vdf_e", "C 方案(E,稳)",
         "静止下垂 8°、上下 ±18°、阻尼 0.99:约 1 秒停下",
         dict(kind="sag", sag=8.0, twist_sag=4.0, pitch_limit=18.0, yaw_limit=15.0, twist_limit=5.0,
              lin_damp=0.99, ang_damp=0.99, hanging_scale=1.0)),
        ("soft", "柔软", "弹簧弱、晃得慢而大,静止时略垂(插件原有预设)", _fixed(_old("soft"))),
        ("bouncy", "Q弹", "衰减小、带回弹,晃得欢(插件原有预设)", _fixed(_old("bouncy"))),
        ("firm", "紧实", "幅度小、很快停,像穿了运动内衣(插件原有预设)", _fixed(_old("firm"))),
        ("big", "夸张", "更重、衰减很小、幅度大,动漫式大幅甩动(插件原有预设)", _fixed(_old("big"))),
    ],
    ("BUST", "SPRING"): [
        ("k1", "Vindictus 原版(K1)",
         "游戏身体动画蓝图里的参数:刚度 0.05、阻尼 0.5、限角 10.8°、不加重力,胸保持模型原形",
         _k()),
        ("k2", "Vindictus + 手臂碰撞(K2)",
         "K1 再加游戏 DA_Breast 的 6 个手臂胶囊。按游戏数据摆在 A 姿势的模型上会压到胸上部",
         _k(capsules=True)),
        ("k3", "Vindictus + 下半身当本体(K3)",
         "K1,把下半身的移动和转动当成角色整体移动,只传 20% 给胸(游戏里跑跳时的感觉)",
         _k(carrier="下半身")),
        ("cloth", "Vindictus 衣服跟胸", "连衣裙 PCF_003、西装 PCF_009 里衣服跟胸的那对节点:阻尼 0.4,比身体稍弹",
         _k(damping=0.4)),
        ("softer", "软一点", "刚度 0.03、阻尼 0.35、限角 18°:晃得大、停得慢", _k(stiffness=0.03, damping=0.35, limit_angle=18.0)),
        ("firmer", "稳一点", "刚度 0.1、阻尼 0.7、限角 8°:晃得小、停得快", _k(stiffness=0.1, damping=0.7, limit_angle=8.0)),
    ],
    ("BUST", "CLOTH"): [
        ("roe_touch", "ROE 高级场景(戳的时候)",
         "Lynn 高级 H 场景被戳时换上的 Magica 参数:无重力、无阻尼、角度恢复弱、根部限角 35° 到末端 0°。"
         "游戏只在戳后 2 秒内显示,这里一直开着",
         dict(_BC_ROE_TOUCH)),
        ("roe_rest", "ROE 高级场景(平时)",
         "同一场景平时的 Magica 参数:阻尼大、没有角度恢复。游戏里平时不显示(混合权重 0),这里显示出来",
         dict(_BC_ROE_REST)),
    ],
    ("HAIR", "RIGID"): list(_CHAIN_RIGID),
    ("HAIR", "SPRING"): [
        ("vdf_hair", "Vindictus 头发",
         "Fiona 头发的 KawaiiPhysics 节点:刚度 0.2、阻尼 0.35(游戏 0.2–0.5)、不限角、不加重力",
         _k(stiffness=0.2, damping=0.35, limit_angle=0.0, radius_cm=2.0, tip=1.0)),
        ("lively", "飘一点", "刚度 0.1、阻尼 0.2:比游戏飘", _k(stiffness=0.1, damping=0.2, limit_angle=0.0, radius_cm=2.0,
                                                          tip=1.0)),
    ],
    ("HAIR", "CLOTH"): [
        ("hair", "头发", "骨骼布料插件的头发预设:角度恢复 0.3、根 / 梢限角 15 / 50°", dict(_BC_HAIR)),
        ("roe_game", "ROE 大厅头发(游戏原值)", "ROE 大厅模型头发、饰物的 Magica 数值:很稳", dict(_BC_GAME)),
    ],
    ("SKIRT", "RIGID"): list(_CHAIN_RIGID),
    ("SKIRT", "SPRING"): [
        ("vdf_skirt", "Vindictus 裙摆",
         "PCF_005 裙摆的 KawaiiPhysics 节点:刚度 0.2、阻尼 0.3、不限角、半径 4 cm;带腿和胯的碰撞体",
         _k(stiffness=0.2, damping=0.3, limit_angle=0.0, radius_cm=4.0, tip=1.0, colliders=True)),
    ],
    ("SKIRT", "CLOTH"): [
        ("skirt", "裙子(防穿腿)", "骨骼布料插件的裙子预设:角度恢复 0.2、背挡、腿和胯的碰撞体、相邻链连接",
         dict(_BC_SKIRT)),
        ("roe_game", "ROE 游戏原值", "ROE 自己的 Magica 数值(很稳),加腿和胯的碰撞体、相邻链连接",
         dict(_BC_GAME, colliders=True, link=True)),
        ("lively", "飘一点", "角度恢复 0.04(Magica 默认 0.2 实际只用 20%)、根 / 梢限角 45 / 80°、惯性 0.6;"
         "带腿和胯的碰撞体、相邻链连接。手势舞里最大摆 25°,防穿腿预设只摆 7°",
         dict(_BC_SKIRT, restore_stiffness=0.04, restore_attenuation=0.5, limit_root=45.0, limit_tip=80.0,
              inertia=0.6)),
    ],
    ("CLOTH", "RIGID"): list(_CHAIN_RIGID),
    ("CLOTH", "SPRING"): [
        ("vdf_cloth", "Vindictus 衣物", "PCF_008 卫衣衣片的 KawaiiPhysics 节点:刚度 0.2、阻尼 0.6、不限角",
         _k(stiffness=0.2, damping=0.6, limit_angle=0.0, radius_cm=2.0, tip=1.0)),
    ],
    ("CLOTH", "CLOTH"): [
        ("cloth", "布料", "骨骼布料插件的头发预设(饰物、飘带一类)", dict(_BC_HAIR)),
        ("roe_game", "ROE 游戏原值", "ROE 大厅模型饰物的 Magica 数值:很稳", dict(_BC_GAME)),
    ],
}
FX_DEFAULT = {"BUST": ("RIGID", "model"), "HAIR": ("RIGID", "model"), "SKIRT": ("RIGID", "model"),
              "CLOTH": ("RIGID", "model")}


def fx_items(category, method):
    return [(k, label, desc) for k, label, desc, _v in FX.get((category, method), [])]


def fx_values(category, method, key):
    for k, _label, _desc, v in FX.get((category, method), []):
        if k == key:
            return dict(v)
    raise KeyError((category, method, key))


def items(key):
    return [(k, label, desc) for k, label, desc, _v in PRESETS[key]]


def values(key, preset):
    for k, _label, _desc, v in PRESETS[key]:
        if k == preset:
            return v
    raise KeyError(preset)
