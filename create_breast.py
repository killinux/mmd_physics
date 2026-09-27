"""新建胸部物理:模型没有胸部刚体(可能连胸骨也没有)时,补 胸骨 + 权重 + 刚体 + 关节。

移植自 Convert_to_MMD5 的 convert/breast.py,参数取自同系列 11 个参考 PMX 实测,按身高 H 归一:
  骨    每侧 1 根,挂在乳房区承重最多的上半身系骨下;骨头在乳尖正后方 depth·H(胸廓里),骨尾 = 乳尖。
  权重  乳尖距离高斯 exp(-(d/σH)²),2.3σ 截断;只从胸部骨(上半身系 + 其 helper 后代)的权重里按比例分出,
        每个顶点总权重不变;中线附近按侧平滑过渡,不串到对侧。
  刚体  球,半径 radius·H,球心在骨上 0.024/0.058 处;物理演算,16 组、不碰撞。
  关节  父链上第一个有刚体的骨 → 胸部刚体,放在骨头;父链没有刚体就给父骨补一个跟骨、不碰撞的锚刚体。
  手感  建完套一个预设(默认 Q弹),之后在面板上调。
已有带权重的胸骨(名字像胸、权重集中在一侧胸前)直接复用,不造骨、不动权重。
乳尖自动找:胸段内、离中线够远、主要由胸部骨带动、不挂布/发骨的顶点里最靠前的一撮;找偏了就在网格
编辑模式选中乳尖附近的顶点,点「用选中顶点作乳尖」。
坐标按 MMD 模型惯例:面朝 -Y,左 = +X(mmd_tools 导入和 Convert_to_MMD5 都是这样)。
"""

import math
import re

import bmesh
import bpy
from mathutils import Vector

from . import groups, params, preview

TAG_NEW = "mmd_physics_created"         # 本插件新建的骨/刚体/关节
MARKER = "MMDPHYS_乳尖_%s"

_UPPER = ("上半身", "上半身1", "上半身2", "上半身3", "上半身4", "上半身5")
_CHEST = ("上半身2", "上半身3", "上半身4", "上半身5")      # 乳尖搜索区(排除腹部)
_STOP = ("首", "頭", "左肩", "右肩", "左腕", "右腕", "左胸", "右胸", "下半身", "腰")
_SIDES = ((1.0, "左", "L"), (-1.0, "右", "R"))
CLOTH_RE = re.compile(r"skirt|スカート|coat|cloak|cape|mantle|shawl|veil|scar[ft]|hangings|drape|apron|robe|frill"
                      r"|sash|ribbon", re.I)
HAIR_RE = re.compile(r"hair|髪|ponytail|twintail|pigtail|braid|bangs|fringe|ahoge|アホ毛|もみあげ|おさげ", re.I)
_CENTER = 0.024 / 0.058     # 球心在骨上的位置(参考:骨头前 0.024H / 骨长 0.058H)
_CUT = 2.3                  # 高斯截断(×σ)
_LATERAL = 0.02             # 乳尖至少离中线 0.02H,排除中线饰物


# -- 扫描 --------------------------------------------------------------------------------
def _skinned_meshes(arm):
    return [o for o in bpy.data.objects
            if o.type == 'MESH' and any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers)]


def _jp(arm):
    """Blender 骨名 → 日文名(mmd_tools 导入时把 左/右 改成 .L/.R,原名在 mmd_bone.name_j)。"""
    out = {}
    for pb in arm.pose.bones:
        mb = getattr(pb, "mmd_bone", None)
        out[pb.name] = (mb.name_j if mb is not None and mb.name_j else pb.name)
    return out


def _by_jp(jp, names):
    rev = {}
    for b, j in jp.items():
        rev.setdefault(j, b)
    return [rev[n] for n in names if n in rev]


