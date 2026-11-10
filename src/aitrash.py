# -*- coding: utf-8 -*-
"""
aitrash.py —— AI 软件残留专项

用户原话：「我装的 AI 软件都在 D 盘，它们在工作过程中可能乱拉文件，没有约束，
各种地方都有东西。比如工作日志、下载没删的软件，还有那种被打断的、干了一半的绘画文件」

四类产出：
  1. AI 软件的日志 / 临时 / 缓存 / __pycache__ / .git 残留   → 可清
  2. AI 软件的产出目录（ComfyUI 的 output、input）           → 要确认
  3. AI 编辑器/助手的隐藏工作区（.workbuddy / .zcode / .codex）→ 细分
  4. 半成品：0 字节图片、.tmp/.part 断点、解压没删的安装包     → 可清

不写死盘符：按名字关键词在本地固定盘里挖，深度 ≤ 3。
"""

import os
import re
import time
import ctypes

from deepscan import _sub_size, _iter_root, _classify
import guard

MB = 1024 * 1024
GB = 1024 * MB

# 认得出是 AI / 编程助手类软件的名字片段
AI_HINTS = (
    "comfy", "stable-diffusion", "stable_diffusion", "sd-webui", "sdwebui", "webui",
    "sdxl", "flux", "fooocus", "invoke", "kohya", "novelai", "midjourney",
    "ollama", "lmstudio", "lm-studio", "text-generation-webui", "koboldcpp",
    "oobabooga", "gpt4all", "llamafile", "localai", "jan", "msty", "anythingllm",
    "index-tts", "indextts", "chattts", "gpt-sovits", "so-vits", "whisper",
    "esrgan", "upscayl", "realesrgan", "gfpgan", "codeformer",
    "swinir", "animegan", "saber", "yotta",
    "claude", "codex", "cursor", "trae", "zcode", "workbuddy", "dsh-desktop",
    "antigravity", "cherry", "qwen", "vllm", "paddle", "easyocr", "u2net",
    "huggingface", "modelscope", "openai", "gemini", "copilot", "aider", "cline",
    "windsurf", "continue", "tabnine", "dify", "flowise", "langchain",
)

# 名字像但不是的东西，别误报
NOT_AI = {
    "cursors",              # Windows 鼠标指针
    "rtuwpsrvcmain",        # Realtek 服务
    "~drvceolog",           # 驱动人生日志
    "continue",             # 名字太通用，只在带 ai 时才认
}

# 名字里带这些就说明是「安装完该删的」
INSTALLER_HINT = re.compile(r"(-windows|-win64|-x64|setup|installer|portable)", re.I)

# 明确的缓存/残留目录（相对用户目录），带中文说明
HOME_CACHE = [
    (r".cache\codex-runtimes", "Codex 运行时缓存（每次跑都拉一份新运行时，旧的从不清理）"),
    (r".cache\huggingface", "HuggingFace 模型下载缓存"),
    (r".cache\torch", "PyTorch 扩展编译缓存"),
    (r".cache\modelscope", "ModelScope 模型下载缓存"),
    (r".codex\.tmp", "Codex 临时文件"),
    (r".workbuddy\logs", "WorkBuddy 运行日志"),
    (r".workbuddy\shell-snapshots", "WorkBuddy 终端快照"),
    (r".workbuddy\clipboard-images", "WorkBuddy 剪贴板图片"),
    (r".workbuddy\traces", "WorkBuddy 调用轨迹"),
    (r".workbuddy\workspace", "WorkBuddy 工作区（会话中间产物）"),
    (r".zcode\cli\exec", "ZCode 每次执行的 stdout 日志"),
    (r".zcode\logs", "ZCode 运行日志"),
    (r".zcode\workspace", "ZCode 工作区缓存"),
    (r".paddlex", "PaddleX 模型缓存"),
    (r".u2net", "U2Net 抠图模型缓存"),
    (r".EasyOCR", "EasyOCR 模型缓存"),
    (r"AppData\Local\ms-playwright", "Playwright 浏览器内核（下载了多份）"),
    (r"AppData\Local\OpenAI", "OpenAI 客户端缓存"),
]

SKIP_DIRS = {"node_modules", "$RECYCLE.BIN", "System Volume Information"}


