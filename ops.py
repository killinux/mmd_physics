"""操作按钮:读取 / 应用 / 预设 / 恢复初始 / 选中 / 预览 / 导出 PMX / 参数存取 JSON。"""

import json
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import groups, params, presets, preview

_GROUP_ITEMS = [(k, label, "") for k, label in groups.GROUPS]


def _root(context):
    if not hasattr(bpy.types.Object, "mmd_type"):
        return None
    root, _model = groups.model_of(context.active_object)
    return root


class _ModelOp:
    @classmethod
    def poll(cls, context):
        return _root(context) is not None


class MMDPHYS_OT_sync(_ModelOp, bpy.types.Operator):
    """从模型读出当前的刚体/关节参数,填到面板上"""
    bl_idname = "mmd_physics.sync"
    bl_label = "读取模型当前参数"
    bl_options = {'REGISTER', 'UNDO'}
    group: EnumProperty(items=_GROUP_ITEMS)

    def execute(self, context):
        g = params.sync_group(_root(context), self.group)
        if g.empty():
            self.report({'WARNING'}, f"{g.label}: 这个模型里没找到对应的物理刚体")
            return {'CANCELLED'}
        self.report({'INFO'}, f"{g.label}: {g.describe()}")
        return {'FINISHED'}


class MMDPHYS_OT_apply(_ModelOp, bpy.types.Operator):
    """把面板上的参数写进模型的刚体/关节(关闭「实时应用」时用)"""
    bl_idname = "mmd_physics.apply"
    bl_label = "应用到模型"
    bl_options = {'REGISTER', 'UNDO'}
    group: EnumProperty(items=_GROUP_ITEMS)

    def execute(self, context):
        g = params.apply_group(_root(context), self.group)
        self.report({'INFO'}, f"{g.label}: 已写入 刚体 {sum(map(len, g.rigids.values()))} / "
                              f"关节 {sum(map(len, g.joints.values()))}")
        return {'FINISHED'}


class MMDPHYS_OT_preset(_ModelOp, bpy.types.Operator):
    """套用预设(只改手感参数,不改刚体大小和碰撞组)"""
    bl_idname = "mmd_physics.preset"
    bl_label = "套用预设"
    bl_options = {'REGISTER', 'UNDO'}
    group: EnumProperty(items=_GROUP_ITEMS)

    def execute(self, context):
        root = _root(context)
        gs = getattr(root.mmd_physics, self.group)
        if not gs.inited:
            params.sync_group(root, self.group)     # 先读一次,大小/碰撞组保持模型原值
        g = params.apply_preset(root, self.group, gs.preset)
        label = next(label for k, label, _d, _v in presets.PRESETS[self.group] if k == gs.preset)
        self.report({'INFO'}, f"{g.label}: 已套用预设「{label}」")
        return {'FINISHED'}


class MMDPHYS_OT_restore(_ModelOp, bpy.types.Operator):
    """恢复到第一次读取时的参数"""
    bl_idname = "mmd_physics.restore"
    bl_label = "恢复初始"
    bl_options = {'REGISTER', 'UNDO'}
    group: EnumProperty(items=_GROUP_ITEMS)

    def execute(self, context):
        root = _root(context)
        gs = getattr(root.mmd_physics, self.group)
        if not gs.original:
            self.report({'WARNING'}, "还没有读取过,没有初始值")
            return {'CANCELLED'}
        params.from_dict(gs, json.loads(gs.original))
        params.apply_group(root, self.group)
        self.report({'INFO'}, "已恢复初始参数")
        return {'FINISHED'}


class MMDPHYS_OT_select(_ModelOp, bpy.types.Operator):
    """在视图里选中这组刚体和关节(会打开 mmd_tools 的刚体/关节显示)"""
    bl_idname = "mmd_physics.select"
    bl_label = "选中刚体/关节"
    bl_options = {'REGISTER', 'UNDO'}
    group: EnumProperty(items=_GROUP_ITEMS)

    def execute(self, context):
        from mmd_tools.core.model import Model
        root = _root(context)
        g = groups.find(self.group, Model(root))
        if g.empty():
            self.report({'WARNING'}, f"{g.label}: 没找到")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        root.mmd_root.show_rigid_bodies = True
        root.mmd_root.show_joints = True
        for o in context.selected_objects:
            o.select_set(False)
        objs = g.objects()
        for o in objs:
            o.hide_set(False)
            o.select_set(True)
        context.view_layer.objects.active = objs[0]
        return {'FINISHED'}


