"""骨骼布料（Magica 风格）的解算和场景部分。

来自 ripper_tpose 仓库的骨骼布料插件（scripts/blender_addons/bone_cloth/core.py），原样搬进来给效果面板用。

原说明 —— 骨骼布料的核心：照 Magica Cloth 2（BoneCloth）的做法，在 Blender 里模拟骨链，烘焙成关键帧。

Magica Cloth 2 防穿模靠的几样东西（https://magicasoft.jp/en/mc2_magicaclothcomponent/ 各约束页），这里都照做：
  - 以动画姿势为基准（Animation Pose Ratio）：每一节都往"它在动画里的方向"拉回去（角度恢复 Angle Restoration），
    偏离动画方向不许超过设定角度（角度限制 Angle Limit），根部严、梢部松；
  - 背挡（Backstop）：每个点在动画位置沿外法线反方向的背后有一个大球，点进不去，所以布不会往身体里陷；
  - 最大距离（Max Distance）：点离动画位置不超过设定距离；
  - 碰撞体（Collider Collision）：身体上的胶囊 / 球，布的点当小球（点模式），或骨段当胶囊（边模式，不会从缝里钻过去）；
  - 惯性限速（Inertia）：身体自己的移动只按比例、而且只在限速以内传给布，技能动作再快也不会把裙子甩穿腿。

和 Magica 一样，一组骨链的根挂在不参与模拟的父骨上（例如裙子挂在下半身），根骨的头跟着动画走，
其余每根骨的尾端是一个质点。骨长是刚性的：每次修正后尾端都投回到"头 + 方向 × 骨长"。

这里只用 numpy 和 mathutils，不依赖 mmd_tools；场景相关的部分（读动画姿势、写关键帧、刚体跟随骨骼）在本文件后半。
"""
import math

import numpy as np

# ---------------------------------------------------------------------------------------------- defaults

DEFAULTS = {
    # 和 Magica Cloth 2 同名的参数；数值按 90 Hz 的模拟步长理解（Magica 默认的模拟频率）
    "gravity": 5.0,                  # m/s²，Magica 默认 5
    "damping": 0.05,                 # 每步速度衰减
    "radius": 0.02,                  # 质点半径（m）
    "restore_stiffness": 0.2,        # 角度恢复：每步拉回的比例
    "restore_attenuation": 0.8,      # 角度恢复的速度衰减：拉回的位移有多少不变成速度
    "limit_root": 25.0,              # 角度限制：根部（度）
    "limit_tip": 60.0,               # 角度限制：梢部（度）
    "inertia": 0.4,                  # 身体移动传给布的比例（Magica 的 World Inertia）
    "move_limit": 3.0,               # 身体移动限速（m/s），超过的部分不传给布
    "turn_limit": 360.0,             # 身体转动限速（度/s）
    "particle_limit": 4.0,           # 质点限速（m/s）
    "backstop": True,
    "backstop_radius": 10.0,         # 背挡球半径（m），很大时相当于一个平面
    "backstop_distance": 0.02,       # 允许往身体方向退的距离（m）
    "max_distance_on": False,
    "max_distance": 0.3,
    "collision_edge": True,          # 边模式（骨段当胶囊）；关掉就是点模式
    "friction": 0.05,
    "floor": True,                   # 地面：世界 Z = floor_height 的平面（Magica 的平面碰撞体），点不许到它下面
    "floor_height": 0.0,
    "substeps": 3,                   # 每帧子步数（30 fps × 3 = 90 Hz）
    "iterations": 4,
    "blend": 1.0,                    # 1 = 完全用模拟结果，0 = 完全用动画
    # 相邻链连接（mmd_physics 加的，Magica 的 Mesh 连接那样）：同一层上离得近的两条链的骨尾，距离只许在
    # 第一帧的 (1 - squash) ~ (1 + stretch) 倍之间变，环形裙子被腿顶起来时相邻裙片不会分开
    "link": False,
    "link_stretch": 0.2,
    "link_squash": 0.5,
    "link_max": 0.2,                 # 只连第一帧时离得比这近的（m）
    # 静止时就陷在会动的碰撞体（腿）里的布骨：关 = 推出去（骨贴着腿走的外套会张开一些，腿不会穿出来）；
    # 开 = 和陷在胯里的一样放过（保持静止时的形状，腿一动就会穿出来）
    "allow_legs": False,
}


def link_pairs(cs, tails, max_dist):
    """每层里每根骨找别的链上最近的两根骨（第一帧骨尾距离 < max_dist）：[(层, i 数组, j 数组, 静止距离)]。"""
    chain = np.zeros(len(cs.names), int)
    for i in range(len(cs.names)):
        chain[i] = i if cs.parent[i] < 0 else chain[cs.parent[i]]
    out = []
    for k, lv in enumerate(cs.levels):
        if len(lv) < 2:
            continue
        p = tails[lv]
        d = np.linalg.norm(p[:, None, :] - p[None, :, :], axis=2)
        same = chain[lv][:, None] == chain[lv][None, :]
        d = np.where(same, np.inf, d)
        pairs = set()
        for a in range(len(lv)):
            for b in np.argsort(d[a])[:2]:
                if d[a, b] < max_dist:
                    pairs.add((min(a, b), max(a, b)))
        if pairs:
            ia = np.array([lv[a] for a, _b in sorted(pairs)])
            ib = np.array([lv[b] for _a, b in sorted(pairs)])
            out.append((k, ia, ib, np.linalg.norm(tails[ia] - tails[ib], axis=1)))
    return out


# ---------------------------------------------------------------------------------------------- vector helpers

def _unit(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-12)


def _rotate(v, axis, angle):
    """Rodrigues: rotate vectors v (n,3) about unit axes (n,3) by angles (n,)."""
    c, s = np.cos(angle)[:, None], np.sin(angle)[:, None]
    return v * c + np.cross(axis, v) * s + axis * np.einsum("ij,ij->i", axis, v)[:, None] * (1 - c)


def _towards(a, b, t=None, max_angle=None):
    """Turn unit vectors a toward unit vectors b: by the fraction t of the angle, or up to max_angle (radians)."""
    dot = np.clip(np.einsum("ij,ij->i", a, b), -1.0, 1.0)
    ang = np.arccos(dot)
    axis = np.cross(a, b)
    n = np.linalg.norm(axis, axis=1)
    # (anti)parallel: any axis perpendicular to a
    fallback = np.cross(a, np.where(np.abs(a[:, :1]) < 0.9, [[1.0, 0, 0]], [[0, 1.0, 0]]))
    axis = np.where(n[:, None] > 1e-9, axis / np.maximum(n, 1e-12)[:, None], _unit(fallback))
    step = ang * t if t is not None else np.minimum(ang, max_angle)
    return _unit(_rotate(a, axis, step))


