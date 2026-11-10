# -*- coding: utf-8 -*-
"""扫描模块：算每一项垃圾占多少地方。"""

import os
import glob
import ctypes
import subprocess
from concurrent.futures import ThreadPoolExecutor

CREATE_NO_WINDOW = 0x08000000


def resolve_paths(paths):
    """展开环境变量和通配符，只返回真实存在的路径。"""
    found = []
    for raw in paths or []:
        p = os.path.expandvars(raw)
        if "*" in p or "?" in p:
            found.extend(glob.glob(p))
        elif os.path.exists(p):
            found.append(p)
    # 去重，保持顺序
    seen = set()
    out = []
    for p in found:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def path_size(path):
    """目录或文件占用字节数。权限不足 / 文件被占用时跳过。"""
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        stack = [path]
        while stack:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                # 目录联接（junction）不能进去算，否则会把别的盘重复计入
                                if entry.is_symlink():
                                    continue
                                attr = entry.stat(follow_symlinks=False).st_file_attributes
                                if attr & 0x400:
                                    continue
                                stack.append(entry.path)
                            else:
                                total += entry.stat(follow_symlinks=False).st_size
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue
        return total
    except (OSError, PermissionError):
        return 0


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("i64Size", ctypes.c_int64),
        ("i64NumItems", ctypes.c_int64),
    ]


def recycle_bin_size(drive_root):
    """用 Shell API 查某个盘回收站占用，比遍历 $Recycle.Bin 快得多。"""
    try:
        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
        res = ctypes.windll.shell32.SHQueryRecycleBinW(
            ctypes.c_wchar_p(drive_root), ctypes.byref(info)
        )
        if res == 0 and info.i64Size > 0:
            return int(info.i64Size)
    except Exception:
        pass
    # 兜底：直接算 $Recycle.Bin
    return path_size(os.path.join(drive_root, "$Recycle.Bin"))


def vss_size():
    """系统还原点（卷影副本）占用总字节数。"""
    ps = (
        "$s = 0; "
        "Get-CimInstance Win32_ShadowStorage -ErrorAction SilentlyContinue | "
        "ForEach-Object { $s += $_.UsedSpace }; "
        "if ($s -gt 0) { $s } else { 0 }"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        txt = (out.stdout or "").strip()
        if txt:
            return int(txt.splitlines()[-1].strip())
    except Exception:
        pass
    return 0


def disk_free(drive_root):
    """返回 (已用字节, 空闲字节, 总字节)。拿不到就返回 (0,0,0)。"""
    try:
        total, used, free = ctypes.c_ulonglong(0), None, None
        free = ctypes.c_ulonglong(0)
        res = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(drive_root),
            ctypes.byref(free), ctypes.byref(total), None)
        if res:
            return int(total.value - free.value), int(free.value), int(total.value)
    except Exception:
        pass
    return 0, 0, 0


def _scan_one(item):
    """算单项：返回 (id, 字节数, 命中的真实路径列表)。"""
    kind = item.get("kind")
    if kind == "recycle":
        total = 0
        hits = []
        for p in item.get("paths", []):
            root = os.path.expandvars(p)
            size = recycle_bin_size(root)
            if size > 0:
                total += size
                hits.append(root)
        return item["id"], total, hits

    if kind == "vss":
        size = vss_size()
        return item["id"], size, ["系统卷影副本"] if size > 0 else []

    if kind == "dism":
        # WinSxS 不能直接删，只报总大小，真正能腾多少得跑完 DISM 才知道
        size = path_size(r"C:\Windows\WinSxS")
        return item["id"], size, [r"C:\Windows\WinSxS"] if size > 0 else []

    hits = resolve_paths(item.get("paths", []))
    total = sum(path_size(p) for p in hits)
    return item["id"], total, hits


def scan_all(items, progress=None, workers=8):
    """
    并发扫描所有项。
    返回 dict: id -> {"size": bytes, "paths": [...], "exists": bool}
    """
    result = {}
    done = 0
    total_items = len(items)

    def _run(it):
        try:
            return _scan_one(it)
        except Exception:
            return it["id"], 0, []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for iid, size, hits in pool.map(_run, items):
            result[iid] = {"size": size, "paths": hits, "exists": bool(hits)}
            done += 1
            if progress:
                try:
                    progress(done, total_items)
                except Exception:
                    pass
    return result
