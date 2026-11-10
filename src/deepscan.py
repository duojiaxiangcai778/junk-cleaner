# -*- coding: utf-8 -*-
"""
深度分析：按「软件」为单位算占用，并自动识别里面哪些是可清的。

和 junk_items.py 的区别
----------------------
junk_items.py   写死路径，命中就命中，命中不了就没了。
deepscan.py     不写死路径，现场遍历目录，自己判断哪个子目录是缓存/日志/临时。
                所以「某个软件又在别处拉了一坨东西」也能被扫出来，不用改代码。

核心是 _walk()：
  · 遇到名字像缓存的子目录（Cache / GPUCache / Temp / logs ...）
    → 整个子树算进「可清理」，不再往下细分
  · 其余目录继续递归，文件大小累加进「总占用」
所以一次遍历同时得出「这软件一共多大」「其中多少能清掉」。
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor

MB = 1024 ** 2
GB = 1024 ** 3

# ---------------- 目录名 → 垃圾类别 ----------------
# 判定依据：这些目录里的东西删掉后，软件会自己重建；删了不丢用户数据。
CRASH_NAMES = {
    "crashpad", "crashdumps", "crashdump", "crashes", "minidump", "minidumps",
    "dumps", "watson", "wer", "errorreports",
}
LOG_NAMES = {
    "log", "logs", "logging", "logfiles", "audit-log", "traces",
}
TEMP_NAMES = {
    "temp", "tmp", ".tmp", "scratch", "scratchpad", "work_tmp",
}
CACHE_NAMES = {
    "cache", "caches", "cache2", "code cache", "gpucache", "gpu cache",
    "dawncache", "dawngraphitecache", "dawnwebgpucache", "dawncachedir",
    "shadercache", "gpushadercache", "grshadercache", "gpu_persistent_cache",
    "gpuprogramcache", "pxp_cache", "dxcache", "glcache",
    "__pycache__", "pytest_cache", "mypy_cache", "ruff_cache",
    "component_crx_cache", "extensions_crx_cache",
    "optimization_guide_model_store", "optguideondevicemodel",
    "translationkit", "wasmttsengine", "segmentation_platform",
    "shared dictionary", "shared_proto_db", "blob_storage", "cacheddata",
    "thumbcache", "thumbnails", "thumbnailcache", "iconcache",
    "emojicache", "mediacache", "media cache", "filecache", "file cache",
    "webcache", "netcache", "disk cache", "imagecache", "image cache",
    "thumb", "thumbtemp", "oritemp",
}
# 明确不碰：删了会丢数据/丢登录态
PROTECT_NAMES = {
    "service worker", "indexeddb", "local storage", "session storage",
    "extensions", "user data", "database", "db_storage", "db", "msgs",
    "backup", "backups", "output", "outputs", "models", "node_modules",
    "custom_nodes", "input", "saved_voices", "saved_bgm", "avatars",
}
# 整棵子树都没用的（更新器残留下的就是安装包）
WHOLE_JUNK_NAMES = {
    "old", "oldversion", "previous", "pending", "downloads", "installers",
}

_EXT_JUNK = re.compile(
    r"\.(part|crdownload|download|partial|tmp|temp|!ut|td|opdownload|aria2|!qb)$",
    re.I)


def _classify(dirname):
    """目录名 → 'cache' / 'temp' / 'log' / 'crash' / None"""
    n = dirname.lower().strip().lstrip(".")
    if n in PROTECT_NAMES:
        return None
    if n in CRASH_NAMES:
        return "crash"
    if n in LOG_NAMES:
        return "log"
    if n in TEMP_NAMES:
        return "temp"
    if n in CACHE_NAMES:
        return "cache"
    # XxxCache / XxxCache2 这类
    if n.endswith("cache") and len(n) > 5 and n not in PROTECT_NAMES:
        return "cache"
    return None


CAT_TEXT = {
    "cache": "缓存",
    "temp": "临时",
    "log": "日志",
    "crash": "崩溃转储",
    "partial": "中断残留",
}


FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_link_entry(entry):
    """
    目录联接（junction）/ 符号链接的判断。
    Windows 上 Python 的 is_dir(follow_symlinks=False) 对 junction 仍然返回 True，
    不拦的话会把别的盘的空间重复算进来（比如 C 盘的 Android\\Sdk 实际联到 D 盘）。
    """
    try:
        if entry.is_symlink():
            return True
        attr = entry.stat(follow_symlinks=False).st_file_attributes
        return bool(attr & FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return False


def _sub_size(path):
    """快速算子树字节数（不递归判类型，纯累加）。"""
    total = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if _is_link_entry(e):
                            continue
                        stack.append(e.path)
                    else:
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    return total


def _walk(root, max_depth=8):
    """
    遍历一个目录。
    返回 (总字节, [(可清路径, 类别, 字节)...])
    """
    total = 0
    found = []
    stack = [(root, 0)]
    while stack:
        cur, depth = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if _is_link_entry(e):
                            continue
                        cat = _classify(e.name)
                        if cat:
                            sz = _sub_size(e.path)
                            total += sz
                            if sz > 0:
                                found.append((e.path, cat, sz))
                        elif depth < max_depth:
                            stack.append((e.path, depth + 1))
                    else:
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    return total, found


# ================= 扫描根定义 =================

def _env(*names):
    for n in names:
        v = os.environ.get(n)
        if v and os.path.isdir(v):
            return v
    return None


BROWSER_HINT = {
    "slimjet", "google", "chrome", "edge", "firefox", "brave", "opera",
    "vivaldi", "chromium", "360se", "360chrome", "qqbrowser", "sogouexplorer",
    "风之影", "genpaobrowser", "steam",
}
DEV_HINT = {
    "npm", "npm-cache", "pnpm", "pnpm-cache", "yarn", "node", "nuget", "pip",
    "electron", "ms-playwright", "playwright", "python", "python311",
    "python314", "git", "github", "dotnet", "android", "android-sdk",
    "visual studio", "vscode", "microsoft visual studio", "cargo", "rustup",
    "go", "gradle", "maven", "cmake", "conan",
}
GAME_HINT = {
    "steam", "epic", "ubisoft", "battle.net", "wegame", "riot", "minecraft",
    "nexon", "ea app", "mumu", "ldplayer", "雷电", "bluestacks",
}


def guess_category(name):
    n = name.lower()
    if any(k in n for k in BROWSER_HINT):
        return "浏览器"
    if any(k in n for k in DEV_HINT):
        return "开发工具"
    if any(k in n for k in GAME_HINT):
        return "游戏 / 模拟器"
    if "nvidia" in n or "amd" in n or "intel" in n:
        return "显卡驱动"
    if "tencent" in n or "qq" in n or "微信" in n or "wechat" in n or "weixin" in n:
        return "腾讯系"
    if "wps" in n or "kingsoft" in n or "office" in n:
        return "办公"
    if any(k in n for k in ("dsh", "zcode", "workbuddy", "trae", "cursor",
                            "codex", "claude", "gemini", "antigravity",
                            "codebuddy", "cherry")):
        return "AI / 编辑器"
    if "update" in n:
        return "更新器残留"
    return "其他"


def app_roots():
    """
    返回 [(显示前缀, 目录)]，每个目录的每个直接子目录算「一个软件」。
    用户根目录下的点目录（.zcode / .workbuddy ...）本身就是软件目录，
    所以单独标记成 'self'，表示「这个目录自己就是那个软件」。
    """
    local = _env("LOCALAPPDATA")
    roaming = _env("APPDATA")
    home = os.path.expanduser("~")
    out = []
    if local:
        out.append(("Local", local))
    if roaming:
        out.append(("Roaming", roaming))
    try:
        for e in os.scandir(home):
            if e.is_dir(follow_symlinks=False) and e.name.startswith("."):
                out.append(("self", e.path))
    except OSError:
        pass
    for p in (r"C:\ProgramData", r"C:\Program Files", r"C:\Program Files (x86)"):
        if os.path.isdir(p):
            out.append(("系统级", p))
    return out


def _scan_one_app(path):
    """扫一个软件目录。"""
    name = os.path.basename(path.rstrip("\\"))
    total, found = _walk(path)
    clean = sum(s for _, _, s in found)
    return dict(
        name=name, path=path, total=total, clean=clean,
        parts=sorted(found, key=lambda x: -x[2]),
        category=guess_category(name),
    )

def scan_app_dirs(progress=None, workers=8, min_mb=8):
    """
    扫 C 盘所有软件目录。
    返回 [app dict]，按可清大小降序。
    """
    # 摊平成「一个软件 = 一个目录」
    targets = []
    seen = set()
    for scope, root in app_roots():
        if scope == "self":
            key = os.path.normcase(os.path.abspath(root))
            if key in seen:
                continue
            seen.add(key)
            targets.append((scope, root))
            continue
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for e in entries:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            key = os.path.normcase(os.path.abspath(e.path))
            if key in seen:
                continue
            seen.add(key)
            targets.append((scope, e.path))

    scope_map = {os.path.normcase(os.path.abspath(p)): s for s, p in targets}
    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for app in pool.map(_scan_one_app, [p for _, p in targets]):
            app["scope"] = scope_map.get(
                os.path.normcase(os.path.abspath(app["path"])), "")
            results.append(app)
            done += 1
            if progress:
                try:
                    progress(done, len(targets))
                except Exception:
                    pass
    results = [a for a in results if a["total"] >= min_mb * MB]
    results.sort(key=lambda a: (-a["clean"], -a["total"]))
    # 同名的补上父目录，避免出现三个「Microsoft」分不清
    counts = {}
    for a in results:
        counts[a["name"]] = counts.get(a["name"], 0) + 1
    for a in results:
        if counts[a["name"]] > 1:
            parent = os.path.basename(os.path.dirname(a["path"].rstrip("\\")))
            a["label"] = "%s (%s)" % (a["name"], parent)
        else:
            a["label"] = a["name"]
    return results


# ================= 系统自身的大头 =================

# 这些不删，只让人看明白 C 盘被什么吃了
SYSTEM_NOTE = {
    "winsxs": "系统组件仓库，系统更新/功能安装的旧版本都堆在这。不能直接删，"
              "要走 DISM 组件清理才安全（工具里「WinSxS 组件清理」那一项就是干这个）。",
    "system32": "系统核心程序和驱动，绝对不动。",
    "installer": "MSI 安装包的补丁缓存。卸载/修复软件时要用，删了以后修复安装会要你重新提供安装包。",
    "assembly": ".NET 全局程序集缓存（GAC），系统组件用，不动。",
    "systemtemp": "系统级临时目录。更新包、浏览器更新下载残留都在这，可清。",
    "temp": "系统临时目录，可清。",
    "syswow64": "32 位兼容层，不动。",
    "systemapps": "系统自带应用，不动。",
    "fonts": "字体，不动。",
    "lastgood": "上一次成功启动的系统配置备份，可删（但蓝屏后就没得回滚了）。",
    "microsoft.net": ".NET 运行时，不动。",
    "servicing": "系统维护组件，不动。",
    "softwaredistribution": "Windows 更新下载缓存，可清（删了下次更新重新下）。",
    "prefetch": "预读文件，可清，会自动重建。",
    "minidump": "蓝屏内存转储，可清。",
}


def scan_system_heavy(min_mb=100):
    """C 盘「系统占大头」清单：Windows 顶层目录 + 盘根大文件。只展示。"""
    out = []
    win = r"C:\Windows"
    try:
        entries = list(os.scandir(win))
    except OSError:
        entries = []
    for e in entries:
        try:
            if not e.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        sz = _sub_size(e.path)
        if sz >= min_mb * MB:
            out.append(dict(
                name=e.name, path=e.path, total=sz, clean=0, parts=[],
                category="系统目录", scope="Windows",
                note=SYSTEM_NOTE.get(e.name.lower(), ""),
            ))
    # 盘根大文件（页面文件 / 休眠文件这些）
    for e in _iter_root(r"C:\\"):
        try:
            if e.is_dir(follow_symlinks=False):
                continue
            sz = e.stat(follow_symlinks=False).st_size
        except OSError:
            continue
        if sz >= min_mb * MB:
            out.append(dict(
                name=e.name, path=e.path, total=sz, clean=0, parts=[],
                category="盘根文件", scope="C:\\",
                note="系统页面/休眠文件，大小由 Windows 管，不建议手动动。",
            ))
    out.sort(key=lambda a: -a["total"])
    for a in out:
        a["label"] = a["name"]
    return out


def _iter_root(root):
    try:
        with os.scandir(root) as it:
            return list(it)
    except OSError:
        return []


# ================= 散落垃圾 =================

def find_loose(roots, min_partial_mb=2, min_log_mb=20):
    """
    找散落在各处的：
      · 中断的下载/半成品（.part .crdownload .tmp ...）
      · 超大日志
      · PyInstaller 解压残留 _MEI*
    返回 dict(partial=[(path,size)], log=[...], mei=[...])
    """
    partial = []
    logs = []
    mei = []
    pmin = min_partial_mb * MB
    lmin = min_log_mb * MB
    stack = list(roots)
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        n = e.name
                        if n.lower().startswith("_mei") and n[4:].isdigit():
                            mei.append((e.path, _sub_size(e.path)))
                            continue
                        if n.lower() in ("node_modules", ".git", "winsxs"):
                            continue
                        stack.append(e.path)
                    else:
                        st = e.stat(follow_symlinks=False)
                        sz = st.st_size
                        if sz < pmin:
                            continue
                        if _EXT_JUNK.search(e.name):
                            partial.append((e.path, sz))
                        elif e.name.lower().endswith((".log", ".dmp")) and sz >= lmin:
                            logs.append((e.path, sz))
                except OSError:
                    continue
    partial.sort(key=lambda x: -x[1])
    logs.sort(key=lambda x: -x[1])
    mei = [m for m in mei if m[1] > 0]
    mei.sort(key=lambda x: -x[1])
    return dict(partial=partial, log=logs, mei=mei)


def loose_roots():
    """散落垃圾要扫的根（限 C 盘用户目录 + 系统临时 + D 盘工作目录）。"""
    roots = []
    for p in (_env("LOCALAPPDATA"), _env("APPDATA"), os.path.expanduser("~"),
              r"C:\Windows\SystemTemp", r"C:\Windows\Temp"):
        if p and os.path.isdir(p):
            roots.append(p)
    for p in (r"D:\D", r"D:\E"):
        if os.path.isdir(p):
            roots.append(p)
    # 去重 + 去掉被包含的子路径
    roots = sorted(set(os.path.normpath(p) for p in roots), key=len)
    out = []
    for p in roots:
        if not any(p.lower().startswith(o.lower() + os.sep) for o in out):
            out.append(p)
    return out