def _swing(a, b):
    """Rotation matrices (n,3,3) turning unit vectors a into b by the shortest arc."""
    v = np.cross(a, b)
    c = np.clip(np.einsum("ij,ij->i", a, b), -1.0, 1.0)
    vx = np.zeros((len(a), 3, 3))
    vx[:, 0, 1], vx[:, 0, 2] = -v[:, 2], v[:, 1]
    vx[:, 1, 0], vx[:, 1, 2] = v[:, 2], -v[:, 0]
    vx[:, 2, 0], vx[:, 2, 1] = -v[:, 1], v[:, 0]
    k = 1.0 / np.maximum(1.0 + c, 1e-6)
    return np.eye(3)[None] + vx + vx @ vx * k[:, None, None]


def _orthonormal(M):
    """A 4x4 with its rotation columns normalized (an armature scaled to metres keeps its scale in the matrix)."""
    M = np.array(M, float)
    M[:3, :3] = M[:3, :3] / np.maximum(np.linalg.norm(M[:3, :3], axis=0, keepdims=True), 1e-12)
    return M


def _slerp_rot(R, t):
    """Fraction t of a rotation matrix (axis-angle scaled)."""
    tr = np.clip((np.trace(R) - 1) / 2, -1.0, 1.0)
    ang = math.acos(tr)
    if ang < 1e-9:
        return np.eye(3)
    axis = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * math.sin(ang))
    a = ang * t
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * K @ K


# ---------------------------------------------------------------------------------------------- the chain set

class ChainSet:
    """Bones simulated together, in topological order (parents first).

    parent[i]   index of the parent in this set, or -1 (a root: its head rides a bone outside the set)
    connected[i] head == the parent's tail (else the head rides the parent's frame at its rest offset)
    length[i]   bone length (m), depth[i] 0 at a root .. 1 at the deepest tip of its chain
    """

    def __init__(self, names, parent, connected, length, depth):
        self.names = list(names)
        self.parent = np.asarray(parent, int)
        self.connected = np.asarray(connected, bool)
        self.length = np.asarray(length, float)
        self.depth = np.asarray(depth, float)
        n = len(self.names)
        lv = np.zeros(n, int)
        for i in range(n):
            lv[i] = 0 if self.parent[i] < 0 else lv[self.parent[i]] + 1
        self.levels = [np.nonzero(lv == k)[0] for k in range(lv.max() + 1 if n else 0)]


# ---------------------------------------------------------------------------------------------- colliders

def _point_pen(p, r, caps):
    """How deep points p (n,3) of radii r sink into each capsule (n,m), and the outward normals (n,m,3)."""
    a, b, ra, rb = caps
    ab = b - a
    L2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-12)
    t = np.clip(np.einsum("nmk,mk->nm", p[:, None, :] - a[None], ab) / L2[None], 0.0, 1.0)
    c = a[None] + t[..., None] * ab[None]
    rc = ra[None] + (rb - ra)[None] * t
    d = p[:, None, :] - c
    dist = np.linalg.norm(d, axis=2)
    return rc + r[:, None] - dist, d / np.maximum(dist, 1e-9)[..., None]


def _push_points(p, r, caps, allow=None):
    """Push points p (n,3) with radii r (n,) out of capsules caps = (a, b, ra, rb) arrays (m,...).  ``allow``
    (n,m): how deep each point may stay in each capsule (what the model has at rest).  Returns the points and
    who touched."""
    if caps is None or len(caps[0]) == 0:
        return p, np.zeros(len(p), bool)
    allow = 0.0 if allow is None else allow
    out = p.copy()
    hit = np.zeros(len(p), bool)
    for _ in range(2):                       # a point between two legs: push from both, twice
        pen, nrm = _point_pen(out, r, caps)
        pen = pen - allow
        touch = pen > 0
        if not touch.any():
            break
        hit |= touch.any(axis=1)
        out = out + (nrm * np.where(touch, pen, 0.0)[..., None]).sum(axis=1)
    return out, hit


def _segment_closest(p0, p1, a, b):
    """Closest points between segments p0-p1 (n,3) and a-b (m,3): parameters s (n,m) on p, t (n,m) on a-b."""
    d1 = (p1 - p0)[:, None, :]
    d2 = (b - a)[None, :, :]
    r = p0[:, None, :] - a[None, :, :]
    A = np.einsum("nmk,nmk->nm", d1, d1)
    E = np.einsum("nmk,nmk->nm", d2, d2)
    F = np.einsum("nmk,nmk->nm", d2, r)
    C = np.einsum("nmk,nmk->nm", d1, r)
    B = np.einsum("nmk,nmk->nm", d1, d2)
    den = A * E - B * B
    s = np.where(den > 1e-12, np.clip((B * F - C * E) / np.maximum(den, 1e-12), 0, 1), 0.0)
    t = (B * s + F) / np.maximum(E, 1e-12)
    t_c = np.clip(t, 0, 1)
    s = np.where(t != t_c, np.clip((B * t_c - C) / np.maximum(A, 1e-12), 0, 1), s)
    return s, t_c


def _edge_pen(head, tail, r, caps):
    a, b, ra, rb = caps
    s, t = _segment_closest(head, tail, a, b)
    cp = head[:, None, :] + s[..., None] * (tail - head)[:, None, :]
    cc = a[None] + t[..., None] * (b - a)[None]
    rc = ra[None] + (rb - ra)[None] * t
    d = cp - cc
    dist = np.linalg.norm(d, axis=2)
    return rc + r[:, None] - dist, d, dist, s


def _push_edges(head, tail, r, caps, allow=None):
    """Edge mode: bone segments head-tail (n,3) against capsules; the tail moves so the segment's closest point
    clears the capsule (the head is held by its parent).  ``allow`` (n,m): how deep each segment may stay in each
    capsule (what the model has at rest)."""
    if caps is None or len(caps[0]) == 0:
        return tail, np.zeros(len(tail), bool)
    pen, d, dist, s = _edge_pen(head, tail, r, caps)
    if allow is not None:
        pen = pen - allow
    touch = (pen > 0) & (s > 0.05)
    if not touch.any():
        return tail, np.zeros(len(tail), bool)
    nrm = d / np.maximum(dist, 1e-9)[..., None]
    # moving the tail by x moves the closest point by s * x
    move = nrm * (np.where(touch, pen, 0.0) / np.maximum(s, 0.2))[..., None]
    return tail + move.sum(axis=1), touch.any(axis=1)


