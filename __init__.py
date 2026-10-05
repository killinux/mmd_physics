"""MMD 物理调节:在 Blender 里调 mmd_tools 模型的物理。

- 效果选择(渲染用,effects*.py):胸部 / 头发 / 裙子 / 其他衣物各选一种方式 —— MMD 刚体(多套预设)、
  弹簧骨骼(KawaiiPhysics 同款,kawaii.py)、骨骼布料(Magica Cloth 2 风格,bonecloth.py)、跟随骨骼 ——
  一键模拟 / 烘焙,一键还原。
- 胸部刚体调参、新建胸部物理、预览、导出 PMX(groups / params / preview / create_breast / ops / ui)。
需要 mmd_tools。
"""

bl_info = {
    "name": "MMD Physics 物理调节",
    "author": "killinux",
    "version": (0, 3, 0),
    "blender": (3, 6, 0),
    "location": "3D 视图 > 侧栏(N) > MMD物理",
    "description": "胸部、头发、裙子、衣物的物理效果任选(MMD 刚体多套预设 / 弹簧骨骼 Vindictus 同款 / "
                   "骨骼布料 Magica 风格 / 跟随骨骼),一键烘焙给渲视频用;胸部刚体调参、新建、预览、导出 PMX。"
                   "需要 mmd_tools",
    "category": "Object",
}

if "bpy" in locals():                      # Reload Scripts / 重新启用时连子模块一起刷新
    import importlib
    for _m in (chains, groups, presets, params, preview, ops, create_breast, ui, kawaii, bonecloth,  # noqa: F821
               rigidfx, effects, effects_ui):                                                         # noqa: F821
        importlib.reload(_m)

import bpy  # noqa: E402

from . import (chains, groups, presets, params, preview, ops, create_breast, ui, kawaii,  # noqa: E402
               bonecloth, rigidfx, effects, effects_ui)


def register():
    params.register()
    ops.register()
    create_breast.register()
    ui.register()
    effects_ui.register()


def unregister():
    effects_ui.unregister()
    ui.unregister()
    create_breast.unregister()
    ops.unregister()
    params.unregister()
