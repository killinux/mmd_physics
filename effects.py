"""效果选择(渲染用)的流程:胸部 / 头发 / 裙子 / 其他衣物各选一种方式,一键算好,一键还原。

apply(scene, root, plan):
1. 第一次:记下原值 —— 刚体(类型、质量、阻尼、摩擦、反弹、碰撞层)、关节(限位、弹簧、Blender 的弹簧设置)、
   场景重力、原动作(加假用户留着)、原来是否已「建立」物理。
2. 每次都从原值开始:清除物理 → 刚体 / 关节写回原值 → 动作换成原动作的新副本(上次的副本删掉)。
3. 选「MMD 刚体」的类:按预设改刚体 / 关节(rigidfx.py);胸部「整套换上」时原来的胸部摆动刚体改成跟骨,
   每条胸链另建一套(kits.py);写法「新建刚体」时给原来不动的链(没有刚体 / 只有跟骨刚体)临时建一套
   (chainbodies.py)。
4. 选其他方式的类:它们的摆动刚体改成跟骨(原类型记在刚体上,chains.ORIG_TYPE)。
5. 建立物理(mmd_tools),关掉刚体世界,按依赖顺序烘弹簧骨骼(kawaii.py)和骨骼布料(bonecloth.py)的链:
   挂在别的链上的链后烘,读到的是前面烘好的姿势。
6. 物理计算「MMD 同款」:关节换成 MMD 的弹簧(SPRING1、没有关节阻尼、旋转弹簧按缩放换算)、重力 98 单位/秒²、
   每个谁都不碰的刚体单独一个碰撞层(否则手会穿进胸里把胸顶开);「mmd_tools 原样」不换算。套件的刚体谁都不碰。
   物理步长:自动 = 用了要粗步长的套件(RGBA:MMD 的 60 Hz)就按它,否则场景原样;也可以直接给每秒步数。
   打开刚体世界,清缓存。
restore(scene, root):清除物理 → 原值 → 删掉套件和新建的链刚体 → 原动作 → 原重力、原步长 → 删掉本插件加的碰撞体
→ 原来建立着就再建立。

plan(effects_ui 从面板拼出来,脚本也可以自己拼):
  {"categories": {"BUST": {"method": "SPRING", "values": {...}}, ...},
   "groups": [{"name", "category", "bones": [...], "roots": [...], "tip": bool, "enabled": bool,
               "still": "" | "nobody" | "static"}, ...],
   "physics": "MMD" | "MMDTOOLS", "gravity_scale": 1.0, "scale": 12.5, "step": "AUTO" | "SCENE" | 每秒步数}
"""

import json
import time

import bpy
import numpy as np

from . import bonecloth, chainbodies, chains, kawaii, kits, rigidfx

STATE = "mmd_physics_fx_state"             # 根对象上:原值(JSON)
WORK = "mmd_physics_fx_work"               # 动作上:本插件建的工作副本
MMD_GRAVITY = 98.0                         # MMD 的重力,单位/秒²
HOLD_FRAMES = 1                            # 动作副本开头保持第一帧姿势的帧数(刚体关节在第二帧建,_hold_start);0 = 不保持
AXES6 = ("x", "y", "z", "ang_x", "ang_y", "ang_z")
LIMITS = tuple("limit_%s_%s_%s" % (k, a, e) for k in ("lin", "ang") for a in "xyz" for e in ("lower", "upper"))


def _model(root):
    from mmd_tools.core.model import Model
    return Model(root)