class Scan:
    """一次性扫描:蒙皮网格每个顶点 (网格, 索引, 骨架空间坐标, [(组名, 权重)]),身高 H,胸段范围。"""

    def __init__(self, arm):
        self.arm = arm
        self.jp = _jp(arm)
        self.meshes = _skinned_meshes(arm)
        inv = arm.matrix_world.inverted()
        bones = set(arm.data.bones.keys())
        self.verts = []
        zs = []
        for m in self.meshes:
            mw = inv @ m.matrix_world
            # 只认骨头的顶点组:mmd_tools 导入 PMX 会加 mmd_edge_scale(全 1)/mmd_vertex_order 等非骨组
            names = [vg.name if vg.name in bones else None for vg in m.vertex_groups]
            for v in m.data.vertices:
                p = mw @ v.co
                zs.append(p.z)
                gs = [(names[g.group], g.weight) for g in v.groups if g.weight > 0.0 and names[g.group]]
                if gs:
                    self.verts.append((m, v.index, p, gs))
        self.H = (max(zs) - min(zs)) if zs else 0.0
        B = arm.data.bones
        seeds = _by_jp(self.jp, _CHEST) or _by_jp(self.jp, _UPPER)
        self.upper = _by_jp(self.jp, _UPPER)
        self.ok = bool(seeds) and self.H > 0.0
        if not self.ok:
            return
        heads = [B[n].head_local for n in seeds]
        neck = _by_jp(self.jp, ("首",))
        self.zmin = min(h.z for h in heads)
        self.zmax = B[neck[0]].head_local.z if neck else max(h.z for h in heads)
        self.yspine = sum(h.y for h in heads) / len(heads)
        self.chest = self.region(seeds)

    def region(self, seeds):
        """种子骨 + 其后代 helper 骨(在颈/头/肩/臂/下半身/左右胸、布/发骨处截断)。胸部 helper
        (如 UE 的 bust/breast 辅助骨)算胸部骨:它们的权重也要能分给新胸骨;已认作胸骨的另外剔除。"""
        out = set(seeds)
        B = self.arm.data.bones
        stack = [B[n] for n in seeds if n in B]
        while stack:
            for c in stack.pop().children:
                j = self.jp.get(c.name, c.name)
                if j.startswith(_STOP) or CLOTH_RE.search(c.name) or HAIR_RE.search(c.name):
                    continue
                if c.name not in out:
                    out.add(c.name)
                    stack.append(c)
        return out


