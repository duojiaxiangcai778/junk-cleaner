# -*- coding: utf-8 -*-
"""
chatdata.py —— 聊天记录（QQ / 微信）数据体积细分

QQ NT 版结构：
  <Tencent Files>/<账号>/nt_qq/
    nt_data/Pic/<YYYY-MM>/{Ori,Thumb,ThumbTemp,OriTemp}
    nt_data/Video/<YYYY-MM>/{Ori,Thumb}
    nt_data/Ptt/<YYYY-MM>/
    nt_data/File/{file_assistant,Thumb,ThumbTemp}
    nt_data/Emoji/{emoji-recv/<YYYY-MM>, personal_emoji/{Ori,Thumb},
                   marketface/<id>, BaseEmojiSyastems/{EmojiSystermResource,ThumbTemp}}
    nt_data/log/*.qqxlog
    nt_db/            聊天记录数据库
    nt_temp/          临时文件

微信 4.x 结构：
  <xwechat_files>/<wxid>/
    cache/ temp/            缓存、临时
    msg/attach/<hash>/      图片/文件附件
    msg/video/ msg/file/ msg/migrate/
    db_storage/             聊天记录数据库
    config/ resource/ business/ apm_record/

设计：不写死盘符，自动把全盘里名叫 Tencent Files / xwechat_files /
WeChat Files 的目录挖出来，再按「类别 + 月份」拆行。每行互不重叠，可独立勾选。
"""

import os
import re

from deepscan import _sub_size, _iter_root

MB = 1024 * 1024
GB = 1024 * MB

MONTH_RE = re.compile(r"^\d{4}[-_]\d{2}$")

# 这些目录里绝不会有聊天记录，扫进去纯浪费时间（WinSxS 光一层就十几万条）
SKIP_NAMES = {
    "node_modules", ".git", "$recycle.bin", "system volume information",
    "windows", "winsxs", "program files", "program files (x86)", "programdata",
    "recovery", "msocache", "windows.old", "system32", "syswow64",
    "__pycache__", ".venv", "venv", "site-packages", "conda-meta",
    "appdata", "perflogs", "config.msi", "intel", "amd", "nvidia",
}


# ---------------------------------------------------------------- 探测

def _drive_roots():
    """只认本地固定盘（DRIVE_FIXED），跳过光驱、U 盘、网络盘——那些扫进去会卡死。"""
    out = []
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        DRIVE_FIXED = 3
        mask = k32.GetLogicalDrives()
        for i, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            if not (mask >> i) & 1:
                continue
            p = letter + ":\\"
            if k32.GetDriveTypeW(ctypes.c_wchar_p(p)) == DRIVE_FIXED:
                out.append(p)
    except Exception:
        for letter in "CDEFGHIJKL":
            p = letter + ":\\"
            try:
                if os.path.isdir(p):
                    out.append(p)
            except OSError:
                continue
    return out


def _discover():
    """
    一趟 BFS 把 QQ / 微信 的数据根全挖出来。
    返回 (qq_roots, wx_roots)，元素分别是 [(账号, nt_qq 路径)] / [(wxid, 目录)]。
    """
    want = {
        "tencent files": "qq",
        "xwechat_files": "wx",
        "wechat files": "wx",
    }
    bases = {"qq": [], "wx": []}
    seen = set()

    for root in _drive_roots():
        if not os.path.isdir(root):
            continue
        queue = [(root, 0)]
        while queue:
            cur, depth = queue.pop(0)
            if depth > 3:
                continue
            try:
                entries = _iter_root(cur)
            except OSError:
                continue
            for e in entries:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                low = e.name.lower()
                if low in SKIP_NAMES:
                    continue
                if low in want:
                    key = os.path.normcase(os.path.abspath(e.path))
                    if key not in seen:
                        seen.add(key)
                        bases[want[low]].append(e.path)
                    continue
                if depth + 1 <= 3:
                    queue.append((e.path, depth + 1))

    qq_roots = []
    for base in bases["qq"]:
        for e in _iter_root(base):
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            ntqq = os.path.join(e.path, "nt_qq")
            if os.path.isdir(ntqq):
                qq_roots.append((e.name, ntqq))
        # 没绑账号的全局数据：Tencent Files\nt_qq\global（旧版遗留 / 公共缓存）
        g = os.path.join(base, "nt_qq", "global")
        if os.path.isdir(os.path.join(g, "nt_data")):
            qq_roots.append(("global", g))

    wx_roots = []
    for base in bases["wx"]:
        for e in _iter_root(base):
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if e.name.lower() in ("all_users", "backup", "applet"):
                continue
            wx_roots.append((e.name, e.path))

    return qq_roots, wx_roots