# -- 识别 -------------------------------------------------------------------------------------------------
def detect_groups(arm):
    """面板的分组列表:每条胸链一组,其余按 chains.cloth_groups,再加原来不动的链(chains.still_groups)。
    不动的链默认参与的条件:这一类没有会晃的链(转换来的模型整个没物理);有会晃的,作者大概是故意让这几条
    不动的,默认不参与,可以勾上。"""
    bust, cloth = chains.detect(arm)
    out = []
    for c in bust:
        out.append({"name": "%s(%s)" % (c.root, "左" if c.side == "L" else "右"), "category": "BUST",
                    "bones": list(c.bones), "roots": [c.root], "tip": bool(c.tip), "enabled": True, "still": ""})
    for g in cloth:
        out.append({"name": g.name, "category": g.category, "bones": list(g.bones),
                    "roots": chains.chain_roots(arm, g.bones), "tip": False, "enabled": True, "still": ""})
    taken = {n for c in bust for n in c.bones} | {n for g in cloth for n in g.bones}
    moving = {g.category for g in cloth}
    for g in chains.still_groups(arm, exclude=taken):
        out.append({"name": g.name, "category": g.category, "bones": list(g.bones),
                    "roots": chains.chain_roots(arm, g.bones), "tip": False, "enabled": g.category not in moving,
                    "still": g.still})
    return out


# -- 原值 -------------------------------------------------------------------------------------------------
def _body_rec(o):
    rb = o.rigid_body
    rec = {"type": o.mmd_rigid.type}
    if rb is not None:
        rec.update(mass=rb.mass, lin=rb.linear_damping, ang=rb.angular_damping, friction=rb.friction,
                   bounce=rb.restitution, cols=[bool(x) for x in rb.collision_collections])
    return rec


def _put_body(o, rec):
    if o.mmd_rigid.type != rec["type"]:
        o.mmd_rigid.type = rec["type"]
    rb = o.rigid_body
    if rb is not None and "mass" in rec:
        rb.mass, rb.linear_damping, rb.angular_damping = rec["mass"], rec["lin"], rec["ang"]
        rb.friction, rb.restitution = rec["friction"], rec["bounce"]
        rb.collision_collections = rec["cols"]
    if chains.ORIG_TYPE in o:
        del o[chains.ORIG_TYPE]


def _joint_rec(j):
    c = j.rigid_body_constraint
    rec = {k: getattr(c, k) for k in LIMITS}
    rec["spring_type"] = c.spring_type
    rec["damp"] = [getattr(c, "spring_damping_" + a) for a in AXES6]
    rec["use"] = [getattr(c, "use_spring_" + a) for a in AXES6]
    rec["k_lin"] = list(j.mmd_joint.spring_linear)
    rec["k_ang"] = list(j.mmd_joint.spring_angular)
    return rec


def _put_joint(j, rec):
    c = j.rigid_body_constraint
    for k in LIMITS:
        setattr(c, k, rec[k])
    j.mmd_joint.spring_linear = rec["k_lin"]          # mmd_tools 顺手把约束的弹簧刚度写回原数
    j.mmd_joint.spring_angular = rec["k_ang"]
    c.spring_type = rec["spring_type"]
    for a, d, u in zip(AXES6, rec["damp"], rec["use"]):
        setattr(c, "spring_damping_" + a, d)
        setattr(c, "use_spring_" + a, u)


def _state(root):
    return json.loads(root[STATE]) if STATE in root else None


def _save(root, state):
    root[STATE] = json.dumps(state, ensure_ascii=False)


def ensure_backup(scene, root):
    state = _state(root)
    if state is not None:
        return state
    m = _model(root)
    arm = m.armature()
    action = arm.animation_data.action if arm.animation_data else None
    world = scene.rigidbody_world
    state = {
        "bodies": {o.name: _body_rec(o) for o in m.rigidBodies() if not chains.made_by_us(o)},
        "joints": {j.name: _joint_rec(j) for j in m.joints()
                   if j.rigid_body_constraint is not None and not chains.made_by_us(j)},
        "gravity": list(scene.gravity), "use_gravity": scene.use_gravity,
        "built": bool(root.mmd_root.is_built),
        "action": action.name if action is not None else "",
        "action_fake": bool(action.use_fake_user) if action is not None else False,
        "colliders": [],
        "substeps": world.substeps_per_frame if world is not None else 0,
        "iterations": world.solver_iterations if world is not None else 0,
    }
    _save(root, state)
    return state


