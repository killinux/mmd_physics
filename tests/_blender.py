"""Blender 里跑的脚本共用:找到插件、导入模型和动作、按配置串设各类方式、打印 PASS / FAIL。只在 Blender 里 import。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import config  # noqa: E402

if config.ADDON_PARENT not in sys.path:
    sys.path.insert(0, config.ADDON_PARENT)

import addon_utils  # noqa: E402
import bpy  # noqa: E402


def argv():
    """命令行里 -- 后面的参数。"""
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def fresh(addons=("mmd_tools", "mmd_physics")):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for name in addons:
        addon_utils.enable(name, default_set=False)


def load(pmx, vmd=None, frames=0, margin=config.MARGIN, morphs=False):
    """导入 PMX(0.08,带物理)和 VMD(0.08,margin);frames > 0 时场景只到 margin + frames。返回 (scene, root, arm)。"""
    types = {"MESH", "ARMATURE", "PHYSICS"} | ({"MORPHS"} if morphs else set())
    bpy.ops.mmd_tools.import_model(filepath=pmx, scale=0.08, types=types)
    root = next(o for o in bpy.data.objects if getattr(o, "mmd_type", "") == "ROOT")
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for o in bpy.data.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = root
    root.select_set(True)
    scene = bpy.context.scene
    if vmd:
        bpy.ops.mmd_tools.import_vmd(filepath=vmd, scale=0.08, margin=margin, bone_mapper="PMX",
                                     update_scene_settings=True)
        scene.frame_start = 1
        if frames:
            scene.frame_end = min(scene.frame_end, margin + frames)
    scene.render.fps = 30
    return scene, root, arm


def configure(fx, spec, base=("RIGID", "model")):
    """配置串 → 面板:"BUST=SPRING:k1,HAIR=CLOTH:hair,CLOTH=FOLLOW";没写的类用 base(模型原样)。
    预设先填好参数,再按 "SKIRT.bc_allow_legs=1" 这种写法改单个参数。"""
    from mmd_physics import effects_ui
    for cat in effects_ui.CATS:
        p = getattr(fx, effects_ui.ATTR[cat])
        p.method, p.preset = base
    for part in [x for x in spec.split(",") if x]:
        key, value = part.split("=")
        if "." in key:
            cat, prop = key.split(".")
            p = getattr(fx, effects_ui.ATTR[cat])
            old = getattr(p, prop)
            setattr(p, prop, value not in ("0", "false", "False") if isinstance(old, bool) else type(old)(float(value)))
            continue
        method, preset = value.split(":") if ":" in value else (value, "")
        p = getattr(fx, effects_ui.ATTR[key])
        p.method = method
        if preset:
            p.preset = preset


def result(name, ok, detail=""):
    """run_checks.py 收集以 PASS / FAIL 开头的行。"""
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail), flush=True)
