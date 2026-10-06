"""测试、对比视频、截图脚本的默认值(本机路径),都在这一个地方;每一项都可以用环境变量改。

模型和动作不在仓库里(游戏导出的模型、下载的模型和舞蹈),换机器时用环境变量指过去。
"""
import os


def _env(name, default):
    return os.environ.get(name) or default


# 插件目录的上一层:Blender 里 sys.path 加上它就能 import mmd_physics
ADDON_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BLENDER = _env("MMDPHYS_BLENDER", r"D:\Program Files\blender-3.6.15-windows-x64\blender.exe")
FFMPEG = _env("MMDPHYS_FFMPEG", "ffmpeg")
FONT = _env("MMDPHYS_FONT", "C\\:/Windows/Fonts/msyh.ttc")          # ffmpeg drawtext 的写法(冒号要转义)

_DANCE = r"E:\Downloads\mmd\0.meeynara手势舞2025.2.14by小王动画"
VMD = _env("MMDPHYS_VMD", os.path.join(_DANCE, "适配瓦雷莎.vmd"))      # 手势舞,10 秒
WAV = _env("MMDPHYS_WAV", os.path.join(_DANCE, "meeynara手势舞2026.2.14.WAV"))
MARGIN = 30                                                           # VMD 导入的 margin:开头 30 帧过渡
# 腿动得大的舞(裙子的布面):抬腿到 55 cm、整整转一圈、前后走 1.5 米,11 秒
_DANCE_LEGS = r"E:\Downloads\mmd\野狼disco扭一扭2026.8.27by小王动画_by_小王动画"
VMD_LEGS = _env("MMDPHYS_VMD_LEGS", os.path.join(_DANCE_LEGS, "适配【原神】瓦雷莎.vmd"))
WAV_LEGS = _env("MMDPHYS_WAV_LEGS", os.path.join(_DANCE_LEGS, "BGM.wav"))

# 三种骨架:Vindictus(breast_physics + 36 根软组织骨,裙子 14 链)、ROE(左胸,裸体)、乳奶模板(单根胸骨,外套骨贴腿)
MODELS = {
    "vindictus": _env("MMDPHYS_PMX_VINDICTUS", r"E:\game_export\Vindictus\Fiona\pmx\PCF_005\PCF_005.pmx"),
    "roe": _env("MMDPHYS_PMX_ROE", r"E:\game_export\RiseOfEros\Lynn\pmx\pc_j01_nk_bs\pc_j01_nk_bs_bustB.pmx"),
    "template": _env("MMDPHYS_PMX_TEMPLATE",
                     r"E:\Downloads\2026.6\2026gantz\Gantz Reika Suit 18\Gantz Reika Suit 18 V1.pmx"),
}

# 「按衣服推荐」的样本(Vindictus):卫衣 = 衣服只跟一部分,钢甲 = 胸骨不带网格
OUTFIT = {
    "hoodie": _env("MMDPHYS_PMX_HOODIE", r"E:\game_export\Vindictus\Fiona\pmx\PCF_008\PCF_008.pmx"),
    "suit": _env("MMDPHYS_PMX_SUIT", r"E:\game_export\Vindictus\Fiona\pmx\PCF_009\PCF_009.pmx"),
    "armor": _env("MMDPHYS_PMX_ARMOR", r"E:\game_export\Vindictus\Fiona\pmx\PCF_067\PCF_067.pmx"),
}

# 「原来不动的链」的样本(下载的转换模型,头发没有刚体;要 MMD 骨名才跳得动,XPS 骨名的套不上舞蹈)
_WORK10 = r"E:\Downloads\2026.6\2026\work10"
STILL = {
    "bunny": _env("MMDPHYS_PMX_BUNNY", _WORK10 + r"\FFVII Tifa as Bunny (Apex Predator) - TFD\Bunny.pmx"),
    "suit": _env("MMDPHYS_PMX_SUIT2", _WORK10 + r"\Tifa as Gantz O Reika Suit V2\Suit V2.pmx"),
}

OUT = _env("MMDPHYS_OUT", r"E:\game_export\_mmd_physics\效果对比")      # 对比视频
SHOTS = _env("MMDPHYS_SHOTS", r"E:\game_export\_mmd_physics\使用说明素材")  # 面板截图