def _restore_values(m, state):
    for o in m.rigidBodies():
        rec = state["bodies"].get(o.name)
        if rec is not None:
            _put_body(o, rec)
    for j in m.joints():
        rec = state["joints"].get(j.name)
        if rec is not None and j.rigid_body_constraint is not None:
            _put_joint(j, rec)


def _fresh_action(arm, state):
    """动作换成原动作的新副本。用户期间换了动作(重新导入 VMD)就以新的为原动作。"""
    ad = arm.animation_data
    cur = ad.action if ad else None
    orig = bpy.data.actions.get(state["action"]) if state["action"] else None
    if cur is not None and not cur.get(WORK) and cur is not orig:
        orig = cur
        state["action"], state["action_fake"] = cur.name, bool(cur.use_fake_user)
    if orig is None:
        return None
    orig.use_fake_user = True                      # 工作副本上场后原动作没有用户,靠假用户留着
    if cur is not None and cur.get(WORK):
        ad.action = orig
        bpy.data.actions.remove(cur)
    work = orig.copy()
    work.name = orig.name + ".物理效果"
    work[WORK] = True
    work.use_fake_user = False
    ad.action = work
    return work


def _hold_start(action, start, frames):
    """动作副本开头 frames 帧保持第一帧的姿势。Blender 在模拟的第二帧(start + 1)才按各刚体当时的位置建关节:
    跟骨的刚体已经摆到第二帧的姿势,摆动刚体和关节还在第一帧的位置,这一帧的错位就永久留在关节里(胸、头发、
    裙子整段偏几度);而且同一个 Blender 里第一次模拟和以后的模拟错位不一样(新开的 Blender 和播过一遍的结果
    不同)。第二帧和第一帧姿势一样就没有错位,结果也不再看之前播没播过。返回改了几条曲线。"""
    n = 0
    for fc in action.fcurves:
        v0 = fc.evaluate(start)
        need = [start + k for k in range(1, frames + 1) if abs(fc.evaluate(start + k) - v0) > 1e-7]
        for f in need:
            fc.keyframe_points.insert(f, v0, options={"FAST"})
        if need:
            fc.update()
            n += 1
    return n


# -- 链的单位和顺序 -----------------------------------------------------------------------------------------
class Unit:
    """一起模拟的一批骨(同一类、同一种方式;挂在同类别的链上的链并进来)。"""

    def __init__(self, category, method, values):
        self.category, self.method, self.values = category, method, values
        self.bones, self.tip, self.level = [], False, 0

    def anchors(self, arm):
        s = set(self.bones)
        return {arm.data.bones[r].parent.name for r in chains.chain_roots(arm, self.bones)
                if arm.data.bones[r].parent is not None} - s


def _units(arm, groups, categories):
    """按方式分好的单位,带层级(0 = 挂在不模拟的骨上;1 = 挂在第 0 层的骨上……)。"""
    plain = []
    for g in groups:
        if not g.get("enabled", True):
            continue
        cat = categories.get(g["category"])
        if cat is None or cat["method"] not in ("SPRING", "CLOTH"):
            continue
        u = Unit(g["category"], cat["method"], cat["values"])
        u.bones, u.tip = list(g["bones"]), bool(g.get("tip"))
        plain.append(u)
    # 同类同方式、挂在对方骨上的并成一个
    merged = True
    while merged:
        merged = False
        for a in plain:
            for b in plain:
                if a is b or a.category != b.category or a.method != b.method:
                    continue
                if a.anchors(arm) & set(b.bones):
                    b.bones = [n.name for n in arm.data.bones if n.name in set(b.bones) | set(a.bones)]
                    b.tip = b.tip or a.tip
                    plain.remove(a)
                    merged = True
                    break
            if merged:
                break
    owner = {n: u for u in plain for n in u.bones}
    for _ in range(len(plain)):
        changed = False
        for u in plain:
            lv = max([owner[a].level + 1 for a in u.anchors(arm) if a in owner and owner[a] is not u] or [0])
            if lv != u.level:
                u.level, changed = lv, True
        if not changed:
            break
    return plain


