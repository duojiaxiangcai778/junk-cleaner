# -*- coding: utf-8 -*-
"""
解除文件占用（自动解锁）：删不掉的文件，找出占着它的进程，把句柄关掉再删。

思路来自 IObit Unlocker / Unlocker 这类工具的通行做法：
  1. Restart Manager API 问系统「这个文件被谁占着」，拿到进程 pid（只认文件路径，快且准）
  2. NtQuerySystemInformation(SystemExtendedHandleInformation) 把全系统句柄表拿下来
  3. 只处理占用进程的句柄：DuplicateHandle 到本进程 → GetFinalPathNameByHandleW 取真实路径 → 比对
  4. 命中就 CreateRemoteThread 在占用进程里跑 kernel32!CloseHandle(原句柄)，把占用关掉
  5. 关完重试删除；还删不掉就 MoveFileEx 登记「重启后删除」，不占地方也不报错

为什么必须这么绕：句柄表是进程私有的，用户态没有「关闭别人进程句柄」的 API。
能用的招只有注入 —— kernel32 在 KnownDLLs 里，同一台机器各 64 位进程的基址一致，
所以把本进程 kernel32!CloseHandle 的地址当线程入口丢给对方就能关。
32 位（WOW64）进程的 kernel32 不在同一个地址空间，不硬关，直接退回「重启后删除」。
"""

import os
import time
import struct
import ctypes
import threading
import ctypes.wintypes as wt

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
rstrtmgr = ctypes.WinDLL("rstrtmgr", use_last_error=True)

PROCESS_DUP_HANDLE = 0x0040
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DUPLICATE_SAME_ACCESS = 0x0002
SYSTEM_EXTENDED_HANDLE_INFORMATION = 64
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
ERROR_MORE_DATA = 234
ERROR_SUCCESS = 0

SE_DEBUG_NAME = "SeDebugPrivilege"
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x0002

_adv = ctypes.WinDLL("advapi32", use_last_error=True)

# ---- 原型声明（64 位下不声明会把句柄截断成 int32，这坑踩过就废）----
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.DuplicateHandle.restype = wt.BOOL
kernel32.DuplicateHandle.argtypes = [
    wt.HANDLE, wt.HANDLE, wt.HANDLE,
    ctypes.POINTER(wt.HANDLE), wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.GetCurrentProcess.restype = wt.HANDLE
kernel32.GetFinalPathNameByHandleW.restype = wt.DWORD
kernel32.GetFinalPathNameByHandleW.argtypes = [
    wt.HANDLE, ctypes.c_wchar_p, wt.DWORD, wt.DWORD]
kernel32.CreateRemoteThread.restype = wt.HANDLE
kernel32.CreateRemoteThread.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
    ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.CloseHandle.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.MoveFileExW.restype = wt.BOOL
kernel32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, wt.DWORD]
kernel32.IsWow64Process.restype = wt.BOOL
kernel32.IsWow64Process.argtypes = [wt.HANDLE, ctypes.POINTER(wt.BOOL)]
ntdll.NtQuerySystemInformation.restype = wt.LONG
ntdll.NtQuerySystemInformation.argtypes = [
    ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]


# ---------------- Restart Manager：这个文件被谁占着 ----------------
CCH_RM_MAX_APP_NAME = 255
CCH_RM_MAX_SVC_NAME = 63
RMCCH_RM_SESSION_KEY = 32


class RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [("dwProcessId", wt.DWORD),
                ("ProcessStartTime", wt.FILETIME)]


class RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [("Process", RM_UNIQUE_PROCESS),
                ("strAppName", wt.WCHAR * (CCH_RM_MAX_APP_NAME + 1)),
                ("strServiceShortName", wt.WCHAR * (CCH_RM_MAX_SVC_NAME + 1)),
                ("ApplicationType", wt.DWORD),
                ("AppStatus", wt.ULONG),
                ("TSSessionId", wt.DWORD),
                ("bRestartable", wt.BOOL)]


