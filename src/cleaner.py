# -*- coding: utf-8 -*-
"""
清理模块：真正动刀的地方。

删得掉就删，删不掉先「自动解除占用」再删；还是不行就登记成
「重启后删除」（MoveFileEx MOVEFILE_DELAY_UNTIL_REBOOT），
下一次开机会由系统清掉，不会因为你开着 QQ / 微信就半途而废。
"""

import os
import re
import time
import queue
import ctypes
import datetime
import subprocess
import threading

import guard
import unlocker

CREATE_NO_WINDOW = 0x08000000

LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                       "DiskJunkCleaner", "log")

_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def log(msg):
    """清理动作留痕，出问题能回看删了什么。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, "clean-%s.log" % datetime.date.today().isoformat())
        with open(path, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _is_link(path):
    """目录联接（junction）/ 符号链接：绝不能跟进去删，否则会删到别的盘去。"""
    try:
        if os.path.islink(path):
            return True
        attr = os.stat(path, follow_symlinks=False).st_file_attributes
        return bool(attr & 0x400)
    except (OSError, AttributeError):
        return False


def _rm_tree(path, fails=None, progress=None, check_root=True):
    """
    删除整个目录，返回 (释放字节, 失败个数, 受保护跳过个数)。
    失败路径会追加进 fails。

    v2.3.2 性能 & 安全修正（三个方面）：
      1) topdown=True + dirs 过滤：遇到受保护目录（node_modules / .dsh / .zcode …）
         **直接不下钻**。旧写法用 topdown=False，是先钻进子目录把文件删光、
         等到回头处理这个目录本身才发现它该受保护 —— 等于保护晚了一步，
         里面的东西早没了。这是 v2.3.0 留下的真漏洞。
      2) 逐文件不再调 guard：旧版每个文件都跑一次 os.path.abspath + 字符串匹配，
         几万个文件纯属白烧 CPU。受保护判断只做在**目录**上（纯字符串，零 stat）。
      3) check_root=False：入口已经判过 is_protected_root 的，别在这里再查一遍
         —— 那要 5 次 os.path.exists/目录，Temp 下几千个子目录就是上万次 stat。

    progress 每 500 个文件回调一次，界面能看到它在动，不再像死机。
    """
    if check_root:
        blocked, why = guard.is_protected_root(path)
        if blocked:
            log("跳过受保护目录 %s（%s）" % (path, why))
            return 0, 0, 1

    freed = 0
    failed = 0
    skipped = 0
    seen = 0
    all_dirs = []          # [(root, [保留下来的子目录名])]，用于最后逆序删空目录

    for root, dirs, files in os.walk(path, topdown=True):
        keep = []
        for d in dirs:
            dp = os.path.join(root, d)
            if _is_link(dp):
                skipped += 1
                continue
            hit, why = guard.is_protected(dp)
            if hit:
                skipped += 1
                log("跳过受保护子目录 %s（%s）" % (dp, why))
                continue
            keep.append(d)
        dirs[:] = keep          # ← 关键：受保护目录不下钻
        all_dirs.append((root, keep))

        for name in files:
            fp = os.path.join(root, name)
            seen += 1
            try:
                size = os.path.getsize(fp)
                os.remove(fp)
                freed += size
            except (OSError, PermissionError):
                failed += 1
                if fails is not None:
                    fails.append(fp)
            if progress is not None and seen % 500 == 0:
                _say(progress, "正在删除… 已处理 %d 个文件" % seen)

    # 逆序遍历就是「子目录先进、父目录后进」，一路 rmdir 收干净
    for root, keep in reversed(all_dirs):
        for d in keep:
            try:
                os.rmdir(os.path.join(root, d))
            except (OSError, PermissionError):
                pass
    try:
        os.rmdir(path)
    except (OSError, PermissionError):
        pass
    return freed, failed, skipped


def _empty_dir(path, fails=None, progress=None):
    """
    清空目录内容，保留目录本身（Temp 这类目录系统还要用）。
    返回 (释放字节, 失败个数, 受保护跳过个数)。v2.3.0 起过 guard。

    v2.3.2：子目录交给 _rm_tree 时带 check_root=False —— 上面第 139 行已经用
    纯字符串匹配判过这个名字了，不用再对着每个子目录做 5 次 os.path.exists。
    """
    freed = 0
    failed = 0
    skipped = 0
    try:
        entries = list(os.scandir(path))
    except (OSError, PermissionError):
        return 0, 1, 0
    for entry in entries:
        try:
            if guard.is_protected(entry.path)[0]:
                skipped += 1
                continue
            if entry.is_dir(follow_symlinks=False):
                if _is_link(entry.path):
                    # 联接目录只断链，不进去删内容
                    continue
                f, fl, sk = _rm_tree(entry.path, fails, progress, check_root=False)
                freed += f
                failed += fl
                skipped += sk
            else:
                size = entry.stat(follow_symlinks=False).st_size
                try:
                    os.remove(entry.path)
                    freed += size
                except (OSError, PermissionError):
                    failed += 1
                    if fails is not None:
                        fails.append(entry.path)
        except (OSError, PermissionError):
            failed += 1
    return freed, failed, skipped


def empty_recycle_bin(drive_root):
    """
    清空指定盘回收站。
    先走 Shell（规范路径），再补一刀直接删 $Recycle.Bin —— Shell 只能清当前用户，
    其它 SID 的回收站（本机实测 E 盘 16 GB 就是这么剩下来的）得管理员直删。
    """
    SHERB_NOCONFIRMATION = 0x1
    SHERB_NOPROGRESSUI = 0x2
    SHERB_NOSOUND = 0x4
    flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    ok = False
    try:
        ok = ctypes.windll.shell32.SHEmptyRecycleBinW(
            None, ctypes.c_wchar_p(drive_root), flags
        ) == 0
    except Exception:
        ok = False

    cleaned = 0
    rb = os.path.join(os.path.abspath(drive_root), "$Recycle.Bin")
    if os.path.isdir(rb):
        fails = []
        try:
            entries = list(os.scandir(rb))
        except OSError:
            entries = []
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    _f, _fl, _sk = _rm_tree(entry.path, fails)
                    cleaned += _f
                else:
                    size = entry.stat(follow_symlinks=False).st_size
                    os.remove(entry.path)
                    cleaned += size
            except (OSError, PermissionError):
                pass
        if fails:
            log("回收站里有 %d 个文件删不掉（被占用）" % len(fails))
    return ok or cleaned > 0


def clear_shadow_copies():
    """删除系统还原点（卷影副本）。需要管理员权限。"""
    try:
        out = subprocess.run(
            ["vssadmin", "delete", "shadows", "/for=C:", "/all", "/quiet"],
            capture_output=True, text=True, timeout=180,
            creationflags=CREATE_NO_WINDOW,
        )
        return out.returncode == 0
    except Exception:
        return False


def _free_bytes(drive):
    try:
        from ctypes import c_ulonglong, c_wchar_p, byref
        free = c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            c_wchar_p(drive), byref(free), None, None)
        return free.value
    except Exception:
        return 0


def _say(progress, text):
    if progress:
        try:
            progress(text)
        except Exception:
            pass


# 单项清理的整体超时：有的目录会卡在系统调用里（删除时 IO 挂住、
# 注入/重启管理器等系统 API 不返回），不设上限整个软件就跟着一起卡。
ITEM_TIMEOUT = 600
UNLOCK_TIMEOUT = 90

# 单项内部超时（DISM 本来就要跑很久，单独放）
_ITEM_TIMEOUTS = {"dism": 1800}


def dism_component_cleanup(progress=None, cancel=None, idle_timeout=300,
                           hard_timeout=3600):
    """
    跑 DISM 组件清理，删掉 WinSxS 里被取代且已过回滚期的旧组件。
    返回 (释放字节, 成功?, 说明)。

    和 v2.1.0 的区别：
      - 实时读 DISM 输出，把百分比喂给界面，不再是「一行字卡到天荒地老」
      - 支持取消（cancel 是 threading.Event）
      - 超过 idle_timeout 秒没有任何输出就判定卡死并终止 —— Windows 的
        CBS/TiWorker 偶尔会真的卡在 boot-recovery 压缩那一步，界面得知道
    """
    before = _free_bytes("C:\\")
    cmd = ["dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW, bufsize=0)
    except Exception as e:
        return 0, False, "调用 DISM 失败：%s" % e

    q = queue.Queue()

    def _reader():
        try:
            for line in iter(proc.stdout.readline, b""):
                q.put(line)
        except Exception:
            pass
        finally:
            q.put(None)

    threading.Thread(target=_reader, daemon=True).start()

    lines = []
    cancelled = False
    stuck = False
    last = time.time()
    started = time.time()
    while True:
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        try:
            chunk = q.get(timeout=0.5)
        except queue.Empty:
            chunk = b"__EMPTY__"
        if chunk is None:
            break
        if chunk != b"__EMPTY__":
            last = time.time()
            text = chunk.decode("mbcs", "replace").strip()
            if text:
                lines.append(text)
                if len(lines) > 300:
                    del lines[:-300]
                m = _PCT_RE.search(text)
                if m:
                    _say(progress, "WinSxS 组件清理中（DISM）%s%%" % m.group(1))
                elif text.startswith("[") or "%" in text:
                    _say(progress, "WinSxS 组件清理中（DISM）…")
            continue
        # 没输出：看是不是卡住了
        if time.time() - last > idle_timeout:
            stuck = True
            break
        if time.time() - started > hard_timeout:
            stuck = True
            break

    if cancelled or stuck:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=15)
    except Exception:
        pass

    after = _free_bytes("C:\\")
    freed = max(0, after - before)
    if cancelled:
        return (freed, False,
                "已取消。DISM 跑到一半停下，已经清理掉的部分仍然有效。")
    if stuck:
        return (freed, False,
                "DISM 连续 %d 秒没有任何输出，判定卡住并终止了。"
                "Windows 的组件服务偶尔会卡在 boot-recovery 压缩这一步，"
                "重启一次再点这项通常就过去了。" % idle_timeout)

    txt = "\n".join(lines)
    if proc.returncode != 0:
        hint = ("需要管理员权限" if ("elevat" in txt.lower() or "错误 5" in txt
                                   or "Error 5" in txt) else txt[-300:])
        return freed, False, "DISM 返回 %s：%s" % (proc.returncode, hint)
    return freed, True, "组件清理完成"


def _prune_empty(root):
    """解锁重试后常常剩一堆空壳目录，顺手收掉（保留 root 本身）。"""
    try:
        for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
            if os.path.normpath(dirpath) == os.path.normpath(root):
                continue
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
            except OSError:
                pass
    except OSError:
        pass


def _retry_after_unlock(fails, progress=None):
    """
    对删不掉的文件：自动解除占用 → 重试删除 → 还不行就登记重启后删除。
    返回 (释放字节, 仍然失败的个数, 登记重启删除的个数)。
    """
    uniq = []
    seen = set()
    for fp in fails:
        if fp in seen:
            continue
        if guard.is_protected(fp)[0]:
            # 最后一道保险：受保护的文件绝不登记「重启后删除」
            continue
        seen.add(fp)
        uniq.append(fp)
    if not uniq:
        return 0, 0, 0

    _say(progress, "有 %d 个文件被占用，正在自动解除占用…" % len(uniq))
    # 解锁要防卡：Restart Manager / 远程线程注入在个别进程上会不返回，
    # 单独开线程跑，超时就放弃解锁、直接走「重启后删除」
    box = {}

    def _do_unlock():
        try:
            box["r"] = unlocker.unlock_files(
                uniq, progress=lambda t: _say(progress, t))
        except Exception as e:
            log("解除占用出错：%s" % e)

    th = threading.Thread(target=_do_unlock, daemon=True)
    th.start()
    th.join(UNLOCK_TIMEOUT)
    if th.is_alive():
        log("解除占用超时（%d 个文件），改走重启后删除" % len(uniq))
        _say(progress, "解除占用超时，改走「下次开机自动删除」")

    freed = 0
    still = []
    for fp in uniq:
        try:
            size = os.path.getsize(fp)
            os.remove(fp)
            freed += size
        except (OSError, PermissionError):
            still.append(fp)

    scheduled = 0
    for fp in still:
        if unlocker.schedule_delete(fp):
            scheduled += 1
    return freed, len(still), scheduled


def clean_item(item, scan_info, force=True, progress=None, cancel=None):
    """
    带超时的入口：真卡死就放弃这一项，别把整个软件拖死。
    （2026-11-03 现场：清理 C:\\Windows\\Temp / 缩略图时某个系统调用不返回，
      老版本就永远停在「正在清理」那一行。）
    """
    timeout = _ITEM_TIMEOUTS.get(item.get("kind"), ITEM_TIMEOUT)
    box = {}

    def _run():
        try:
            box["r"] = _clean_item_inner(item, scan_info, force, progress, cancel)
        except Exception as e:
            box["r"] = dict(id=item.get("id"), name=item.get("name"), freed=0,
                            failed=1, ok=False, note=str(e), scheduled=0)

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        log("清理「%s」超过 %d 秒没完成，跳过" % (item.get("name"), timeout))
        return dict(id=item.get("id"), name=item.get("name", ""), freed=0,
                    failed=1, ok=False,
                    note="清理超时（%d 分钟没跑完，多半卡在系统调用上）。"
                         "这项先跳过，重启后再试一次" % max(1, timeout // 60),
                    scheduled=0)
    return box.get("r") or dict(id=item.get("id"), name=item.get("name", ""),
                                freed=0, failed=1, ok=False,
                                note="未知错误", scheduled=0)


def _clean_item_inner(item, scan_info, force=True, progress=None, cancel=None):
    """
    清理单项。
    force=True 时对删不掉的文件自动解除占用、重试、最后登记重启删除。
    返回 dict: {"id","name","freed","failed","ok","note","scheduled"}
    """
    iid = item["id"]
    kind = item.get("kind")
    name = item.get("name", iid)
    freed = 0
    failed = 0
    ok = True
    note = ""
    scheduled = 0

    hits = (scan_info or {}).get("paths") or []

    if kind == "recycle":
        for root in item.get("paths", []):
            root = os.path.expandvars(root)
            if empty_recycle_bin(root):
                freed += (scan_info or {}).get("size", 0)
                log("清空回收站 %s" % root)
            else:
                ok = False
                note = "回收站清空失败（可能已被部分清空）"
        return dict(id=iid, name=name, freed=freed, failed=failed,
                    ok=ok, note=note, scheduled=scheduled, skipped=0)

    if kind == "vss":
        if clear_shadow_copies():
            freed = (scan_info or {}).get("size", 0)
            log("删除系统还原点，释放 %d 字节" % freed)
        else:
            ok = False
            note = "删除还原点失败：需要管理员权限，或系统保护被组策略锁定"
        return dict(id=iid, name=name, freed=freed, failed=failed,
                    ok=ok, note=note, scheduled=scheduled, skipped=0)

    if kind == "dism":
        freed, ok, note = dism_component_cleanup(progress=progress, cancel=cancel)
        log("DISM 组件清理 -> 释放 %d 字节，%s" % (freed, note))
        return dict(id=iid, name=name, freed=freed, failed=failed,
                    ok=ok, note=note, scheduled=scheduled, skipped=0)

    fails = []
    skipped = 0
    for p in hits:
        if cancel is not None and cancel.is_set():
            note = "已取消"
            ok = False
            break
        hit, why = guard.is_protected_root(p)
        if hit:
            skipped += 1
            log("跳过受保护路径 %s（%s）" % (p, why))
            note = "已跳过受保护的东西：%s" % why
            continue
        try:
            if os.path.isdir(p):
                f, fl, sk = _empty_dir(p, fails, progress)
                skipped += sk
            elif os.path.isfile(p):
                size = os.path.getsize(p)
                os.remove(p)
                f, fl = size, 0
            else:
                f, fl = 0, 0
            freed += f
            failed += fl
            log("清理 %s -> 释放 %d 字节，失败 %d 个，保护跳过 %d 个" % (p, f, fl, skipped))
        except (OSError, PermissionError) as e:
            failed += 1
            note = str(e)

    if fails and force:
        extra, still, sched = _retry_after_unlock(fails, progress)
        freed += extra
        scheduled += sched
        # 失败数按「重试后仍然失败」重算，比第一次的粗数更准
        failed = max(0, failed - len(fails)) + still
        if sched:
            note = "有 %d 个文件仍被占用，已登记为重启后自动删除" % sched
        if not still:
            note = ""
        # 文件删掉后常剩空目录，再收一遍
        for p in hits:
            try:
                if os.path.isdir(p):
                    _prune_empty(p)
            except OSError:
                pass

    if failed and not freed:
        ok = False
        if not note:
            note = "文件被占用或权限不足，全部跳过"

    return dict(id=iid, name=name, freed=freed, failed=failed,
                ok=ok, note=note, scheduled=scheduled, skipped=skipped)
