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


def items(key):
    return [(k, label, desc) for k, label, desc, _v in PRESETS[key]]


def values(key, preset):
    for k, _label, _desc, v in PRESETS[key]:
        if k == preset:
            return v
    raise KeyError(preset)