def find_qq_roots():
    return _discover()[0]


def find_wechat_roots():
    return _discover()[1]


# ---------------------------------------------------------------- 行构造

def _row(rid, name, category, level, paths, desc, kind="dir"):
    return dict(id=rid, name=name, category=category, level=level,
                kind=kind, paths=list(paths), desc=desc)


# 类别显示顺序：先看最占地方的图片视频，最后才是数据库
CAT_ORDER = {
    "QQ·图片": 0, "QQ·视频": 1, "QQ·表情": 2, "QQ·语音": 3, "QQ·文件": 4,
    "QQ·临时": 5, "QQ·日志": 6, "QQ·其他": 7, "QQ·散落": 8, "QQ·数据库": 9,
    "微信·附件": 10, "微信·视频": 11, "微信·文件": 12, "微信·缓存": 13,
    "微信·临时": 14, "微信·日志": 15, "微信·其他": 16, "微信·数据库": 19,
}


def _months(parent):
    """列出 parent 下的 YYYY-MM 子目录，返回 [(月, 路径)]，按月份倒序。"""
    out = []
    for e in _iter_root(parent):
        try:
            if not e.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if MONTH_RE.match(e.name):
            out.append((e.name, e.path))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def _month_dirs(parent, depth=2):
    """
    在 parent 下找所有 YYYY-MM 目录，最多往下钻 depth 层。
    微信 4.x 的 msg/attach 是 <hash>/<YYYY-MM>/ 两层，
    直接列 parent 只能看到哈希名，所以这里要钻一层再找月份。
    返回 [(月, 路径)]；同名月份的多个哈希目录会各算一行（路径不同）。
    """
    out = []
    queue = [(parent, 1)]
    while queue:
        cur, lv = queue.pop(0)
        for e in _iter_root(cur):
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if MONTH_RE.match(e.name):
                out.append((e.name, e.path))
            elif lv < depth:
                queue.append((e.path, lv + 1))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


# ---------------------------------------------------------------- QQ

QQ_DESC = {
    "pic_ori": "聊天里发的图片原图。删了以后翻聊天记录，图片就显示不出来了"
               "（缩略图还在，但点开原图是空的）。",
    "pic_thumb": "图片缩略图。就是聊天窗口里预览用的小图，删了聊天记录里图片变灰，"
                 "但有原图的话点开还能看。这个是纯缓存，可安全清。",
    "vid_ori": "视频原片。删了聊天记录里的视频就没了。",
    "vid_thumb": "视频首帧缩略图。纯缓存，可安全清。",
    "ptt": "语音消息文件。删了语音就听不了了。",
    "emoji": "表情包缓存。删了表情包要重新加载，聊天记录里还能点开重下。",
    "file": "聊天里收发的文件、群文件。删了就真没了，先确认。",
    "log": "QQ 运行日志，纯垃圾。",
    "temp": "QQ 临时文件（收发文件时的中转），纯垃圾。",
    "db": "聊天记录数据库本体（文字消息、好友列表都在这）。删了聊天记录全没，不动。",
}


