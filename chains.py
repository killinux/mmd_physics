"""效果选择用的物理分组:从 mmd_tools 模型里找出 胸部 / 头发 / 裙子 / 其他衣物 的骨链。

- **胸部**:摆动刚体(物理演算)挂在名字像胸的骨上。
  - 摆动骨的父骨也像胸(ROE 的 左胸、Vindictus 的 breast_physics_01、Biped 的 bust_1 这类锚点骨)时,
    从父骨起链:父骨的位置跟身体走,子孙骨模拟。
  - 否则(乳奶模板:刚体直接挂在躯干下的单根骨上),从摆动骨自己起链;它没有子骨时末端补一个点,
    这根骨才能转。
  - 链 = 起点骨 + 名字也像胸或没有摆动刚体的子孙骨;挂在胸上、名字不像胸的摆动刚体(吊坠、飘带)
    不进胸链,归到其他衣物,继续按刚体算,挂在跟着胸走的骨上。
  - 模型没有胸部刚体时按名字找:名字像胸、父骨不像胸、带权重的骨。
- **头发 / 裙子 / 其他衣物**:其余摆动刚体的骨,按挂点骨和去掉数字的名字分组(和骨骼布料插件一样),
  链末端没有刚体的梢骨也算进去。挂在头下或名字像头发的 = 头发;名字像裙子的 = 裙子;其余 = 其他衣物
  (饰物、披风、尾巴、屁股肉……)。
- **原来不动的链**(still_groups):没有摆动刚体、在 MMD 里不会晃的骨链 —— 转换来的模型(XPS、别的游戏)整个没有
  刚体(nobody),或者作者只给了跟骨刚体(static)。没有刚体的要名字像头发 / 裙子 / 衣物才算;脸部的骨(舌、颊、眉、
  眼、嘴……)和手腕、脚踝以下的骨(手指、脚趾)不算;至少两节。

刚体的「物理类型」按**原来的**算:效果烘焙会把一些刚体临时改成「跟骨」,改之前的类型记在刚体上(ORIG_TYPE)。
本插件新建的刚体(套件、给不动的链建的,MADE_TAGS)不算模型的刚体。
"""

import re

BREAST_RE = re.compile(r"boob|breast|bust|oppai|おっぱい|乳|mune|胸", re.I)
NOT_BREAST_RE = re.compile(r"上半身|胸骨|chest|spine|upper_?body", re.I)
HELPER_RE = re.compile(r"^point_|^ac[ _]|_ac(_|\d|$)", re.I)     # ROE 的辅助骨、饰品骨,名字带胸但不是胸
HAIR_RE = re.compile(r"hair|髪|发|髮|ahoge|アホ毛|もみあげ|ponytail|ポニ|テール|ツイン|twin|bang|前髪|横髪|後髪|サイド", re.I)
SKIRT_RE = re.compile(r"skirt|スカート|すかーと|裙|hem", re.I)
HEAD_NAMES = ("頭", "head", "Head")
# 没有刚体的链要名字像这些才算(头发、裙子另有 HAIR_RE / SKIRT_RE)
CLOTH_NAME_RE = re.compile(r"cloth|cape|cloak|mant|マント|coat|コート|ribbon|リボン|sleeve|袖|tail|しっぽ|尻尾|"
                           r"necktie|ネクタイ|feather|羽|tassel|房|scarf|マフラー|apron|エプロン|frill|フリル|chain|鎖|"
                           r"earring|ピアス|イヤリング|veil|ベール|sash|lace|strap|紐|flap|裾|襟|collar|hood|フード|"
                           r"loincloth|前垂|後垂|飾", re.I)
FACE_RE = re.compile(r"facial|cheek|tongue|jaw|(?<![a-z])eye|brow|(?<![a-z])lips?(?![a-z])|mouth|teeth|tooth|nose|"
                     r"頬|舌|顎|あご|目|瞳|眉|瞼|唇|歯|鼻", re.I)
LIMB_END_RE = re.compile(r"手首|足首|つま先|足先|指|wrist|ankle|hand|foot|toe|finger|thumb", re.I)
# MMD 的标准骨(身体本身,不是挂在身上的东西)
STANDARD = frozenset("""全ての親 センター グルーブ 腰 上半身 上半身1 上半身2 上半身3 首 首1 頭 両目 左目 右目 下半身
操作中心 左肩P 右肩P 左肩 右肩 左肩C 右肩C 左腕 右腕 左腕捩 右腕捩 左ひじ 右ひじ 左手捩 右手捩 左手首 右手首 左ダミー
右ダミー 左足 右足 左ひざ 右ひざ 左足首 右足首 左つま先 右つま先 左足IK 右足IK 左つま先IK 右つま先IK 左足D 右足D 左ひざD
右ひざD 左足首D 右足首D 左足先EX 右足先EX 腰キャンセル左 腰キャンセル右 足IK親 左足IK親 右足IK親 腕IK""".split())

