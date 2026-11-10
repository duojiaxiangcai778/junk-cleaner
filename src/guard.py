# -*- coding: utf-8 -*-
"""
受保护路径守卫 —— v2.3.0 新增。

为什么要有这个文件
------------------
v2.2.0 把 pnpm 的包存储（%LOCALAPPDATA%\\pnpm\\store 和 D:\\.pnpm-store）当成
"可清理"项，结果 2026-11-03 17:02 一次清掉 2.2 GB，直接把 DSH 桌面端
（以及 Trae / Cursor / ZCode 这些同样用 pnpm 装插件的 Electron 应用）的
依赖树搞崩：pnpm 下次校验发现 store 没了，就把 node_modules 判为无效并清空，
插件 manifest 读不到 → DSH 启动时进 Safe Mode → 插件设置全部显示丢失。

同一批还清了 %APPDATA%\\dsh-desktop\\Cache，以及 %LOCALAPPDATA%\\*-updater 通配
命中的 dsh-desktop-updater。

结论：光改 junk_items.py 的路径还不够 —— 通配符和将来手滑都能再踩一遍。
所以在这里加一层「最后一道闸」：cleaner 每次要删东西之前都先问一遍，
命中保护规则就跳过并写日志，宁可少清，不可误删。
"""

import os
import sys

# ---------------------------------------------------------------------------
# 保护规则：路径里只要出现这些片段（小写比较），一律不删。
# 每条是 (片段, 人话理由)。片段用反斜杠开头，避免误匹配项目名。
# ---------------------------------------------------------------------------
_PROTECTED = [
    (r"\dsh-desktop",      "DSH 桌面端数据（harness / profiles / 插件 / 会话 / 记忆）"),
    (r"\.dsh",             "DSH 用户配置与插件目录"),
    (r"\.mnemon",          "Mnemon 记忆系统的记忆库"),
    (r"\pnpm\store",       "pnpm 全局包存储（删了会让 Electron 应用插件全失效）"),
    (r"\.pnpm-store",      "pnpm 包存储（含 DSH 自带的 store）"),
    (r"\node_modules",     "程序依赖目录（删了软件/插件直接坏掉）"),
    (r"\.workbuddy",       "WorkBuddy 配置、会话与记忆"),
    (r"\.zcode",           "ZCode 配置与记忆"),
    (r"\.codex",           "Codex 配置"),
    (r"\.cursor",          "Cursor 配置"),
    (r"\.trae",            "Trae 配置"),
    (r"\.claude",          "Claude 配置"),
    (r"\.gemini",          "Gemini 配置"),
    (r"\.antigravity",     "Antigravity 配置"),
    (r"\deepseek-harness", "DSH 工作区与源码"),
]

# 注意：这里**故意不保护** \Tencent Files 和微信目录。
# 2026-11-04 用户明确：QQ/微信聊天记录（图片、视频、语音、缩略图）本来就是要清的，
# 「聊天记录」页签的职责就是清这些。整套保护会把这个页签废掉。
# 真正不能动的 QQ 文字数据库（nt_db）由 chatdata.py 把它定成 view 级（不可勾选）来守，
# 不归 guard 管 —— 分权清楚，别混。

# 目录级「结构保护」：一个目录如果直接含这些东西，它就是软件本体或项目，
# 不是缓存，整棵不删。
_STRUCT_MARKERS = (".git", "package.json", "node_modules", "manifest.json", "pyproject.toml")


def _norm(path):
    """统一成小写、单反斜杠的绝对路径，用于片段匹配。"""
    try:
        p = os.path.abspath(path)
    except (OSError, ValueError):
        p = str(path)
    return p.replace("/", "\\").lower()


def is_protected(path):
    """
    这个路径能不能删？返回 (True/False, 理由)。
    只做字符串比较，不碰磁盘，遍历时逐个文件调用也不慢。
    """
    if not path:
        return False, ""
    low = _norm(path)

    # 正在运行的自己（PyInstaller 解出来的 _MEIxxxx）绝不能删
    if "_mei" in low:
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass and _norm(meipass) in low:
            return True, "本程序自己的运行时目录"

    for frag, why in _PROTECTED:
        if frag in low:
            return True, why
    return False, ""


def is_protected_root(path):
    """
    目录级检查：路径本身受保护，或者它就是软件/项目本体（含 .git、package.json 等）。
    只在开始处理某个目录时调一次，不进每个文件。
    """
    hit, why = is_protected(path)
    if hit:
        return True, why
    try:
        for name in _STRUCT_MARKERS:
            if os.path.exists(os.path.join(path, name)):
                return True, "目录里有 %s，判定为软件/项目本体" % name
    except (OSError, PermissionError):
        pass
    return False, ""


def explain(path):
    """给日志用的一句话。没命中返回空串。"""
    hit, why = is_protected_root(path)
    return why if hit else ""
