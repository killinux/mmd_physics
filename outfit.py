"""按胸前穿的东西推荐胸部的效果(效果选择用):看每侧乳尖附近最外面那层网格跟胸骨走得比皮肤多还是少。

胸部物理只带得动权重在胸骨上的顶点。衣服跟胸骨走得比底下的皮肤少,胸晃大了皮肤就从衣服里穿出来,往前颠
(RGBA 式的平移)最容易穿;胸骨上一个顶点都没有(钢甲这类把胸整个包死的),胸部物理怎么设都看不见。
推荐照社区的分法(紳士wiki:RGBA 式、AH 式「薄着〜生乳向き」,N 式、プルート式「厚着・被服向き」)。每侧:

1. 乳尖、胸根同 kits(同侧胸链带的顶点里最靠前的一撮,左右镜像平均;链根骨的骨头),胸深 = 胸根到乳尖。
2. 乳尖附近的顶点:沿 胸根 → 乳尖 投影在 0.5–2 倍胸深之间、离轴不超过 0.35 倍胸深,按「网格 + 材质」分层。
3. 每层顶点上的权重分到四类骨:胸骨、会摆的骨(有摆动刚体的骨和它下面的:头发、饰物链、裙子)、头下的骨、
   身体(其余)。会摆的 + 头下的超过一半的层不算(卫衣帽绳的毛球、垂在胸前的头发),少于 5 个顶点的层不算。
4. 判断(w = 这层跟胸骨的平均权重;皮肤 = 乳尖处最里面那层 = 沿轴伸得最不远的,皮肤正好到乳尖,衣服在外面):
   - 胸骨上带的顶点不到 8 个 → none「胸骨不带网格」:胸部物理看不见,不用设。
   - 有一层 w < 0.2 w_皮肤、主要跟身体走、又伸到乳尖前面(> 1.05 倍胸深)→ stiff「挡着一层不跟胸的」
     (甲片、硬外套):只能小幅晃。
   - 最外面那层 w < 0.8 w_皮肤 → partial「衣服只跟一部分」(外套、卫衣):收着晃。
   - 0.8–0.95 → loose「衣服大致跟着」(薄衣):转着晃可以,往前颠(RGBA)会穿。
   - 否则 free「裸着或贴身」(泳装、紧身衣、跟皮肤一样刷的衣服):怎么晃都行。
本机样本(10-06,tests/check_outfit.py):ROE 裸体 / 空姐、乳奶模板模型、Vindictus PCF_003 连衣裙(103 %)、PCF_009
西装(敞着,衬衫 97 %,套 RGBA 渲出来不穿)= free;PCF_005 连衣裙(93 %,套 RGBA 渲出来皮肤顶出布面)= loose;
PCF_008 卫衣(79 %)= partial;PCF_067 钢甲 = none。卫衣帽绳上的毛球挂在会摆的骨上,不算。
"""

import math

from mathutils import Vector

from . import chains, kits

LABELS = {"none": "胸骨不带网格", "stiff": "挡着一层不跟胸的", "partial": "衣服只跟一部分", "loose": "衣服大致跟着",
          "free": "裸着或贴身"}
ADVICE = {"none": "胸部物理看不见,不用设", "stiff": "只能小幅晃,不然胸会穿出去", "partial": "收着晃,晃大了皮肤会从衣服里穿出来",
          "loose": "转着晃可以,往前颠(RGBA 式)会穿", "free": "怎么晃都行"}
SHORT = {"none": "胸部物理看不见", "stiff": "只能小幅晃", "partial": "收着晃", "loose": "往前颠(RGBA)会穿",
         "free": "怎么晃都行"}                     # 侧栏窄,面板上只放短的
# 推荐的预设(按当前方式);none 不改
RECOMMEND = {
    "free": {"RIGID": "rgba", "SPRING": "k1"},
    "loose": {"RIGID": "tda", "SPRING": "k1"},
    "partial": {"RIGID": "vdf_e", "SPRING": "firmer", "CLOTH": "roe_rest"},
    "stiff": {"RIGID": "firm", "SPRING": "firmer", "CLOTH": "roe_rest"},
}
ORDER = ("none", "free", "loose", "partial", "stiff")          # 两侧不一样时取更严的


def _bone_classes(arm, bust):
    """骨名 → 'bust' / 'swing' / 'head' / 'body'。"""
    dyn = chains.dynamic_bones(arm) - set(bust)
    out = {}
    for b in arm.data.bones:                          # 父在前
        if b.name in bust:
            out[b.name] = "bust"
            continue
        p = b.parent
        if b.name in dyn or (p is not None and out.get(p.name) == "swing"):
            out[b.name] = "swing"
        elif any(n in chains.HEAD_NAMES for n in chains.names_of(arm.pose.bones[b.name])) or \
                (p is not None and out.get(p.name) == "head"):
            out[b.name] = "head"
        else:
            out[b.name] = "body"
    return out