def _qq_rows(account, ntqq):
    rows = []
    ntd = os.path.join(ntqq, "nt_data")
    tag = "QQ" if account == "global" else "QQ " + account

    # ---- 图片：按月份 + 原图/缩略图
    pic = os.path.join(ntd, "Pic")
    for month, mdir in _months(pic):
        for sub, key, level in (("Thumb", "pic_thumb", "safe"),
                                ("Ori", "pic_ori", "caution")):
            p = os.path.join(mdir, sub)
            if os.path.isdir(p) and _sub_size(p) > 0:
                rows.append(_row(
                    "qq:pic:%s:%s:%s" % (account, key, month),
                    "%s 图片%s · %s" % (tag, "缩略图" if sub == "Thumb" else "原图", month),
                    "QQ·图片", level, [p], QQ_DESC[key]))
        # 临时残留
        for sub in ("ThumbTemp", "OriTemp"):
            p = os.path.join(mdir, sub)
            if os.path.isdir(p) and _sub_size(p) > 0:
                rows.append(_row(
                    "qq:pic:%s:tmp:%s:%s" % (account, sub, month),
                    "%s 图片临时残留 · %s" % (tag, month),
                    "QQ·临时", "safe", [p], "图片加载过程中的临时缩略图，纯垃圾。"))

    # ---- 视频
    vid = os.path.join(ntd, "Video")
    for month, mdir in _months(vid):
        for sub, key, level in (("Thumb", "vid_thumb", "safe"),
                                ("Ori", "vid_ori", "caution")):
            p = os.path.join(mdir, sub)
            if os.path.isdir(p) and _sub_size(p) > 0:
                rows.append(_row(
                    "qq:vid:%s:%s:%s" % (account, key, month),
                    "%s 视频%s · %s" % (tag, "缩略图" if sub == "Thumb" else "原片", month),
                    "QQ·视频", level, [p], QQ_DESC[key]))

    # ---- 语音
    ptt = os.path.join(ntd, "Ptt")
    for month, mdir in _months(ptt):
        if _sub_size(mdir) > 0:
            rows.append(_row("qq:ptt:%s:%s" % (account, month),
                             "%s 语音 · %s" % (tag, month),
                             "QQ·语音", "caution", [mdir], QQ_DESC["ptt"]))

    # ---- 表情
    emoji = os.path.join(ntd, "Emoji")
    recv = os.path.join(emoji, "emoji-recv")
    for month, mdir in _months(recv):
        if _sub_size(mdir) > 0:
            rows.append(_row("qq:emoji:%s:%s" % (account, month),
                             "%s 收到的表情包 · %s" % (tag, month),
                             "QQ·表情", "safe", [mdir], QQ_DESC["emoji"]))
    pp = os.path.join(emoji, "personal_emoji")
    for sub in ("Ori", "Thumb"):
        p = os.path.join(pp, sub)
        if os.path.isdir(p) and _sub_size(p) > 0:
            rows.append(_row("qq:emoji:%s:personal:%s" % (account, sub),
                             "%s 个人收藏表情%s" % (tag, "原图" if sub == "Ori" else "缩略图"),
                             "QQ·表情", "safe" if sub == "Thumb" else "caution",
                             [p], "自己收藏/存的表情包文件。"))
    mf = os.path.join(emoji, "marketface")
    if os.path.isdir(mf) and _sub_size(mf) > 0:
        rows.append(_row("qq:emoji:%s:marketface" % account,
                         "%s 商城表情缓存" % tag,
                         "QQ·表情", "safe", [mf],
                         "商城表情的下载缓存，删了下次用到会重新下。"))
    sysres = os.path.join(emoji, "BaseEmojiSyastems", "EmojiSystermResource")
    if os.path.isdir(sysres) and _sub_size(sysres) > 0:
        rows.append(_row("qq:emoji:%s:system" % account,
                         "%s 系统表情资源" % tag,
                         "QQ·表情", "safe", [sysres],
                         "QQ 自带小黄脸的资源缓存，删了会自动重建。"))

    # ---- 文件
    fdir = os.path.join(ntd, "File")
    fa = os.path.join(fdir, "file_assistant")
    if os.path.isdir(fa) and _sub_size(fa) > 0:
        rows.append(_row("qq:file:%s:assistant" % account,
                         "%s 收到的文件（含群文件）" % tag,
                         "QQ·文件", "caution", [fa], QQ_DESC["file"]))
    for sub in ("Thumb", "ThumbTemp"):
        p = os.path.join(fdir, sub)
        if os.path.isdir(p) and _sub_size(p) > 0:
            rows.append(_row("qq:file:%s:%s" % (account, sub),
                             "%s 文件缩略图%s" % (tag, "临时" if "Temp" in sub else ""),
                             "QQ·临时", "safe", [p], QQ_DESC["file"]))

    # ---- 其他单项
    for sub, key, cat, level in (
        ("dataline", "dataline", "QQ·文件", "caution"),
        ("avatar", "avatar", "QQ·临时", "safe"),
    ):
        p = os.path.join(ntd, sub)
        if os.path.isdir(p) and _sub_size(p) > 0:
            rows.append(_row("qq:%s:%s" % (key, account),
                             "%s %s" % (tag, "手机传电脑的文件" if key == "dataline" else "头像缓存"),
                             cat, level, [p],
                             "手机和电脑互传的文件。" if key == "dataline" else "好友头像缓存，会自动重建。"))

    log = os.path.join(ntd, "log")
    if os.path.isdir(log) and _sub_size(log) > 0:
        rows.append(_row("qq:log:%s" % account, "%s 运行日志" % tag,
                         "QQ·日志", "safe", [log], QQ_DESC["log"]))
    temp = os.path.join(ntqq, "nt_temp")
    if os.path.isdir(temp) and _sub_size(temp) > 0:
        rows.append(_row("qq:temp:%s" % account, "%s 临时文件" % tag,
                         "QQ·临时", "safe", [temp], QQ_DESC["temp"]))
    db = os.path.join(ntqq, "nt_db")
    if os.path.isdir(db) and _sub_size(db) > 0:
        rows.append(_row("qq:db:%s" % account, "%s 聊天记录数据库" % tag,
                         "QQ·数据库", "view", [db], QQ_DESC["db"]))
    return rows


