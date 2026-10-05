"""识别:每个模型的胸链左右两侧都认到,其余摆动骨分成头发 / 裙子 / 其他衣物。

blender -b --factory-startup --python check_detect.py -- [PMX ...]      (不写 = config.MODELS 全部)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _blender  # noqa: E402

for path in _blender.argv() or list(_blender.config.MODELS.values()):
    _blender.fresh()
    from mmd_physics import chains  # noqa: E402

    scene, root, arm = _blender.load(path)
    bust, groups = chains.detect(arm)
    print("=" * 90)
    print(path)
    for c in bust:
        print("  BUST %s %-28s %3d bones %s" % (c.side, c.root, len(c.bones), "tip" if c.tip else ""))
    counts = {}
    for g in groups:
        counts[g.category] = counts.get(g.category, 0) + 1
        print("  %-6s %-40s %3d bones, roots %s" % (g.category, g.name[:40], len(g.bones),
                                                    chains.chain_roots(arm, g.bones)[:4]))
    sides = sorted({c.side for c in bust})
    _blender.result("detect %s" % os.path.basename(path), sides == ["L", "R"],
                    "bust chains %d (sides %s), groups %s" % (len(bust), "".join(sides), counts))