def _find_lockers(path):
    """问系统：这个文件被哪些进程开着。返回 pid 列表（可能为空）。"""
    session = wt.DWORD(0)
    key = ctypes.create_unicode_buffer(RMCCH_RM_SESSION_KEY + 1)
    rc = rstrtmgr.RmStartSession(ctypes.byref(session), 0, key)
    if rc != ERROR_SUCCESS:
        return []
    try:
        files = (ctypes.c_wchar_p * 1)(path)
        rc = rstrtmgr.RmRegisterResources(session, 1, files, 0, None, 0, None)
        if rc != ERROR_SUCCESS:
            return []
        needed = wt.UINT(0)
        count = wt.UINT(0)
        reasons = wt.DWORD(0)
        rc = rstrtmgr.RmGetList(session, ctypes.byref(needed),
                                ctypes.byref(count), None, ctypes.byref(reasons))
        arr = None
        if rc == ERROR_MORE_DATA and needed.value:
            arr = (RM_PROCESS_INFO * needed.value)()
            count = wt.UINT(needed.value)
            rc = rstrtmgr.RmGetList(session, ctypes.byref(needed),
                                    ctypes.byref(count), arr, ctypes.byref(reasons))
        if rc != ERROR_SUCCESS or arr is None:
            return []
        return [int(arr[i].Process.dwProcessId) for i in range(count.value)]
    except Exception:
        return []
    finally:
        try:
            rstrtmgr.RmEndSession(session)
        except Exception:
            pass


# ---------------- 句柄表 ----------------
def _query_all_handles():
    """返回 [(pid, handle)]。一次全量，后面按 pid 过滤。"""
    size = 1 << 22
    ret = ctypes.c_ulong(0)
    buf = ctypes.create_string_buffer(size)
    for _ in range(6):
        st = ntdll.NtQuerySystemInformation(
            SYSTEM_EXTENDED_HANDLE_INFORMATION, buf, size, ctypes.byref(ret))
        # NTSTATUS 是有符号 LONG，0xC0000004 到这里是负数，必须按 32 位比
        if (st & 0xFFFFFFFF) == STATUS_INFO_LENGTH_MISMATCH:
            size *= 2
            buf = ctypes.create_string_buffer(size)
            continue
        if (st & 0xFFFFFFFF) != 0:
            return []
        break
    else:
        return []

    data = buf.raw[:ret.value]
    if len(data) < 16:
        return []
    count = struct.unpack_from("<Q", data, 0)[0]
    out = []
    off = 16
    # SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX 在 x64 下 40 字节
    for _i in range(count):
        if off + 40 > len(data):
            break
        _obj, pid, handle, _acc, _bt, _ti, _at, _rs = struct.unpack_from(
            "<QQQIHHII", data, off)
        out.append((pid, handle))
        off += 40
    return out


def _enable_debug_privilege():
    """SeDebugPrivilege：管理员下才有，能打开别的用户的进程。"""
    try:
        token = wt.HANDLE()
        if not _adv.OpenProcessToken(kernel32.GetCurrentProcess(),
                                     TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                                     ctypes.byref(token)):
            return False
        try:
            luid = wt.LUID()
            if not _adv.LookupPrivilegeValueW(None, SE_DEBUG_NAME, ctypes.byref(luid)):
                return False
            class _TP(ctypes.Structure):
                _fields_ = [("Count", wt.DWORD), ("Luid", wt.LUID),
                            ("Attributes", wt.DWORD)]
            tp = _TP()
            tp.Count = 1
            tp.Luid = luid
            tp.Attributes = SE_PRIVILEGE_ENABLED
            ok = _adv.AdjustTokenPrivileges(token, False, ctypes.byref(tp),
                                           0, None, None)
            return bool(ok)
        finally:
            kernel32.CloseHandle(token)
    except Exception:
        return False


def _norm(path):
    """\\?\\C:\\xxx 和 C:\\xxx 统一成小写，方便比。"""
    if not path:
        return ""
    p = path
    if p.startswith("\\\\?\\"):
        p = p[4:]
    if p[:4].upper() == "UNC\\":
        p = "\\\\" + p[4:]
    return os.path.normpath(p).lower()


def _is_wow64(hproc):
    try:
        flag = wt.BOOL(0)
        if kernel32.IsWow64Process(hproc, ctypes.byref(flag)):
            return bool(flag.value)
        return False
    except Exception:
        return False