def _kawaii_specs(arm, units, colliders):
    out = []
    scale_m = kawaii.cm_to_m(arm)
    for u in units:
        v = u.values
        settings = {k: v[k] for k in ("stiffness", "damping", "world_damping_location", "world_damping_rotation",
                                     "limit_angle", "radius_cm")}
        settings["gravity_cm"] = (0.0, 0.0, -float(v.get("gravity_cm", 0.0)))
        settings["target_fps"] = int(v.get("target_fps", 60))
        settings["allow_legs"] = bool(v.get("allow_legs", False))
        caps = []
        if v.get("capsules"):
            caps += kawaii.vindictus_capsules(arm, scale_m)
        if v.get("colliders"):
            anchors = sorted(u.anchors(arm))
            centre = body_centre(arm, anchors[0]) if anchors else None
            # 腿的碰撞体在链底下动(不跟链挂在同一根身体骨上):第一帧陷进去多少不放过
            caps += [kawaii.ObjectCapsule(arm, o, moving=o.parent_bone != centre) for o in colliders]
        tip = float(v.get("tip", 0.0)) or (1.0 if u.tip else 0.0)
        carrier = None if v.get("carrier", "NONE") in ("NONE", "", None) else v["carrier"]
        members = set(u.bones)
        for root in chains.chain_roots(arm, u.bones):
            out.append(kawaii.spec(kawaii.Chain(arm, root, members=members, tip=tip), settings, carrier, caps,
                                   rest_allow=True))
    return out


BODY_BONES = ("頭", "首", "上半身3", "上半身2", "上半身", "下半身", "センター",
              "左肩", "右肩", "左腕", "右腕", "左ひじ", "右ひじ", "左手首", "右手首", "左足", "右足", "左ひざ", "右ひざ")


def body_centre(arm, anchor):
    """骨骼布料的「身体」骨(惯性和背挡的轴):挂点骨往上最近的标准 MMD 身体骨。Vindictus 的裙子挂在
    Outfit005_skirt_root 上,那根骨朝前上方,拿它当轴背挡会把后面、侧面的裙片往上推。"""
    b = arm.data.bones.get(anchor) if anchor else None
    while b is not None:
        if any(n in BODY_BONES for n in chains.names_of(arm.pose.bones[b.name])):
            return b.name
        b = b.parent
    return anchor


def _batch_cloth(arm, units):
    """同一层、同一类、挂在同一根身体骨上的骨骼布料单位并成一批,一起模拟(参数相同,numpy 只走一遍)。"""
    batches = {}
    for u in units:
        roots = chains.chain_roots(arm, u.bones)
        anchors = sorted({arm.data.bones[r].parent.name for r in roots if arm.data.bones[r].parent is not None})
        key = (u.category, body_centre(arm, anchors[0]) if anchors else None)
        b = batches.get(key)
        if b is None:
            b = batches[key] = Unit(u.category, u.method, u.values)
            b.level = u.level
        b.bones = [n.name for n in arm.data.bones if n.name in set(b.bones) | set(u.bones)]
    return list(batches.values())