def _front_tip(pts):
    """一撮点里最靠前(-Y)的少数几个的均值。"""
    pts = sorted(pts, key=lambda q: q.y)
    k = min(len(pts), max(8, len(pts) // 30))
    return sum(pts[:k], Vector()) / k


def find_existing(scan):
    """已有胸骨 {侧: (骨名, 乳尖)}:名字像胸、子树有 ≥20 个 >0.3 权重的顶点、九成权重在一侧,且权重重心
    在胸前(胸段高度内、脊柱前方、离开中线);同侧多个取层级最高者(链根)。乳尖取该骨权重顶点最靠前的一撮。"""
    arm, H = scan.arm, scan.H
    cands = [b for b in arm.data.bones
             if (groups.BREAST_RE.search(b.name) or groups.BREAST_RE.search(scan.jp.get(b.name, "")))
             and not groups.NOT_BREAST_RE.search(scan.jp.get(b.name, b.name))
             and not b.name.startswith(("_dummy_", "_shadow_"))]
    subtree = {b.name: {b.name} | {c.name for c in b.children_recursive} for b in cands}
    watched = set().union(*subtree.values()) if subtree else set()
    verts = [(p, gs) for _m, _i, p, gs in scan.verts if any(n in watched for n, _ in gs)]
    found = {}
    for side, _label, _s in _SIDES:
        best = None
        for b in cands:
            names = subtree[b.name]
            sw = sside = 0.0
            strong = []
            acc = Vector()
            for p, gs in verts:
                w = sum(x for n, x in gs if n in names)
                if w <= 0.01:
                    continue
                sw += w
                acc += p * w
                if p.x * side > 0:
                    sside += w
                if w > 0.3:
                    strong.append(p)
            if len(strong) < 20 or sside < 0.9 * sw:
                continue
            c = acc / sw
            if c.x * side < 0.01 * H or not (scan.zmin <= c.z <= scan.zmax) or c.y > scan.yspine - 0.02 * H:
                continue
            depth = len(b.parent_recursive)
            if best is None or depth < best[0]:
                best = (depth, b.name, _front_tip(strong))
        if best:
            found[side] = best[1:]
    return found


def auto_apex(scan, side):
    """几何乳尖:胸段内、离中线够远、胸部骨为主(≥50%)、不挂布/发骨的顶点里最靠前的一撮。"""
    H = scan.H
    pts = []
    for _m, _i, p, gs in scan.verts:
        if p.x * side < _LATERAL * H or not (scan.zmin <= p.z <= scan.zmax):
            continue
        if any(w > 0.05 and (CLOTH_RE.search(n) or HAIR_RE.search(n)) for n, w in gs):
            continue
        tot = sum(w for _n, w in gs)
        if sum(w for n, w in gs if n in scan.chest) < 0.5 * tot:
            continue
        pts.append(p)
    return _front_tip(pts) if pts else None


def _chest_parent(scan, donors, A, side, sigma):
    """新骨的父骨:乳房区(高斯加权)承重最多的上半身系骨,helper 归到其上半身系祖先。"""
    B = scan.arm.data.bones
    anc = {}
    for n in donors:
        b = B.get(n)
        while b and b.name not in scan.upper:
            b = b.parent
        anc[n] = b.name if b else None
    score = {}
    for _m, _i, p, gs in scan.verts:
        if p.x * side <= 0:
            continue
        d = (p - A).length
        if d > _CUT * sigma:
            continue
        g = math.exp(-(d / sigma) ** 2)
        for n, w in gs:
            c = anc.get(n)
            if c:
                score[c] = score.get(c, 0.0) + g * w
    return max(score, key=score.get) if score else None


def _split_weights(scan, donors, targets, sigma):
    """targets: {side: (骨名, 乳尖)}。每个顶点按到乳尖的高斯 g 从胸部骨的权重里分出 g 份给胸骨,
    两侧重叠处 g 之和封顶 1;中线 ±0.25|乳尖x| 内按侧平滑过渡。总权重不变。返回改动的顶点数。"""
    cut = _CUT * sigma
    n = 0
    for m, idx, p, gs in scan.verts:
        dw = [(g, w) for g, w in gs if g in donors]
        if not dw:
            continue
        f = {}
        for side, (name, A) in targets.items():
            d = (p - A).length
            if d >= cut:
                continue
            r0 = max(0.25 * abs(A.x), 1e-4)
            t = min(1.0, max(0.0, (p.x * side + r0) / (2.0 * r0)))
            g = math.exp(-(d / sigma) ** 2) * t * t * (3.0 - 2.0 * t)
            if g > 1e-3:
                f[name] = g
        if not f:
            continue
        tot = sum(f.values())
        if tot > 1.0:
            f = {k: v / tot for k, v in f.items()}
            tot = 1.0
        keep = 1.0 - tot
        wd = sum(w for _g, w in dw)
        for g, w in dw:
            vg = m.vertex_groups[g]
            if w * keep > 1e-4:
                vg.add([idx], w * keep, 'REPLACE')
            else:
                vg.remove([idx])
        for name, g in f.items():
            vg = m.vertex_groups.get(name) or m.vertex_groups.new(name=name)
            vg.add([idx], wd * g, 'ADD')
        n += 1
    return n


# -- 标记(给用户看乳尖在哪) ----------------------------------------------------------------
def set_marker(context, side_key, world_pos, size):
    name = MARKER % side_key
    ob = bpy.data.objects.get(name)
    if ob is None:
        ob = bpy.data.objects.new(name, None)
        ob.empty_display_type = 'SPHERE'
        ob.hide_render = True
        context.scene.collection.objects.link(ob)
    ob.empty_display_size = size
    ob.location = world_pos
    ob.show_in_front = True


def clear_markers():
    for s in ("L", "R"):
        ob = bpy.data.objects.get(MARKER % s)
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)


# -- 流程 ---------------------------------------------------------------------------------
def _settle(context, root):
    """新建/删除前:停预览、Clean,刚体世界关掉(否则新建的刚体一创建就被求值挪位)。"""
    if root.mmd_physics.pv_active:
        preview.stop(context, root)
    if root.mmd_root.is_built:
        preview._call_on(root, bpy.ops.mmd_tools.clean_rig, context)
    rbw = context.scene.rigidbody_world
    if rbw is not None and rbw.enabled:
        rbw.enabled = False
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def detect(context, root):
    """找已有胸骨和自动乳尖,写进 breast_new(手动指定的那侧不动),放标记。返回每侧说明。"""
    from mmd_tools.core.model import Model
    arm = Model(root).armature()
    scan = Scan(arm)
    if not scan.ok:
        return None, ["找不到上半身系骨或蒙皮网格"]
    nb = root.mmd_physics.breast_new
    existing = find_existing(scan)
    msgs = []
    mw = arm.matrix_world
    for side, label, key in _SIDES:
        manual = getattr(nb, "manual_" + key.lower())
        if side in existing:
            bone, A = existing[side]
            setattr(nb, "apex_" + key.lower(), mw @ A)
            msgs.append(f"{label}: 已有胸骨 {bone},直接复用")
        elif manual:
            msgs.append(f"{label}: 用手动指定的乳尖")
        else:
            A = auto_apex(scan, side)
            if A is None:
                setattr(nb, "found_" + key.lower(), False)
                msgs.append(f"{label}: 没找到乳尖")
                continue
            setattr(nb, "apex_" + key.lower(), mw @ A)
            msgs.append(f"{label}: 自动找到乳尖")
        setattr(nb, "found_" + key.lower(), True)
        set_marker(context, key, Vector(getattr(nb, "apex_" + key.lower())), 0.012 * scan.H)
    return scan, msgs


def _anchor(model, arm, jp, rigids, bone_name, radius):
    """沿父链找第一个有刚体的骨,最多找到第一根上半身系骨为止;都没有就给那根骨补一个跟骨、
    不碰撞的锚刚体(只当关节的锚,不影响别的物理)。返回 (锚刚体, 新建锚的骨名或 None)。"""
    B = arm.data.bones
    cur = B[bone_name].parent
    target = None
    while cur is not None:
        if cur.name in rigids:
            return rigids[cur.name], None
        if jp.get(cur.name, cur.name) in _UPPER:
            target = cur
            break
        cur = cur.parent
    target = target or B[bone_name].parent
    if target is None:
        return None, None
    head = arm.matrix_world @ target.head_local
    rb = model.createRigidBody(
        shape_type=0, location=head, rotation=(0.0, 0.0, 0.0), size=(radius, 0.0, 0.0), dynamics_type=0,
        collision_group_number=0, collision_group_mask=[True] * 16,
        name=jp.get(target.name, target.name), bone=target.name,
        mass=1.0, friction=0.5, linear_damping=0.5, angular_damping=0.5, bounce=0.0)
    rb[TAG_NEW] = 1
    rigids[target.name] = rb
    return rb, jp.get(target.name, target.name)


def create(context, root):
    """补齐胸骨/权重/刚体/关节,套初始预设。返回说明列表;失败抛 RuntimeError。"""
    from mmd_tools.core.model import Model
    _settle(context, root)
    model = Model(root)
    arm = model.armature()
    scan = Scan(arm)
    if not scan.ok:
        raise RuntimeError("找不到上半身系骨(上半身/上半身2…)或蒙皮网格")
    st = root.mmd_physics
    nb = st.breast_new
    H = scan.H
    sigma = nb.sigma * H
    existing = find_existing(scan)
    msgs = [f"{'左' if s > 0 else '右'}: 复用 {n}" for s, (n, _A) in existing.items()]
    lr_style = any(n.endswith((".L", ".R")) for n in arm.data.bones.keys())
    inv = arm.matrix_world.inverted()

    # 1. 骨 + 权重(没有胸骨的那侧)
    todo = {}
    for side, label, key in _SIDES:
        if side in existing:
            continue
        name = ("胸." + key) if lr_style else (label + "胸")
        if name in arm.data.bones and not arm.data.bones[name].get(TAG_NEW):
            msgs.append(f"{label}: 已有同名骨 {name} 但权重不在乳房区,跳过")
            continue
        if getattr(nb, "manual_" + key.lower()):
            A = inv @ Vector(getattr(nb, "apex_" + key.lower()))
        else:
            A = auto_apex(scan, side)
        if A is None:
            msgs.append(f"{label}: 没找到乳尖(可在网格编辑模式选中乳尖顶点后指定),跳过")
            continue
        todo[side] = (name, label, A)
    if todo:
        skip = {n for n, _l, _A in todo.values()}
        for n, _A in existing.values():
            skip |= {n} | {c.name for c in arm.data.bones[n].children_recursive}
        donors = {n for n in scan.region(scan.upper) if n not in skip}
        plans = []
        for side, (name, label, A) in todo.items():
            parent = _chest_parent(scan, donors, A, side, sigma)
            if parent:
                plans.append((side, name, label, A, parent))
            else:
                msgs.append(f"{label}: 乳尖附近没有胸部骨的权重,跳过")
        if plans:
            view_layer = context.view_layer
            view_layer.objects.active = arm
            bpy.ops.object.mode_set(mode='EDIT')
            eb = arm.data.edit_bones
            for side, name, label, A, parent in plans:
                b = eb.get(name) or eb.new(name)
                b.head = A + Vector((0.0, nb.depth * H, 0.0))      # 面朝 -Y,乳尖后方 = +Y
                b.tail = A
                b.roll = 0.0
                b.parent = eb[parent]
                b.use_connect = False
                b.use_deform = True
            bpy.ops.object.mode_set(mode='OBJECT')
            for side, name, label, A, parent in plans:
                arm.data.bones[name][TAG_NEW] = "breast"
                pb = arm.pose.bones[name]
                pb.lock_location = (True, True, True)
                if hasattr(pb, "mmd_bone"):
                    pb.mmd_bone.name_j = label + "胸"
                    pb.mmd_bone.name_e = ("Left" if side > 0 else "Right") + "Breast"
                existing[side] = (name, A)
            nv = _split_weights(scan, donors, {s: (n, A) for s, n, _l, A, _p in plans}, sigma)
            for side, name, label, A, parent in plans:
                msgs.append(f"{label}: 新建 {name}(挂在 {parent} 下)")
            msgs.append(f"分出权重 {nv} 个顶点")

    # 2. 刚体 + 关节(没有胸部刚体的胸骨)
    rigids = {o.mmd_rigid.bone: o for o in model.rigidBodies() if o.mmd_rigid.bone}
    jp = _jp(arm)
    mw = arm.matrix_world
    radius = nb.radius * H
    n_rb = 0
    anchors = []
    for side, (name, A) in existing.items():
        if name in rigids:
            continue
        b = arm.data.bones[name]
        head = mw @ b.head_local
        apex = mw @ A
        rigid = model.createRigidBody(
            shape_type=0, location=head + (apex - head) * _CENTER, rotation=(0.0, 0.0, 0.0),
            size=(radius, 0.0, 0.0), dynamics_type=1,
            collision_group_number=15, collision_group_mask=[True] * 16,
            name=jp.get(name, name), bone=name,
            mass=1.0, friction=0.5, linear_damping=0.5, angular_damping=0.5, bounce=0.0)
        rigid[TAG_NEW] = 1
        rigid[groups.TAG] = "breast"
        rigids[name] = rigid
        anchor, made = _anchor(model, arm, jp, rigids, name, radius)
        if made:
            anchors.append(made)
        if anchor is None:
            msgs.append(f"{jp.get(name, name)}: 没有父骨,只建了刚体")
            continue
        r = math.radians(10.0)
        joint = model.createJoint(
            location=head, rotation=(0.0, 0.0, 0.0), rigid_a=anchor, rigid_b=rigid,
            maximum_location=(0.0, 0.0, 0.0), minimum_location=(0.0, 0.0, 0.0),
            maximum_rotation=(r, r, r), minimum_rotation=(-r, -r, -r),
            spring_linear=(0.0, 0.0, 0.0), spring_angular=(0.0, 0.0, 0.0),
            name=jp.get(name, name))
        joint[TAG_NEW] = 1
        joint[groups.TAG] = "breast"
        n_rb += 1
    rbw = context.scene.rigidbody_world
    if rbw is not None:
        rbw.enabled = False            # mmd_tools 建刚体时会按需新建并启用刚体世界
    if n_rb:
        msgs.append(f"刚体+关节 {n_rb} 组" + (f"(给 {'、'.join(anchors)} 补了锚刚体)" if anchors else ""))
    elif not msgs:
        msgs.append("两侧都已有胸部刚体,没有要新建的")

    # 3. 读进面板,套初始预设
    gs = st.breast
    gs.inited = False
    gs.original = ""
    g = params.sync_group(root, "breast")
    if not g.empty():
        gs.preset = nb.preset
        params.apply_preset(root, "breast", nb.preset)
    clear_markers()
    for key in ("l", "r"):
        setattr(nb, "manual_" + key, False)
        setattr(nb, "found_" + key, False)
    return msgs


def remove_created(context, root):
    """删掉本插件新建的胸部刚体/关节/锚刚体;新建的胸骨连同权重并回父骨后删除(复用的胸骨不动)。"""
    from mmd_tools.core.model import Model
    _settle(context, root)
    model = Model(root)
    arm = model.armature()
    objs = [o for o in list(model.rigidBodies()) + list(model.joints()) if o.get(TAG_NEW)]
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    created = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones if b.get(TAG_NEW) == "breast"}
    for m in _skinned_meshes(arm):
        for name, pname in created.items():
            vg = m.vertex_groups.get(name)
            if vg is None:
                continue
            pvg = (m.vertex_groups.get(pname) or m.vertex_groups.new(name=pname)) if pname else None
            for v in m.data.vertices:
                for g in v.groups:
                    if g.group == vg.index:
                        if pvg is not None and g.weight > 0.0:
                            pvg.add([v.index], g.weight, 'ADD')
                        break
            m.vertex_groups.remove(vg)
    if created:
        context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode='EDIT')
        eb = arm.data.edit_bones
        for name in created:
            if name in eb:
                eb.remove(eb[name])
        bpy.ops.object.mode_set(mode='OBJECT')
    gs = root.mmd_physics.breast
    gs.inited = False
    gs.original = ""
    return len(objs), len(created)


