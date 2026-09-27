"""物理分组:从 mmd_tools 模型里找出某一类物理(胸部;后续衣服、头发)的刚体和关节,按左右分好。

识别只看名字和结构,导入的 PMX 和 Convert_to_MMD5 转出来的 blend 都适用:
- 胸部:绑在胸骨上(骨名像 左胸/右胸/breast/boob/bust/oppai/乳…)的刚体;或刚体名像胸的**物理**刚体
  (跟骨的静态刚体多半是躯干碰撞体,光看刚体名不算);关节 = 一端连着这些刚体的关节。
- 本插件写过的刚体会打标记(TAG),之后即使被改成「跟骨」也还认得(「关闭物理」预设能再开回来)。
"""

import re

BREAST_RE = re.compile(r"boob|breast|bust|oppai|おっぱい|乳|mune|胸", re.I)
# 名字带「胸」但其实是躯干的
NOT_BREAST_RE = re.compile(r"上半身|胸骨|chest|spine|upper_?body", re.I)
_LEFT_RE = re.compile(r"^左|左$|(^|[_.\s])(l|left)([_.\s\d]|$)", re.I)
_RIGHT_RE = re.compile(r"^右|右$|(^|[_.\s])(r|right)([_.\s\d]|$)", re.I)

GROUPS = (
    ("breast", "胸部"),
)
TAG = "mmd_physics_group"               # 刚体/关节上的标记:所属分组


class Group:
    """一类物理在某个模型上的刚体/关节,按 L/R 分(MMD 左 = +X)。"""

    def __init__(self, key, label):
        self.key, self.label = key, label
        self.rigids = {"L": [], "R": []}
        self.joints = {"L": [], "R": []}

    def empty(self):
        return not (self.rigids["L"] or self.rigids["R"])

    def objects(self):
        return [o for s in "LR" for o in self.rigids[s] + self.joints[s]]

    def describe(self):
        parts = []
        for s, label in (("L", "左"), ("R", "右")):
            if self.rigids[s]:
                names = "、".join(rigid_name(o) for o in self.rigids[s])
                parts.append(f"{label}: {names}(刚体 {len(self.rigids[s])} / 关节 {len(self.joints[s])})")
        return ";".join(parts) or "没找到"


def model_of(obj):
    """(root, Model);obj 不在 mmd 模型里时 (None, None)。"""
    if obj is None:
        return None, None
    from mmd_tools.core.model import Model
    root = Model.findRoot(obj)
    return (root, Model(root)) if root else (None, None)


def rigid_name(o):
    return o.mmd_rigid.name_j or o.name


def side_of(obj, name, arm):
    if _LEFT_RE.search(name):
        return "L"
    if _RIGHT_RE.search(name):
        return "R"
    p = obj.matrix_world.translation
    if arm is not None:
        p = arm.matrix_world.inverted() @ p
    return "L" if p.x >= 0.0 else "R"


def _breast_name(n):
    return bool(n) and BREAST_RE.search(n) is not None and NOT_BREAST_RE.search(n) is None


def _is_breast(o):
    if o.get(TAG) == "breast" or _breast_name(o.mmd_rigid.bone):
        return True
    return int(o.mmd_rigid.type) != 0 and _breast_name(rigid_name(o))


def find_breast(model):
    g = Group("breast", "胸部")
    arm = model.armature()
    side = {}
    for o in model.rigidBodies():
        if not _is_breast(o):
            continue
        s = side_of(o, o.mmd_rigid.bone or rigid_name(o), arm)
        g.rigids[s].append(o)
        side[o] = s
    for j in model.joints():
        rbc = j.rigid_body_constraint
        if rbc is None:
            continue
        a, b = rbc.object1, rbc.object2
        t = b if b in side else a if a in side else None
        if t is not None:
            g.joints[side[t]].append(j)
    return g


_FINDERS = {"breast": find_breast}


def find(key, model):
    return _FINDERS[key](model)
