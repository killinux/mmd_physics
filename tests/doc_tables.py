"""docs/效果一览与手动做法.md 的附录(套件和全部预设的数值)直接从插件代码生成,改了 kits.py / presets.py 重跑一次;
加 --html 时再按使用说明页的样子出一份网页(本地看,不进仓库)。不用 Blender,普通 Python 就能跑。

python tests\\doc_tables.py [--html E:\\game_export\\_mmd_physics\\MMD物理_效果与手动做法.html]
"""
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOC = os.path.join(ROOT, "docs", "效果一览与手动做法.md")
BEGIN = "<!-- 附录开始:下面由 tests/doc_tables.py 生成,别手改 -->"
END = "<!-- 附录结束 -->"


# -- 插件的数据(只执行数据部分,不需要 bpy / mathutils) ------------------------------------------------------
def load_data():
    src = open(os.path.join(ROOT, "kits.py"), encoding="utf-8").read()
    ns = {}
    exec(src[src.index("RGBA = dict("):src.index("def items():")], ns)
    pns = {}
    exec(open(os.path.join(ROOT, "presets.py"), encoding="utf-8").read(), pns)
    return ns["KITS"], pns["FX"], pns["BREAST"]


ROLE = {"anchor": "锚(跟骨)", "main": "主(驱动胸骨)", None: "辅助(不绑骨)"}
MODE = {0: "ボーン追従", 1: "物理演算", 2: "物理+ボーン"}
SHAPE = {0: "球", 1: "箱", 2: "胶囊"}
CAT = {"BUST": "胸部", "HAIR": "头发", "SKIRT": "裙子", "CLOTH": "其他衣物"}


def n(x, k=3):
    s = ("%." + str(k) + "f") % x
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def v3(v, k=3):
    return "(%s)" % ", ".join(n(x, k) for x in v)


def _size(shape, sz):
    if shape == 0:
        return "半径 %s" % n(sz[0])
    if shape == 2:
        return "半径 %s、高 %s" % (n(sz[0]), n(sz[1]))
    return "半边长 %s" % v3(sz)


def _lim(lo, hi, k=3, unit=""):
    out = []
    for ax, a, b in zip("XYZ", lo, hi):
        if a > b:
            out.append("%s 自由" % ax)
        elif a == 0 and b == 0:
            continue
        elif a == b:
            out.append("%s 固定 %s%s" % (ax, n(a, k), unit))
        else:
            out.append("%s %s~%s%s" % (ax, n(a, k), n(b, k), unit))
    return "、".join(out) if out else "全锁"


def _springs(t):
    return "—" if not any(t) else v3(t, 1)


