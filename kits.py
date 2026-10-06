"""胸部多段刚体套件(渲染用):把模型原来的胸部刚体整套换成社区的结构。效果烘焙时建,还原时删。

套件的数值照原文件逐字段抄(PMX 单位、左侧、角度用度),右侧按 X 镜像:
- RGBA 式 1.5β(rgba):mmd_jiggle_bones 附带的 RGBA_L.pmx(「RGBA式おっぱい剛体 VerVer1.5β」,作者声明
  "構造は自由にお使いください")。每侧 6 个刚体、9 个关节,弹簧全 0:主刚体之外都是不绑骨的辅助刚体,
  关节把它们互相锁住(两处平移上下限相等且不为 0,把胸托高),整个结构没有自由度,靠 MMD 关节「软」、解算有误差
  才晃。Blender 的关节硬,物理步长要粗(MMD 的 60 Hz),托高要减(见 docs)。
- Tda 式(tda):Tda式ミクAP改変 的 胸上 → 胸上2(尖端可前后平移,平移弹簧 200)+ 胸下 + 補助关节,旋转弹簧 100。
  本机三个 Tda 改模(ミク / ルカ / ハク)的胸部网格都只刷在「胸上2」上,胸上、胸下只是辅助刚体;这里 胸上2 绑在
  模型的胸骨上,和原版一样。
- 欧美转换式(western):Leberx44qa / KittyInHiding 一系 XPS 转 PMX 的 Boob → boobs 2 → boobs 3:质量 0.8、阻尼 0.9999,
  旋转弹簧 150 / 400、可平移约 ±0.04 单位加平移弹簧 400 / 150,上下只往下摆 20°(本机 Android 18 的数值)。
  原版三段骨各带一块权重,但根骨 boobs left 不归物理管,第二、三段的刚体锁在一起:动起来就是一整块,和这里
  只驱动模型自己的胸骨一样。
- AH 式(ah):Chainsaw Man Makima by Animanpower(HS2 转 PMX)上的 AH式(アローヘッド):胸操作(跟骨)经「調整用」
  关节挂一个胶囊「接続」,AH1(胸根,带权重的「胸」)、AH2(胸先)、衝突 三个刚体锁在接続上,整块只靠这一个关节
  动:只能往上平移 0.3、上下转 ±20°、左右转 ±10°,弹簧很硬(平移 5000 / 800 / 200,旋转 2500 / 500 / 100),阻尼
  0.9999 / 0.99:幅度小、来得快的「プリン」晃。原版也只有「胸」(AH1)带权重。「着衣用」两个关节把左右的 AH2 锁在
  一起,两边一起晃(原版穿衣服时用;link_sides,面板的「左右连着」)。Makima 移植时整套朝正前方、乳尖却偏外 24°;
  这里按原版「胸先 = 乳尖」让 AH 轴对着乳尖,比例照 Makima(胸根到乳尖 1.2、到 AH2 1.5)。

装到模型上(每条胸链一套,chains.BustChain):
- 支点 = 链根骨的骨头(左胸 / breast_physics_01 / 乳奶1);乳尖 = 链上的骨带的顶点里最靠前的一撮。
- 模板的「胸根 → 乳尖」对到模型的「支点 → 乳尖」:先绕竖轴转、再按上下倾角转(不滚)、等比缩放;刚体大小、
  平移限位跟着缩放,旋转弹簧 × 缩放²(和 mmd_like 换算单位的道理一样),平移弹簧不变。模板的胸根、乳尖按同一
  规则取:胸根 = 胸链根骨的骨头,乳尖 = 带权重的顶点里最靠前的一撮(RGBA 没有网格:主刚体的前表面,同 mmd_jiggle_bones)。
- 主刚体绑在链上第一根原来就摆的骨上(Breast_L02 / breast_physics_02 / 乳奶1),锚刚体跟它的父骨;
  其余刚体不绑骨(mmd_tools 建物理时按关节把它们挂到锚上摆位)。
- 原来链上的摆动刚体改成跟骨(chains.ORIG_TYPE 记原类型,效果还原时写回);套件建的刚体 / 关节带 TAG,
  建物理以后设成谁都不碰(no_collisions),还原时 remove() 删掉。
坐标换算和 mmd_tools 导入 PMX 一样:位置 xzy,欧拉角 YXZ、xzy 取反,旋转限位上下限对调取反。
"""

