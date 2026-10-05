"""Blender 里预览物理:Build(mmd_tools)+ 打开刚体世界 + 播放测试动作;停止时 Clean 并还原场景。

让预览接近 MMD(停止时全部还原):
- 关节和重力按 effects.mmd_like(和「效果选择」的「MMD 同款」一样):模型在 Blender 里是 PMX 的 1/scale
  (常用 12.5);MMD 的重力是 98 单位/秒²(9.8 × 10,three.js MMDPhysics / saba / MMDAgent-EX 都这样),换成
  98/scale 米/秒²;旋转弹簧的量纲带长度² → 乘 1/scale²;关节换成 SPRING1、去掉 mmd_tools 加的 0.5 关节阻尼
  (MMD 的 PMX 关节没有阻尼),质量、衰减、线性弹簧与尺度无关。
- 谁都不碰的刚体(PMX 里和所有组都不碰撞)单独一个碰撞层:mmd_tools 只给开始时挨着的刚体加了不碰撞约束,
  不改的话手臂甩过来会把胸顶开。
- 帧率 30fps(MMD 动作的帧率)。
Blender 的刚体引擎和 MMD 的老版 Bullet 仍有差别,预览用来看幅度/方向/有没有炸,手感以 MMD 实测为准。
导出前一定要停止预览:Build 着的模型导出,物理把骨头带离原位,PMX 一开场关节就被拉开。
"""

import json
import math

import bpy
from mathutils import Matrix, Quaternion, Vector

TEST_ACTION = "mmd_physics_test"
TEST_END = 160
MMD_GRAVITY = 98.0                          # MMD 的重力,单位/秒²(9.8 × 10)
_CENTER = ("センター", "center", "全ての親")
_UPPER = ("上半身", "上半身1", "upper body")


def _pick(arm, names):
    for n in names:
        pb = arm.pose.bones.get(n)
        if pb is not None:
            return pb
    return None


def _height(arm):
    zs = [(arm.matrix_world @ b.head_local).z for b in arm.data.bones]
    return (max(zs) - min(zs)) if zs else 1.0


def _local_vec(arm, pb, world_vec):
    rest = arm.matrix_world.to_3x3() @ pb.bone.matrix_local.to_3x3()
    return rest.inverted() @ world_vec


def _local_rot(arm, pb, axis, deg):
    rest = arm.matrix_world.to_quaternion() @ pb.bone.matrix_local.to_quaternion()
    return rest.inverted() @ Quaternion(axis, math.radians(deg)) @ rest


def _key_rot(pb, q, frame):
    if pb.rotation_mode == 'QUATERNION':
        pb.rotation_quaternion = q
        pb.keyframe_insert("rotation_quaternion", frame=frame, group=pb.name)
    elif pb.rotation_mode == 'AXIS_ANGLE':
        axis, ang = q.to_axis_angle()
        pb.rotation_axis_angle = (ang, *axis)
        pb.keyframe_insert("rotation_axis_angle", frame=frame, group=pb.name)
    else:
        pb.rotation_euler = q.to_euler(pb.rotation_mode)
        pb.keyframe_insert("rotation_euler", frame=frame, group=pb.name)


def make_test_action(arm):
    """约 5 秒(30fps):上下颠 → 左右扭腰 → 前后倾 → 静止看余晃。幅度按身高算。"""
    act = bpy.data.actions.new(TEST_ACTION)
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    H = _height(arm)
    touched = []
    center = _pick(arm, _CENTER)
    if center is not None:
        a = 0.03 * H
        seq = [(1, 0.0), (8, 0.0)]
        f = 8
        for k in range(8):                  # 上下颠 8 次,每 6 帧换向
            f += 6
            seq.append((f, a if k % 2 == 0 else -0.4 * a))
        seq.append((f + 6, 0.0))
        for frame, z in seq:
            center.location = _local_vec(arm, center, Vector((0.0, 0.0, z)))
            center.keyframe_insert("location", frame=frame, group=center.name)
        touched.append(center.name)
    upper = _pick(arm, _UPPER)
    if upper is not None:
        twist = [(60, 0.0), (68, 20.0), (76, -20.0), (84, 20.0), (92, -20.0), (100, 0.0)]
        lean = [(108, 12.0), (116, -8.0), (124, 0.0)]
        _key_rot(upper, Quaternion(), 1)
        _key_rot(upper, Quaternion(), 60)
        for frame, deg in twist:
            _key_rot(upper, _local_rot(arm, upper, Vector((0.0, 0.0, 1.0)), deg), frame)
        for frame, deg in lean:
            _key_rot(upper, _local_rot(arm, upper, Vector((1.0, 0.0, 0.0)), deg), frame)
        _key_rot(upper, Quaternion(), TEST_END)
        touched.append(upper.name)
    return act, touched