def _floor_dirs(c, head, length, lo, outward):
    """Bone directions c (n,3) from ``head`` turned up just enough that the tails head + c * length stay at
    z >= lo: a hanging skirt folds onto the floor.  A bone pointing straight down falls over along the horizontal
    part of ``outward``.  Returns the directions and which bones were turned."""
    zmin = np.clip((lo - head[:, 2]) / np.maximum(length, 1e-9), -1.0, 1.0)
    low = c[:, 2] < zmin
    if not low.any():
        return c, low
    hor, fb = c[:, :2], outward[:, :2]
    hn, fn = np.linalg.norm(hor, axis=1), np.linalg.norm(fb, axis=1)
    hor = np.where((hn > 1e-6)[:, None], hor / np.maximum(hn, 1e-12)[:, None],
                   np.where((fn > 1e-6)[:, None], fb / np.maximum(fn, 1e-12)[:, None], [[1.0, 0.0]]))
    s = np.sqrt(np.maximum(1.0 - zmin * zmin, 0.0))
    turned = np.concatenate([hor * s[:, None], zmin[:, None]], axis=1)
    return np.where(low[:, None], turned, c), low


# ---------------------------------------------------------------------------------------------- solver

def simulate(cs, base, centre, colliders, fps, params=None, log=None, rest=None):
    """Simulate the chain set over the frames.

    cs         ChainSet
    base       per frame: dict with 'rot' (n,3,3) world rotations of the bones in the animated pose (bone Y axis
               along the bone, Blender convention), 'head' (n,3), 'tail' (n,3) world positions in that pose
    centre     per frame: 4x4 world matrix of the bone the chains hang on (inertia, backstop normals)
    colliders  per frame: (a, b, ra, rb) capsule arrays in world space (a sphere has a == b), or None
    params     DEFAULTS' keys, plus 'unit': metres per world unit (default 1; 0.08 for a model in MMD units)
    rest       the model at rest: dict 'head', 'tail' (n,3) and 'caps' (the colliders), or None.  How deep the
               cloth sits in a collider at rest (a skirt's roots inside the hip capsule) stays allowed.  Optional
               'moving' (m,) bools: colliders that move under the cloth (the legs) - no allowance there unless
               params 'allow_legs'
    Returns per frame: (rot (n,3,3), head (n,3)) - the simulated world rotation and head of every bone.
    """
    P = dict(DEFAULTS)
    P.update(params or {})
    unit = float(P.get("unit", 1.0))                     # the lengths and speeds in P are metres
    for k in ("gravity", "radius", "move_limit", "particle_limit", "backstop_radius", "backstop_distance",
              "max_distance", "link_max"):
        P[k] = P[k] / unit
    n = len(cs.names)
    sub = max(1, int(P["substeps"]))
    dt = 1.0 / fps / sub
    step90 = dt * 90.0                                   # Magica's per-step numbers are per 1/90 s
    damp = 1.0 - (1.0 - P["damping"]) ** step90
    restore = 1.0 - (1.0 - P["restore_stiffness"]) ** step90
    limit = np.radians(P["limit_root"] + (P["limit_tip"] - P["limit_root"]) * cs.depth)
    radius = np.full(n, P["radius"])
    # what the model has inside a collider at rest is allowed (a skirt hugging the hips); a leg that swings into
    # the cloth is not: the animated pose of a skirt without keys is its rest shape under the hips, and lifting
    # a thigh puts it deep inside
    allow_e = allow_p = None
    if rest is not None and rest.get("caps") is not None and len(rest["caps"][0]):
        allow_e = np.maximum(_edge_pen(rest["head"], rest["tail"], radius, rest["caps"])[0], 0.0)
        allow_p = np.maximum(_point_pen(rest["tail"], radius, rest["caps"])[0], 0.0)
        # an allowance in a collider that moves under the cloth goes wherever the leg goes: a coat whose bones run
        # inside the thighs at rest would let the legs straight through it.  So none there - the bones are pushed
        # out of the legs (the coat opens up a little), as MMD pushes a skirt's bodies out of the legs' bodies.
        # Keeping it only for the chain roots is not enough: the chain hangs on from a root tail inside the thigh
        if rest.get("moving") is not None and not P["allow_legs"]:
            moving = np.asarray(rest["moving"], bool)
            allow_e[:, moving] = 0.0
            allow_p[:, moving] = 0.0
    gravity = np.array([0.0, 0.0, -P["gravity"]])
    root = cs.parent < 0
    par = np.where(root, 0, cs.parent)

    # rest offsets: a head that is not on its parent's tail rides the parent's frame
    b0 = base[0]
    off = np.zeros((n, 3))
    for i in range(n):
        p = cs.parent[i]
        if p >= 0 and not cs.connected[i]:
            off[i] = b0["rot"][p].T @ (b0["head"][i] - b0["head"][p])

    links = {k: (ia, ib, r) for k, ia, ib, r in link_pairs(cs, base[0]["tail"], P["link_max"])} if P["link"] else {}
    x = base[0]["tail"].copy()                            # particles: the bone tails
    x_old = x.copy()
    C_prev = _orthonormal(centre[0])
    C_sub_prev = C_prev
    results = []
    hits = floor_hits = 0
    rot = np.array(base[0]["rot"], float)
    head = np.array(base[0]["head"], float)
    for f in range(len(base)):
        bf, bp = base[f], base[max(f - 1, 0)]
        C_now = _orthonormal(centre[f])
        cap = colliders[f] if colliders is not None else None
        cap_prev = colliders[max(f - 1, 0)] if colliders is not None else None
        for s in range(sub):
            w = (s + 1) / sub
            # the animated pose and the colliders, in between the frames
            hb = bp["head"] + (bf["head"] - bp["head"]) * w
            tb = bp["tail"] + (bf["tail"] - bp["tail"]) * w
            Rb = bp["rot"] if w < 0.5 else bf["rot"]
            Cw = C_prev + (C_now - C_prev) * w
            caps = None
            if cap is not None and len(cap[0]):
                caps = tuple(cp + (cn - cp) * w for cp, cn in zip(cap_prev, cap))
            d0 = _unit(tb - hb)

            # 1. inertia: carry the particles with the body except the felt share (and never above the limits)
            Cw = _orthonormal(Cw)
            o = C_sub_prev[:3, 3]
            move = Cw[:3, 3] - o
            turn = Cw[:3, :3] @ C_sub_prev[:3, :3].T
            speed = np.linalg.norm(move) / dt
            felt_t = P["inertia"] * min(1.0, P["move_limit"] / speed) if speed > 1e-9 else P["inertia"]
            ang = math.acos(np.clip((np.trace(turn) - 1) / 2, -1, 1))
            felt_r = P["inertia"] * min(1.0, math.radians(P["turn_limit"]) * dt / ang) if ang > 1e-9 else P["inertia"]
            Rc = _slerp_rot(turn, 1.0 - felt_r)
            shift = move * (1.0 - felt_t)
            x = (x - o) @ Rc.T + o + shift
            x_old = (x_old - o) @ Rc.T + o + shift

            # 2. integrate (Verlet): damping, speed limit, gravity
            v = (x - x_old) / dt * (1.0 - damp)
            sp = np.linalg.norm(v, axis=1)
            v *= np.minimum(1.0, P["particle_limit"] / np.maximum(sp, 1e-9))[:, None]
            v += gravity * dt
            x_old = x.copy()
            x = x + v * dt

            # 3. constraints, root to tip
            rot = np.zeros((n, 3, 3))
            head = np.zeros((n, 3))
            for it in range(int(P["iterations"])):
                last = it == int(P["iterations"]) - 1
                for level, lv in enumerate(cs.levels):
                    p = par[lv]
                    r_ = root[lv]
                    # the parent's turn away from the animated pose carries this bone's baseline
                    D = np.where(r_[:, None, None], np.eye(3)[None], rot[p] @ np.transpose(Rb[p], (0, 2, 1)))
                    h = np.where(r_[:, None], hb[lv],
                                 np.where(cs.connected[lv][:, None], x[p],
                                          head[p] + np.einsum("nij,nj->ni", rot[p], off[lv])))
                    g = _unit(np.einsum("nij,nj->ni", D, d0[lv]))          # the baseline direction
                    c = _unit(x[lv] - h)
                    if it == 0:
                        # angle restoration (once a step) - the move does not all become speed
                        c2 = _towards(c, g, t=np.full(len(lv), restore))
                        nx = h + c2 * cs.length[lv][:, None]
                        x_old[lv] += (nx - x[lv]) * P["restore_attenuation"]
                        x[lv] = nx
                        c = c2
                    # angle limit
                    c = _towards(g, c, max_angle=limit[lv])
                    x[lv] = h + c * cs.length[lv][:, None]
                    # colliders
                    if caps is not None:
                        if P["collision_edge"]:
                            nx, hit = _push_edges(h, x[lv], radius[lv], caps,
                                                  allow=None if allow_e is None else allow_e[lv])
                        else:
                            nx, hit = _push_points(x[lv], radius[lv], caps,
                                                   allow=None if allow_p is None else allow_p[lv])
                        if hit.any():
                            # friction: kill part of the sliding speed of the touching points
                            fr = P["friction"]
                            x_old[lv[hit]] += (nx[hit] - x_old[lv[hit]]) * fr
                            hits += int(hit.sum()) if last else 0
                        x[lv] = h + _unit(nx - h) * cs.length[lv][:, None]
                    # backstop / max distance, measured from where the animation puts the tail
                    if P["backstop"] or P["max_distance_on"]:
                        tb_lv = tb[lv]
                        if P["backstop"]:
                            # outward normal: from the centre bone's axis to the animated tail
                            ax_o, ax_d = Cw[:3, 3], _unit(Cw[:3, 1][None])[0]
                            rel = tb_lv - ax_o
                            nrm = _unit(rel - np.outer(rel @ ax_d, ax_d))
                            R_, D_ = P["backstop_radius"], P["backstop_distance"]
                            cen = tb_lv - nrm * (R_ + D_)
                            dv = x[lv] - cen
                            dl = np.linalg.norm(dv, axis=1)
                            inside = dl < R_
                            if inside.any():
                                x[lv] = np.where(inside[:, None], cen + dv / np.maximum(dl, 1e-9)[:, None] * R_, x[lv])
                        if P["max_distance_on"]:
                            dv = x[lv] - tb_lv
                            dl = np.linalg.norm(dv, axis=1)
                            far = dl > P["max_distance"]
                            if far.any():
                                x[lv] = np.where(far[:, None], tb_lv + dv / dl[:, None] * P["max_distance"], x[lv])
                        x[lv] = h + _unit(x[lv] - h) * cs.length[lv][:, None]
                    # neighbouring chains: keep the tails' spacing within the stretch / squash range
                    if level in links:
                        ia, ib, r0 = links[level]
                        dv = x[ib] - x[ia]
                        dl = np.maximum(np.linalg.norm(dv, axis=1), 1e-9)
                        lo, hi = r0 * (1.0 - P["link_squash"]), r0 * (1.0 + P["link_stretch"])
                        err = np.where(dl > hi, dl - hi, np.where(dl < lo, dl - lo, 0.0))
                        if np.any(err != 0.0):
                            corr = (dv / dl[:, None]) * (0.5 * err)[:, None]
                            np.add.at(x, ia, corr)
                            np.add.at(x, ib, -corr)
                            pos = {int(b): k for k, b in enumerate(lv)}
                            heads = h[[pos[int(b)] for b in lv]]
                            x[lv] = heads + _unit(x[lv] - heads) * cs.length[lv][:, None]
                    # the floor: a hard plane, even where the animation itself goes below it (a long skirt when
                    # she crouches); the push up does not become speed, sliding on it loses the friction share
                    if P["floor"]:
                        ax_o, ax_d = Cw[:3, 3], _unit(Cw[:3, 1][None])[0]
                        rel = x[lv] - ax_o
                        c, low = _floor_dirs(_unit(x[lv] - h), h, cs.length[lv],
                                             P["floor_height"] + radius[lv], rel - np.outer(rel @ ax_d, ax_d))
                        if low.any():
                            nx = h + c * cs.length[lv][:, None]
                            k = lv[low]
                            vel = x[k] - x_old[k]                  # this step's motion
                            vel[:, 2] = np.maximum(vel[:, 2], 0.0)  # into the floor: stopped
                            vel[:, :2] *= 1.0 - P["friction"]
                            x[lv] = nx
                            x_old[k] = nx[low] - vel
                            floor_hits += int(low.sum()) if last else 0
                    c = _unit(x[lv] - h)
                    head[lv] = h
                    # the bone's frame: the animated frame carried by the parent, swung onto the simulated direction
                    rot[lv] = _swing(g, c) @ D @ Rb[lv]
            C_sub_prev = Cw
        # blend with the animation
        if P["blend"] < 1.0:
            out_rot = np.zeros_like(rot)
            out_head = np.zeros_like(head)
            for lv in cs.levels:
                p = par[lv]
                r_ = root[lv]
                D = np.where(r_[:, None, None], np.eye(3)[None], out_rot[p] @ np.transpose(bf["rot"][p], (0, 2, 1)))
                h = np.where(r_[:, None], bf["head"][lv],
                             np.where(cs.connected[lv][:, None], out_head[p] + np.einsum(
                                 "nij,nj->ni", out_rot[p], np.array([[0, 1.0, 0]]) * cs.length[p][:, None]),
                                      out_head[p] + np.einsum("nij,nj->ni", out_rot[p], off[lv])))
                g = _unit(np.einsum("nij,nj->ni", D, _unit(bf["tail"][lv] - bf["head"][lv])))
                cdir = rot[lv][:, :, 1]
                c = _towards(g, cdir, t=np.full(len(lv), P["blend"]))
                out_rot[lv] = _swing(g, c) @ D @ bf["rot"][lv]
                out_head[lv] = h
            results.append((out_rot, out_head))
        else:
            results.append((rot.copy(), head.copy()))
        C_prev = C_now
    if log:
        log("bone cloth: %d bones, %d frames, %d substeps x %d iterations, %d collider contacts, %d on the floor"
            % (n, len(base), sub, int(P["iterations"]), hits, floor_hits))
    return results