def has_created(model):
    return any(o.get(TAG_NEW) for o in list(model.rigidBodies()) + list(model.joints()))


# -- 操作 ---------------------------------------------------------------------------------
def _root(context):
    from . import ops
    return ops._root(context)


class _ModelOp:
    @classmethod
    def poll(cls, context):
        return _root(context) is not None


class MMDPHYS_OT_breast_detect(_ModelOp, bpy.types.Operator):
    """找已有胸骨或自动找乳尖,在视图里用小球标出来(新建前先看看位置对不对)"""
    bl_idname = "mmd_physics.breast_detect"
    bl_label = "检测乳尖"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        root = _root(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        _scan, msgs = detect(context, root)
        self.report({'INFO'}, ";".join(msgs))
        return {'FINISHED'}


class MMDPHYS_OT_breast_apex_select(bpy.types.Operator):
    """网格编辑模式下,用选中顶点的中心作为乳尖(按左右自动分;两侧都选了就两侧一起设)"""
    bl_idname = "mmd_physics.breast_apex_select"
    bl_label = "用选中顶点作乳尖"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and _root(context) is not None

    def execute(self, context):
        from mmd_tools.core.model import Model
        root = _root(context)
        arm = Model(root).armature()
        inv = arm.matrix_world.inverted()
        acc = {1.0: [], -1.0: []}
        for ob in context.objects_in_mode_unique_data:
            bm = bmesh.from_edit_mesh(ob.data)
            for v in bm.verts:
                if v.select:
                    p = ob.matrix_world @ v.co
                    acc[1.0 if (inv @ p).x >= 0.0 else -1.0].append(p)
        if not acc[1.0] and not acc[-1.0]:
            self.report({'WARNING'}, "没有选中顶点")
            return {'CANCELLED'}
        nb = root.mmd_physics.breast_new
        done = []
        for side, label, key in _SIDES:
            pts = acc[side]
            if not pts:
                continue
            c = sum(pts, Vector()) / len(pts)
            setattr(nb, "apex_" + key.lower(), c)
            setattr(nb, "manual_" + key.lower(), True)
            setattr(nb, "found_" + key.lower(), True)
            set_marker(context, key, c, 0.02 * max(arm.dimensions))
            done.append(label)
        self.report({'INFO'}, f"已指定{'、'.join(done)}乳尖({sum(len(v) for v in acc.values())} 个顶点)")
        return {'FINISHED'}


class MMDPHYS_OT_breast_apex_clear(_ModelOp, bpy.types.Operator):
    """取消手动指定的乳尖,改回自动"""
    bl_idname = "mmd_physics.breast_apex_clear"
    bl_label = "改回自动"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        nb = _root(context).mmd_physics.breast_new
        for key in ("l", "r"):
            setattr(nb, "manual_" + key, False)
            setattr(nb, "found_" + key, False)
        clear_markers()
        return {'FINISHED'}


class MMDPHYS_OT_breast_create(_ModelOp, bpy.types.Operator):
    """补齐胸骨(没有才建)、权重、球形刚体和关节,再套初始预设;已有带权重的胸骨直接复用"""
    bl_idname = "mmd_physics.breast_create"
    bl_label = "新建胸部物理"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        root = _root(context)
        try:
            msgs = create(context, root)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, "胸部物理: " + ";".join(msgs))
        print("[mmd_physics] 新建胸部物理: " + ";".join(msgs))
        return {'FINISHED'}


