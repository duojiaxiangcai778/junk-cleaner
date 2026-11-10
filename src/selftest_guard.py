# -*- coding: utf-8 -*-
"""
guard 自测 —— 不启动界面、不动真实垃圾，只验证「该拦的拦住、不该拦的放行」。

跑法：
    python E:\垃圾清理工具\src\selftest_guard.py

2026-11-04 事故之后加的回归脚本，以后改 guard.py / junk_items.py 先跑一遍这个。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guard
import junk_items
import cleaner

ok = 0
bad = 0


def check(name, got, want):
    global ok, bad
    if got == want:
        ok += 1
        print("  [PASS] %s" % name)
    else:
        bad += 1
        print("  [FAIL] %s  got=%r want=%r" % (name, got, want))


print("=== 1. 必须拦住的路径（DSH / ZCode 的记忆、插件、技能） ===")
must_block = [
    # --- pnpm store：2026-11-03 事故真凶 ---
    r"C:\Users\Administrator\AppData\Local\pnpm\store",
    r"D:\.pnpm-store",
    r"C:\Users\Administrator\AppData\Roaming\dsh-desktop\harness\.pnpm-store",
    # --- DSH 桌面端：缓存 / 更新包 / 依赖 ---
    r"C:\Users\Administrator\AppData\Roaming\dsh-desktop\Cache",
    r"C:\Users\Administrator\AppData\Roaming\dsh-desktop\Code Cache",
    r"C:\Users\Administrator\AppData\Local\dsh-desktop-updater\pending",
    r"C:\Users\Administrator\AppData\Roaming\dsh-desktop\harness\profiles\web\node_modules\dsh-mnemon",
    r"D:\D\dsh-desktop\DSH Desktop\resources\app.asar",
    # --- DSH 技能 / 插件 / 会话 / 存储 ---
    r"C:\Users\Administrator\AppData\Roaming\dsh-desktop\harness\skills",
    r"C:\Users\Administrator\AppData\Roaming\dsh-desktop\harness\skills\dsh-skill-authoring\SKILL.md",
    r"C:\Users\Administrator\AppData\Roaming\dsh-desktop\harness\plugins\dsh-searxng",
    r"C:\Users\Administrator\AppData\Roaming\dsh-desktop\harness\sessions",
    r"C:\Users\Administrator\AppData\Roaming\dsh-desktop\harness\storages",
    r"C:\Users\Administrator\AppData\Roaming\dsh-desktop\harness\mcp",
    r"C:\Users\Administrator\AppData\Roaming\dsh-desktop\harness\profiles\.generations\live\dsh-mnemon+0.5.33+abc\node_modules\dsh-mnemon",
    # --- DSH 用户配置 / 记忆 ---
    r"C:\Users\Administrator\.dsh\plugins\ui-liquid-glass",
    r"C:\Users\Administrator\.dsh\sessions",
    r"C:\Users\Administrator\.dsh\storages",
    r"C:\Users\Administrator\.mnemon\runtime\MEMORY.md",
    r"C:\Users\Administrator\.mnemon\runtime\memories.json",
    r"C:\Users\Administrator\.mnemon\documents",
    r"C:\Users\Administrator\Documents\deepseek-harness\default-workspace",
    # --- ZCode 技能 / 记忆 / 插件 ---
    r"C:\Users\Administrator\.zcode\skills",
    r"C:\Users\Administrator\.zcode\skills\my-skill\SKILL.md",
    r"C:\Users\Administrator\.zcode\cli\memories",
    r"C:\Users\Administrator\.zcode\cli\memories\projects\default\memory\MEMORY.md",
    r"C:\Users\Administrator\.zcode\cli\plugins\data\computer-use@zcode-plugins-official",
    r"C:\Users\Administrator\.zcode\cli\plugins\cache\zcode-plugins-official\pdf\0.2.2\skills",
    r"C:\Users\Administrator\.zcode\cli\agents",
    r"C:\Users\Administrator\.zcode\cli\artifacts",
    r"C:\Users\Administrator\.zcode\workspace\default",
    r"C:\Users\Administrator\.zcode\v2",
    r"C:\Users\Administrator\.zcode\AGENTS.md",
    # --- 其它 AI 工具 ---
    r"C:\Users\Administrator\.workbuddy\memory",
    r"C:\Users\Administrator\.codex",
]
for p in must_block:
    check(p, guard.is_protected(p)[0], True)

print("=== 2. 必须放行的普通垃圾 ===")
must_pass = [
    r"C:\Users\Administrator\AppData\Local\Temp",
    r"C:\Windows\Temp",
    r"C:\Windows\Prefetch",
    r"C:\Users\Administrator\AppData\Local\Google\Chrome\User Data\Default\Cache",
    r"C:\Users\Administrator\AppData\Local\Microsoft\Edge\User Data\Default\Code Cache",
    r"C:\Users\Administrator\AppData\Local\npm-cache",
    r"C:\Users\Administrator\AppData\Local\pip\Cache",
    r"C:\Windows\Logs\CBS",
    # --- QQ / 微信聊天记录：用户明确要清的，必须放行 ---
    r"C:\Users\Administrator\Documents\Tencent Files\1234567890\nt_qq\nt_data\Pic\2026-10\Ori",
    r"C:\Users\Administrator\Documents\Tencent Files\1234567890\nt_qq\nt_data\Video\2026-09\Ori",
    r"C:\Users\Administrator\Documents\Tencent Files\1234567890\nt_qq\nt_data\Ptt\2026-09\Ori",
    r"C:\Users\Administrator\Documents\Tencent Files\1234567890\nt_qq\nt_data\Emoji\personal_emoji\Ori",
    r"C:\Users\Administrator\Documents\Tencent Files\1234567890\nt_qq\nt_db",
    r"C:\Users\Administrator\Documents\xwechat_files\wxid_abc\msg\attach",
    r"C:\Users\Administrator\Documents\WeChat Files\wxid_abc\FileStorage\Cache",
    r"D:\Tencent Files\1234567890\nt_qq\nt_data\Pic\Thumb",
]
for p in must_pass:
    check(p, guard.is_protected(p)[0], False)

print("=== 3. 结构保护：目录里有 package.json 就不删 ===")
tmp = tempfile.mkdtemp(prefix="guardtest_")
try:
    fake = os.path.join(tmp, "fake_electron_app")
    os.makedirs(os.path.join(fake, "dist"))
    with open(os.path.join(fake, "package.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    with open(os.path.join(fake, "dist", "main.js"), "w", encoding="utf-8") as f:
        f.write("// x")
    hit, why = guard.is_protected_root(fake)
    check("含 package.json 的目录被拦", hit, True)
    print("         理由：%s" % why)

    # 真跑一次 _rm_tree，确认一个文件都没删
    freed, failed, skipped = cleaner._rm_tree(fake)
    check("_rm_tree 释放字节为 0", freed, 0)
    check("_rm_tree 跳过计数为 1", skipped, 1)
    check("目录仍然存在", os.path.isdir(fake), True)
    check("package.json 仍然存在", os.path.isfile(os.path.join(fake, "package.json")), True)

    print("=== 4. 普通目录照常删 ===")
    junk = os.path.join(tmp, "plain_junk")
    os.makedirs(junk)
    with open(os.path.join(junk, "a.tmp"), "w") as f:
        f.write("x" * 100)
    freed2, failed2, skipped2 = cleaner._rm_tree(junk)
    check("普通目录被删干净（目录消失）", os.path.isdir(junk), False)
    check("普通目录释放了字节", freed2, 100)
finally:
    try:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass

print("=== 5. 清理项里不允许再出现 safe 级的 DSH / pnpm store ===")
DANGER = ("pnpm_store", "dsh_cache")
for it in junk_items.ITEMS:
    if it["id"] in DANGER:
        check("%s 不是 safe 级" % it["id"], it["level"] != "safe", True)
        for p in it.get("paths", []):
            check("%s 的路径会被 guard 拦" % it["id"],
                  guard.is_protected(os.path.expandvars(p))[0], True)

print("=== 6. updater 通配项里 dsh-desktop-updater 会被 guard 拦 ===")
check("dsh-desktop-updater 被拦",
      guard.is_protected(r"C:\Users\Administrator\AppData\Local\dsh-desktop-updater")[0],
      True)
check("普通编辑器 updater 放行",
      guard.is_protected(r"C:\Users\Administrator\AppData\Local\trae-updater")[0],
      False)

print()
print("结果：%d 通过 / %d 失败" % (ok, bad))
sys.exit(0 if bad == 0 else 1)