def appendix(kits, fx, breast):
    out = ["## 附录 A 套件数值", "",
           "模板模型上的原值,左侧(PMX 单位:X 左右、Y 上下、Z 前后,模型面朝 −Z)。右侧把 X 取反、旋转的 Y 和 Z 取反,"
           "关节的 X 平移、Y / Z 旋转限位取反对调。关节限位里没写到的轴是锁死的(0~0);下限大于上限是「自由」。",
           "对到别的模型时按第 4 节整体转、等比缩放 s:刚体尺寸、位置、平移限位 × s,旋转弹簧 × s²;质量、阻尼、旋转限位、"
           "平移弹簧不变。", ""]
    for key, kit in kits.items():
        out += ["### %s(`%s`)" % (kit["label"], key), "",
                "来源:%s。胸根 %s → 乳尖 %s%s。" % (kit["source"], v3(kit["root"], 4), v3(kit["front"], 4),
                                               ";物理步长 %d Hz" % kit["step_hz"] if kit.get("step_hz") else ""), "",
                "| 刚体 | 作用 | 形状 | 尺寸 | 位置 | 旋转° | 质量 | 移動 / 回転減衰 | 物理演算 |",
                "|---|---|---|---|---|---|---|---|---|"]
        for b in kit["bodies"]:
            out.append("| %s | %s | %s | %s | %s | %s | %s | %s / %s | %s |" % (
                b["name"], ROLE[b["role"]], SHAPE[b["shape"]], _size(b["shape"], b["size"]), v3(b["pos"]),
                v3(b["rot"], 2), n(b["mass"]), n(b["lin"], 4), n(b["ang"], 4), MODE[b["mode"]]))
        out += ["", "| 关节 | A → B | 位置 | 旋转° | 移動制限 | 回転制限 | ばね 移動 | ばね 回転 |",
                "|---|---|---|---|---|---|---|---|"]
        for j in kit["joints"]:
            out.append("| %s%s | %s → %s | %s | %s | %s | %s | %s | %s |" % (
                j["name"], "(主关节)" if j.get("main") else "", j["a"], j["b"], v3(j["pos"]), v3(j["rot"], 2),
                _lim(j["tmin"], j["tmax"]), _lim(j["rmin"], j["rmax"], 1, "°"), _springs(j.get("tspring", (0, 0, 0))),
                _springs(j.get("rspring", (0, 0, 0)))))
        for p in kit.get("pairs", ()):
            out.append("| %s(左右之间) | %s %s %s | 两个 %s 的正中间 | 0 | 全锁 | 全锁 | — | — |" % (
                p["name"], "右" + p["body"] if p.get("reverse") else "左" + p["body"], "→",
                "左" + p["body"] if p.get("reverse") else "右" + p["body"], p["body"]))
        out.append("")

    rigid = fx[("BUST", "RIGID")]
    out += ["## 附录 B 全部预设的数值", "", "### B.1 胸部 · MMD 刚体", "",
            "**固定值**:写进挂胸的摆动刚体和关节,平移锁死。摆动 = 上下摆和左右摆,扭转 = 绕前后轴。", "",
            "| 预设 | 质量 | 移動 / 回転減衰 | 摆动 ±° | 扭转 ±° | 旋转弹簧(三轴) |", "|---|---|---|---|---|---|"]
    for _k, label, _d, v in rigid:
        if v.get("kind") == "fixed":
            out.append("| %s | %s | %s / %s | %s | %s | %s |" % (
                label, n(v["mass"]), n(v["lin_damp"], 4), n(v["ang_damp"], 4), n(v["rot"]),
                n(v.get("twist_limit", v["rot"])), n(v["spring_rot"], 1)))
    out += ["", "**按下垂角定弹簧**:弹簧按第 3 节的式子算。", "",
            "| 预设 | 静止下垂° | 扭转下垂° | 上下摆 / 左右摆 / 扭转限位 ±° | 移動 / 回転減衰 |", "|---|---|---|---|---|"]
    for _k, label, _d, v in rigid:
        if v.get("kind") == "sag":
            out.append("| %s | %s | %s | %s / %s / %s | %s / %s |" % (
                label, n(v["sag"]), n(v["twist_sag"]), n(v["pitch_limit"]), n(v["yaw_limit"]), n(v["twist_limit"]),
                n(v["lin_damp"]), n(v["ang_damp"])))
    out += ["", "**整套换上**:套件的数值见附录 A。", "",
            "| 预设 | 套件 | 大小 × | 幅度 × | 托高 | 质量 × | 左右连着 |", "|---|---|---|---|---|---|---|"]
    for _k, label, _d, v in rigid:
        if v.get("kind") == "kit":
            out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                label, kits[v["kit"]]["label"], n(v["kit_scale"]), n(v["kit_limit"]), n(v["kit_lift"]),
                n(v["kit_mass"]), "是" if v["kit_pair"] else "否"))
    out += ["", "### B.2 头发 / 裙子 / 其他衣物 · MMD 刚体", "",
            "**按比例**(模型自带的刚体):", "",
            "| 预设 | 阻尼 × | 阻尼至少 | 关节旋转限位 × |", "|---|---|---|---|"]
    for _k, label, _d, v in fx[("HAIR", "RIGID")]:
        if v.get("kind") == "scale":
            out.append("| %s | %s | %s | %s |" % (label, n(v["damp_scale"]), n(v["damp_min"]), n(v["limit_scale"])))
    out += ["", "**新建刚体**(给原来不动的链,5.1 节;质量是链根的,往梢减到一半;下垂角是整条链的):", "",
            "| 类 | 质量 | 移動 / 回転減衰 | 摆动 ±° | 扭转 ±° | 静止下垂° |", "|---|---|---|---|---|---|"]
    for cat in ("HAIR", "SKIRT", "CLOTH"):
        for _k, label, _d, v in fx.get((cat, "RIGID"), []):
            if v.get("kind") == "build":
                out.append("| %s | %s | %s / %s | %s | %s | %s |" % (
                    CAT[cat], n(v["mass"]), n(v["lin_damp"]), n(v["ang_damp"]), n(v["rot"]), n(v["twist_limit"]),
                    n(v["sag"])))
    out += ["", "### B.3 弹簧骨骼(KawaiiPhysics)", "",
            "| 类 | 预设 | 刚度 | 阻尼 | 抵消整体移动 / 转动 | 限角° | 碰撞半径 cm | 重力 cm/s² | 末端补点 | 碰撞 | 角色本体 |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    fps = set()
    for cat in CAT:
        for _k, label, _d, v in fx.get((cat, "SPRING"), []):
            fps.add(v["target_fps"])
            col = "、".join(x for x, on in (("手臂胶囊", v["capsules"]), ("腿和胯", v["colliders"])) if on) or "—"
            out.append("| %s | %s | %s | %s | %s / %s | %s | %s | %s | %s | %s | %s |" % (
                CAT[cat], label, n(v["stiffness"]), n(v["damping"]), n(v["world_damping_location"]),
                n(v["world_damping_rotation"]), n(v["limit_angle"]) if v["limit_angle"] else "不限", n(v["radius_cm"]),
                n(v["gravity_cm"]), n(v["tip"]), col, v["carrier"] if v["carrier"] != "NONE" else "—"))
    out += ["", "模拟频率都是 %s Hz。" % " / ".join(str(x) for x in sorted(fps)), ""]
    out += ["### B.4 骨骼布料(Magica Cloth 2 风格)", "",
            "和独立的「骨骼布料」插件同名同义,长度单位米。", "",
            "| 类 | 预设 | 重力 | 阻尼 | 质点半径 | 角度恢复 / 恢复速度衰减 | 角度限制 根 / 梢° | 惯性 | 移动 / 转动 / 质点限速 "
            "| 背挡 | 边碰撞 | 腿胯碰撞 | 相邻链连接 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    rest = None
    for cat in CAT:
        for _k, label, _d, v in fx.get((cat, "CLOTH"), []):
            out.append("| %s | %s | %s | %s | %s | %s / %s | %s / %s | %s | %s / %s / %s | %s | %s | %s | %s |" % (
                CAT[cat], label, n(v["gravity"]), n(v["damping"]), n(v["radius"]), n(v["restore_stiffness"]),
                n(v["restore_attenuation"]), n(v["limit_root"]), n(v["limit_tip"]), n(v["inertia"]), n(v["move_limit"]),
                n(v["turn_limit"]), n(v["particle_limit"]),
                ("距离 %s" % n(v["backstop_distance"])) if v["backstop"] else "关", "开" if v["collision_edge"] else "关",
                "开" if v["colliders"] else "关", "开" if v["link"] else "关"))
            rest = v
    out += ["", "其余几项各预设都一样:摩擦 %s、地面%s(高度 %s)、子步数 %d、迭代 %d、混合 %s;相邻链连接的可拉长 %s、"
            "可压短 %s、只连近于 %s 米。" % (n(rest["friction"]), "开" if rest["floor"] else "关", n(rest["floor_height"]),
                                     rest["substeps"], rest["iterations"], n(rest["blend"]), n(rest["link_stretch"]),
                                     n(rest["link_squash"]), n(rest["link_max"])), ""]
    out += ["### B.5 胸部刚体调参(导出 PMX 用)的预设", "",
            "| 预设 | 物理演算 | 质量 | 移動 / 回転減衰 | 反発力 / 摩擦力 | 回転制限 ±°(三轴) | ばね定数-回転(三轴) |",
            "|---|---|---|---|---|---|---|"]
    for _k, label, _d, v in breast:
        if v.get("mode") == "0":
            out.append("| %s | ボーン追従 | — | — | — | — | — |" % label)
            continue
        out.append("| %s | 物理演算 | %s | %s / %s | %s / %s | %s | %s |" % (
            label, n(v["mass"]), n(v["lin_damp"]), n(v["ang_damp"]), n(v["bounce"]), n(v["friction"]), n(v["rot"]),
            n(v["spring_rot"], 1)))
    out.append("")
    return "\n".join(out)


# -- Markdown(本文用到的那几种写法)→ HTML ------------------------------------------------------------------
CSS = """
:root { --bg:#f6f7f9; --card:#fff; --text:#1d2430; --muted:#5d6878; --line:#dfe3ea; --accent:#d9480f; --chip:#eef1f6;
  --code:#f0f2f5; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#15181d; --card:#1d2128; --text:#e3e7ee;
  --muted:#9aa4b2; --line:#2e343e; --accent:#ff8c42; --chip:#262b34; --code:#262b34; } }
:root[data-theme="dark"] { --bg:#15181d; --card:#1d2128; --text:#e3e7ee; --muted:#9aa4b2; --line:#2e343e;
  --accent:#ff8c42; --chip:#262b34; --code:#262b34; }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.75 "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif; }
a { color: var(--accent); text-decoration: none; }
code { font-family: Consolas, "Cascadia Mono", "Microsoft YaHei", monospace; font-size: 13px; background: var(--code);
  padding: 1px 6px; border-radius: 4px; }
pre { background: var(--code); padding: 10px 14px; border-radius: 8px; overflow-x: auto; }
pre code { padding: 0; background: none; font-size: 14px; }
header.top { background: linear-gradient(135deg, #2b3240, #3b2a22); color: #fff; padding: 32px 24px 26px; }
header.top .in { max-width: 1480px; margin: 0 auto; }
header.top h1 { margin: 0 0 6px; font-size: 28px; letter-spacing: 1px; }
header.top p { margin: 4px 0; max-width: 1000px; opacity: .92; }
header.top code { background: rgba(255,255,255,.15); color: #fff; }
.wrap { max-width: 1480px; margin: 0 auto; padding: 24px; display: grid; grid-template-columns: 230px minmax(0, 1fr);
  gap: 32px; }
nav.toc { position: sticky; top: 16px; align-self: start; font-size: 14px; max-height: calc(100vh - 32px);
  overflow-y: auto; }
nav.toc b { display: block; color: var(--muted); font-weight: normal; margin-bottom: 6px; }
nav.toc a { display: block; padding: 3px 10px; border-left: 2px solid var(--line); color: var(--text); }
nav.toc a:hover { border-left-color: var(--accent); color: var(--accent); }
main { min-width: 0; }
section { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 20px 28px;
  margin-bottom: 22px; }
h2 { margin: 0 0 12px; font-size: 22px; display: flex; align-items: center; gap: 10px; }
h2 .n { display: inline-grid; place-items: center; min-width: 30px; height: 30px; padding: 0 6px; border-radius: 8px;
  background: var(--accent); color: #fff; font-size: 16px; }
h3 { margin: 22px 0 8px; font-size: 17px; }
p { margin: 8px 0; }
ul, ol { margin: 6px 0; padding-left: 24px; }
li { margin: 3px 0; }
table { width: 100%; border-collapse: collapse; margin: 10px 0 6px; font-size: 14px; }
th, td { text-align: left; vertical-align: top; padding: 6px 9px; border-bottom: 1px solid var(--line); }
th { background: var(--chip); font-weight: 600; white-space: nowrap; }
tr:nth-child(even) td { background: color-mix(in srgb, var(--chip) 45%, transparent); }
.tablewrap { overflow-x: auto; }
footer { color: var(--muted); font-size: 13px; text-align: center; padding: 10px 0 40px; }
@media (max-width: 1100px) { .wrap { grid-template-columns: 1fr; } nav.toc { position: static; max-height: none; }
  nav.toc a { display: inline-block; border-left: 0; padding: 2px 8px 2px 0; } }
@media (max-width: 760px) { .wrap { padding: 12px 16px; } section { padding: 14px 16px; } }
"""


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return s


def _join(lines):
    """硬折行的中文行接起来:两边都是英文字母 / 数字时才补空格。"""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if out and ln and re.match(r"[A-Za-z0-9]", ln[0]) and re.match(r"[A-Za-z0-9.,)]", out[-1]):
            out += " "
        out += ln
    return out


def _cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def to_html(md):
    lines = md.split("\n")
    title, intro, sections = "", [], []
    cur = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("<!--"):
            i += 1
            continue
        if ln.startswith("# "):
            title = ln[2:].strip()
            i += 1
            continue
        if ln.startswith("## "):
            head = ln[3:].strip()
            m = re.match(r"(\d+)\.\s*(.*)", head) or re.match(r"附录\s*([A-Z])\s*(.*)", head)
            num, text = (m.group(1), m.group(2)) if m else ("", head)
            cur = {"id": "s%d" % len(sections), "num": num, "title": text, "body": []}
            sections.append(cur)
            i += 1
            continue
        (cur["body"] if cur else intro).append(ln)
        i += 1

    def blocks(body):
        out, k = [], 0
        while k < len(body):
            ln = body[k]
            if not ln.strip():
                k += 1
                continue
            if ln.startswith("### "):
                out.append("<h3>%s</h3>" % inline(ln[4:].strip()))
                k += 1
            elif ln.startswith("```"):
                k += 1
                code = []
                while k < len(body) and not body[k].startswith("```"):
                    code.append(body[k])
                    k += 1
                k += 1
                out.append("<pre><code>%s</code></pre>" % html.escape("\n".join(code)))
            elif ln.startswith("|"):
                rows = []
                while k < len(body) and body[k].startswith("|"):
                    rows.append(body[k])
                    k += 1
                head, data = _cells(rows[0]), [_cells(r) for r in rows[2:]]
                t = ["<div class=\"tablewrap\"><table><tr>%s</tr>" % "".join("<th>%s</th>" % inline(c) for c in head)]
                for r in data:
                    t.append("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in r))
                out.append("".join(t) + "</table></div>")
            elif re.match(r"(- |\d+\. )", ln):
                tag = "ol" if ln[0].isdigit() else "ul"
                items = []
                while k < len(body) and (re.match(r"(- |\d+\. )", body[k]) or (body[k].startswith("  ") and items)):
                    if re.match(r"(- |\d+\. )", body[k]):
                        items.append([re.sub(r"^(- |\d+\. )", "", body[k])])
                    else:
                        items[-1].append(body[k])
                    k += 1
                out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % inline(_join(it)) for it in items), tag))
            else:
                para = []
                while k < len(body) and body[k].strip() and not re.match(r"(- |\d+\. |\||### |```)", body[k]):
                    para.append(body[k])
                    k += 1
                out.append("<p>%s</p>" % inline(_join(para)))
        return "\n".join(out)

    toc = "\n".join('<a href="#%s">%s%s</a>' % (s["id"], (s["num"] + ". ") if s["num"].isdigit() else
                                                  ("附录 %s " % s["num"] if s["num"] else ""), html.escape(s["title"]))
                    for s in sections)
    secs = "\n".join('<section id="%s"><h2>%s%s</h2>\n%s\n</section>' % (
        s["id"], ('<span class="n">%s</span>' % s["num"]) if s["num"] else "", html.escape(s["title"]),
        blocks(s["body"])) for s in sections)
    return ("<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>MMD物理 效果与手动做法</title>\n"
            "<style>%s</style>\n</head>\n<body>\n<header class=\"top\"><div class=\"in\"><h1>%s</h1>\n%s\n</div></header>\n"
            "<div class=\"wrap\">\n<nav class=\"toc\"><b>目录</b>\n%s\n</nav>\n<main>\n%s\n</main>\n</div>\n"
            "<footer>由 mmd_physics/tests/doc_tables.py 从 docs/效果一览与手动做法.md 生成 · 本地文件,没有上传</footer>\n"
            "</body>\n</html>\n") % (CSS, html.escape(title), blocks(intro), toc, secs)


def main():
    kits, fx, breast = load_data()
    with open(DOC, encoding="utf-8", newline="") as fh:
        text = fh.read()
    a, b = text.index(BEGIN) + len(BEGIN), text.index(END)
    new = text[:a] + "\n\n" + appendix(kits, fx, breast) + "\n" + text[b:]
    if new != text:
        with open(DOC + ".tmp", "w", encoding="utf-8", newline="") as fh:
            fh.write(new)
        os.replace(DOC + ".tmp", DOC)
        print("附录已更新:", DOC)
    else:
        print("附录没有变化")
    if "--html" in sys.argv:
        out = sys.argv[sys.argv.index("--html") + 1]
        with open(out + ".tmp", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(to_html(new))
        os.replace(out + ".tmp", out)
        print("网页:", out)


if __name__ == "__main__":
    main()