# ---------------------------------------------------------------------------------------------- Blender side

try:
    import bpy
    from mathutils import Matrix, Vector
except ImportError:                                       # the solver above also runs outside Blender (tests)
    bpy = None

TRACK = "mmd_tools_rigid_track"       # mmd_tools: the constraint that makes a bone follow its rigid body
FOLLOW = "bone_cloth_follow"          # ours: carries a rigid body with its bone
COLLIDER_TAG = "bone_cloth_collider"
BACKUP = "bone_cloth_backup"


def physics_bones(arm):
    """Pose bones a dynamic rigid body moves: mmd_tools' rigid-track constraint, or (physics not built yet) the
    bones of mode 1 / 2 rigid bodies under the same model."""
    out = {pb.name for pb in arm.pose.bones if TRACK in pb.constraints}
    root = arm.parent
    if not out and root is not None:
        for o in root.children_recursive:
            if getattr(o, "mmd_type", "") == "RIGID_BODY" and o.mmd_rigid.type in ("1", "2") \
                    and o.mmd_rigid.bone in arm.pose.bones:
                out.add(o.mmd_rigid.bone)
    return out


def keyed_bones(arm):
    action = arm.animation_data.action if arm.animation_data else None
    out = set()
    for fc in action.fcurves if action else ():
        if fc.data_path.startswith('pose.bones["') and fc.data_path.endswith('"].rotation_quaternion'):
            out.add(fc.data_path[len('pose.bones["'):-len('"].rotation_quaternion')])
    return out