ORIG_TYPE = "mmd_physics_orig_type"     # 刚体上:效果烘焙改类型之前的物理类型
MADE_TAGS = ("mmd_physics_kit", "mmd_physics_chainbody")   # 本插件新建的刚体 / 关节上的标记(kits.TAG、chainbodies.TAG)

CATEGORIES = (
    ("BUST", "胸部"),
    ("HAIR", "头发"),
    ("SKIRT", "裙子"),
    ("CLOTH", "其他衣物"),
)
CATEGORY_LABEL = dict(CATEGORIES)


def names_of(pb):
    """一根骨的几个名字:Blender 名、PMX 日文名、英文名。"""
    out = [pb.name]
    mb = getattr(pb, "mmd_bone", None)
    if mb is not None:
        out += [mb.name_j, mb.name_e]
    return [n for n in out if n]


def looks_breast(pb):
    ns = names_of(pb)
    return any(BREAST_RE.search(n) for n in ns) and not any(NOT_BREAST_RE.search(n) for n in ns) \
        and not any(HELPER_RE.search(n) for n in ns)


def body_type(o):
    """刚体原来的物理类型('0' 跟骨 / '1' 物理 / '2' 物理+骨位置)。"""
    t = o.get(ORIG_TYPE)
    return str(t) if t is not None else o.mmd_rigid.type


def mmd_root(obj):
    while obj is not None and getattr(obj, "mmd_type", "") != "ROOT":
        obj = obj.parent
    return obj


def made_by_us(o):
    """本插件新建的刚体 / 关节(套件、给不动的链建的):每次烘焙前删掉重建,不算模型的。"""
    return any(o.get(t) for t in MADE_TAGS)


def model_bodies(arm):
    """这个模型(骨架所在的 MMD 根下)的刚体对象。场景里有同骨架的别的模型时不会混进来;本插件新建的不算。"""
    import bpy
    root = mmd_root(arm)
    out = []
    for o in (root.children_recursive if root is not None else bpy.data.objects):
        if getattr(o, "mmd_type", "") == "RIGID_BODY" and o.mmd_rigid.bone in arm.pose.bones and not made_by_us(o):
            out.append(o)
    return out


def bodies_by_bone(arm):
    out = {}
    for o in model_bodies(arm):
        out.setdefault(o.mmd_rigid.bone, []).append(o)
    return out


def dynamic_bones(arm, bodies=None):
    """原来有摆动刚体(物理 / 物理+骨位置)的骨。"""
    bodies = bodies_by_bone(arm) if bodies is None else bodies
    return {b for b, objs in bodies.items() if any(body_type(o) in ("1", "2") for o in objs)}


def side_of(arm, bone_name):
    """'L' / 'R':先看名字,再看位置(MMD 左 = 模型的左 = Blender +X)。"""
    pb = arm.pose.bones[bone_name]
    for n in names_of(pb):
        if re.search(r"^左|左$|(^|[_.\s])(l|left)([_.\s\d]|$)", n, re.I):
            return "L"
        if re.search(r"^右|右$|(^|[_.\s])(r|right)([_.\s\d]|$)", n, re.I):
            return "R"
    return "L" if pb.bone.head_local.x >= 0.0 else "R"


# -- 胸部 -------------------------------------------------------------------------------------------
class BustChain:
    """一侧的一条胸链。root:起点骨(位置跟身体走);bones:先序,父在前;tip:末端要不要补点。"""

    def __init__(self, side, root, bones, tip):
        self.side, self.root, self.bones, self.tip = side, root, bones, tip

    def __repr__(self):
        return "<BustChain %s %s: %d bones%s>" % (self.side, self.root, len(self.bones), ", tip" if self.tip else "")


def _chain_from(arm, root, dyn):
    """root + 子孙:名字像胸的、或没有摆动刚体的(梢骨);挂在胸上、名字不像胸的摆动骨及其子孙不算。"""
    out = []

    def walk(bone):
        out.append(bone.name)
        for c in bone.children:
            pb = arm.pose.bones[c.name]
            if c.name in dyn and not looks_breast(pb):
                continue
            walk(c)

    walk(arm.data.bones[root])
    return out


def _weighted(arm):
    """有网格权重的顶点组名(骨名)。"""
    root = mmd_root(arm)
    out = set()
    for o in (root.children_recursive if root is not None else ()):
        if o.type != "MESH" or not o.vertex_groups:
            continue
        index = {g.index: g.name for g in o.vertex_groups}
        seen = set()
        for v in o.data.vertices:
            for g in v.groups:
                if g.weight > 0.01 and g.group not in seen:
                    seen.add(g.group)
        out.update(index[i] for i in seen)
    return out