class MMDPHYS_OT_breast_remove_created(_ModelOp, bpy.types.Operator):
    """删除本插件新建的胸部刚体/关节/锚刚体;新建的胸骨连同权重并回父骨(模型原有的不动)"""
    bl_idname = "mmd_physics.breast_remove_created"
    bl_label = "删除新建的胸部物理"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        n_obj, n_bone = remove_created(context, _root(context))
        self.report({'INFO'}, f"已删除 刚体/关节 {n_obj} 个、胸骨 {n_bone} 根(权重并回父骨)")
        return {'FINISHED'}


def draw_create(layout, context, root):
    """胸部面板在模型没有胸部刚体时显示的「新建」区。"""
    nb = root.mmd_physics.breast_new
    box = layout.box()
    box.label(text="这个模型没有胸部物理,可以新建:", icon='ADD')
    box.operator("mmd_physics.breast_detect", icon='VIEWZOOM')
    col = box.column(align=True)
    for key, label in (("l", "左"), ("r", "右")):
        if getattr(nb, "found_" + key):
            src = "手动" if getattr(nb, "manual_" + key) else "自动"
            p = getattr(nb, "apex_" + key)
            col.label(text=f"{label}乳尖({src}): {p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f}")
        else:
            col.label(text=f"{label}乳尖: 未检测")
    row = box.row(align=True)
    row.operator("mmd_physics.breast_apex_select", icon='VERTEXSEL')
    row.operator("mmd_physics.breast_apex_clear", text="", icon='X')
    box.label(text="找偏了:Tab 进网格编辑,选中乳尖附近顶点后点上面", icon='INFO')
    col = box.column(align=True)
    col.prop(nb, "depth")
    col.prop(nb, "sigma")
    col.prop(nb, "radius")
    box.prop(nb, "preset")
    row = box.row()
    row.scale_y = 1.3
    row.operator("mmd_physics.breast_create", icon='PHYSICS')
    box.label(text="已有带权重的胸骨会直接复用,不造骨、不动权重", icon='INFO')


_CLASSES = (MMDPHYS_OT_breast_detect, MMDPHYS_OT_breast_apex_select, MMDPHYS_OT_breast_apex_clear,
            MMDPHYS_OT_breast_create, MMDPHYS_OT_breast_remove_created)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