def _pose_backup(arm, names):
    return {n: [v for row in arm.pose.bones[n].matrix_basis for v in row] for n in names}


def _pose_restore(arm, backup):
    for n, flat in backup.items():
        pb = arm.pose.bones.get(n)
        if pb is not None:
            pb.matrix_basis = Matrix([flat[0:4], flat[4:8], flat[8:12], flat[12:16]])


def _call_on(root, op, context):
    """mmd_tools 的 Build/Clean 按活动对象找模型。"""
    view_layer = context.view_layer
    prev = view_layer.objects.active
    view_layer.objects.active = root
    try:
        op()
    finally:
        if prev is not None and prev.name in view_layer.objects:
            view_layer.objects.active = prev


def start(context, root, motion):
    from mmd_tools.core.model import Model
    from .effects import mmd_like
    from .params import joint_backup
    st = root.mmd_physics
    if st.pv_active:
        stop(context, root)
    scene = context.scene
    model = Model(root)
    arm = model.armature()
    if root.mmd_root.is_built:
        _call_on(root, bpy.ops.mmd_tools.clean_rig, context)
    ad = arm.animation_data
    world = scene.rigidbody_world
    joints = list(model.joints())
    state = {
        "frame": scene.frame_current, "start": scene.frame_start, "end": scene.frame_end,
        "world": bool(world and world.enabled),
        "action": ad.action.name if ad and ad.action else "",
        "motion": motion, "pose": {},
        "gravity": list(scene.gravity), "use_gravity": scene.use_gravity,
        "fps": [scene.render.fps, scene.render.fps_base],
        "joints": {j.name: joint_backup(j) for j in joints},
        "cols": {o.name: [bool(x) for x in o.rigid_body.collision_collections]
                 for o in model.rigidBodies() if o.rigid_body is not None},
    }
    if motion == 'TEST':
        names = [pb.name for pb in (_pick(arm, _CENTER), _pick(arm, _UPPER)) if pb is not None]
        state["pose"] = _pose_backup(arm, names)
        make_test_action(arm)
        scene.frame_start, scene.frame_end = 1, TEST_END
    st.pv_state = json.dumps(state, ensure_ascii=False)
    _call_on(root, bpy.ops.mmd_tools.build_rig, context)
    mmd_like(scene, model, st.mmd_scale)
    scene.render.fps, scene.render.fps_base = 30, 1.0         # MMD 的动作是 30fps
    world = scene.rigidbody_world
    world.enabled = True
    world.point_cache.frame_start = scene.frame_start
    world.point_cache.frame_end = scene.frame_end
    scene.frame_set(scene.frame_start)
    st.pv_active = True
    screen = context.screen
    if screen is not None and not screen.is_animation_playing:
        bpy.ops.screen.animation_play()


def stop(context, root):
    from mmd_tools.core.model import Model
    from .params import preview_joint
    st = root.mmd_physics
    scene = context.scene
    screen = context.screen
    if screen is not None and screen.is_animation_playing:
        bpy.ops.screen.animation_cancel(restore_frame=False)
    state = json.loads(st.pv_state) if st.pv_state else {}
    scene.frame_set(scene.frame_start)
    if root.mmd_root.is_built:
        _call_on(root, bpy.ops.mmd_tools.clean_rig, context)
    world = scene.rigidbody_world
    if world is not None:
        world.enabled = bool(state.get("world", False))
    model = Model(root)
    backups = state.get("joints", {})
    for j in model.joints():
        preview_joint(j, None, backups.get(j.name))
    cols = state.get("cols", {})
    for o in model.rigidBodies():
        if o.rigid_body is not None and o.name in cols:
            o.rigid_body.collision_collections = cols[o.name]
    if "gravity" in state:
        scene.gravity = state["gravity"]
        scene.use_gravity = state.get("use_gravity", True)
    if "fps" in state:
        scene.render.fps, scene.render.fps_base = state["fps"]
    arm = model.armature()
    if state.get("motion") == 'TEST':
        ad = arm.animation_data
        if ad is not None:
            ad.action = bpy.data.actions.get(state.get("action", "")) if state.get("action") else None
        test = bpy.data.actions.get(TEST_ACTION)
        if test is not None:
            bpy.data.actions.remove(test)
        _pose_restore(arm, state.get("pose", {}))
        scene.frame_start, scene.frame_end = state.get("start", 1), state.get("end", 250)
    scene.frame_set(state.get("frame", scene.frame_start))
    st.pv_active = False
    st.pv_state = ""