def bust_chains(arm, bodies=None):
    """[BustChain],左右都在里面。见模块说明。"""
    bodies = bodies_by_bone(arm) if bodies is None else bodies
    dyn = dynamic_bones(arm, bodies)
    bones = arm.data.bones
    swing = [b for b in dyn if looks_breast(arm.pose.bones[b])]
    roots = []
    for b in sorted(swing, key=lambda n: bones.find(n)):
        parent = bones[b].parent
        if parent is not None and parent.name in swing:
            continue                                    # 不是最上面那根摆动骨
        if parent is not None and looks_breast(arm.pose.bones[parent.name]):
            root = parent.name                          # 锚点骨(左胸 / breast_physics_01 / bust_1)
        else:
            root = b                                    # 乳奶模板:摆动骨直接挂在躯干下
        if root not in roots:
            roots.append(root)
    if not roots:                                       # 没有胸部刚体:按名字 + 权重
        weighted = None
        for b in bones:
            pb = arm.pose.bones[b.name]
            if not looks_breast(pb) or (b.parent is not None and looks_breast(arm.pose.bones[b.parent.name])):
                continue
            weighted = _weighted(arm) if weighted is None else weighted
            if b.name in weighted or any(c.name in weighted for c in b.children_recursive):
                roots.append(b.name)
    out = []
    for root in roots:
        names = _chain_from(arm, root, dyn)
        out.append(BustChain(side_of(arm, root), root, names, tip=len(names) == 1))
    return out


# -- 头发 / 裙子 / 其他衣物 ----------------------------------------------------------------------------
def _prefix(name):
    """组名:去掉数字的骨名(Skirt_L_03 -> Skirt_L,スカート_1_0 -> スカート,hair.012 -> hair)。"""
    key = re.sub(r"[._\-\s]{2,}", "_", re.sub(r"\d+", "", name)).strip("._- ")
    return key or name


def _free_tip(arm, bone, moving):
    """链下面没有别的东西带动的骨:没有刚体、约束、付与,再往下也没有物理骨(转换器的裙摆梢骨)。"""
    pb = arm.pose.bones[bone.name]
    mb = getattr(pb, "mmd_bone", None)
    if bone.name in moving or any(c.name != "mmd_tools_rigid_track" for c in pb.constraints):
        return False
    if mb is not None and (mb.has_additional_rotation or mb.has_additional_location):
        return False
    return not any(c.name in moving for c in bone.children_recursive)


def _is_head(arm, name):
    return any(n in HEAD_NAMES for n in names_of(arm.pose.bones[name]))


def _under_head(arm, name):
    """name 是头骨或挂在头骨下面。"""
    b = arm.data.bones.get(name)
    while b is not None:
        if _is_head(arm, b.name):
            return True
        b = b.parent
    return False


class ClothGroup:
    """still:"" = 有摆动刚体的链;"nobody" = 没有刚体;"static" = 只有跟骨刚体(still_groups)。"""

    def __init__(self, name, category, bones, anchor, still=""):
        self.name, self.category, self.bones, self.anchor, self.still = name, category, bones, anchor, still

    def __repr__(self):
        return "<ClothGroup %s %s: %d bones on %s%s>" % (self.category, self.name, len(self.bones), self.anchor,
                                                         ", " + self.still if self.still else "")


def classify(arm, names, anchor):
    pbs = [arm.pose.bones[n] for n in names]
    all_names = [x for pb in pbs for x in names_of(pb)]
    if any(SKIRT_RE.search(n) for n in all_names):
        return "SKIRT"
    if any(HAIR_RE.search(n) for n in all_names) or (anchor and _under_head(arm, anchor)):
        return "HAIR"
    return "CLOTH"


def cloth_groups(arm, bodies=None, exclude=()):
    """[ClothGroup]:除胸链以外的摆动骨,按挂点骨 + 名字分组(骨骼布料插件的 chain_groups)。"""
    bodies = bodies_by_bone(arm) if bodies is None else bodies
    moving = dynamic_bones(arm, bodies) - set(exclude)
    groups = {}
    for b in arm.data.bones:                            # 骨骼顺序:父在前
        if b.name not in moving:
            continue
        top = b
        while top.parent is not None and top.parent.name in moving and _prefix(top.parent.name) == _prefix(b.name):
            top = top.parent
        anchor = top.parent.name if top.parent is not None else ""
        groups.setdefault((anchor, _prefix(b.name)), []).append(b.name)
    out = []
    for (anchor, pre), names in groups.items():
        members = set(names)
        for n in names:
            for c in arm.data.bones[n].children:
                if c.name not in members and c.name not in exclude and _free_tip(arm, c, moving):
                    members.add(c.name)
                    members.update(d.name for d in c.children_recursive)
        names = [b.name for b in arm.data.bones if b.name in members]
        label = "%s (%s)" % (pre, anchor) if anchor else pre
        out.append(ClothGroup(label, classify(arm, names, anchor), names, anchor))
    return out