def _sample(scene, arm, units, frames, colliders):
    """骨骼布料各单位的动画姿势(世界空间)、挂点骨矩阵、碰撞体、链外父骨,一次过帧全部读出。"""
    out = {}
    for u in units:
        cs = bonecloth.chain_set(arm, u.bones)
        roots = [n for n, p in zip(cs.names, cs.parent) if p < 0]
        anchors = sorted({arm.data.bones[n].parent.name for n in roots if arm.data.bones[n].parent is not None})
        names = cs.names
        out[id(u)] = dict(cs=cs, centre=body_centre(arm, anchors[0]) if anchors else None,
                          pbs=[arm.pose.bones[n] for n in names],
                          par=sorted({arm.pose.bones[n].parent.name for n in names
                                      if arm.pose.bones[n].parent is not None
                                      and arm.pose.bones[n].parent.name not in names}),
                          base=[], cen=[], caps=[], parents=[], colliders=colliders if u.values.get("colliders") else [])
    for f in frames:
        scene.frame_set(f)
        A = arm.matrix_world
        for u in units:
            d = out[id(u)]
            pbs = d["pbs"]
            d["base"].append({"rot": np.array([np.array((A @ pb.matrix).to_3x3().normalized()) for pb in pbs]),
                              "head": np.array([tuple(A @ pb.head) for pb in pbs]),
                              "tail": np.array([tuple(A @ pb.tail) for pb in pbs])})
            d["cen"].append(np.array(A @ arm.pose.bones[d["centre"]].matrix) if d["centre"] else np.array(A))
            d["caps"].append(bonecloth._capsules(d["colliders"]) if d["colliders"] else None)
            d["parents"].append({n: arm.pose.bones[n].matrix.copy() for n in d["par"]})
    for d in out.values():
        if all(c is None for c in d["caps"]):
            d["caps"] = None
    return out


def _apply_kit(m, arm, groups, v, plan):
    """胸部「整套换上」:每条胸链的原摆动刚体改成跟骨(记原类型),另建一套 kits.py 的刚体和关节。返回说明。"""
    lines = []
    side_bones = {}
    for g in groups:
        side_bones.setdefault(chains.side_of(arm, g["roots"][0]), set()).update(g["bones"])
    apexes = kits.side_apexes(arm, side_bones)
    key = v.get("kit", "rgba")
    built = {}
    for g in groups:
        root = g["roots"][0]
        chain = chains.BustChain(chains.side_of(arm, root), root, list(g["bones"]), bool(g.get("tip")))
        bones = set(chain.bones)
        for o in m.rigidBodies():
            if o.mmd_rigid.bone in bones and chains.body_type(o) in ("1", "2") and not chains.made_by_us(o):
                if chains.ORIG_TYPE not in o:
                    o[chains.ORIG_TYPE] = o.mmd_rigid.type
                o.mmd_rigid.type = "0"
        r = kits.build(m, arm, chain, key, scale=v.get("kit_scale", 1.0),
                       limit_scale=v.get("kit_limit", 1.0), lift=v.get("kit_lift", 1.0),
                       mass_scale=v.get("kit_mass", 1.0),
                       pmx_scale=plan.get("scale", 12.5), side_bones=side_bones[chain.side],
                       apex=apexes.get(chain.side))
        built.setdefault(chain.side, []).append(r)
        lines.append("%s %s(驱动 %s,大小 ×%.2f)" % (kits.KITS[key]["label"], g["name"], r["main"], r["rel"]))
    if v.get("kit_pair") and kits.has_pairs(key):          # 左右连着(AH 式「着衣用」):同序号的左右两条链
        n = sum(kits.link_sides(m, key, a, b) for a, b in zip(built.get("L", []), built.get("R", [])))
        lines.append("左右连着(%d 个关节)" % n)
    return lines


def step_hz(plan):
    """这次的物理步长(每秒步数),0 = 场景原样。"""
    step = plan.get("step", "AUTO")
    if step == "SCENE":
        return 0
    if step != "AUTO":
        return int(step)
    c = plan["categories"].get("BUST")
    if c is not None and c["method"] == "RIGID" and c["values"].get("kind") == "kit":
        return kits.step_hz(c["values"].get("kit", ""))
    return 0


