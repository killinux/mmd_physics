"""「按衣服推荐」的判断(outfit.py):每个模型判出来的种类要和预期一样。
通过 = 种类对;另外点一次「按衣服推荐」,只跟一部分 / 挡着一层的模型胸部预设要换成推荐的(MMD 刚体:C 方案 / 紧实),
贴身 / 裸着 / 胸骨不带网格的不改。

blender -b --factory-startup --python check_outfit.py -- PMX=预期 [PMX=预期 ...]      预期:free / partial / stiff / none
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender  # noqa: E402
from _blender import bpy  # noqa: E402

PAIRS = [a.rsplit("=", 1) for a in _blender.argv()]

for pmx, want in PAIRS:
    _blender.fresh()
    from mmd_physics import outfit  # noqa: E402
    from mmd_tools.core.model import Model  # noqa: E402
    t = time.time()
    scene, root, arm = _blender.load(pmx)
    result, worst = outfit.analyse(arm)
    t_an = time.time() - t
    bpy.ops.mmd_physics.fx_detect()
    fx = root.mmd_physics_fx
    before = fx.bust.preset
    bpy.ops.mmd_physics.fx_outfit()
    after = fx.bust.preset
    expect_preset = outfit.RECOMMEND.get(worst, {}).get(fx.bust.method, before)
    ok = worst == want and after == expect_preset
    print("OUTFIT %s | %s | %s" % (os.path.basename(pmx), worst, fx.outfit))
    _blender.result("outfit %s" % os.path.basename(pmx), ok, "%s (want %s), preset %s -> %s | %s | %.1f s" % (
        worst, want, before, after, outfit.summary(result, worst), t_an))
