"""使用说明的面板截图:另开一个有界面的 Blender(不碰正在用的那个),导入模型和舞蹈,点「识别物理分组」、选方式、
「模拟 / 烘焙」,把侧栏切到「MMD物理」标签后截图;再展开裙子的参数截一张。偏好设置不保存,结束直接退出。

blender --factory-startup --enable-event-simulate --window-geometry 0 0 2560 1540 --python panel_screenshots.py -- [OUTDIR] [PMX] [MODE]

MODE = effects(默认):窗口整图 window.png、侧栏 面板_总览.png、面板_裙子参数.png;
MODE = kits:胸部选「MMD 刚体 · RGBA 式」并展开参数,侧栏 面板_胸部套件.png(整套换上的参数、按衣服推荐、物理步长)。
另有坐标 regions.json、日志 shot.log。
- Blender 3.6 没有 Region.active_panel_category:用模拟点击沿侧栏右边的标签栏往下点,直到本插件的面板被画出来。
  不用 Ctrl+Tab(鼠标在 3D 视图上会弹出模式饼菜单)。
- 包 draw 的函数必须正好是 (self, context):Blender 按函数的参数个数建参数元组,多出来的默认参数是空指针,会崩。
- 模拟拖动侧栏边缘拉宽没成功(试过各种偏移、关掉区域重叠),状态行会被截断。
"""
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender  # noqa: E402
from _blender import addon_utils, bpy, config  # noqa: E402

_args = _blender.argv()
OUT = _args[0] if _args else config.SHOTS
PMX = _args[1] if len(_args) > 1 else config.MODELS["vindictus"]
MODE = _args[2] if len(_args) > 2 else "effects"
CONFIGS = {"effects": "BUST=SPRING:k1,HAIR=SPRING:vdf_hair,SKIRT=CLOTH:lively,CLOTH=FOLLOW", "kits": "BUST=RIGID:rgba"}
LOG = os.path.join(OUT, "shot.log")
os.makedirs(OUT, exist_ok=True)

prefs = bpy.context.preferences
prefs.use_preferences_save = False           # 绝不写用户的 userpref.blend
for code in ("zh_HANS", "zh_CN"):
    try:
        prefs.view.language = code
        break
    except TypeError:
        pass
prefs.view.use_translate_interface = True
prefs.view.use_translate_tooltips = True
prefs.view.use_translate_new_dataname = False
prefs.view.ui_scale = 0.9

DRAWN = {"main": 0.0}
state = {"step": 0, "tries": 0, "regions": {}}


def log(*a):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")


def view3d():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == 'VIEW_3D':
            ui = next(r for r in area.regions if r.type == 'UI')
            main = next(r for r in area.regions if r.type == 'WINDOW')
            return win, area, ui, main
    raise RuntimeError("no 3D view")


def ev(win, type_, value, x, y):
    win.event_simulate(type=type_, value=value, x=int(x), y=int(y))


def watched(orig, key):
    def draw(self, context):                 # 正好 (self, context),见上面
        DRAWN[key] = time.time()
        orig(self, context)
    return draw


def setup():
    addon_utils.enable("mmd_tools", default_set=False)
    addon_utils.enable("mmd_physics", default_set=False)
    from mmd_physics import ui as pui  # noqa: E402
    pui.MMDPHYS_PT_main.draw = watched(pui.MMDPHYS_PT_main.draw, "main")
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    scene, root, arm = _blender.load(PMX, config.VMD, morphs=True)
    bpy.ops.mmd_physics.fx_detect()
    fx = root.mmd_physics_fx
    _blender.configure(fx, CONFIGS[MODE])
    if MODE == "kits":
        fx.bust.show = True
    t = time.time()
    bpy.ops.mmd_physics.fx_apply()
    log("applied in %.0f s: %s" % (time.time() - t, fx.status[:200]))
    for k in ("show_rigid_bodies", "show_joints", "show_temporary_objects"):
        if hasattr(root.mmd_root, k):
            setattr(root.mmd_root, k, False)
    scene.frame_set(150)
    win, area, ui, main = view3d()
    space = area.spaces.active
    space.show_region_ui = True
    space.shading.type = 'SOLID'
    space.shading.color_type = 'TEXTURE'
    space.overlay.show_bones = False         # 骨架挡在模型前面只是噪音
    space.overlay.show_relationship_lines = False
    with bpy.context.temp_override(window=win, area=area, region=main):
        bpy.ops.view3d.view_axis(type='FRONT')
        for o in bpy.data.objects:
            o.select_set(False)
        arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.view3d.view_selected()
    arm.select_set(False)
    bpy.context.view_layer.objects.active = root
    root.select_set(True)