def _close_remote_handle(hproc, handle_value):
    """在目标进程里跑 CloseHandle(句柄)，把占用关掉。"""
    try:
        addr = ctypes.cast(kernel32.CloseHandle, ctypes.c_void_p).value
        if not addr:
            return False
        tid = wt.DWORD(0)
        th = kernel32.CreateRemoteThread(
            hproc, None, 0, ctypes.c_void_p(addr),
            ctypes.c_void_p(handle_value), 0, ctypes.byref(tid))
        if not th:
            return False
        try:
            kernel32.WaitForSingleObject(th, 2000)
        finally:
            kernel32.CloseHandle(th)
        return True
    except Exception:
        return False


def _find_lockers_guarded(path, timeout=1.5):
    """
    带超时的 _find_lockers。
    Restart Manager 对个别路径（比如回收站里被 System 占着的文件）会卡住不返回，
    之前整个清理流程就是被这一句拖死的。超时就当「查不到」，跳过这个文件。
    """
    box = {"pids": [], "done": False}

    def _run():
        try:
            box["pids"] = _find_lockers(path)
        except Exception:
            box["pids"] = []
        box["done"] = True

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout)
    return box["pids"] or []


def schedule_delete(path):
    """登记成「重启后删除」。删不掉的兜底，不占空间也不报错。"""
    try:
        return bool(kernel32.MoveFileExW(
            os.path.abspath(path), None, MOVEFILE_DELAY_UNTIL_REBOOT))
    except Exception:
        return False


def unlock_files(paths, progress=None, max_files=400):
    """
    尝试解除这些文件的占用。
    返回 dict(ok=成功解锁的路径集合, closed=关掉的句柄数, pids=涉及进程数,
              skipped=因是 32 位进程跳过的进程数)。
    """
    targets = set()
    for p in paths or []:
        try:
            if os.path.isfile(p):
                targets.add(_norm(p))
        except Exception:
            pass
    res = dict(ok=set(), closed=0, pids=0, skipped=0)
    if not targets:
        return res

    _enable_debug_privilege()
    files = list(targets)[:max_files]

    # 1) 谁占着这些文件（设总预算，别被 Restart Manager 拖死）
    lockers = set()
    deadline = time.time() + 20
    for i, f in enumerate(files):
        if time.time() > deadline:
            break
        if progress and (i % 10 == 0):
            progress("正在解除占用：定位占用进程 %d / %d" % (i + 1, len(files)))
        for pid in _find_lockers_guarded(f):
            if pid > 4 and pid != os.getpid():
                lockers.add(pid)
    res["pids"] = len(lockers)
    if not lockers:
        return res

    # 2) 全量句柄表，只留这几个进程的
    handles = [(pid, h) for pid, h in _query_all_handles() if pid in lockers]
    if not handles:
        return res

    # 3) 打开进程（WOW64 的跳过，注入不了）
    procs = {}
    for pid in lockers:
        hp = kernel32.OpenProcess(
            PROCESS_DUP_HANDLE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not hp:
            continue
        if _is_wow64(hp):
            res["skipped"] += 1
            kernel32.CloseHandle(hp)
            continue
        procs[pid] = hp

    try:
        cur = kernel32.GetCurrentProcess()
        seen = 0
        for pid, h in handles:
            hp = procs.get(pid)
            if not hp:
                continue
            seen += 1
            if progress and seen % 500 == 0:
                progress("正在解除占用：检查句柄 %d / %d" % (seen, len(handles)))
            # 先复制到本进程，拿到真实路径
            dup = wt.HANDLE()
            if not kernel32.DuplicateHandle(
                    hp, wt.HANDLE(h), cur, ctypes.byref(dup), 0,
                    False, DUPLICATE_SAME_ACCESS):
                continue
            try:
                buf = ctypes.create_unicode_buffer(32768)
                n = kernel32.GetFinalPathNameByHandleW(dup, buf, 32768, 0)
                if not n or n >= 32768:
                    continue
                real = _norm(buf.value)
                if real not in targets:
                    continue
                # 命中：关掉对方进程里那个句柄
                if _close_remote_handle(hp, h):
                    res["ok"].add(real)
                    res["closed"] += 1
            finally:
                kernel32.CloseHandle(dup)
    finally:
        for hp in procs.values():
            kernel32.CloseHandle(hp)
    return res