# ---------------------------------------------------------------- 找 AI 软件

def _fixed_drives():
    out = []
    try:
        k32 = ctypes.windll.kernel32
        mask = k32.GetLogicalDrives()
        for i, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            if not (mask >> i) & 1:
                continue
            p = letter + ":\\"
            if k32.GetDriveTypeW(ctypes.c_wchar_p(p)) == 3:
                out.append(p)
    except Exception:
        for letter in "CDEFGHIJKL":
            p = letter + ":\\"
            if os.path.isdir(p):
                out.append(p)
    return out


def _is_ai(name):
    low = name.lower()
    if low in NOT_AI:
        return False
    return any(h in low for h in AI_HINTS)


def find_ai_roots(max_depth=2):
    """
    在本地盘里找 AI 软件目录。
    返回 [(名字, 路径)]，同一路径不重复。
    """
    found = []
    seen = set()
    for root in _fixed_drives():
        queue = [(root, 0)]
        while queue:
            cur, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for e in _iter_root(cur):
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                if e.name.lower() in SKIP_DIRS:
                    continue
                key = os.path.normcase(os.path.abspath(e.path))
                if key in seen:
                    continue
                if _is_ai(e.name):
                    seen.add(key)
                    found.append((e.name, e.path))
                    continue          # 命中就不再往里钻，避免出几十个子项
                queue.append((e.path, depth + 1))
    return found


# ---------------------------------------------------------------- 行

def _row(rid, name, category, level, paths, desc, kind="dir"):
    # v2.3.0：扫到的东西只要落在 guard 保护范围（DSH / pnpm store /
    # node_modules / 各种编辑器的配置目录），直接降成「不动」，
    # 别让它在列表里顶着「可清理」勾上去却删不掉。
    paths = list(paths)
    if level != "view":
        for p in paths:
            hit, why = guard.is_protected(p)
            if hit:
                level = "view"
                desc = "%s（此项受保护，不参与清理：%s）" % (desc, why)
                break
    return dict(id=rid, name=name, category=category, level=level,
                kind=kind, paths=paths, desc=desc, size=0)


def _size(paths):
    return sum(_sub_size(p) for p in paths)


CAT_NOTE = {
    "log": "运行日志，删了不影响使用。",
    "temp": "临时文件，纯垃圾。",
    "cache": "缓存，删了会自动重建（首次启动会慢一点）。",
    "crash": "崩溃转储，纯垃圾。",
}


