"""MMD 物理调节:在 Blender 里调 mmd_tools 模型的物理参数(刚体 + 关节),预览后导出 PMX。

当前支持胸部;衣服、头发按同一套框架后续加入(groups.py 加识别,presets.py 加预设,ui.py 加面板)。
需要 mmd_tools。
"""

bl_info = {
    "name": "MMD Physics 物理调节",
    "author": "killinux",
    "version": (0, 1, 0),
    "blender": (3, 6, 0),
    "location": "3D 视图 > 侧栏(N) > MMD物理",
    "description": "调节/新建 MMD 模型的胸部物理(刚体/关节全部参数、预设、Blender 内预览、导出 PMX),需要 mmd_tools",
    "category": "Object",
}

if "bpy" in locals():                      # Reload Scripts / 重新启用时连子模块一起刷新
    import importlib
    for _m in (groups, presets, params, preview, ops, create_breast, ui):     # noqa: F821
        importlib.reload(_m)

import bpy  # noqa: E402

from . import groups, presets, params, preview, ops, create_breast, ui  # noqa: E402


def register():
    params.register()
    ops.register()
    create_breast.register()
    ui.register()


def unregister():
    ui.unregister()
    create_breast.unregister()
    ops.unregister()
    params.unregister()