def _prefix(name):
    """Group key of a cloth bone: its name without its numbers, whether they count segments, chains or both
    (Skirt_L_03 -> Skirt_L, スカート_1_0 -> スカート, hair.012 -> hair)."""
    import re
    key = re.sub(r"[._\-\s]{2,}", "_", re.sub(r"\d+", "", name)).strip("._- ")
    return key or name


def _free_tip(arm, bone, bones):
    """A bone under cloth that nothing else moves: no rigid body, no constraint, no MMD additional transform,
    and no physics further down (a converter's skirt ends in hem bones without rigid bodies)."""
    pb = arm.pose.bones[bone.name]
    mb = getattr(pb, "mmd_bone", None)
    if bone.name in bones or len(pb.constraints) or (mb is not None and (mb.has_additional_rotation
                                                                          or mb.has_additional_location)):
        return False
    return not any(c.name in bones for c in bone.children_recursive)


def chain_groups(arm, bones):
    """Cloth bones grouped for the panel, by the bone they hang on and their name family (_prefix).  The bones
    hanging below a group that nothing else moves (_free_tip: the hem bones at the tips) join it, so the
    simulated chains reach the hem.  Returns [(group name, [bone names, parents first])]."""
    bones = set(bones)
    groups = {}
    for b in arm.data.bones:                          # armature order: parents before children
        if b.name not in bones:
            continue
        top = b
        while top.parent is not None and top.parent.name in bones and _prefix(top.parent.name) == _prefix(b.name):
            top = top.parent
        anchor = top.parent.name if top.parent is not None else ""
        groups.setdefault((anchor, _prefix(b.name)), []).append(b.name)
    out = []
    for (anchor, pre), names in groups.items():
        members = set(names)
        for n in names:
            for c in arm.data.bones[n].children:
                if c.name not in members and _free_tip(arm, c, bones):
                    members.add(c.name)
                    members.update(d.name for d in c.children_recursive)
        names = [b.name for b in arm.data.bones if b.name in members]
        out.append(("%s (%s)" % (pre, anchor) if anchor else pre, names))
    return out


def metres_per_unit(arm):
    """Metres per Blender unit for this model.  The cloth's numbers are metres; mmd_tools imports a model at
    scale 0.08 (1.5-2 units tall, metres) or at scale 1 (15-25 units tall: MMD units, 8 cm each)."""
    A = arm.matrix_world
    zs = [(A @ p).z for b in arm.data.bones for p in (b.head_local, b.tail_local)]
    return 1.0 if not zs or max(zs) - min(zs) < 5.0 else 0.08


def _arm_scale(arm):
    return sum(arm.matrix_world.to_scale()) / 3.0


