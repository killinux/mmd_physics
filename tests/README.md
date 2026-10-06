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
| `MMDPHYS_PMX_HOODIE` / `MMDPHYS_PMX_SUIT` / `MMDPHYS_PMX_ARMOR` | Vindictus `PCF_008.pmx`(卫衣)/ `PCF_009.pmx`(西装)/ `PCF_067.pmx`(钢甲) | 「按衣服推荐」的检查样本 |
| `MMDPHYS_OUT` | `E:\game_export\_mmd_physics\效果对比` | 对比视频 |
| `MMDPHYS_SHOTS` | `E:\game_export\_mmd_physics\使用说明素材` | 面板截图 |
| `MMDPHYS_FFMPEG` | `ffmpeg` | 拼视频 |

## 检查(改完插件跑一遍)

```
python tests\run_checks.py                  全部,约 25 分钟
python tests\run_checks.py detect kawaii    只跑其中几项
```

每项一个后台 Blender,输出 `PASS ...` / `FAIL ...`,最后汇总;有失败返回 1。完整输出在系统临时目录的
`mmd_physics_checks\` 下。

| 检查 | 脚本 | 通过的标准 | 本机结果(10-05) |
|---|---|---|---|
| detect | `check_detect.py` | 三种骨架的胸链左右都认到 | Vindictus 2 条、ROE 2 条、乳奶模板 4 条单骨 |
| kawaii | `check_kawaii.py` | 新版 `kawaii.bake()` 和 0.2.0 版([`kawaii_v020_reference.py`](kawaii_v020_reference.py))逐帧一样;别的骨架也能动 | 518 条曲线差 0 |
| effects | `check_effects.py` | 几种方式各算一遍,点「还原」后刚体、关节、动作、重力和原来逐项一样,不留碰撞体、工作动作;ROE 上再算整套换上(RGBA、欧美转换)和 PmxTailor | 0 处不同 |
| kits | `check_kits.py` | 胸部整套换上的五个预设(RGBA、Tda、欧美转换、AH、AH 着衣用)经面板各算一遍:每条胸链建一套(刚体、关节数对,左右连着时加上左右之间的),物理步长按套件(RGBA 60 Hz,其余场景原样),主胸骨在动(常见摆幅 > 0.3°)、没炸(没有 NaN、不超过 60°),左右连着时两侧每帧偏转差 < 1°;还原后套件一个不剩、步长回到原来的 | 各套件的摆幅见插件 README「胸部多段套件」 |
| outfit | `check_outfit.py` | 「按衣服推荐」判出来的种类和预期一样,点按钮后胸部预设换成推荐的 | PCF_005 大致跟着、PCF_008 只跟一部分、PCF_067 不带网格、ROE / 乳奶模板裸着或贴身 |
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
python tests\demo_videos.py                 全部 9 组,约 100 分钟
python tests\demo_videos.py body            只出一组:bust / body / roe / template / kits / kits_roe / kits_template /
                                            kits_ah_roe / kits_ah
```

每一格由 [`render_tile.py`](render_tile.py) 在后台 Blender 里渲(一次一个),再用 ffmpeg 拼成带标签的网格、配音乐:

| 组 | 视频 | 格子 |
|---|---|---|
| bust | `胸部_6种_Vindictus_PCF_005.mp4` | MMD 刚体:模型原样(B)、C 方案(E)、乳奶模板;弹簧骨骼 K1、K3;骨骼布料 ROE 戳的时候 |
| body | `头发裙子衣物_5种_Vindictus_PCF_005.mp4` | 全部刚体、弹簧骨骼、骨骼布料(防穿腿)、骨骼布料(飘一点)、跟随骨骼 |
| roe | `胸部_3种_ROE_j01.mp4` | bustB 刚体、K1、ROE 戳的时候 |
| template | `胸部裙子_4种_乳奶模板模型.mp4` | 刚体、弹簧骨骼、骨骼布料(防穿腿)、骨骼布料(飘一点) |
| kits | `胸部_多段套件_6种_Vindictus_PCF_005.mp4` | 模型原样(B)、RGBA 式(60 Hz)、Tda 式、欧美转换式、PmxTailor 胸(大)、乳奶模板 |
| kits_roe | `胸部_多段套件_4种_ROE_j01.mp4` | bustB、RGBA 式、Tda 式、欧美转换式 |
| kits_template | `胸部_多段套件_4种_乳奶模板模型.mp4` | 模型原样(乳奶模板)、RGBA 式、Tda 式、欧美转换式 |
| kits_ah_roe | `胸部_AH式_4种_ROE_j01.mp4` | bustB、AH 式原版质量(×1)、AH 式(×3)、AH 着衣用(左右连着 ×10) |
| kits_ah | `胸部_AH式_4种_Vindictus_PCF_005.mp4` | 同上,PCF_005 |

已经渲好的格子会跳过:改了插件要重渲某一格,先把 `_tiles\<组名>\NN.mp4` 挪走。
格子的标签里不要用半角冒号、逗号(ffmpeg drawtext 的参数分隔符,后半截会被当成字体文件,中文变方框)。

## 其他工具

| 脚本 | 做什么 |
|---|---|
| [`skirt_solver_variants.py`](skirt_solver_variants.py) | 调裙子参数:动画只采样一次,直接调 `bonecloth.simulate` 换参数跑好几遍(每遍十几秒),比较偏角、末端位移、碰撞推力、陷进腿多深。「腿里的重叠也放过」默认关就是用它比出来的 |
| [`doc_tables.py`](doc_tables.py) | 重新生成 `docs/效果一览与手动做法.md` 的附录(套件和全部预设的数值,直接读 `kits.py`、`presets.py`);改了预设就跑一次。加 `--html 路径` 再出一份网页版(本地看)。普通 Python 就能跑,不用 Blender |
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
- **后台 Blender 别设「低于正常」优先级**:别的窗口在渲染时,低优先级的检查进程分不到 CPU(17 分钟只跑了 7 秒),
  看起来像卡死。一次只跑一个,用正常优先级。
- **Blender 退出时崩(btRigidBody::removeConstraintRef)**:退出时按对象名字的顺序释放,关节(`J.`)、mmd_tools 的不碰撞约束
  (`ncc`)排在刚体前面就先被删,刚体释放时还去读它们。套件的刚体名以数字开头(`0kit_…`),排在最前面;删套件时也先删刚体。
  改之前 PCF_005 的套件格子渲完退出时 3 次崩 2 次(视频是完整的,`demo_videos.py` 现在也照收)。
- **新开的 Blender 和播过一遍的物理不一样**:Blender 在模拟的第二帧按各刚体当时的位置建关节,跟骨的刚体已经摆到
  第二帧的姿势,摆动刚体还在第一帧,这一帧的错位留在关节里;同一个 Blender 里第一次模拟和以后的错位不一样
  (ROE + Tda 3.75° 对 2.81°,一个检查里第一个预设和后面的就对不上)。效果选择现在让动作副本开头保持一帧
  (`effects.HOLD_FRAMES`),两种情况逐帧相同。查这类问题:`diag` 时先比静态状态(都一样),再换开头不动的测试动作。
- **结果行要在行首**:Blender 自己的 C 输出(依赖循环提示等)按块刷新,会留半行在 PASS / FAIL 前面,`run_checks.py`
  就漏掉这一项;`_blender.result` 先换行再打印。
- **RGBA 式两侧不一样不一定是放歪了**:对齐左右严格对称,手势舞左右不对称,宽松的结构就会一边晃得多;用对称的
  上下颠试(两侧 6.1 / 6.9°)才分得清。