# ---------------------------------------------------------------- 微信

WX_DESC = {
    "cache": "微信缓存（图片、视频、浏览过的内容缓存），可安全清，清完会自动重建。",
    "temp": "微信临时文件，纯垃圾。",
    "attach": "聊天里的图片、文件附件。删了翻聊天记录就看不到图了。",
    "video": "聊天里的视频文件。删了聊天记录里的视频就没了。",
    "file": "聊天里收的文件。删了就真没了。",
    "db": "聊天记录数据库（消息文本、通讯录）。删了聊天记录全没，不动。",
    "resource": "内置资源（emoji、字体等），一般不用动。",
}


def _wx_rows(wxid, wdir):
    rows = []
    tag = "微信 " + (wxid if len(wxid) <= 24 else wxid[:20] + "…")

    for sub, cat, level, desc in (
        ("cache", "微信·缓存", "safe", WX_DESC["cache"]),
        ("temp", "微信·临时", "safe", WX_DESC["temp"]),
    ):
        p = os.path.join(wdir, sub)
        if os.path.isdir(p) and _sub_size(p) > 0:
            rows.append(_row("wx:%s:%s" % (wxid, sub), "%s %s" % (tag, "缓存" if sub == "cache" else "临时文件"),
                             cat, level, [p], desc))

    msg = os.path.join(wdir, "msg")
    # 附件：微信 4.x 是 attach/<hash>/<YYYY-MM>/，钻一层找月份后按月份合并
    attach = os.path.join(msg, "attach")
    if os.path.isdir(attach) and _sub_size(attach) > 0:
        months = _month_dirs(attach, depth=2)
        if months:
            by_month = {}
            for month, mdir in months:
                by_month.setdefault(month, []).append(mdir)
            for month in sorted(by_month, reverse=True):
                dirs = by_month[month]
                sz = sum(_sub_size(d) for d in dirs)
                if sz <= 0:
                    continue
                rows.append(_row("wx:%s:attach:%s" % (wxid, month),
                                 "%s 图片附件 · %s" % (tag, month),
                                 "微信·附件", "caution", dirs, WX_DESC["attach"]))
        else:
            rows.append(_row("wx:%s:attach" % wxid, "%s 图片附件" % tag,
                             "微信·附件", "caution", [attach], WX_DESC["attach"]))
    for sub, cat, desc in (("video", "微信·视频", WX_DESC["video"]),
                           ("file", "微信·文件", WX_DESC["file"])):
        p = os.path.join(msg, sub)
        if os.path.isdir(p) and _sub_size(p) > 0:
            rows.append(_row("wx:%s:%s" % (wxid, sub),
                             "%s %s" % (tag, "视频" if sub == "video" else "文件"),
                             cat, "caution", [p], desc))

    for sub, cat, level, desc in (
        ("db_storage", "微信·数据库", "view", WX_DESC["db"]),
        ("resource", "微信·其他", "view", WX_DESC["resource"]),
        ("business", "微信·其他", "view", "小程序等业务数据。"),
        ("apm_record", "微信·日志", "safe", "微信性能埋点记录，纯日志。"),
    ):
        p = os.path.join(wdir, sub)
        if os.path.isdir(p) and _sub_size(p) > 0:
            rows.append(_row("wx:%s:%s" % (wxid, sub), "%s %s" % (
                tag, {"db_storage": "聊天记录数据库", "resource": "内置资源",
                      "business": "小程序数据", "apm_record": "日志"}[sub]),
                cat, level, [p], desc))
    return rows


# ---------------------------------------------------------------- 对外

