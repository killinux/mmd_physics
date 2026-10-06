"""一次跑完插件的检查(每个检查一个后台 Blender,一次一个),收集 PASS / FAIL。有失败时返回 1。

    python run_checks.py [detect] [kawaii] [effects] [skirt] [kits] [outfit] [still]      (不写 = 全部,约 35 分钟)

模型、动作、Blender 的路径见 config.py;每个检查的完整输出在系统临时目录的 mmd_physics_checks 下。
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402

M = config.MODELS
S = config.STILL
CHECKS = {
    # 三种骨架的胸链左右都认到
    "detect": [("check_detect.py", [M["vindictus"], M["roe"], M["template"]])],
    # 新版弹簧骨骼和 0.2.0 逐帧一样;别的骨架也能动
    "kawaii": [("check_kawaii.py", [M["vindictus"], M["roe"], M["template"]])],
    # 几种方式各算一遍,还原后和原来逐项一样
    "effects": [
        ("check_effects.py", [M["vindictus"], "60", "",
                              "BUST=SPRING:k1,HAIR=SPRING:vdf_hair,SKIRT=CLOTH:skirt,CLOTH=FOLLOW",
                              "BUST=CLOTH:roe_touch,HAIR=CLOTH:hair,SKIRT=CLOTH:lively,CLOTH=CLOTH:cloth"]),
        ("check_effects.py", [M["template"], "60", "BUST=SPRING:k1,SKIRT=SPRING:vdf_skirt,CLOTH=FOLLOW"]),
        # 整套换上(套件的刚体 / 关节要删干净)、PmxTailor(固定值 + 单给的扭转限位)
        ("check_effects.py", [M["roe"], "60", "BUST=RIGID:rgba", "BUST=RIGID:pmxtailor_l", "BUST=RIGID:western"]),
    ],
    # 裙子左右对称、不卡住、腿不穿出来(整段手势舞);乳奶模板模型的外套会撑开 30 多度,上限放宽
    "skirt": [
        ("check_skirt.py", [M["vindictus"], "300", "SKIRT=CLOTH:skirt", "45", "5", "1"]),
        ("check_skirt.py", [M["vindictus"], "300", "SKIRT=CLOTH:lively", "45", "5", "1"]),
        ("check_skirt.py", [M["vindictus"], "300", "SKIRT=SPRING:vdf_skirt", "45", "5", "1"]),
        ("check_skirt.py", [M["template"], "300", "SKIRT=CLOTH:skirt", "50", "5", "1"]),
    ],
    # 按衣服推荐:判出来的种类和预期一样,点按钮后预设换成推荐的
    "outfit": [("check_outfit.py", [M["vindictus"] + "=loose", M["roe"] + "=free", M["template"] + "=free",
                                    config.OUTFIT["hoodie"] + "=partial", config.OUTFIT["suit"] + "=free",
                                    config.OUTFIT["armor"] + "=none"])],
    # 胸部套件:每条胸链建一套、步长按套件、在动不炸,还原后不剩
    "kits": [
        ("check_kits.py", [M["roe"], "300"]),
        ("check_kits.py", [M["template"], "300"]),
        ("check_kits.py", [M["vindictus"], "300"]),
    ],
    # 原来不动的链(转换来的模型没有刚体):认得到;模型原样照旧不动;新建刚体 / 弹簧骨骼 / 骨骼布料都晃起来、
    # 不炸开,还原后新建的刚体一个不剩。PCF_005 删掉裙子的刚体,当作没物理的裙子
    "still": [
        ("check_still.py", [S["bunny"], "150", "", "10", "0"]),
        ("check_still.py", [S["bunny"], "150", "HAIR=RIGID:build", "10", "1", "75"]),
        ("check_still.py", [S["bunny"], "150", "HAIR=SPRING:vdf_hair", "10", "1", "75"]),
        ("check_still.py", [S["bunny"], "150", "HAIR=CLOTH:hair", "10", "1", "75"]),
        ("check_still.py", [S["suit"], "150", "HAIR=RIGID:build", "10", "1", "75"]),
        ("check_still.py", [M["vindictus"], "150", "SKIRT=RIGID:build", "14", "1", "60", "skirt"]),
        ("check_still.py", [M["vindictus"], "150", "SKIRT=CLOTH:skirt", "14", "1", "60", "skirt"]),
    ],
}


def main():
    which = [a for a in sys.argv[1:]] or list(CHECKS)
    logs = os.path.join(tempfile.gettempdir(), "mmd_physics_checks")
    os.makedirs(logs, exist_ok=True)
    passed, failed = [], []
    for key in which:
        for n, (script, args) in enumerate(CHECKS[key], 1):
            log = os.path.join(logs, "%s_%d.log" % (key, n))
            cmd = [config.BLENDER, "-b", "--factory-startup", "--python", os.path.join(HERE, script), "--"] + args
            t = time.time()
            with open(log, "w", encoding="utf-8", errors="replace") as fh:
                code = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=1800).returncode
            lines = [ln.rstrip() for ln in open(log, encoding="utf-8", errors="replace")
                     if ln.startswith(("PASS ", "FAIL ")) or "Traceback" in ln]
            print("[%s %d] %s  exit %d, %.0f s  (%s)" % (key, n, script, code, time.time() - t, log), flush=True)
            for ln in lines:
                print("    " + ln, flush=True)
            results = [ln for ln in lines if ln.startswith(("PASS ", "FAIL "))]
            if code != 0 or not results:
                failed.append("%s %d %s: exit %d, %d results - see %s" % (key, n, script, code, len(results), log))
            passed += [ln for ln in results if ln.startswith("PASS ")]
            failed += [ln for ln in lines if not ln.startswith("PASS ")]
    print("\n%d passed, %d failed" % (len(passed), len(failed)))
    for ln in failed:
        print("  " + ln)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