class MMDPHYS_OT_preview_start(_ModelOp, bpy.types.Operator):
    """Build 物理并播放(内置测试动作或场景现有动作);Blender 的物理只能粗看,手感以 MMD 为准"""
    bl_idname = "mmd_physics.preview_start"
    bl_label = "开始预览"
    bl_options = {'REGISTER'}

    def execute(self, context):
        root = _root(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        preview.start(context, root, root.mmd_physics.preview_motion)
        return {'FINISHED'}


class MMDPHYS_OT_preview_stop(_ModelOp, bpy.types.Operator):
    """停止播放、Clean 物理、删掉测试动作,场景还原到预览前"""
    bl_idname = "mmd_physics.preview_stop"
    bl_label = "停止并还原"
    bl_options = {'REGISTER'}

    def execute(self, context):
        root = _root(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        preview.stop(context, root)
        return {'FINISHED'}


class MMDPHYS_OT_export_pmx(_ModelOp, bpy.types.Operator, ExportHelper):
    """导出 PMX:先停止预览/清掉 Build,再调用 mmd_tools 导出"""
    bl_idname = "mmd_physics.export_pmx"
    bl_label = "导出 PMX"
    bl_options = {'REGISTER'}
    filename_ext = ".pmx"
    filter_glob: StringProperty(default="*.pmx", options={'HIDDEN'})
    scale: FloatProperty(name="缩放", description="Blender → PMX 的缩放,本系列模型用 12.5", default=12.5,
                         min=0.001, soft_max=100.0)
    copy_textures: BoolProperty(name="复制贴图", description="贴图复制到 PMX 旁的 textures 文件夹", default=True)

    def invoke(self, context, event):
        root = _root(context)
        if root is not None:
            self.scale = root.mmd_physics.mmd_scale
            if not self.filepath:
                name = root.mmd_root.name or root.name
                base = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
                self.filepath = os.path.join(base, name + ".pmx")
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        from mmd_tools.core.model import Model
        root = _root(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if root.mmd_physics.pv_active or root.mmd_root.is_built:
            if root.mmd_physics.pv_active:
                preview.stop(context, root)
            else:
                preview._call_on(root, bpy.ops.mmd_tools.clean_rig, context)
        arm = Model(root).armature()
        for o in context.selected_objects:
            o.select_set(False)
        arm.select_set(True)
        context.view_layer.objects.active = arm
        res = bpy.ops.mmd_tools.export_pmx(filepath=self.filepath, scale=self.scale,
                                           copy_textures=self.copy_textures, log_level='ERROR')
        if 'FINISHED' not in res:
            self.report({'ERROR'}, "导出失败,看控制台")
            return {'CANCELLED'}
        self.report({'INFO'}, f"已导出 {self.filepath}")
        return {'FINISHED'}


class MMDPHYS_OT_save_json(_ModelOp, bpy.types.Operator, ExportHelper):
    """把这组参数存成 JSON(换模型/换工程时再读回来)"""
    bl_idname = "mmd_physics.save_json"
    bl_label = "保存参数"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})
    group: EnumProperty(items=_GROUP_ITEMS)

    def execute(self, context):
        gs = getattr(_root(context).mmd_physics, self.group)
        data = {"mmd_physics": 1, "group": self.group, "params": params.to_dict(gs)}
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        self.report({'INFO'}, f"已保存 {self.filepath}")
        return {'FINISHED'}


class MMDPHYS_OT_load_json(_ModelOp, bpy.types.Operator, ImportHelper):
    """从 JSON 读参数并应用到模型(刚体大小等也会一起改,换了模型请先检查尺寸)"""
    bl_idname = "mmd_physics.load_json"
    bl_label = "读取参数"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})
    group: EnumProperty(items=_GROUP_ITEMS)

    def execute(self, context):
        root = _root(context)
        with open(self.filepath, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("group") != self.group:
            self.report({'ERROR'}, f"这个文件是「{data.get('group')}」的参数,不是「{self.group}」")
            return {'CANCELLED'}
        gs = getattr(root.mmd_physics, self.group)
        if not gs.inited:
            params.sync_group(root, self.group)
        params.from_dict(gs, data["params"])
        params.apply_group(root, self.group)
        self.report({'INFO'}, f"已读取 {os.path.basename(self.filepath)}")
        return {'FINISHED'}


_CLASSES = (MMDPHYS_OT_sync, MMDPHYS_OT_apply, MMDPHYS_OT_preset, MMDPHYS_OT_restore, MMDPHYS_OT_select,
            MMDPHYS_OT_preview_start, MMDPHYS_OT_preview_stop, MMDPHYS_OT_export_pmx,
            MMDPHYS_OT_save_json, MMDPHYS_OT_load_json)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