def scan():
    """
    返回 (rows, info)。
    rows  : 每个元素一个可独立勾选的清理行
    info  : {qq: [(账号, 大小)], wx: [(wxid, 大小)], programs: [(名字, 大小)]}
    """
    rows = []
    info = {"qq": [], "wx": [], "programs": []}

    for account, ntqq in find_qq_roots():
        sz = _sub_size(ntqq)
        if sz <= 0:
            continue
        info["qq"].append((account, sz))
        rows.extend(_qq_rows(account, ntqq))

    for wxid, wdir in find_wechat_roots():
        sz = _sub_size(wdir)
        if sz <= 0:
            continue
        info["wx"].append((wxid, sz))
        rows.extend(_wx_rows(wxid, wdir))

    # QQ 接收文件夹根下散落的文件（不在 Tencent Files 里，但也占 QQ 数据的账）
    rows.extend(loose_files())

    # 程序自身安装目录（不是数据，但是用户会关心「QQ 才几百兆」）
    for name, paths in (
        ("QQ 程序", []),
        ("微信程序", []),
    ):
        pass

    rows = [r for r in rows if _row_size(r) > 0]
    rows.sort(key=lambda r: (CAT_ORDER.get(r["category"], 50),
                             r["category"], -r["size"]))
    return rows, info


def _row_size(row):
    if "size" in row and row["size"] is not None:
        return row["size"]
    total = 0
    for p in row["paths"]:
        try:
            if os.path.isfile(p):
                # 单独的文件（比如 QQ 接收目录根下散落的视频）不能拿 _sub_size 算，
                # 对文件 scandir 会直接抛 NotADirectoryError 返回 0
                total += os.path.getsize(p)
                continue
        except OSError:
            continue
        total += _sub_size(p)
    row["size"] = total
    return total


# ---------------------------------------------------------------- 快速清理页用
#
# 聊天记录页签是「按月份拆开、逐项勾」，适合精挑细选；
# 但用户打开软件第一眼看的是快速清理页，那里必须能直接勾着一把清掉。
# 所以在快速清理页给 QQ / 微信各出三条聚合项：缓存（可清）/ 聊天内容（需确认）/ 数据库（不动）。

def fmt(n):
    n = float(n or 0)
    if n >= 1024 ** 3:
        return "%.2f GB" % (n / 1024 ** 3)
    if n >= 1024 ** 2:
        return "%.1f MB" % (n / 1024 ** 2)
    if n >= 1024:
        return "%.0f KB" % (n / 1024)
    return "%d B" % n


def _cat_brief(rows, limit=8):
    """按类别把一堆行汇总成「图片缩略图 9.4 GB、表情 2.5 GB」这种一行话。"""
    agg = {}
    for r in rows:
        agg[r["category"]] = agg.get(r["category"], 0) + r["size"]
    if not agg:
        return "—"
    parts = []
    for cat, sz in sorted(agg.items(), key=lambda x: -x[1]):
        short = cat.split("·")[-1] if "·" in cat else cat
        parts.append("%s %s" % (short, fmt(sz)))
    return "、".join(parts[:limit])


QUICK_DEFS = {
    ("qq", "safe"): dict(
        name="QQ 缓存（缩略图 / 表情 / 日志 / 临时）",
        category="聊天软件 · QQ",
        note="QQ 自己生成的缓存：图片缩略图、视频缩略图、表情包、运行日志、临时文件、"
             "头像缓存。删了 QQ 下次用到会自己重新下载/重建，聊天文字、原图、视频、"
             "文件一个都不动。\n"
             "缩略图删掉后，聊天记录里的图片第一次翻的时候会重新加载一下（点开还是原图）；"
             "清理前最好先退出 QQ，正在被占用的图会被自动跳过（不报错、不卡住）。",
    ),
    ("qq", "caution"): dict(
        name="QQ 聊天内容（原图 / 视频 / 语音 / 文件）",
        category="聊天软件 · QQ",
        note="聊天里实际收发的图片原图、视频原片、语音、文件。删了之后翻聊天记录，"
             "对应的图/视频/文件就点不开了（聊天文字还在）。\n"
             "这项默认不勾，想腾空间再自己勾；想按月份挑着删，去「聊天记录」页签。",
    ),
    ("qq", "view"): dict(
        name="QQ 聊天记录数据库",
        category="聊天软件 · QQ",
        note="聊天的文字记录、好友列表本体，删了聊天记录就全没了。只显示大小，不参与清理。",
    ),
    ("wx", "safe"): dict(
        name="微信 缓存（图片缓存 / 临时 / 日志）",
        category="聊天软件 · 微信",
        note="微信的图片/视频缓存、临时文件、性能日志。删了微信会自己重建，"
             "聊天记录和收到的文件不受影响。清理前建议先退出微信。",
    ),
    ("wx", "caution"): dict(
        name="微信 聊天内容（图片 / 视频 / 文件）",
        category="聊天软件 · 微信",
        note="聊天里的图片附件、视频、收到的文件。删了翻聊天记录就看不到对应内容了。"
             "默认不勾，自己决定。",
    ),
    ("wx", "view"): dict(
        name="微信 数据库 / 小程序数据",
        category="聊天软件 · 微信",
        note="聊天记录数据库、内置资源、小程序业务数据。删了聊天记录全没，只显示不清理。",
    ),
}