def _hide_meshes(root):
    """烘焙时先把模型的网格藏起来(逐帧求值快很多)。腿和胯的碰撞体也是网格,但不能藏:hide_viewport 的物体
    不参与求值,胶囊会一直停在第一帧,不跟腿走,裙子撞上留在原地的胶囊就被顶起来卡住。"""
    hidden = []
    for o in root.children_recursive:
        if o.type == "MESH" and getattr(o, "mmd_type", "") == "NONE" and not o.hide_viewport \
                and not o.get(bonecloth.COLLIDER_TAG):
            o.hide_viewport = True
            hidden.append(o)
    return hidden


# -- 物理计算 ----------------------------------------------------------------------------------------------
def own_layers(m):
    """每个和所有组都不碰的刚体单独一个碰撞层(19, 18, ……):MMD 里它们谁都不碰,mmd_tools 只给开始时挨着的
    刚体之间加了不碰撞约束,手臂甩过来照样会撞上胸。"""
    layer = 19
    for o in m.rigidBodies():
        if chains.made_by_us(o):
            continue                                # 套件、新建的链刚体谁都不碰(kits / chainbodies.no_collisions)
        if o.rigid_body is not None and all(o.mmd_rigid.collision_group_mask) and layer > 0:
            o.rigid_body.collision_collections = [i == layer for i in range(20)]
            layer -= 1
    return 19 - layer


def mmd_like(scene, m, scale, gravity_scale=1.0):
    """关节按 MMD 的方式:SPRING1、关节阻尼 0(Blender 把 SPRING1 的阻尼取反,0 = Bullet 的默认 1.0 = MMD)、
    旋转弹簧 × (1/scale)²(弹簧量纲带长度²)、平移弹簧不变;重力 98 单位/秒² 换成米。返回换算的关节数。"""
    s = 1.0 / scale
    n = 0
    for j in m.joints():
        c = j.rigid_body_constraint
        if c is None or c.type != "GENERIC_SPRING":
            continue
        c.spring_type = "SPRING1"
        for a in AXES6:
            setattr(c, "spring_damping_" + a, 0.0)
        kl, ka = j.mmd_joint.spring_linear, j.mmd_joint.spring_angular
        c.spring_stiffness_x, c.spring_stiffness_y, c.spring_stiffness_z = kl[0], kl[1], kl[2]
        c.spring_stiffness_ang_x, c.spring_stiffness_ang_y, c.spring_stiffness_ang_z = (
            ka[0] * s * s, ka[1] * s * s, ka[2] * s * s)
        n += 1
    own_layers(m)
    scene.use_gravity = True
    scene.gravity = (0.0, 0.0, -MMD_GRAVITY * s * gravity_scale)
    return n


def free_cache(scene):
    world = scene.rigidbody_world
    if world is None:
        return
    world.point_cache.frame_start = scene.frame_start
    world.point_cache.frame_end = scene.frame_end
    with bpy.context.temp_override(scene=scene, point_cache=world.point_cache):
        bpy.ops.ptcache.free_bake()


def bake_cache(scene):
    """渲染前烘焙刚体缓存(场景帧范围)。"""
    world = scene.rigidbody_world
    if world is None:
        return False
    world.point_cache.frame_start = scene.frame_start
    world.point_cache.frame_end = scene.frame_end
    with bpy.context.temp_override(scene=scene, point_cache=world.point_cache):
        bpy.ops.ptcache.free_bake()
        bpy.ops.ptcache.bake(bake=True)
    return True