def _standard(pb):
    return any(n in STANDARD for n in names_of(pb))


def _driven(pb):
    """别的东西在带这根骨:约束(IK、复制旋转……,mmd_tools 的刚体跟随不算)、MMD 付与。"""
    if any(c.name != "mmd_tools_rigid_track" for c in pb.constraints):
        return True
    mb = getattr(pb, "mmd_bone", None)
    return mb is not None and (mb.has_additional_rotation or mb.has_additional_location)


HEADISH_RE = re.compile(r"^頭$|(^|[\s_.])head($|[\s_.\d])", re.I)   # 頭、head、Bip001 Head、AC Head


def _in_face(arm, name):
    """脸部的骨:自己或往上到头之间有名字像脸部的骨(舌、颊、眉……);名字像头发的不算。"""
    pb = arm.pose.bones[name]
    if any(HAIR_RE.search(n) for n in names_of(pb)):
        return False
    b = arm.data.bones[name]
    while b is not None:
        nm = names_of(arm.pose.bones[b.name])
        if any(HEADISH_RE.search(n) for n in nm):
            return False
        if any(FACE_RE.search(n) for n in nm):
            return True
        b = b.parent
    return False


def _under_limb_end(arm, name):
    """手腕、脚踝以下的骨(手指、脚趾):自己或往上有名字像手腕 / 脚踝 / 手指 / 脚趾的骨。"""
    b = arm.data.bones[name]
    while b is not None:
        if any(LIMB_END_RE.search(n) for n in names_of(arm.pose.bones[b.name])):
            return True
        b = b.parent
    return False


def still_groups(arm, bodies=None, exclude=()):
    """[ClothGroup(still=...)]:没有摆动刚体、在 MMD 里不会晃的骨链(模块说明)。exclude:已经分进别的组的骨。"""
    bodies = bodies_by_bone(arm) if bodies is None else bodies
    dyn = dynamic_bones(arm, bodies)
    exclude = set(exclude)
    weighted = _weighted(arm)
    below = {}                                          # 这根骨或子孙带权重

    def has_weight(b):
        if b.name not in below:
            below[b.name] = b.name in weighted or any(has_weight(c) for c in b.children)
        return below[b.name]

    cand = set()
    for b in arm.data.bones:
        if b.name in exclude or b.name in dyn:
            continue
        pb = arm.pose.bones[b.name]
        if _standard(pb) or _driven(pb) or looks_breast(pb) or not has_weight(b):
            continue
        if _in_face(arm, b.name) or _under_limb_end(arm, b.name):
            continue
        cand.add(b.name)
    groups = {}
    for b in arm.data.bones:                            # 骨骼顺序:父在前
        if b.name not in cand:
            continue
        top = b
        while top.parent is not None and top.parent.name in cand and _prefix(top.parent.name) == _prefix(b.name):
            top = top.parent
        anchor = top.parent.name if top.parent is not None else ""
        groups.setdefault((anchor, _prefix(b.name)), []).append(b.name)
    out = []
    for (anchor, pre), names in groups.items():
        members = set(names)
        depth = 0
        for n in names:
            d, p = 1, arm.data.bones[n].parent
            while p is not None and p.name in members:
                d, p = d + 1, p.parent
            depth = max(depth, d)
        if depth < 2:
            continue
        status = "static" if any(n in bodies for n in names) else "nobody"
        all_names = [x for n in names for x in names_of(arm.pose.bones[n])]
        if status == "nobody" and not any(r.search(x) for x in all_names for r in (HAIR_RE, SKIRT_RE, CLOTH_NAME_RE)):
            continue                                    # 没有刚体、名字也不像衣物头发:不知道是什么,不碰
        label = "%s (%s)" % (pre, anchor) if anchor else pre
        out.append(ClothGroup(label, classify(arm, names, anchor), names, anchor, still=status))
    return out


def detect(arm):
    """(胸链列表, 其他分组列表)。"""
    bodies = bodies_by_bone(arm)
    bust = bust_chains(arm, bodies)
    in_bust = {n for c in bust for n in c.bones}
    return bust, cloth_groups(arm, bodies, exclude=in_bust)


def chain_roots(arm, names):
    """一组骨里的链根(父骨不在组里的)。"""
    s = set(names)
    return [n for n in names if arm.data.bones[n].parent is None or arm.data.bones[n].parent.name not in s]
