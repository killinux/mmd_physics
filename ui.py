"""侧栏面板:3D 视图 N → MMD物理。主面板 + 胸部(后续加衣服、头发)+ 预览/导出。"""

import bpy

from . import create_breast, groups, ops


def _root(context):
    return ops._root(context)


class MMDPHYS_PT_main(bpy.types.Panel):
    bl_label = "MMD 物理调节"
    bl_idname = "MMDPHYS_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MMD物理"

    def draw(self, context):
        layout = self.layout
        if not hasattr(bpy.types.Object, "mmd_type"):
            layout.label(text="需要先启用 mmd_tools 插件", icon='ERROR')
            return
        root = _root(context)
        if root is None:
            layout.label(text="选中 MMD 模型里的任一对象", icon='INFO')
            return
        st = root.mmd_physics
        layout.label(text=f"模型: {root.mmd_root.name or root.name}", icon='OUTLINER_OB_ARMATURE')
        layout.prop(st, "live")
        if st.pv_active:
            layout.label(text="预览中:改物理类型/碰撞组要重新开始预览才生效", icon='PLAY')


class _GroupPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MMD物理"
    bl_parent_id = "MMDPHYS_PT_main"
    group = ""

    @classmethod
    def poll(cls, context):
        return hasattr(bpy.types.Object, "mmd_type") and _root(context) is not None

    def draw(self, context):
        from mmd_tools.core.model import Model
        layout = self.layout
        root = _root(context)
        st = root.mmd_physics
        gs = getattr(st, self.group)
        model = Model(root)
        g = groups.find(self.group, model)
        if g.empty():
            if self.group == "breast":
                create_breast.draw_create(layout, context, root)
            else:
                layout.label(text="这个模型里没找到对应的物理刚体", icon='ERROR')
            return
        layout.label(text=g.describe(), icon='CHECKMARK')
        row = layout.row(align=True)
        row.operator("mmd_physics.sync", icon='FILE_REFRESH').group = self.group
        row.operator("mmd_physics.select", text="", icon='RESTRICT_SELECT_OFF').group = self.group
        if not gs.inited:
            layout.label(text="先点「读取模型当前参数」", icon='INFO')
            return

        row = layout.row(align=True)
        row.prop(gs, "preset", text="预设")
        row.operator("mmd_physics.preset", text="套用").group = self.group

        row = layout.row(align=True)
        row.prop(gs, "link")
        if not gs.link:
            row.prop(gs, "side", expand=True)
        p = gs.left if (gs.link or gs.side == 'left') else gs.right

        box = layout.box()
        box.label(text="刚体", icon='MESH_UVSPHERE')
        box.prop(p, "mode")
        box.row().prop(p, "shape", expand=True)
        if p.shape == 'SPHERE':
            box.prop(p, "size", index=0, text="半径")
        elif p.shape == 'CAPSULE':
            col = box.column(align=True)
            col.prop(p, "size", index=0, text="半径")
            col.prop(p, "size", index=1, text="高")
        else:
            box.prop(p, "size", text="半边长(Blender XYZ)")
        col = box.column(align=True)
        for f in ("mass", "lin_damp", "ang_damp", "bounce", "friction"):
            col.prop(p, f)
        box.prop(p, "group")
        box.label(text="不碰撞的组(按下 = 不和该组碰撞):")
        grid = box.grid_flow(columns=8, even_columns=True, align=True)
        for i in range(16):
            grid.prop(p, "nocollide", index=i, text=str(i + 1), toggle=True)

        box = layout.box()
        box.label(text="关节(X 左右 / Y 上下 / Z 前后,同 PMXEditor)", icon='CONSTRAINT')
        row = box.row(align=True)
        row.prop(gs, "sym_rot", toggle=True)
        row.prop(gs, "sym_loc", toggle=True)
        if gs.sym_rot:
            box.prop(p, "rot_max", text="旋转限制 ±")
        else:
            box.prop(p, "rot_min")
            box.prop(p, "rot_max")
        box.prop(p, "spring_rot")
        if gs.sym_loc:
            box.prop(p, "loc_max", text="移动限制 ±")
        else:
            box.prop(p, "loc_min")
            box.prop(p, "loc_max")
        box.prop(p, "spring_loc")

        row = layout.row(align=True)
        if not st.live:
            row.operator("mmd_physics.apply", icon='CHECKMARK').group = self.group
        row.operator("mmd_physics.restore", icon='LOOP_BACK').group = self.group
        row = layout.row(align=True)
        row.operator("mmd_physics.save_json", icon='EXPORT').group = self.group
        row.operator("mmd_physics.load_json", icon='IMPORT').group = self.group
        if self.group == "breast" and create_breast.has_created(model):
            layout.operator("mmd_physics.breast_remove_created", icon='TRASH')


class MMDPHYS_PT_breast(_GroupPanel, bpy.types.Panel):
    bl_label = "胸部刚体(调参 / 导出 PMX)"
    bl_idname = "MMDPHYS_PT_breast"
    bl_order = 1
    bl_options = {'DEFAULT_CLOSED'}
    group = "breast"


class MMDPHYS_PT_preview(bpy.types.Panel):
    bl_label = "预览 / 导出"
    bl_idname = "MMDPHYS_PT_preview"
    bl_order = 2
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MMD物理"
    bl_parent_id = "MMDPHYS_PT_main"

    @classmethod
    def poll(cls, context):
        return hasattr(bpy.types.Object, "mmd_type") and _root(context) is not None

    def draw(self, context):
        layout = self.layout
        st = _root(context).mmd_physics
        layout.prop(st, "mmd_scale")
        layout.prop(st, "preview_motion")
        if st.pv_active:
            layout.operator("mmd_physics.preview_stop", icon='SNAP_FACE')
        else:
            layout.operator("mmd_physics.preview_start", icon='PLAY')
        layout.label(text="Blender 的物理只能粗看,手感以 MMD 为准", icon='INFO')
        layout.separator()
        layout.operator("mmd_physics.export_pmx", icon='EXPORT')
        layout.label(text="导出前会自动停止预览(Build 着导出会拉坏关节)", icon='INFO')


_CLASSES = (MMDPHYS_PT_main, MMDPHYS_PT_breast, MMDPHYS_PT_preview)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