import math

from mathutils import Euler, Matrix, Vector

from . import chains

TAG = "mmd_physics_kit"             # 套件建的刚体 / 关节上:套件键

RGBA = dict(
    label="RGBA 式 1.5β",
    source="mmd_jiggle_bones 附带的 RGBA_L.pmx(RGBA式おっぱい剛体 VerVer1.5β)",
    step_hz=60,                                 # 要 MMD 的粗步长才晃(效果的「物理步长」自动时用)
    root=(0.4478, 15.1373, -0.626),            # 胸根(模板「左胸」骨头 = 主关节)
    front=(0.7739, 15.1624, -1.5001),           # 乳尖:主刚体「胸」的前表面(前、前後 刚体在更前面 0.2)
    bodies=[
        dict(name="上半身2", role="anchor", shape=2, size=(0.45, 1.8, 0.0), pos=(0.57, 15.2128, -0.1992),
             rot=(7.41, -0.78, -6.0), mass=1.0, lin=0.5, ang=0.5, mode=0),
        dict(name="後", role=None, shape=0, size=(0.3, 0.0, 0.0), pos=(0.4478, 15.1373, -0.626),
             rot=(-4.27, 69.42, -88.4), mass=1.0, lin=0.9, ang=0.9, mode=1),
        dict(name="回転", role=None, shape=0, size=(0.45, 0.0, 0.0), pos=(0.6167, 15.1503, -1.0787),
             rot=(-4.27, 69.42, -88.4), mass=1.0, lin=0.9, ang=0.9, mode=2),
        dict(name="前", role=None, shape=0, size=(0.35, 0.0, 0.0), pos=(0.84, 15.15, -1.7),
             rot=(-4.27, 69.42, -88.4), mass=1.0, lin=0.99, ang=0.99, mode=1),
        dict(name="前後", role=None, shape=0, size=(0.4, 0.0, 0.0), pos=(0.84, 15.15, -1.7),
             rot=(-4.27, 69.42, -88.4), mass=1.0, lin=0.9, ang=0.9, mode=1),
        dict(name="胸", role="main", shape=0, size=(0.45, 0.0, 0.0), pos=(0.6167, 15.1503, -1.0787),
             rot=(-4.27, 69.42, -88.4), mass=1.0, lin=0.9, ang=0.9, mode=1),
    ],
    joints=[
        dict(name="後1", a="上半身2", b="後", pos=(0.08, 15.15, 0.35), rot=(0.0, -20.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="後2", a="後", b="胸", pos=(0.4478, 15.1373, -0.626), rot=(0.0, -20.0, 0.0),
             tmin=(0.0, 0.3, 1.0), tmax=(0.0, 0.3, 0.0), rmin=(1.0, 1.0, 1.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="回転1", a="上半身2", b="回転", pos=(0.4478, 15.1373, -0.626), rot=(0.0, -20.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(-45.0, -60.0, -15.0), rmax=(45.0, 60.0, 15.0)),
        dict(name="前1", a="上半身2", b="前", pos=(0.4478, 15.1373, -0.626), rot=(0.0, -20.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="前2", a="前", b="回転", pos=(0.84, 15.15, -1.7), rot=(0.0, -20.0, 0.0),
             tmin=(0.0, 0.33, 0.0), tmax=(0.0, 0.33, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="回転2", a="回転", b="胸", pos=(0.84, 15.15, -1.7), rot=(0.0, -20.0, 0.0),
             tmin=(1.0, 1.0, 1.0), tmax=(0.0, 0.0, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="前後1", a="上半身2", b="前後", pos=(0.84, 16.73, -1.7), rot=(0.0, -20.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="前後2", a="前後", b="胸", pos=(0.84, 15.15, -1.7), rot=(0.0, -20.0, 0.0),
             tmin=(1.0, 1.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(1.0, 1.0, 1.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="胸", a="上半身2", b="胸", pos=(0.4478, 15.1368, -0.626), rot=(0.0, -20.0, 0.0),
             tmin=(-0.5, -0.5, -0.4), tmax=(0.5, 0.5, 0.3), rmin=(-45.0, -60.0, -15.0), rmax=(45.0, 60.0, 15.0)),
    ],
)

TDA = dict(
    label="Tda 式",
    source="Tda式ミクAP改変 モリガン風 Ver1.08(Tda式ミクBB R-18.pmx)的 胸上 / 胸上2 / 胸下",
    root=(0.4364, 15.6448, -0.4849),           # 胸上 的关节(骨头)
    front=(0.7936, 15.3672, -1.589),            # 胸上 / 胸上2 / 胸下 带的顶点里最靠前的一撮
    bodies=[
        dict(name="胸", role="anchor", shape=2, size=(0.6, 0.8, 1.8739), pos=(0.0, 15.2851, -0.7016),
             rot=(0.0, 0.0, 89.98), mass=1.0, lin=0.0, ang=0.0, mode=0),
        dict(name="胸上", role=None, shape=2, size=(0.1, 0.6, 0.0), pos=(0.55, 15.6818, -0.75), rot=(15.0, 75.0, 90.0),
             mass=0.1, lin=0.99, ang=0.99, mode=1),
        dict(name="胸上2", role="main", shape=0, size=(0.35, 0.8884, 0.0), pos=(0.6328, 15.2531, -1.0751),
             rot=(0.0, 0.0, 0.0), mass=0.4, lin=0.99, ang=0.99, mode=1),
        dict(name="胸下", role=None, shape=2, size=(0.1, 0.8, 0.0), pos=(0.55, 14.7767, -0.75), rot=(0.0, 80.0, -85.0),
             mass=0.1, lin=0.99, ang=0.99, mode=1),
    ],
    joints=[
        dict(name="胸上", a="胸", b="胸上", pos=(0.4364, 15.6448, -0.4849), rot=(5.04, 0.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(-35.0, -10.0, -5.0), rmax=(15.0, 10.0, 5.0),
             tspring=(0.0, 0.0, 0.0), rspring=(100.0, 100.0, 100.0)),
        dict(name="胸上2", a="胸上", b="胸上2", pos=(0.6437, 15.6797, -1.0717), rot=(5.8, 0.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 20.0, 0.2), rmin=(-35.0, 0.0, 0.0), rmax=(35.0, 0.0, 0.0),
             tspring=(0.0, 0.0, 200.0), rspring=(20.0, 0.0, 0.0)),
        dict(name="胸下", a="胸", b="胸下", pos=(0.4581, 14.7432, -0.4062), rot=(5.04, 0.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(-35.0, -10.0, -5.0), rmax=(15.0, 10.0, 5.0),
             tspring=(0.0, 0.0, 0.0), rspring=(100.0, 100.0, 100.0)),
        dict(name="補助", a="胸上2", b="胸下", pos=(0.6341, 14.8463, -1.1731), rot=(5.8, 0.0, 0.0),
             tmin=(-0.1, 0.0, 0.0), tmax=(0.1, 20.0, 0.1), rmin=(-40.0, 0.0, 0.0), rmax=(40.0, 0.0, 0.0),
             tspring=(200.0, 0.0, 200.0), rspring=(20.0, 0.0, 0.0)),
    ],
)

WESTERN = dict(
    label="欧美 XPS 转换式",
    source="Leberx44qa / KittyInHiding 一系的 XPS 转 PMX(本机 Android 18 (Supergirl Malfunction))的 Boob_L 三段",
    root=(0.475, 15.265, 0.112),               # 胸链根骨 boobs left 的骨头
    front=(1.198, 15.3657, -1.9266),            # boobs left / 2 / 3 带的顶点里最靠前的一撮
    bodies=[
        dict(name="上半身2", role="anchor", shape=1, size=(0.87, 0.87, 0.348), pos=(0.0, 15.4441, 0.198),
             rot=(9.45, 0.0, 0.0), mass=1.0, lin=0.5, ang=0.5, mode=0),
        dict(name="Boob", role=None, shape=2, size=(0.609, 0.1305, 0.0), pos=(0.7892, 15.2755, -0.8421),
             rot=(-0.03, 158.58, 89.95), mass=0.8, lin=0.9999, ang=0.999, mode=1),
        dict(name="boobs2", role="main", shape=0, size=(0.7, 0.0, 0.0), pos=(0.9914, 14.8002, -1.1132),
             rot=(0.0, 0.0, 0.0), mass=0.8, lin=0.999, ang=0.999, mode=1),
        dict(name="boobs3", role=None, shape=2, size=(0.7, 0.0396, 0.0), pos=(0.9985, 14.8056, -1.1014),
             rot=(27.42, 5.91, 12.66), mass=0.8, lin=0.999, ang=0.999, mode=1),
    ],
    joints=[
        dict(name="Boob", a="上半身2", b="Boob", pos=(0.5721, 15.4042, 0.0339), rot=(-0.38, -15.8, 0.11),
             tmin=(-0.0435, -0.0435, -0.0087), tmax=(0.0435, 0.087, 0.0087), rmin=(-20.0, -25.0, -1.0),
             rmax=(0.0, 25.0, 1.0), tspring=(400.0, 150.0, 150.0), rspring=(150.0, 400.0, 0.0)),
        dict(name="boobs2", a="Boob", b="boobs2", pos=(0.7512, 15.5152, -0.7665), rot=(0.0, 0.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(-20.0, -25.0, -1.0), rmax=(0.0, 25.0, 1.0),
             tspring=(400.0, 150.0, 150.0), rspring=(150.0, 400.0, 0.0)),
        dict(name="boobs3", a="boobs2", b="boobs3", pos=(0.9219, 15.5885, -1.1507), rot=(0.0, 0.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
    ],
)

AH = dict(
    label="AH 式",
    source="Chainsaw Man Makima by Animanpower(HS2 转 PMX)上的 AH式(アローヘッド):胸操作 → 接続 + AH1 / AH2 / 衝突",
    root=(0.6316, 15.1108, -0.6249),           # AH1(带权重的「胸」)的骨头 = 胸根
    front=(0.6316, 15.1108, -1.8239),           # 胸根沿 AH 轴(正前方)量出到乳尖的距离 1.199:AH 轴对着乳尖
    bodies=[
        dict(name="胸操作", role="anchor", shape=1, size=(0.1, 0.1, 0.1), pos=(0.6316, 15.1108, -0.8379),
             rot=(0.0, 0.0, 0.0), mass=1.0, lin=0.5, ang=0.5, mode=0),
        dict(name="AH1", role="main", shape=0, size=(0.3, 0.0, 0.0), pos=(0.6316, 15.1108, -0.6249),
             rot=(0.0, 0.0, 0.0), mass=0.4, lin=0.9999, ang=0.99, mode=1),
        dict(name="AH2", role=None, shape=0, size=(0.3, 0.0, 0.0), pos=(0.6316, 15.1108, -2.1399),
             rot=(0.0, 0.0, 0.0), mass=0.1, lin=0.9999, ang=0.99, mode=1),
        dict(name="接続", role=None, shape=2, size=(0.1, 1.515, 0.0), pos=(0.6316, 15.1108, -1.3824),
             rot=(0.0, 90.0, -90.0), mass=0.1, lin=0.9999, ang=0.99, mode=1),
        dict(name="衝突", role=None, shape=0, size=(0.4, 0.0, 0.0), pos=(0.6316, 15.1108, -0.9579),
             rot=(0.0, 0.0, 0.0), mass=0.1, lin=0.9999, ang=0.99, mode=1),
    ],
    joints=[
        dict(name="調整用", a="胸操作", b="接続", pos=(0.6316, 15.1108, -0.8379), rot=(0.0, 0.0, 0.0), main=True,
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.3, 0.0), rmin=(-20.0, -10.0, 0.0), rmax=(20.0, 10.0, 0.0),
             tspring=(5000.0, 800.0, 200.0), rspring=(2500.0, 500.0, 100.0)),
        dict(name="接続", a="接続", b="衝突", pos=(0.6316, 15.1108, -0.9579), rot=(0.0, 0.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="AH1", a="AH1", b="接続", pos=(0.6316, 15.1108, -0.6249), rot=(0.0, 0.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="AH2", a="AH2", b="接続", pos=(0.6316, 15.1108, -2.1399), rot=(0.0, 0.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="接続*1", a="衝突", b="接続", pos=(0.6316, 15.1108, -0.9579), rot=(0.0, 0.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="AH1*1", a="接続", b="AH1", pos=(0.6316, 15.1108, -0.6249), rot=(0.0, 0.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
        dict(name="AH2*1", a="接続", b="AH2", pos=(0.6316, 15.1108, -2.1399), rot=(0.0, 0.0, 0.0),
             tmin=(0.0, 0.0, 0.0), tmax=(0.0, 0.0, 0.0), rmin=(0.0, 0.0, 0.0), rmax=(0.0, 0.0, 0.0)),
    ],
    # 左右之间(link_sides):左 AH2 ↔ 右 AH2 全锁(原版「着衣用」,正反各一个),关节在两个 AH2 正中间
    pairs=[dict(name="着衣用", body="AH2"), dict(name="着衣用-", body="AH2", reverse=True)],
)

KITS = {"rgba": RGBA, "tda": TDA, "western": WESTERN, "ah": AH}


def items():
    return [(k, v["label"], v["source"]) for k, v in KITS.items()]


def has_pairs(key):
    """这个套件有没有左右之间的关节(AH 式「着衣用」)。"""
    return bool(KITS.get(key, {}).get("pairs"))


def step_hz(key):
    """这个套件要的物理步长(每秒步数),0 = 不挑。"""
    return int(KITS.get(key, {}).get("step_hz", 0))


# -- 模板:PMX → Blender ----------------------------------------------------------------------------------
def _mirror(kit):
    """左 → 右:X 取反;欧拉角 Y、Z 取反;关节的 X 平移、Y / Z 旋转限位取反对调(自由轴 下限 > 上限 仍是自由)。"""
    def flip(lo, hi, axes):
        lo, hi = list(lo), list(hi)
        for k in axes:
            lo[k], hi[k] = -hi[k], -lo[k]
        return tuple(lo), tuple(hi)

    out = dict(kit, root=(-kit["root"][0],) + tuple(kit["root"][1:]),
               front=(-kit["front"][0],) + tuple(kit["front"][1:]), bodies=[], joints=[])
    for b in kit["bodies"]:
        out["bodies"].append(dict(b, pos=(-b["pos"][0], b["pos"][1], b["pos"][2]),
                                  rot=(b["rot"][0], -b["rot"][1], -b["rot"][2])))
    for j in kit["joints"]:
        tmin, tmax = flip(j["tmin"], j["tmax"], (0,))
        rmin, rmax = flip(j["rmin"], j["rmax"], (1, 2))
        out["joints"].append(dict(j, pos=(-j["pos"][0], j["pos"][1], j["pos"][2]),
                                  rot=(j["rot"][0], -j["rot"][1], -j["rot"][2]),
                                  tmin=tmin, tmax=tmax, rmin=rmin, rmax=rmax))
    return out


def side_kit(key, side):
    kit = KITS[key]
    return kit if side == "L" else _mirror(kit)


def _xzy(v):
    return Vector((v[0], v[2], v[1]))


def _pmx_matrix(pos, rot_deg):
    """PMX 位置 + 欧拉角(度)→ Blender 的 4×4(PMX 单位),同 mmd_tools 导入。"""
    r = Vector([math.radians(x) for x in rot_deg]).xzy * -1
    return Matrix.Translation(_xzy(pos)) @ Euler(r, "YXZ").to_matrix().to_4x4()


# -- 模型上的位置 -------------------------------------------------------------------------------------------
def _weighted_points(arm, bones, threshold=0.3):
    """链上的骨带(权重和 > threshold)的顶点,世界坐标(静止网格)。"""
    root = chains.mmd_root(arm)
    bones = set(bones)
    out = []
    for o in (root.children_recursive if root is not None else ()):
        if o.type != "MESH" or not o.vertex_groups:
            continue
        idx = {g.index for g in o.vertex_groups if g.name in bones}
        if not idx:
            continue
        mw = o.matrix_world
        for v in o.data.vertices:
            w = sum(g.weight for g in v.groups if g.group in idx)
            if w > threshold:
                out.append(mw @ v.co)
    return out


def breast_frame(arm, chain, side_bones=None):
    """(支点, 乳尖),世界坐标。乳尖 = 最靠前(-Y)的 3% 顶点的平均;没有带权重的顶点就用链上最远的骨尾。
    side_bones:同侧所有胸链的骨。乳奶模板每侧上下两根骨各是一条链,各自带的那块网格找不准乳尖(上面那块的
    最前面在外侧),整侧一起找。"""
    mw = arm.matrix_world
    pivot = mw @ arm.data.bones[chain.root].head_local
    pts = _weighted_points(arm, side_bones or chain.bones)
    if len(pts) >= 8:
        pts.sort(key=lambda p: p.y)
        k = max(4, len(pts) // 33)
        apex = sum(pts[:k], Vector()) / k
    else:
        tails = [mw @ arm.data.bones[n].tail_local for n in chain.bones]
        apex = max(tails, key=lambda p: (p - pivot).length)
    return pivot, apex


def side_apexes(arm, side_bones):
    """每侧的乳尖 {侧: 世界坐标};两侧都有时取镜像平均(骨架空间 X 取反),两侧套件严格对称。网格权重本身左右
    差一点,各找各的乳尖会让套件左右差 1-2°,宽松的套件(RGBA)摆幅就差出三成。"""
    inv = arm.matrix_world.inverted()
    local = {}
    for side, bones in side_bones.items():
        pts = _weighted_points(arm, bones)
        if len(pts) < 8:
            continue
        pts.sort(key=lambda q: q.y)
        k = max(4, len(pts) // 33)
        local[side] = inv @ (sum(pts[:k], Vector()) / k)
    if "L" in local and "R" in local:
        a = (local["L"] + Vector((-local["R"].x, local["R"].y, local["R"].z))) / 2.0
        local = {"L": a, "R": Vector((-a.x, a.y, a.z))}
    return {side: arm.matrix_world @ v for side, v in local.items()}


def main_bone(arm, chain, bodies=None):
    """链上第一根原来就有摆动刚体的骨(先序);没有就是链根。"""
    dyn = chains.dynamic_bones(arm, bodies)
    return next((n for n in chain.bones if n in dyn), chain.root)


def _aim(v):
    """把 +X 转到方向 v 的旋转(先仰角、再绕竖轴,不滚),和这两个角。"""
    yaw = math.atan2(v.y, v.x)
    pitch = math.atan2(v.z, math.hypot(v.x, v.y))
    return Matrix.Rotation(yaw, 4, "Z") @ Matrix.Rotation(-pitch, 4, "Y"), yaw, pitch


def fit(kit, pivot, apex):
    """模板(PMX 单位)→ 世界的变换 T、缩放 s、转了多少度(绕竖轴, 上下):胸根 → 支点,胸根→乳尖 转到 支点→乳尖。"""
    root, front = _xzy(kit["root"]), _xzy(kit["front"])
    a, b = (front - root), (apex - pivot)
    s = b.length / a.length
    ra, ya, pa = _aim(a)
    rb, yb, pb = _aim(b)
    T = Matrix.Translation(pivot) @ rb @ ra.inverted() @ Matrix.Scale(s, 4) @ Matrix.Translation(-root)
    return T, s, (math.degrees(yb - ya), math.degrees(pb - pa))


# -- 建 / 删 ---------------------------------------------------------------------------------------------
def _is_main_joint(kit, j):
    """主关节(「幅度 ×」改它):套件里标了 main 的那个;没标就是 锚 → 主刚体。"""
    if any(x.get("main") for x in kit["joints"]):
        return bool(j.get("main"))
    role = {b["name"]: b["role"] for b in kit["bodies"]}
    return role.get(j["a"]) == "anchor" and role.get(j["b"]) == "main"


def _loc_rot(world):
    """矩阵 → (位置, 欧拉角 YXZ),去掉缩放。"""
    loc, rot, _scale = world.decompose()
    return loc, rot.to_euler("YXZ")


def build(model, arm, chain, key, scale=1.0, limit_scale=1.0, lift=1.0, mass_scale=1.0, damping=None,
          pmx_scale=12.5, side_bones=None, apex=None, prefix=None):
    """在一条胸链上建一套 key 套件。scale:在自动缩放上再乘;limit_scale:主关节的平移 / 旋转限位乘(mmd_jiggle_bones
    的「抖动强度」只改这个);lift:平移上下限相等且不为 0 的轴(RGBA 把胸托高的两处)乘;damping:(移动, 旋转) 覆盖
    主刚体和锚的阻尼;pmx_scale:Blender → PMX 的倍数(导入 0.08 = 12.5);side_bones:同侧所有胸链的骨(找乳尖);
    apex:直接给乳尖(side_apexes 的左右对称结果)。返回说明。"""
    kit = side_kit(key, chain.side)
    if apex is None:
        pivot, apex = breast_frame(arm, chain, side_bones)
    else:
        pivot = arm.matrix_world @ arm.data.bones[chain.root].head_local
    T, s, theta = fit(kit, pivot, apex)
    if scale != 1.0:
        T = T @ Matrix.Translation(_xzy(kit["root"])) @ Matrix.Scale(scale, 4) @ Matrix.Translation(-_xzy(kit["root"]))
    s *= scale
    s_rel = s * pmx_scale                       # 套件比模板大多少(按模型自己的 PMX 单位)
    main = main_bone(arm, chain)
    parent = arm.data.bones[main].parent
    anchor_bone = parent.name if parent is not None else chain.root
    # 名字以数字开头:Blender 退出时按名字顺序释放对象,刚体要排在关节(J.)和 mmd_tools 的不碰撞约束(ncc)前面,
    # 否则约束先删了,刚体释放时还去读它(btRigidBody::removeConstraintRef),偶尔崩溃(PCF_005 渲完退出时见过)
    tag = prefix or ("0kit_%s.%s.%s" % (key, chain.side, chain.root))
    grp = model.rigidGroupObject()
    gw = grp.matrix_world.inverted()
    made, world = {}, {}
    for b in kit["bodies"]:
        world[b["name"]] = tuple((T @ _pmx_matrix(b["pos"], b["rot"])).translation)
        W = gw @ T @ _pmx_matrix(b["pos"], b["rot"])
        loc, rot = _loc_rot(W)
        size = Vector(b["size"]) * s
        if b["shape"] == 1:
            size = size.xzy
        bone = main if b["role"] == "main" else anchor_bone if b["role"] == "anchor" else None
        lin, ang = (b["lin"], b["ang"]) if damping is None or b["role"] is None else damping
        o = model.createRigidBody(
            shape_type=b["shape"], location=loc, rotation=rot, size=size, dynamics_type=b["mode"],
            collision_group_number=15, collision_group_mask=[True] * 16,
            name="%s.%s" % (tag, b["name"]), bone=bone, mass=b["mass"] * mass_scale, friction=0.5,
            linear_damping=lin, angular_damping=ang, bounce=0.0)
        o[TAG] = key
        made[b["name"]] = o
    jgrp = model.jointGroupObject()
    jw = jgrp.matrix_world.inverted()
    joints = []
    for j in kit["joints"]:
        W = jw @ T @ _pmx_matrix(j["pos"], j["rot"])
        loc, rot = _loc_rot(W)
        k = limit_scale if _is_main_joint(kit, j) else 1.0
        tmin, tmax = Vector(j["tmin"]), Vector(j["tmax"])
        rmin, rmax = Vector([math.radians(x) for x in j["rmin"]]), Vector([math.radians(x) for x in j["rmax"]])
        if lift != 1.0:                         # 上下限相等且不为 0 = 固定偏移(托高)
            fixed = [lo == hi and lo != 0.0 for lo, hi in zip(tmin, tmax)]
            tmin = Vector([lo * lift if f else lo for lo, f in zip(tmin, fixed)])
            tmax = Vector([hi * lift if f else hi for hi, f in zip(tmax, fixed)])
        free_t = [lo > hi for lo, hi in zip(tmin, tmax)]
        free_r = [lo > hi for lo, hi in zip(rmin, rmax)]
        tmin = Vector([lo if f else lo * k for lo, f in zip(tmin, free_t)])
        tmax = Vector([hi if f else hi * k for hi, f in zip(tmax, free_t)])
        rmin = Vector([lo if f else lo * k for lo, f in zip(rmin, free_r)])
        rmax = Vector([hi if f else hi * k for hi, f in zip(rmax, free_r)])
        ts, rs = j.get("tspring", (0.0, 0.0, 0.0)), j.get("rspring", (0.0, 0.0, 0.0))
        o = model.createJoint(
            location=loc, rotation=rot, rigid_a=made[j["a"]], rigid_b=made[j["b"]],
            maximum_location=tmax.xzy * s, minimum_location=tmin.xzy * s,
            maximum_rotation=rmin.xzy * -1, minimum_rotation=rmax.xzy * -1,
            spring_linear=Vector(ts).xzy, spring_angular=Vector(rs).xzy * (s_rel * s_rel),
            name="%s.%s" % (tag, j["name"]))
        o[TAG] = key
        joints.append(o)
    return {"chain": chain.root, "side": chain.side, "main": main, "anchor": anchor_bone, "scale": s, "rel": s_rel,
            "yaw": theta[0], "pitch": theta[1], "pivot": tuple(pivot), "apex": tuple(apex), "bodies": len(made),
            "joints": len(joints), "objects": {k: o.name for k, o in made.items()}, "world": world}


def link_sides(model, key, left, right):
    """左右两套之间的关节(AH 式「着衣用」:左右 AH2 锁死,两边一起晃)。left / right:两侧 build() 的返回。
    关节全锁,朝向不影响,放在两个刚体正中间。返回个数。"""
    import bpy
    pairs = KITS[key].get("pairs", ())
    jw = model.jointGroupObject().matrix_world.inverted()
    tag = "0kit_%s.LR.%s.%s" % (key, left["chain"], right["chain"])
    n = 0
    for p in pairs:
        a = bpy.data.objects[left["objects"][p["body"]]]
        b = bpy.data.objects[right["objects"][p["body"]]]
        if p.get("reverse"):
            a, b = b, a
        mid = (Vector(left["world"][p["body"]]) + Vector(right["world"][p["body"]])) / 2.0
        loc, rot = _loc_rot(jw @ Matrix.Translation(mid))
        o = model.createJoint(
            location=loc, rotation=rot, rigid_a=a, rigid_b=b, maximum_location=Vector(), minimum_location=Vector(),
            maximum_rotation=Vector(), minimum_rotation=Vector(), spring_linear=Vector(), spring_angular=Vector(),
            name="%s.%s" % (tag, p["name"]))
        o[TAG] = key
        n += 1
    return n


def no_collisions(model):
    """建物理以后:套件的刚体谁都不碰(不在任何碰撞层)。返回个数。"""
    n = 0
    for o in model.rigidBodies():
        if o.get(TAG) and o.rigid_body is not None:
            o.rigid_body.collision_collections = [False] * 20
            n += 1
    return n


def remove(model):
    """删掉套件建的刚体和关节:先删刚体(删的时候摘掉它挂着的约束引用,约束还在),再删关节。返回个数。"""
    import bpy
    objs = [o for o in list(model.rigidBodies()) + list(model.joints()) if o.get(TAG)]
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    return len(objs)
