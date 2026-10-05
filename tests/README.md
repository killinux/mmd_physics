# 测试和对比视频

插件改完以后,用这里的脚本检查有没有改坏,以及重新出对比视频、使用说明的截图。
都在后台 Blender 3.6 里跑(截图除外),需要 mmd_tools。

## 路径

模型和舞蹈不在仓库里(游戏导出的模型、下载的模型和舞蹈),默认路径都写在 [`config.py`](config.py) 一个地方,
每一项都能用环境变量改:

| 环境变量 | 默认 | 用途 |
|---|---|---|
| `MMDPHYS_BLENDER` | `D:\Program Files\blender-3.6.15-windows-x64\blender.exe` | 跑脚本的 Blender |
| `MMDPHYS_VMD` / `MMDPHYS_WAV` | 手势舞 `适配瓦雷莎.vmd` 和它的音乐 | 动作(10 秒),视频配乐 |
| `MMDPHYS_PMX_VINDICTUS` | Vindictus Fiona `PCF_005.pmx` | breast_physics + 36 根软组织骨;裙子 14 链、头发 36 组、羽毛 |
| `MMDPHYS_PMX_ROE` | ROE Lynn `pc_j01_nk_bs_bustB.pmx` | 左胸 / 右胸 骨架(裸体) |
| `MMDPHYS_PMX_TEMPLATE` | `Gantz Reika Suit 18 V1.pmx` | 乳奶模板(单根胸骨);外套的骨骼贴着腿走 |
| `MMDPHYS_OUT` | `E:\game_export\_mmd_physics\效果对比` | 对比视频 |
| `MMDPHYS_SHOTS` | `E:\game_export\_mmd_physics\使用说明素材` | 面板截图 |
| `MMDPHYS_FFMPEG` | `ffmpeg` | 拼视频 |

## 检查(改完插件跑一遍)

```
python tests\run_checks.py                  全部,约 10 分钟
python tests\run_checks.py detect kawaii    只跑其中几项
```

每项一个后台 Blender,输出 `PASS ...` / `FAIL ...`,最后汇总;有失败返回 1。完整输出在系统临时目录的
`mmd_physics_checks\` 下。

| 检查 | 脚本 | 通过的标准 | 本机结果(10-05) |
|---|---|---|---|
| detect | `check_detect.py` | 三种骨架的胸链左右都认到 | Vindictus 2 条、ROE 2 条、乳奶模板 4 条单骨 |
| kawaii | `check_kawaii.py` | 新版 `kawaii.bake()` 和 0.2.0 版([`kawaii_v020_reference.py`](kawaii_v020_reference.py))逐帧一样;别的骨架也能动 | 518 条曲线差 0 |
| effects | `check_effects.py` | 几种方式各算一遍,点「还原」后刚体、关节、动作、重力和原来逐项一样,不留碰撞体、工作动作 | 0 处不同 |
| skirt | `check_skirt.py` | 整段手势舞:裙链左右平均差 < 5°、最大偏角 < 45°(乳奶模板 50°)、链根以下的骨陷进腿胶囊 < 1 cm | PCF_005 防穿腿 右 -0.3 / 左 -0.5°、最大 7.5°;飘一点 -2.1 / -3.2°、最大 25.1°;弹簧骨骼 9.1 / 9.0°、最大 28.1°;乳奶模板外套 31.1 / 31.0°(撑开)、最大 43.1°、陷入 0.11 cm |

10-05 全部 17 项通过,约 12 分钟。

单项也能直接跑,例如:

```
blender -b --factory-startup --python tests\check_skirt.py -- <pmx> 300 "SKIRT=CLOTH:skirt"
```

配置串的写法(`_blender.configure`):`类=方式:预设`,逗号隔开,没写的类是「MMD 刚体 · 模型原样」;
`类.参数=值` 改单个参数(写在那一类的方式后面),例如 `SKIRT=CLOTH:skirt,SKIRT.bc_allow_legs=1`。
类:BUST / HAIR / SKIRT / CLOTH;方式:RIGID / SPRING / CLOTH / FOLLOW;预设见 `presets.py` 的 FX 表。

## 对比视频

```
python tests\demo_videos.py                 全部 4 组,约 40 分钟
python tests\demo_videos.py body            只出一组:bust / body / roe / template
```

每一格由 [`render_tile.py`](render_tile.py) 在后台 Blender 里渲(一次一个),再用 ffmpeg 拼成带标签的网格、配音乐:

| 组 | 视频 | 格子 |
|---|---|---|
| bust | `胸部_6种_Vindictus_PCF_005.mp4` | MMD 刚体:模型原样(B)、C 方案(E)、乳奶模板;弹簧骨骼 K1、K3;骨骼布料 ROE 戳的时候 |
| body | `头发裙子衣物_5种_Vindictus_PCF_005.mp4` | 全部刚体、弹簧骨骼、骨骼布料(防穿腿)、骨骼布料(飘一点)、跟随骨骼 |
| roe | `胸部_3种_ROE_j01.mp4` | bustB 刚体、K1、ROE 戳的时候 |
| template | `胸部裙子_4种_乳奶模板模型.mp4` | 刚体、弹簧骨骼、骨骼布料(防穿腿)、骨骼布料(飘一点) |

已经渲好的格子会跳过:改了插件要重渲某一格,先把 `_tiles\<组名>\NN.mp4` 挪走。
格子的标签里不要用半角冒号、逗号(ffmpeg drawtext 的参数分隔符,后半截会被当成字体文件,中文变方框)。

## 其他工具

| 脚本 | 做什么 |
|---|---|
| [`skirt_solver_variants.py`](skirt_solver_variants.py) | 调裙子参数:动画只采样一次,直接调 `bonecloth.simulate` 换参数跑好几遍(每遍十几秒),比较偏角、末端位移、碰撞推力、陷进腿多深。「腿里的重叠也放过」默认关就是用它比出来的 |
| [`panel_screenshots.py`](panel_screenshots.py) | 使用说明的面板截图:另开一个有界面的 Blender(`--enable-event-simulate`),模拟点击切到「MMD物理」标签后截图。偏好设置不保存,不碰正在用的 Blender |

```
blender --factory-startup --enable-event-simulate --window-geometry 0 0 2560 1540 --python tests\panel_screenshots.py -- <输出目录>
blender -b --factory-startup --python tests\skirt_solver_variants.py -- <pmx> 300 SKIRT skirt "base;allow_legs:allow_legs=1"
```

## 以前踩过的坑

- **烘焙时把碰撞体一起藏了**:为了快把模型网格设成 `hide_viewport`,腿的碰撞胶囊也是网格,Blender 不求值藏起来的物体,
  胶囊停在第一帧,裙子撞上留在原地的胶囊被顶起来卡住(右侧平均 +18°、最大 128°)。`check_skirt.py` 盯的就是这个。
- **骨骼贴着腿走的外套**:静止时就陷在腿胶囊里的骨如果放过,腿一动就整个穿出来(陷入 2.5 cm);现在腿里不放过,
  外套会撑开 30 多度(和模型自带的 MMD 刚体一样是撑开的)。
- **包 Blender 面板的 draw**:新函数必须正好是 `(self, context)`,多出来的默认参数会让 Blender 崩溃。