def chain_set(arm, names):
    """ChainSet of these bones (armature order keeps parents first)."""
    wanted = set(names)
    names = [b.name for b in arm.data.bones if b.name in wanted]
    index = {n: i for i, n in enumerate(names)}
    parent, connected, length = [], [], []
    for n in names:
        b = arm.data.bones[n]
        p = index.get(b.parent.name, -1) if b.parent is not None else -1
        parent.append(p)
        connected.append(p >= 0 and (b.head_local - b.parent.tail_local).length < 1e-4)
        length.append(b.length * _arm_scale(arm))
    depth_abs = []
    for i in range(len(names)):
        depth_abs.append(0 if parent[i] < 0 else depth_abs[parent[i]] + 1)
    deepest = list(depth_abs)                         # each bone: the deepest level below it
    for i in reversed(range(len(names))):
        if parent[i] >= 0:
            deepest[parent[i]] = max(deepest[parent[i]], deepest[i])
    chain_max = list(deepest)                         # carried down from the chain's root
    for i in range(len(names)):
        if parent[i] >= 0:
            chain_max[i] = chain_max[parent[i]]
    depth = [d / m if m else 0.0 for d, m in zip(depth_abs, chain_max)]
    return ChainSet(names, parent, connected, length, depth)


def collider_objects(arm):
    return [o for o in arm.children if o.get(COLLIDER_TAG)]


def _capsules(objs):
    """World capsules (a, b, ra, rb) of our collider objects: a mesh along its local Y from -len/2 to +len/2."""
    a, b, ra, rb = [], [], [], []
    for o in objs:
        M = o.matrix_world
        half = float(o.get("bc_len", 0.0)) / 2
        s = (M.col[0].xyz.length + M.col[2].xyz.length) / 2
        a.append(tuple(M @ Vector((0.0, -half, 0.0))))
        b.append(tuple(M @ Vector((0.0, half, 0.0))))
        ra.append(float(o.get("bc_r0", 0.05)) * s)
        rb.append(float(o.get("bc_r1", o.get("bc_r0", 0.05))) * s)
    if not a:
        return None
    return np.array(a), np.array(b), np.array(ra), np.array(rb)


def set_follow(scene, arm, bones, on=True):
    """``bones`` stop following their rigid bodies (mmd_tools' track constraint muted) and their rigid bodies
    ride the bones instead, kinematic, from where they were built at rest - what MMD's bone-follow mode does - so
    the physics still hanging on them (chains, other cloth) keeps colliding with them.  on=False undoes it.
    Returns the number of rigid bodies changed."""
    bones = set(bones)
    for name in bones:
        pb = arm.pose.bones.get(name)
        track = pb.constraints.get(TRACK) if pb is not None else None
        if track is None:
            continue
        # a muted constraint still links the bone to the rigid body's tracking empty, and the rigid body now rides
        # the bone: a dependency cycle that left bones (a08's front flaps) at stale places.  Its target is cleared
        # and kept by name instead.
        if on:
            if track.target is not None:
                pb[TRACK + "_target"] = track.target.name
            track.target = None
            track.mute = True
        else:
            name_t = pb.get(TRACK + "_target")
            if name_t and name_t in bpy.data.objects:
                track.target = bpy.data.objects[name_t]
            track.mute = False
    rest = {b.name: arm.matrix_world @ b.matrix_local for b in arm.data.bones}
    changed = 0
    for o in scene.objects:
        if getattr(o, "mmd_type", "") != "RIGID_BODY" or o.rigid_body is None or o.mmd_rigid.bone not in bones:
            continue
        c = o.constraints.get(FOLLOW)
        if on and c is None:
            o.rigid_body.kinematic = True
            c = o.constraints.new("CHILD_OF")
            c.name = FOLLOW
            c.target = arm
            c.subtarget = o.mmd_rigid.bone
            c.inverse_matrix = rest[o.mmd_rigid.bone].inverted()   # the body sits where it was built, at rest
            changed += 1
        elif not on and c is not None:
            o.constraints.remove(c)
            o.rigid_body.kinematic = o.mmd_rigid.type == "0"
            changed += 1
    return changed


def free_physics_cache(scene):
    world = scene.rigidbody_world
    if world is None:
        return
    with bpy.context.temp_override(scene=scene, point_cache=world.point_cache):
        bpy.ops.ptcache.free_bake()


def _backup_action(arm):
    """The action as it was before the first bake (a fake-user copy; restore() puts it back)."""
    action = arm.animation_data.action if arm.animation_data else None
    if action is None:
        return None
    name = arm.get(BACKUP)
    if name and name in bpy.data.actions:
        return bpy.data.actions[name]
    copy = action.copy()
    copy.name = action.name + ".骨骼布料前"
    copy.use_fake_user = True
    arm[BACKUP] = copy.name
    return copy


def _fcurves_of(action, bone):
    path = 'pose.bones["%s"].rotation_quaternion' % bone
    return [fc for fc in action.fcurves if fc.data_path == path]


def _copy_bone_keys(src, dst, bones):
    """The rotation keys of ``bones`` in action ``dst`` back to what action ``src`` has."""
    for bone in bones:
        for fc in _fcurves_of(dst, bone):
            dst.fcurves.remove(fc)
        for fc in _fcurves_of(src, bone):
            new = dst.fcurves.new(fc.data_path, index=fc.array_index, action_group=bone)
            new.keyframe_points.add(len(fc.keyframe_points))
            co = np.empty(2 * len(fc.keyframe_points))
            fc.keyframe_points.foreach_get("co", co)
            new.keyframe_points.foreach_set("co", co)
            for k in new.keyframe_points:
                k.interpolation = "LINEAR"
            new.update()


def sample_pose(scene, arm, names, centre, frames, colliders):
    """The animated pose of ``names`` (world rotation, head, tail), the centre bone's world matrix and the
    colliders, frame by frame.  The bones' rigid bodies must not move them (set_follow); the rigid body world is
    paused meanwhile, only the animation is read."""
    world = scene.rigidbody_world
    was = world.enabled if world is not None else None
    if world is not None:
        world.enabled = False
    # reading bones needs no mesh: the meshes leave the depsgraph meanwhile (a 270k-vertex model reads far faster)
    skip = [o for o in scene.objects if o.type == "MESH" and not o.hide_viewport and not o.get(COLLIDER_TAG)]
    for o in skip:
        o.hide_viewport = True
    base, cen, caps, parents = [], [], [], []
    pbs = [arm.pose.bones[n] for n in names]
    par_names = sorted({pb.parent.name for pb in pbs if pb.parent is not None and pb.parent.name not in names})
    try:
        for f in frames:
            scene.frame_set(f)
            A = arm.matrix_world
            rot = np.array([np.array((A @ pb.matrix).to_3x3().normalized()) for pb in pbs])
            head = np.array([tuple(A @ pb.head) for pb in pbs])
            tail = np.array([tuple(A @ pb.tail) for pb in pbs])
            base.append({"rot": rot, "head": head, "tail": tail})
            cen.append(np.array(A @ arm.pose.bones[centre].matrix) if centre else np.array(A))
            caps.append(_capsules(colliders))
            parents.append({n: arm.pose.bones[n].matrix.copy() for n in par_names})
    finally:
        for o in skip:
            o.hide_viewport = False
        if world is not None:
            world.enabled = was
    if all(c is None for c in caps):
        caps = None
    else:
        empty = (np.zeros((0, 3)), np.zeros((0, 3)), np.zeros(0), np.zeros(0))
        caps = [c if c is not None else empty for c in caps]
    return base, cen, caps, parents