# -- 主流程 ------------------------------------------------------------------------------------------------
def apply(scene, root, plan, log=print):
    t0 = time.time()
    m = _model(root)
    arm = m.armature()
    state = ensure_backup(scene, root)
    if root.mmd_root.is_built:
        m.clean()
    kits.remove(m)
    chainbodies.remove(m)
    _restore_values(m, state)
    work = _fresh_action(arm, state)
    cats = plan["categories"]
    groups = [g for g in plan["groups"] if g.get("enabled", True)]
    by_cat = {}
    for g in groups:
        by_cat.setdefault(g["category"], []).append(g)
    report = []
    # 3. MMD 刚体的类:预设写进刚体 / 关节
    for cat, gs in by_cat.items():
        c = cats.get(cat)
        if c is None or c["method"] != "RIGID":
            continue
        still = [g for g in gs if g.get("still")]
        bones = [n for g in gs if not g.get("still") for n in g["bones"]]
        if cat == "BUST" and c["values"].get("kind") == "kit":
            report.append("胸部整套换上:" + ";".join(_apply_kit(m, arm, gs, c["values"], plan)))
        elif cat == "BUST":
            lines = rigidfx.apply_bust(m, bones, c["values"], plan.get("scale", 12.5))
            report.append("胸部 MMD 刚体:%s" % ("模型原样" if not lines else ";".join(lines)))
        else:
            n = rigidfx.apply_chains(m, bones, c["values"]) if bones else 0
            line = "%s MMD 刚体:%s" % (chains.CATEGORY_LABEL[cat], "改了 %d 个刚体" % n if n else "模型原样")
            if still and c["values"].get("kind") == "build":
                nb, nj = chainbodies.build(m, arm, [g["bones"] for g in still], c["values"], plan.get("scale", 12.5))
                line += ";%d 组原来不动的链新建刚体 %d 个、关节 %d 个" % (len(still), nb, nj)
            elif still:
                line += ";%d 组原来不动的链照旧不动(写法选「新建刚体」才会晃)" % len(still)
            report.append(line)
    # 4. 其他方式的类:摆动刚体改成跟骨
    follow = set()
    for cat, gs in by_cat.items():
        c = cats.get(cat)
        if c is not None and c["method"] != "RIGID":
            follow.update(n for g in gs for n in g["bones"])
    changed = 0
    for o in m.rigidBodies():
        if o.mmd_rigid.bone in follow and chains.body_type(o) in ("1", "2"):
            if chains.ORIG_TYPE not in o:
                o[chains.ORIG_TYPE] = o.mmd_rigid.type
            o.mmd_rigid.type = "0"
            changed += 1
    # 还有摆动刚体就让动作开头保持一帧(_hold_start):弹簧骨骼、骨骼布料随后也按这份动作算
    if work is not None and HOLD_FRAMES and any(chains.body_type(o) in ("1", "2") for o in m.rigidBodies()):
        n = _hold_start(work, scene.frame_start, HOLD_FRAMES)
        if n:
            report.append("动作开头保持 %d 帧(%d 条曲线):刚体关节在第二帧建,那时姿势不动才不留错位" % (HOLD_FRAMES, n))
    # 碰撞体(腿、胯),要的单位才建
    units = _units(arm, groups, cats)
    colliders = bonecloth.collider_objects(arm)
    if any(u.values.get("colliders") for u in units) and not colliders:
        colliders = bonecloth.add_body_colliders(arm, log=lambda s: None)
        state["colliders"] = sorted(set(state.get("colliders", [])) | {o.name for o in colliders})
    # 5. 建立物理,烘链
    scene.frame_set(scene.frame_start)
    t = time.time()
    m.build()
    kits.no_collisions(m)
    chainbodies.no_collisions(m)
    report.append("建立物理 %.1f 秒" % (time.time() - t))
    world = scene.rigidbody_world
    world_on = world.enabled if world is not None else False
    if world is not None:
        world.enabled = False
    hidden = _hide_meshes(root)
    frames = list(range(scene.frame_start, scene.frame_end + 1))
    fps = scene.render.fps / scene.render.fps_base
    try:
        for level in sorted({u.level for u in units}):
            lv = [u for u in units if u.level == level]
            springs = [u for u in lv if u.method == "SPRING"]
            if springs:
                t = time.time()
                specs = _kawaii_specs(arm, springs, colliders)
                fr, bases = kawaii.simulate(scene, arm, specs)
                kawaii.write_keys(arm, fr, bases, tag=False)
                report.append("弹簧骨骼(第 %d 层):%d 条链 %d 根骨,%.1f 秒" % (level, len(specs), len(bases),
                                                                          time.time() - t))
            cloths = _batch_cloth(arm, [u for u in lv if u.method == "CLOTH"])
            if cloths:
                t = time.time()
                rests = {id(u): bonecloth.rest_pose(scene, arm, bonecloth.chain_set(arm, u.bones).names, colliders)
                         if u.values.get("colliders") else None for u in cloths}
                data = _sample(scene, arm, cloths, frames, colliders)
                for u in cloths:
                    d = data[id(u)]
                    if rests[id(u)] is not None:
                        # 不跟布料挂在同一根身体骨上的碰撞体(腿)在布料底下动,静止时陷进去多少不放过
                        rests[id(u)]["moving"] = [o.parent_bone != d["centre"] for o in colliders]
                    params = {k: v for k, v in u.values.items() if k != "colliders"}
                    params["unit"] = bonecloth.metres_per_unit(arm)
                    sim = bonecloth.simulate(d["cs"], d["base"], d["cen"], d["caps"], fps, params, rest=rests[id(u)])
                    bonecloth.write_keys(arm, d["cs"], frames, sim, d["parents"])
                report.append("骨骼布料(第 %d 层):%d 批 %d 根骨,%.1f 秒" % (
                    level, len(cloths), sum(len(u.bones) for u in cloths), time.time() - t))
    finally:
        for o in hidden:
            o.hide_viewport = False
        if world is not None:
            world.enabled = world_on
    # 6. 物理计算
    if plan.get("physics", "MMD") == "MMD":
        n = mmd_like(scene, m, plan.get("scale", 12.5), plan.get("gravity_scale", 1.0))
        report.append("物理按 MMD 同款:%d 个关节换算,重力 %g 单位/秒²" % (n, MMD_GRAVITY * plan.get("gravity_scale", 1.0)))
    else:
        scene.gravity, scene.use_gravity = state["gravity"], state["use_gravity"]
    world = scene.rigidbody_world
    if world is not None:
        hz = step_hz(plan)
        if hz:
            world.substeps_per_frame = max(1, int(round(hz / fps)))
            report.append("物理步长 %d Hz(每帧 %d 步)" % (round(fps * world.substeps_per_frame),
                                                        world.substeps_per_frame))
        elif state.get("substeps"):
            world.substeps_per_frame = state["substeps"]
        world.enabled = True
    free_cache(scene)
    scene.frame_set(scene.frame_start)
    _save(root, state)
    report.append("跟骨的刚体 %d 个,用时 %.1f 秒%s" % (changed, time.time() - t0,
                                                 ",动作副本 " + work.name if work is not None else ""))
    for line in report:
        log(line)
    return report


def restore(scene, root):
    """回到第一次用效果之前。返回 False = 没用过。"""
    state = _state(root)
    if state is None:
        return False
    m = _model(root)
    arm = m.armature()
    if root.mmd_root.is_built:
        m.clean()
    _restore_values(m, state)
    kits.remove(m)
    chainbodies.remove(m)
    ad = arm.animation_data
    cur = ad.action if ad else None
    orig = bpy.data.actions.get(state["action"]) if state["action"] else None
    if orig is not None and ad is not None:
        ad.action = orig
        orig.use_fake_user = state["action_fake"]
    if cur is not None and cur.get(WORK) and cur is not orig:
        bpy.data.actions.remove(cur)
    for name in state.get("colliders", []):
        o = bpy.data.objects.get(name)
        if o is not None:
            bpy.data.objects.remove(o)
    scene.gravity, scene.use_gravity = state["gravity"], state["use_gravity"]
    world = scene.rigidbody_world
    if world is not None and state.get("substeps"):
        world.substeps_per_frame, world.solver_iterations = state["substeps"], state["iterations"]
    del root[STATE]
    if state["built"]:
        scene.frame_set(scene.frame_start)
        m.build()
    free_cache(scene)
    return True