def quick_groups(rows):
    """
    把聊天数据聚合成快速清理页能直接勾的几条大项。
    rows 必须已经算过 size（scan() 的返回值就是）。
    """
    out = []
    for prefix, who in (("qq:", "qq"), ("wx:", "wx")):
        sub = [r for r in rows if r["id"].startswith(prefix)]
        # 接收目录里的散落文件跟聊天内容不是一回事，单独出一行，别混进聚合里
        loose = [r for r in sub if r["category"] == "QQ·散落"]
        sub = [r for r in sub if r["category"] != "QQ·散落"]
        if not sub and not loose:
            continue
        for level in ("safe", "caution", "view"):
            group = [r for r in sub if r["level"] == level]
            if not group:
                continue
            total = sum(r["size"] for r in group)
            if total <= 0:
                continue
            d = QUICK_DEFS.get((who, level))
            if not d:
                continue
            paths = []
            for r in group:
                for p in r["paths"]:
                    if p not in paths:
                        paths.append(p)
            out.append(dict(
                id="chat-quick:%s:%s" % (who, level),
                name=d["name"],
                category=d["category"],
                level=level,
                kind="dir",
                paths=paths,
                size=total,
                desc="%s\n\n构成：%s" % (d["note"], _cat_brief(group)),
            ))
        # 接收目录里的散落文件：单独一行，别跟聊天内容绑在一起
        for r in loose:
            out.append(dict(
                id=r["id"], name=r["name"], category="聊天软件 · QQ",
                level="caution", kind="file", paths=list(r["paths"]),
                size=r["size"], desc=r["desc"],
            ))
    return out


def _qq_homes():
    """由 nt_qq 路径反推 QQ 数据根（Tencent Files 的父目录）。"""
    homes = set()
    for _account, ntqq in find_qq_roots():
        p = ntqq
        for _ in range(4):
            p = os.path.dirname(p)
            if not p:
                break
            if os.path.basename(p).lower() in ("tencent files", "tencentfiles"):
                homes.add(os.path.dirname(p))
                break
    return sorted(homes)


def loose_files(min_mb=50):
    """
    QQ 接收目录根下散落的文件。
    用户把「文件保存位置」设成了接收目录时，聊天里收发的文件会直接堆在根目录，
    不是聊天记录，但删了对应消息也就点不开了 —— 所以标 caution，不默认勾。
    """
    rows = []
    for idx, home in enumerate(_qq_homes()):
        files = []
        total = 0
        for e in _iter_root(home):
            try:
                if e.is_dir(follow_symlinks=False):
                    continue
                sz = e.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            if sz > 0:
                files.append(e.path)
                total += sz
        if total < min_mb * MB:
            continue
        rows.append(_row(
            "qq:loose:%d" % idx,
            "QQ 接收文件夹里的散落文件（%d 个）" % len(files),
            "QQ·散落", "caution", files,
            "位置：%s\n这些是聊天里收发的文件被 QQ 直接存在接收目录根下的（视频、截图、"
            "安装包之类），不是聊天记录。删了聊天记录里对应的文件消息就点不开了，"
            "但聊天文字不受影响。\n先双击进去看一眼，不想要的再勾。" % home,
            kind="file"))
    return rows


if __name__ == "__main__":
    import time
    t = time.time()
    rows, info = scan()
    print("耗时 %.1fs, %d 行" % (time.time() - t, len(rows)))
    print("QQ:", [(a, "%.2f GB" % (s / GB)) for a, s in info["qq"]])
    print("WX:", [(a, "%.2f GB" % (s / GB)) for a, s in info["wx"]])
    print("-" * 90)
    for r in rows:
        print("%8.1f MB [%-4s] %-34s %s" % (
            _row_size(r) / MB, r["level"], r["category"], r["name"]))
