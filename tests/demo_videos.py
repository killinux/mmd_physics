"""效果对比视频:每一格用 render_tile.py 在后台 Blender 里渲(一次一个),再用 ffmpeg 拼成带标签的网格,配舞蹈音乐。

    python demo_videos.py [bust|body|roe|template|kits|kits_roe|kits_template ...]      (不写 = 全部)

输出在 config.OUT:<名字>.mp4,每一格在 _tiles/<名字>/NN.mp4(+ .log)。已经有的格子跳过:
改了插件要重渲某一格,先把那一格的 mp4 挪走。模型、动作、Blender 的路径见 config.py。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402

M = config.MODELS
DEMOS = {
    "bust": dict(name="胸部_6种_Vindictus_PCF_005", view="chest", size=480, cols=3, pmx=M["vindictus"], tiles=[
        ("MMD 刚体 · 模型原样(归档的 B)", ""),
        ("MMD 刚体 · C 方案(E)", "BUST=RIGID:vdf_e"),
        ("MMD 刚体 · 乳奶模板", "BUST=RIGID:template"),
        ("弹簧骨骼 · Vindictus 原版(K1)", "BUST=SPRING:k1"),
        ("弹簧骨骼 · 下半身当本体(K3)", "BUST=SPRING:k3"),
        ("骨骼布料 · ROE 戳的时候", "BUST=CLOTH:roe_touch"),
    ]),
    "body": dict(name="头发裙子衣物_5种_Vindictus_PCF_005", view="full:25", size=480, cols=5, pmx=M["vindictus"], tiles=[
        ("全部 MMD 刚体(模型原样)", ""),
        ("弹簧骨骼(Vindictus 参数)", "HAIR=SPRING:vdf_hair,SKIRT=SPRING:vdf_skirt,CLOTH=SPRING:vdf_cloth"),
        ("骨骼布料(裙子防穿腿)", "HAIR=CLOTH:hair,SKIRT=CLOTH:skirt,CLOTH=CLOTH:cloth"),
        ("骨骼布料(裙子飘一点)", "HAIR=CLOTH:hair,SKIRT=CLOTH:lively,CLOTH=CLOTH:cloth"),
        ("跟随骨骼(不模拟)", "HAIR=FOLLOW,SKIRT=FOLLOW,CLOTH=FOLLOW"),
    ]),
    "roe": dict(name="胸部_3种_ROE_j01", view="chest", size=480, cols=3, pmx=M["roe"], tiles=[
        ("MMD 刚体 · 模型原样(bustB)", ""),
        ("弹簧骨骼 · Vindictus 原版(K1)", "BUST=SPRING:k1"),
        ("骨骼布料 · ROE 戳的时候", "BUST=CLOTH:roe_touch"),
    ]),
    "template": dict(name="胸部裙子_4种_乳奶模板模型", view="full:25", size=480, cols=4, pmx=M["template"], tiles=[
        ("MMD 刚体 · 模型原样(乳奶模板)", ""),
        ("弹簧骨骼(胸 K1、裙子 Vindictus)", "BUST=SPRING:k1,SKIRT=SPRING:vdf_skirt,CLOTH=SPRING:vdf_cloth"),
        ("骨骼布料(胸 ROE、裙子防穿腿)", "BUST=CLOTH:roe_touch,SKIRT=CLOTH:skirt,CLOTH=CLOTH:cloth"),
        ("骨骼布料(胸 ROE、裙子飘一点)", "BUST=CLOTH:roe_touch,SKIRT=CLOTH:lively,CLOTH=CLOTH:cloth"),
    ]),
    # 胸部「整套换上」的多段刚体套件(kits.py)和 PmxTailor 的参数
    "kits": dict(name="胸部_多段套件_6种_Vindictus_PCF_005", view="chest", size=480, cols=3, pmx=M["vindictus"], tiles=[
        ("MMD 刚体 · 模型原样(归档的 B)", ""),
        ("整套换上 · RGBA 式(60 Hz)", "BUST=RIGID:rgba"),
        ("整套换上 · Tda 式", "BUST=RIGID:tda"),
        ("整套换上 · 欧美 XPS 转换式", "BUST=RIGID:western"),
        ("MMD 刚体 · PmxTailor 胸(大)", "BUST=RIGID:pmxtailor_l"),
        ("MMD 刚体 · 乳奶模板", "BUST=RIGID:template"),
    ]),
    "kits_roe": dict(name="胸部_多段套件_4种_ROE_j01", view="chest", size=480, cols=4, pmx=M["roe"], tiles=[
        ("MMD 刚体 · 模型原样(bustB)", ""),
        ("整套换上 · RGBA 式(60 Hz)", "BUST=RIGID:rgba"),
        ("整套换上 · Tda 式", "BUST=RIGID:tda"),
        ("整套换上 · 欧美 XPS 转换式", "BUST=RIGID:western"),
    ]),
    "kits_template": dict(name="胸部_多段套件_4种_乳奶模板模型", view="chest", size=480, cols=4, pmx=M["template"],
                          tiles=[
        ("MMD 刚体 · 模型原样(乳奶模板)", ""),
        ("整套换上 · RGBA 式(60 Hz)", "BUST=RIGID:rgba"),
        ("整套换上 · Tda 式", "BUST=RIGID:tda"),
        ("整套换上 · 欧美 XPS 转换式", "BUST=RIGID:western"),
    ]),
    # AH 式(kits.py 的 ah):原版、质量 ×3、着衣用(左右连着)
    "kits_ah_roe": dict(name="胸部_AH式_4种_ROE_j01", view="chest", size=480, cols=4, pmx=M["roe"], tiles=[
        ("MMD 刚体 · 模型原样(bustB)", ""),
        ("AH 式 · 原版质量(×1)", "BUST=RIGID:ah,BUST.kit_mass=1"),
        ("整套换上 · AH 式(质量 ×3)", "BUST=RIGID:ah"),
        ("AH 式 · 着衣用(左右连着 ×10)", "BUST=RIGID:ah_clothed"),
    ]),
    "kits_ah": dict(name="胸部_AH式_4种_Vindictus_PCF_005", view="chest", size=480, cols=4, pmx=M["vindictus"], tiles=[
        ("MMD 刚体 · 模型原样(归档的 B)", ""),
        ("AH 式 · 原版质量(×1)", "BUST=RIGID:ah,BUST.kit_mass=1"),
        ("整套换上 · AH 式(质量 ×3)", "BUST=RIGID:ah"),
        ("AH 式 · 着衣用(左右连着 ×10)", "BUST=RIGID:ah_clothed"),
    ]),
}


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def render(demo, k, label, spec):
    folder = os.path.join(config.OUT, "_tiles", demo["name"])
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, "%02d.mp4" % k)
    if os.path.isfile(out) and os.path.getsize(out) > 10000:
        return out
    cmd = [config.BLENDER, "-b", "--factory-startup", "--python", os.path.join(HERE, "render_tile.py"), "--",
           "--pmx", demo["pmx"], "--vmd", config.VMD, "--wav", config.WAV, "--out", out, "--view", demo["view"],
           "--config", spec, "--size", str(demo["size"])]
    t = time.time()
    with open(out + ".log", "w", encoding="utf-8", errors="replace") as fh:
        code = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=3600).returncode
    lines = [ln.strip() for ln in open(out + ".log", encoding="utf-8", errors="replace")
             if ln.startswith(("FX ", "FX_RENDER_DONE", "Error", "Traceback"))]
    ok = os.path.isfile(out) and (code == 0 or _complete(out))
    note = "(Blender 退出时崩了,视频是完整的)" if ok and code != 0 else ""
    log("%s %02d %s: exit %d%s, %.0f s | %s" % (demo["name"], k, label, code, note, time.time() - t,
                                               " / ".join(lines)[:400]))
    return out if ok else None


def _complete(path):
    """视频写完了没有:ffprobe 读得出时长。PCF_005 换了套件以后 Blender 渲完退出时偶尔会崩(释放刚体时),
    视频已经写完,照样收下。"""
    folder = os.path.dirname(config.FFMPEG)
    probe = os.path.join(folder, "ffprobe") if folder else "ffprobe"
    r = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip()) > 1.0
    except ValueError:
        return False


def grid(demo, tiles):
    """格子按 cols 排,每格上方居中写标签;标签里别用半角冒号、逗号(drawtext 的参数分隔符)。"""
    n, cols = len(tiles), demo["cols"]
    rows = (n + cols - 1) // cols
    parts, inputs = [], []
    for i, (label, path) in enumerate(tiles):
        inputs += ["-i", path]
        parts.append("[%d:v]drawtext=fontfile='%s':text='%s':fontsize=22:fontcolor=white:box=1:boxcolor=black@0.55:"
                     "boxborderw=8:x=(w-text_w)/2:y=12[v%d]" % (i, config.FONT, label, i))
    row_labels = []
    for r in range(rows):
        cells = ["[v%d]" % i for i in range(r * cols, min(n, (r + 1) * cols))]
        parts.append(("%shstack=inputs=%d[q%d]" % ("".join(cells), len(cells), r)) if len(cells) > 1
                     else "%scopy[q%d]" % (cells[0], r))
        if rows > 1 and len(cells) < cols:          # 最后一行不满:补黑边居中,宽度和别的行一样才拼得起来
            parts.append("[q%d]pad=%d:ih:(ow-iw)/2:0:black[r%d]" % (r, cols * demo["size"], r))
        else:
            parts.append("[q%d]copy[r%d]" % (r, r))
        row_labels.append("[r%d]" % r)
    parts.append(("%svstack=inputs=%d[v]" % ("".join(row_labels), rows)) if rows > 1 else "[r0]copy[v]")
    script = os.path.join(config.OUT, demo["name"] + ".filter")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(";\n".join(parts))
    out = os.path.join(config.OUT, demo["name"] + ".mp4")
    cmd = [config.FFMPEG, "-nostdin", "-v", "error", "-y"] + inputs + [
        "-filter_complex_script", script, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", out]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    os.remove(script)
    log("grid %s: %s %s" % (out, r.returncode, r.stderr[-500:]))
    return out


def main():
    which = sys.argv[1:] or list(DEMOS)
    os.makedirs(config.OUT, exist_ok=True)
    for key in which:
        demo = DEMOS[key]
        done = [(label, path) for k, (label, spec) in enumerate(demo["tiles"], 1)
                for path in [render(demo, k, label, spec)] if path]
        if done:
            grid(demo, done)


if __name__ == "__main__":
    main()