def _layers(arm, pivot, apex, classes):
    """乳尖附近的顶点按 (网格, 材质) 分层:{层名: dict(n, bust, swing, head, body, reach)}。"""
    axis = apex - pivot
    depth = axis.length
    u = axis / depth
    root = chains.mmd_root(arm)
    out = {}
    for o in (root.children_recursive if root is not None else ()):
        if o.type != "MESH" or not o.vertex_groups or getattr(o, "mmd_type", "NONE") != "NONE":
            continue
        cls = {g.index: classes.get(g.name) for g in o.vertex_groups}
        mat_of = {}
        for poly in o.data.polygons:
            for vi in poly.vertices:
                mat_of.setdefault(vi, poly.material_index)
        mw = o.matrix_world
        for v in o.data.vertices:
            rel = mw @ v.co - pivot
            along = rel.dot(u)
            if along < 0.5 * depth or along > 2.0 * depth:
                continue
            if math.sqrt(max(0.0, rel.length_squared - along * along)) > 0.35 * depth:
                continue
            share = {"bust": 0.0, "swing": 0.0, "head": 0.0, "body": 0.0}
            tot = 0.0
            for g in v.groups:
                c = cls.get(g.group)
                if c is not None and g.weight > 0.0:
                    share[c] += g.weight
                    tot += g.weight
            if tot <= 0.0:
                continue
            mi = mat_of.get(v.index, 0)
            mat = o.material_slots[mi].material if mi < len(o.material_slots) else None
            key = "%s / %s" % (o.name, mat.name if mat else "-")
            L = out.setdefault(key, {"n": 0, "bust": 0.0, "swing": 0.0, "head": 0.0, "body": 0.0, "reach": 0.0,
                                     "along": 0.0})
            L["n"] += 1
            for k in share:
                L[k] += share[k] / tot
            L["reach"] = max(L["reach"], along / depth)
            L["along"] += along / depth
    for L in out.values():
        for k in ("bust", "swing", "head", "body", "along"):
            L[k] /= L["n"]
    return out


def judge(layers):
    """(种类, 说明, 短说明)。百分数 = 这层跟胸骨的权重 / 皮肤的。"""
    kept = {k: L for k, L in layers.items() if L["swing"] + L["head"] <= 0.5 and L["n"] >= 5}
    if not kept:
        return "none", "乳尖附近没有跟身体走的网格", "没网格"
    skin_key, skin = min(kept.items(), key=lambda kv: (round(kv[1]["reach"], 2), -kv[1]["bust"]))
    ws = max(skin["bust"], 1e-6)
    stiff = [(k, L) for k, L in kept.items() if L["bust"] < 0.2 * ws and L["body"] > 0.5 and L["reach"] > 1.05]
    if stiff:
        k, L = max(stiff, key=lambda kv: kv[1]["reach"])
        return "stiff", "「%s」不跟胸骨(%.0f%%),挡在乳尖前 %.0f%%" % (k, 100 * L["bust"] / ws, 100 * (L["reach"] - 1)),             "有一层挡着"
    k, L = max(kept.items(), key=lambda kv: kv[1]["reach"])
    ratio = L["bust"] / ws
    if k == skin_key:
        return "free", "最外层就是「%s」" % k, "就是皮肤"
    what, short = "最外层「%s」跟胸骨是皮肤的 %.0f%%" % (k, 100 * ratio), "%.0f%%" % (100 * ratio)
    if ratio < 0.8:
        return "partial", what, short
    if ratio < 0.95:
        return "loose", what, short
    return "free", what, short


def analyse(arm, bust=None):
    """每侧 {侧: (种类, 说明, 短说明)},和两侧合起来的种类(取更严的)。bust:chains.bust_chains 的结果。"""
    bust = chains.bust_chains(arm) if bust is None else bust
    by_side = {}
    for c in bust:
        by_side.setdefault(c.side, []).append(c)
    side_bones = {s: {n for c in cs for n in c.bones} for s, cs in by_side.items()}
    apexes = kits.side_apexes(arm, side_bones)
    out = {}
    for side, cs in by_side.items():
        if side not in apexes:
            out[side] = ("none", "胸骨上没有带网格", "没网格")
            continue
        root = min(cs, key=lambda c: abs(arm.data.bones[c.root].head_local.x)).root
        pivot = arm.matrix_world @ arm.data.bones[root].head_local
        classes = _bone_classes(arm, side_bones[side])
        out[side] = judge(_layers(arm, pivot, apexes[side], classes))
    if not out:
        return {}, "none"
    worst = max((v[0] for v in out.values()), key=ORDER.index)
    return out, worst


def summary(result, worst):
    """完整的一行(报告、日志用):种类(建议) | 每侧的说明。"""
    if not result:
        return "没找到胸链"
    sides = ";".join("%s:%s" % ({"L": "左", "R": "右"}.get(s, s), v[1]) for s, v in sorted(result.items()))
    return "%s(%s) | %s" % (LABELS[worst], ADVICE[worst], sides)


def panel(result, worst):
    """面板上的三行(用 | 分开):种类、短建议、每侧的百分数。"""
    if not result:
        return "没找到胸链"
    sides = " · ".join("%s %s" % ({"L": "左", "R": "右"}.get(s, s), v[2]) for s, v in sorted(result.items()))
    return "%s | %s | %s" % (LABELS[worst], SHORT[worst], sides)