def shot(name, crop):
    """整个窗口截图;crop = 侧栏的另存一张(Blender 的像素和区域坐标都是左下角起)。"""
    import numpy as np
    win, area, ui, main = view3d()
    path = os.path.join(OUT, "window.png" if not crop else "_window_%s.png" % name)
    with bpy.context.temp_override(window=win, area=area, region=main):
        bpy.ops.screen.screenshot(filepath=path, check_existing=False)
    state["regions"][name] = {"win": [win.width, win.height], "ui": [ui.x, ui.y, ui.width, ui.height]}
    with open(os.path.join(OUT, "regions.json"), "w", encoding="utf-8") as fh:
        json.dump(state["regions"], fh, indent=1)
    if crop:
        img = bpy.data.images.load(path)
        w, h = img.size
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(h, w, 4)[ui.y:ui.y + ui.height, ui.x:ui.x + ui.width]
        out = bpy.data.images.new(name, ui.width, ui.height, alpha=True)
        out.pixels.foreach_set(np.ascontiguousarray(px).ravel())
        out.filepath_raw = os.path.join(OUT, name + ".png")
        out.file_format = 'PNG'
        out.save()
        os.remove(path)
    log("shot", name)


def tick():
    try:
        return _tick()
    except Exception:                                  # noqa: BLE001
        log("ERROR", traceback.format_exc())
        os._exit(3)


def _tick():
    s = state["step"]
    if s == 0:
        setup()
        state["step"] = 1
        return 1.0
    win, area, ui, main = view3d()
    if s == 1:
        if time.time() - DRAWN["main"] < 0.5:
            log("tab found after", state["tries"], "clicks")
            state["step"] = 2
            return 0.5
        state["tries"] += 1
        x = ui.x + ui.width - 12                      # 标签栏在侧栏右边缘
        y = ui.y + ui.height - 30 - (state["tries"] - 1) * 18
        if y < ui.y:
            log("tab not found")
            os._exit(4)
        ev(win, 'MOUSEMOVE', 'NOTHING', x, y)
        ev(win, 'LEFTMOUSE', 'PRESS', x, y)
        ev(win, 'LEFTMOUSE', 'RELEASE', x, y)
        return 0.25
    if s == 2:
        ev(win, 'MOUSEMOVE', 'NOTHING', 400, ui.y + ui.height // 2)     # 鼠标挪开,别让按钮高亮
        state["step"] = 3
        return 0.5
    if s == 3 and MODE == "kits":
        shot("面板_胸部套件", crop=True)
        log("done")
        os._exit(0)
    if s == 3:
        shot("window", crop=False)
        shot("面板_总览", crop=True)
        root = next(o for o in bpy.data.objects if getattr(o, "mmd_type", "") == "ROOT")
        root.mmd_physics_fx.skirt.show = True
        for a in win.screen.areas:
            a.tag_redraw()
        state["step"] = 4
        return 0.8
    if s == 4:
        x, y = ui.x + ui.width // 2, ui.y + ui.height // 2
        ev(win, 'MOUSEMOVE', 'NOTHING', x, y)
        for _ in range(5):                            # 往下滚,让裙子的参数整个露出来
            ev(win, 'WHEELDOWNMOUSE', 'PRESS', x, y)
        ev(win, 'MOUSEMOVE', 'NOTHING', 400, y)
        state["step"] = 5
        return 1.0
    if s == 5:
        shot("面板_裙子参数", crop=True)
        log("done")
        os._exit(0)
    return None


bpy.app.timers.register(tick, first_interval=2.0)