def write_keys(arm, cs, frames, sim, parents):
    """Key the simulated bones: pose basis = (parent pose x rest offset)^-1 x simulated matrix, armature space."""
    action = arm.animation_data.action
    A_inv = arm.matrix_world.inverted()
    A_rot_inv = arm.matrix_world.to_3x3().normalized().inverted()
    index = {n: i for i, n in enumerate(cs.names)}
    rest_rel = {}
    for n in cs.names:
        b = arm.data.bones[n]
        rest_rel[n] = (b.parent.matrix_local.inverted() @ b.matrix_local) if b.parent else b.matrix_local
    values = {n: [] for n in cs.names}
    for k, f in enumerate(frames):
        rot, head = sim[k]
        arm_mats = {}
        for i, n in enumerate(cs.names):
            M = (A_rot_inv @ Matrix(rot[i].tolist())).to_4x4()
            M.translation = A_inv @ Vector(head[i])
            arm_mats[n] = M
            b = arm.data.bones[n]
            if b.parent is None:
                P = Matrix.Identity(4)
            elif b.parent.name in index:
                P = arm_mats[b.parent.name]
            else:
                P = parents[k][b.parent.name]
            q = ((P @ rest_rel[n]).inverted() @ M).to_quaternion()
            if values[n] and q.dot(values[n][-1][1]) < 0:
                q.negate()
            values[n].append((f, q))
    for n in cs.names:
        arm.pose.bones[n].rotation_mode = "QUATERNION"
        for fc in _fcurves_of(action, n):
            action.fcurves.remove(fc)
        path = 'pose.bones["%s"].rotation_quaternion' % n
        for j in range(4):
            fc = action.fcurves.new(path, index=j, action_group=n)
            fc.keyframe_points.add(len(values[n]))
            co = np.array([(f, q[j]) for f, q in values[n]], float).reshape(-1)
            fc.keyframe_points.foreach_set("co", co)
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
            fc.update()


def rest_pose(scene, arm, names, colliders):
    """World heads and tails of ``names`` and the colliders' capsules with the armature in its rest pose, for
    simulate()'s ``rest``; None without colliders."""
    if not colliders:
        return None
    was = arm.data.pose_position
    arm.data.pose_position = "REST"
    scene.frame_set(scene.frame_current)
    try:
        A = arm.matrix_world
        out = {"head": np.array([tuple(A @ arm.pose.bones[n].head) for n in names]),
               "tail": np.array([tuple(A @ arm.pose.bones[n].tail) for n in names]),
               "caps": _capsules(colliders)}
    finally:
        arm.data.pose_position = was
        scene.frame_set(scene.frame_current)
    return out


def bake(scene, arm, sim_groups, follow_bones, params, frames=None, log=print):
    """Simulate every group of ``sim_groups`` ([(name, bones)]) and key the result, let ``follow_bones`` play
    their keys, leave the rest to the MMD physics.  The action before the first bake is kept (restore())."""
    if frames is None:
        frames = list(range(scene.frame_start, scene.frame_end + 1))
    sim_bones = [b for _g, names in sim_groups for b in names]
    backup = _backup_action(arm)
    if backup is not None and sim_bones:
        _copy_bone_keys(backup, arm.animation_data.action, sim_bones)    # simulate from the original keys
    set_follow(scene, arm, set(sim_bones) | set(follow_bones), True)
    colliders = collider_objects(arm)
    fps = scene.render.fps / scene.render.fps_base
    current = scene.frame_current
    params = dict(params)
    params.setdefault("unit", metres_per_unit(arm))   # a model in MMD units: 8 cm a unit
    log("bone cloth: %.2f m per unit, %d frames" % (params["unit"], len(frames)))
    for name, names in sim_groups:
        cs = chain_set(arm, names)
        roots = [n for n, p in zip(cs.names, cs.parent) if p < 0]
        anchors = {arm.data.bones[n].parent.name for n in roots if arm.data.bones[n].parent is not None}
        centre = sorted(anchors)[0] if anchors else None
        rest = rest_pose(scene, arm, cs.names, colliders)
        base, cen, caps, parents = sample_pose(scene, arm, cs.names, centre, frames, colliders)
        sim = simulate(cs, base, cen, caps, fps, params, log=lambda s, g=name: log("%s: %s" % (g, s)), rest=rest)
        write_keys(arm, cs, frames, sim, parents)
    scene.frame_set(current)
    free_physics_cache(scene)
    log("bone cloth: %d groups simulated (%d bones), %d bones follow their keys, %d colliders"
        % (len(sim_groups), len(sim_bones), len(follow_bones), len(colliders)))


def restore(scene, arm):
    """Undo bake(): the original action back, every bone on its rigid body again."""
    name = arm.get(BACKUP)
    if name and name in bpy.data.actions:
        arm.animation_data.action = bpy.data.actions[name]
    set_follow(scene, arm, [pb.name for pb in arm.pose.bones], False)
    free_physics_cache(scene)


# ---------------------------------------------------------------------------------------------- colliders from the body

LEGS = (("左足", "左ひざ"), ("右足", "右ひざ"))


def bone_by_mmd(arm, name_j):
    for pb in arm.pose.bones:
        mb = getattr(pb, "mmd_bone", None)
        if pb.name == name_j or (mb is not None and mb.name_j == name_j):
            return pb.name
    return None


def _deform_twin(arm, name):
    """足 -> 足D when there is one: Convert_to_MMD5 rigs weight the leg mesh to the D bones."""
    if name is None:
        return None
    mb = getattr(arm.pose.bones[name], "mmd_bone", None)
    return bone_by_mmd(arm, (mb.name_j if mb is not None and mb.name_j else name) + "D") or name