def _ai_root_rows(name, root):
    """拆一个 AI 软件目录：缓存/日志/产出/模型。"""
    rows = []
    tag = name

    # 这些子目录不往下钻（要么单独处理，要么是第三方包）
    STOP = {"models", "model", "output", "outputs", "input", "inputs",
            "custom_nodes", "site-packages", "node_modules", "resources",
            "venv", ".venv", "python", "runtime", "bin", "lib", "libs"}

    junk = {}

    def _collect(cur, depth):
        for e in _iter_root(cur):
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            low = e.name.lower()
            cat = _classify(e.name)
            if cat and cat != "protect":
                sz = _sub_size(e.path)
                if sz >= 1 * MB:
                    junk[(cat, e.path)] = sz
                continue
            if low in (".git", "__pycache__"):
                sz = _sub_size(e.path)
                if sz >= 1 * MB:
                    junk[("cache", e.path)] = sz
                continue
            if depth < 3 and low not in STOP:
                _collect(e.path, depth + 1)

    _collect(root, 0)
    for (cat, path), sz in sorted(junk.items(), key=lambda x: -x[1])[:8]:
        rel = os.path.relpath(path, root)
        # 模型缓存不算「随便可删」，要用户确认
        lv = "safe"
        if "cache" in cat and any(k in rel.lower() for k in ("hf_cache", "huggingface", "modelscope")):
            lv = "caution"
        rows.append(_row(
            "ai:%s:%s" % (tag, rel.replace("\\", "/")),
            "%s · %s" % (tag, rel),
            "AI·缓存日志", lv, [path],
            CAT_NOTE.get(cat, "缓存/临时目录，可清。") + "（%s）" % rel))

    # 产出 / 输入 / 日志：目录名对得上就报，深度 3 内都找
    SPECIAL = {
        "output": ("AI·产出", "caution", "AI 生成的结果全在这。删了图就没了，先自己看一眼。"),
        "outputs": ("AI·产出", "caution", "AI 生成的结果全在这。删了图就没了，先自己看一眼。"),
        "input": ("AI·产出", "caution", "喂给 AI 的输入素材。删了下次要重新放。"),
        "inputs": ("AI·产出", "caution", "喂给 AI 的输入素材。删了下次要重新放。"),
        "temp": ("AI·临时", "safe", "生成过程中的中间图，纯垃圾。"),
        "tmp": ("AI·临时", "safe", "临时文件，纯垃圾。"),
        "logs": ("AI·缓存日志", "safe", "运行日志，删了不影响。"),
        "log": ("AI·缓存日志", "safe", "运行日志，删了不影响。"),
        "models": ("AI·模型", "view", "模型权重。删了要重新下几十 GB，除非你确定不用了，别动。"),
        "model": ("AI·模型", "view", "模型权重。删了要重新下，别动。"),
    }
    hits = []

    def _find_special(cur, depth):
        for e in _iter_root(cur):
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            low = e.name.lower()
            if low in SPECIAL:
                hits.append((e.path, low))
                continue
            if depth < 3 and low not in ("node_modules", "site-packages", ".git",
                                         "custom_nodes", "resources", "__pycache__"):
                _find_special(e.path, depth + 1)

    _find_special(root, 0)
    for path, low in hits:
        sz = _sub_size(path)
        if sz < 1 * MB:
            continue
        cat, lv, desc = SPECIAL[low]
        rel = os.path.relpath(path, root)
        rows.append(_row("ai:%s:%s" % (tag, rel.replace("\\", "/")),
                         "%s · %s" % (tag, rel), cat, lv, [path], desc))
    return rows


def _home_cache_rows():
    rows = []
    home = os.path.expanduser("~")
    for rel, desc in HOME_CACHE:
        p = os.path.join(home, rel.replace("\\", os.sep))
        if not os.path.isdir(p):
            continue
        sz = _sub_size(p)
        if sz < 5 * MB:
            continue
        # .tmp / cli\exec 这种纯垃圾算可清，工作区类要确认
        level = "caution" if any(k in rel for k in ("workspace", "OpenAI")) else "safe"
        rows.append(_row("home:%s" % rel.replace("\\", "/"),
                         os.path.basename(rel) if "\\" not in rel else rel,
                         "AI·缓存日志", level, [p], desc))
    return rows


# ---------------------------------------------------------------- 半成品 / 断点

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".mp4", ".webm",
           ".wav", ".flac", ".mp3", ".ogg")
PART_EXT = (".tmp", ".temp", ".part", ".partial", ".download", ".crdownload",
            ".aria2", "!ut", ".td")


def _skip_dir(name, path):
    """目录联接/符号链接不跟进去（会把别的盘的文件算到这里来）。"""
    if name.lower() in ("node_modules", ".git", "site-packages", "models", "model",
                        "__pycache__", "custom_nodes"):
        return True
    try:
        if os.path.islink(path):
            return True
        return bool(os.stat(path, follow_symlinks=False).st_file_attributes & 0x400)
    except (OSError, AttributeError):
        return True


def scan_broken(roots, min_mb=1):
    """
    找半成品：0 字节图片/音视频、断点续传残片。
    返回 (broken_rows, partial_rows)，元素是 (路径, 字节)。
    """
    broken = []
    partial = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if not _skip_dir(d, os.path.join(dp, d))]
            for f in fns:
                low = f.lower()
                is_img = low.endswith(IMG_EXT)
                is_part = low.endswith(PART_EXT)
                if not (is_img or is_part):
                    continue
                p = os.path.join(dp, f)
                try:
                    sz = os.path.getsize(p)
                except OSError:
                    continue
                if is_img and sz == 0:
                    broken.append((p, 0))
                elif is_part and sz >= min_mb * MB:
                    partial.append((p, sz))
    return broken, partial


# ---------------------------------------------------------------- 安装包残留

def find_leftover_installers(roots, min_mb=80):
    """
    找「装完了没删」的东西：AI 目录里的大 exe/msi/7z/zip，
    以及名字里带 -windows / setup / portable 的解压目录。
    """
    hits = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        base = os.path.basename(root.rstrip("\\"))
        # 整个目录就是个解压出来的安装包
        if INSTALLER_HINT.search(base) and _is_ai(base):
            sz = _sub_size(root)
            if sz >= min_mb * MB:
                hits.append((root, sz, "整个目录是解压出来的安装包，装完就能删"))
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if not _skip_dir(d, os.path.join(dp, d))]
            for f in fns:
                if not f.lower().endswith((".exe", ".msi", ".7z", ".zip", ".rar", ".iso")):
                    continue
                p = os.path.join(dp, f)
                try:
                    sz = os.path.getsize(p)
                except OSError:
                    continue
                if sz >= min_mb * MB:
                    hits.append((p, sz, "大安装包，装完一般就不用留了"))
    # 去重 + 去掉被父目录包含的
    hits.sort(key=lambda x: -x[1])
    out = []
    seen = set()
    for p, sz, note in hits:
        if p in seen:
            continue
        seen.add(p)
        out.append((p, sz, note))
    return out


# ---------------------------------------------------------------- 对外

def scan():
    """返回 (rows, info)。"""
    rows = []
    roots = find_ai_roots()
    info = {"roots": roots, "total": 0}

    # 同名目录（D:\E\ComfyUI-aki 和 E:\ComfyUI-aki）要标出盘符，不然分不清
    name_cnt = {}
    for n, _ in roots:
        name_cnt[n] = name_cnt.get(n, 0) + 1

    for name, root in roots:
        sz = _sub_size(root)
        if sz < 5 * MB:
            continue
        info["total"] += sz
        tag = name if name_cnt[name] == 1 else "%s (%s)" % (name, root[:2])
        rows.extend(_ai_root_rows(tag, root))

    rows.extend(_home_cache_rows())

    # 半成品只在 AI 目录里找，别去扫整个盘
    ai_paths = [p for _, p in roots]
    broken, partial = scan_broken(ai_paths)
    for p, _sz in broken[:30]:
        rows.append(_row("ai:broken:%s" % p, "半成品·0 字节 %s" % os.path.basename(p),
                         "AI·半成品", "safe", [p],
                         "生成到一半就中断了，文件是空的，纯垃圾。", kind="file"))
    for p, sz in sorted(partial, key=lambda x: -x[1])[:20]:
        rows.append(_row("ai:partial:%s" % p,
                         "断点残留 %.1f MB %s" % (sz / MB, os.path.basename(p)),
                         "AI·半成品", "safe", [p],
                         "下载/生成中断留下的半截文件，纯垃圾。", kind="file"))

    for p, sz, note in find_leftover_installers(ai_paths)[:20]:
        rows.append(_row("ai:inst:%s" % p, "装完没删 · %s" % os.path.basename(p),
                         "AI·安装包", "caution", [p], note,
                         kind="file" if os.path.isfile(p) else "dir"))

    # 同一个目录可能被「缓存收集」和「特殊目录」两边各产生一行，按 id 去重
    uniq = {}
    for r in rows:
        uniq.setdefault(r["id"], r)
    rows = list(uniq.values())

    _attach_sizes(rows)
    rows = [r for r in rows if r["size"] > 0]
    # 能清的排前面（大的在上），只展示的模型放最后
    lv = {"safe": 0, "caution": 1, "view": 2}
    rows.sort(key=lambda r: (lv.get(r["level"], 9), -r["size"]))
    return rows, info


def _row_size(row):
    return row["size"]


def _attach_sizes(rows):
    for r in rows:
        r["size"] = _size(r["paths"])
    return rows


if __name__ == "__main__":
    t = time.time()
    rows, info = scan()
    print("%.1fs  找到 %d 个 AI 软件目录，合计 %.2f GB；%d 行"
          % (time.time() - t, len(info["roots"]), info["total"] / GB, len(rows)))
    print("目录：", [n for n, _ in info["roots"]])
    print("-" * 92)
    for r in rows:
        print("%8.1f MB [%-7s] %-10s %s" % (r["size"] / MB, r["level"], r["category"], r["name"]))