def _weighted_points(arm, bone, threshold=0.5):
    """Rest-pose world positions of the vertices weighted to ``bone`` (any mesh under the model)."""
    pts = []
    meshes = [o for o in (arm.parent or arm).children_recursive if o.type == "MESH"]
    for o in meshes:
        if bone not in o.vertex_groups:
            continue
        gi = o.vertex_groups[bone].index
        M = o.matrix_world
        n = len(o.data.vertices)
        co = np.empty(n * 3)
        o.data.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        keep = []
        for v in o.data.vertices:
            for g in v.groups:
                if g.group == gi and g.weight >= threshold:
                    keep.append(v.index)
                    break
        if keep:
            m = np.array(M)
            pts.append(co[keep] @ m[:3, :3].T + m[:3, 3])
    return np.concatenate(pts) if pts else np.zeros((0, 3))


def _segment_bones(arm, a, b, tol=0.03):
    """Bones whose rest head lies on segment a-b (world, within ``tol`` metres, not past its far end)."""
    A = arm.matrix_world
    ab = b - a
    L2 = max(float(ab @ ab), 1e-12)
    out = set()
    for bb in arm.data.bones:
        h = np.array(tuple(A @ bb.head_local))
        t = float((h - a) @ ab) / L2
        if -0.05 <= t <= 0.95 and np.linalg.norm(h - (a + t * ab)) <= tol:
            out.add(bb.name)
    return out


def _radius_along(points, a, b, pct=70.0, lo=0.02, hi=0.25):
    """The body's radius round segment a-b at each half (a percentile of the nearby points' distances)."""
    if len(points) < 8:
        return None
    ab = b - a
    L2 = max(float(ab @ ab), 1e-12)
    t = np.clip((points - a) @ ab / L2, 0, 1)
    d = np.linalg.norm(points - (a + t[:, None] * ab), axis=1)
    out = []
    for sel in (t < 0.5, t >= 0.5):
        out.append(float(np.clip(np.percentile(d[sel], pct), lo, hi)) if sel.sum() >= 4 else None)
    if out[0] is None and out[1] is None:
        return None
    return out[0] or out[1], out[1] or out[0]


def _capsule_mesh(name, r0, r1, length, segs=16, rings=4):
    """A wire capsule along Y from -length/2 (radius r0) to +length/2 (radius r1)."""
    verts, edges = [], []
    half = length / 2
    for y0, r, sign in ((-half, r0, -1), (half, r1, 1)):
        for k in range(rings + 1):
            phi = math.pi / 2 * k / rings
            y = y0 + sign * r * math.sin(phi)
            rr = r * math.cos(phi)
            start = len(verts)
            for j in range(segs):
                th = 2 * math.pi * j / segs
                verts.append((rr * math.cos(th), y, rr * math.sin(th)))
                edges.append((start + j, start + (j + 1) % segs))
    for j in range(0, segs, max(1, segs // 4)):          # four lines along the side
        edges.append((j, (rings + 1) * segs + j))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    return me


def add_collider(arm, bone, a, b, r0, r1, name=None):
    """A capsule collider from world point ``a`` (radius r0) to ``b`` (radius r1), in the rest pose, riding
    ``bone``.  Metres."""
    a, b = Vector(tuple(a)), Vector(tuple(b))
    length = (b - a).length
    name = name or "骨骼布料碰撞体_%s" % bone
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old)
    ob = bpy.data.objects.new(name, _capsule_mesh(name, r0, r1, length))
    ob[COLLIDER_TAG] = True
    ob["bc_r0"], ob["bc_r1"], ob["bc_len"] = r0, r1, length
    ob.display_type = "WIRE"
    ob.hide_render = True
    ob.visible_shadow = False
    (arm.users_collection[0] if arm.users_collection else bpy.context.scene.collection).objects.link(ob)
    ob.parent = arm
    ob.parent_type = "BONE"
    ob.parent_bone = bone
    # bone parenting is measured from the bone's tail in the rest pose: put the capsule there through
    # matrix_parent_inverse, so its own transform stays identity (move / scale it freely afterwards)
    bb = arm.data.bones[bone]
    tail_rest = arm.matrix_world @ (Matrix.Translation(bb.tail_local) @ bb.matrix_local.to_3x3().to_4x4())
    place = Matrix.Translation((a + b) / 2) @ Vector((0.0, 1.0, 0.0)).rotation_difference(
        (b - a).normalized()).to_matrix().to_4x4()
    ob.matrix_parent_inverse = tail_rest.inverted() @ place
    return ob


def add_body_colliders(arm, log=print):
    """Capsules on the thighs (hip joint to knee) and calves (knee to ankle) and across the hips, as thick as the
    mesh round them: what a skirt must not go through.  They ride the bones the mesh is weighted to (足D / ひざD
    on Convert_to_MMD5 rigs, which are short bones, so the joints give the capsules' ends)."""
    made, hip_joints = [], []
    A = arm.matrix_world
    u = metres_per_unit(arm)                          # the sizes below are metres
    for (thigh_j, knee_j), ankle_j in zip(LEGS, ("左足首", "右足首")):
        joints = [bone_by_mmd(arm, j) for j in (thigh_j, knee_j, ankle_j)]
        if None in joints:
            continue
        heads = [np.array(tuple(A @ arm.data.bones[j].head_local)) for j in joints]
        for k, j in enumerate((thigh_j, knee_j)):
            main = joints[k]
            bone = _deform_twin(arm, main)
            a, b = heads[k], heads[k + 1]
            # the mesh round this segment may be weighted to helpers too (ThighTwist, CalfTwist): every bone
            # whose head lies on the segment counts
            pts = np.concatenate([_weighted_points(arm, n)
                                  for n in _segment_bones(arm, a, b, tol=0.03 / u) | {bone, main}])
            r = _radius_along(pts, a, b, lo=0.02 / u, hi=0.25 / u) or (0.07 / u, 0.05 / u)
            made.append(add_collider(arm, bone, a, b, r[0], r[1]))
        hip_joints.append(heads[0])
    hips = bone_by_mmd(arm, "下半身")
    if hips is not None and len(hip_joints) == 2:
        a, b = hip_joints
        r = _radius_along(_weighted_points(arm, hips), a, b, pct=60.0, lo=0.02 / u, hi=0.25 / u) \
            or (0.09 / u, 0.09 / u)
        made.append(add_collider(arm, hips, a, b, max(r), max(r), name="骨骼布料碰撞体_胯"))
    log("bone cloth: %d colliders (m): %s" % (len(made), ", ".join(
        "%s r %.3f/%.3f len %.3f" % (o.name, o["bc_r0"] * u, o["bc_r1"] * u, o["bc_len"] * u) for o in made)))
    return made
