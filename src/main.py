# -*- coding: utf-8 -*-
"""
磁盘垃圾清理 —— 界面入口。

四个页签：
  快速清理   固定的 40+ 项常见垃圾（改这个看 junk_items.py）
  C 盘占用   逐个软件拆开算：谁产生了多少垃圾 / 缓存，以及系统自己占了哪些大头
  聊天记录   QQ、微信的图片 / 视频 / 表情 / 语音 / 文件，按月份拆开
  AI 残留    装在各盘的 AI 软件拉起的工作区、日志、半成品、装完没删的包

改动说明文字 / 增减固定清理项，请改 junk_items.py。
"""

import os
import sys
import json
import ctypes
import threading
import datetime
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from junk_items import ITEMS          # noqa: E402
import scanner                         # noqa: E402
import guard
import cleaner                         # noqa: E402
import deepscan                        # noqa: E402
import chatdata                        # noqa: E402
import aitrash                         # noqa: E402

APP_NAME = "磁盘垃圾清理"
VERSION = "2.3.2"

# 用户的勾选偏好落盘，下次打开还是上次那套（自动退出 / 强制清理）
CFG_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "DiskJunkCleaner", "config.json")


def load_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def resource_path(name):
    """PyInstaller 单文件解开后资源在 _MEIPASS，源码运行时在脚本目录。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

# ---- 配色（中性深色，状态色只做小面积）----
BG = "#16181c"
PANEL = "#1c1f24"
PANEL2 = "#22262c"
LINE = "#2a2e35"
INK = "#e8eaed"
INK2 = "#9aa0a6"
INK3 = "#6b7178"
ACCENT = "#4a9eff"
WARN = "#e8a33d"
DANGER = "#e05a5a"
OK = "#3fb950"
SEL = "#24384f"
HOVER = "#282d34"

FONT_UI = "Microsoft YaHei UI"
F_TITLE = (FONT_UI, 15, "bold")
F_TAB = (FONT_UI, 10)
F_BODY = (FONT_UI, 10)
F_SMALL = (FONT_UI, 9)

LEVEL_TEXT = {"safe": "可清理", "caution": "需确认", "view": "不动"}
LEVEL_COLOR = {"safe": OK, "caution": WARN, "view": INK3}

GB = 1024 ** 3
MB = 1024 ** 2

TABS = [
    ("quick", "快速清理", "常见垃圾：临时文件、缓存、更新包残留、回收站"),
    ("cdisk", "C 盘占用", "逐个软件拆开算账，看清 200 多 GB 到底被谁吃了"),
    ("chat", "聊天记录", "QQ、微信的图片视频表情文件，按月份一块块清"),
    ("ai", "AI 残留", "AI 软件的工作区、日志、半成品、装完没删的包"),
]


def fmt_size(n):
    """字节转人话。"""
    n = float(n or 0)
    if n >= 1024 ** 3:
        return "%.2f GB" % (n / 1024 ** 3)
    if n >= 1024 ** 2:
        return "%.1f MB" % (n / 1024 ** 2)
    if n >= 1024:
        return "%.0f KB" % (n / 1024)
    return "0" if n == 0 else "%.0f B" % n


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _dark_titlebar(win):
    """窗口标题栏也压成深色，不然顶部一条亮色很突兀。"""
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        on = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))
        color = ctypes.c_int(0x0024211C)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
        text_color = ctypes.c_int(0x00EDEAE8)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 36, ctypes.byref(text_color), ctypes.sizeof(text_color))
    except Exception:
        pass


class FlatButton(tk.Button):
    """深色扁平按钮：主按钮实心，次按钮透明加细边。"""

    def __init__(self, master, text, command, kind="ghost", **kw):
        if kind == "primary":
            # 蓝底上的字必须是白字 —— 以前是深蓝近黑（#08121f），
            # 在 #4a9eff 上看着跟禁用态一样，用户以为点不了
            bg, fg, active = ACCENT, "#ffffff", "#5aa9ff"
        elif kind == "danger":
            bg, fg, active = DANGER, "#ffffff", "#e87070"
        elif kind == "tab_on":
            bg, fg, active = PANEL2, INK, PANEL2
        else:
            bg, fg, active = PANEL2, INK, HOVER
        super().__init__(
            master, text=text, command=command, bg=bg, fg=fg,
            activebackground=active, activeforeground=fg,
            bd=0, relief="flat", highlightthickness=0,
            font=(FONT_UI, 9), padx=14, pady=6, cursor="hand2",
            **kw
        )
        self._bg = bg
        self._hover = active
        self._kind = kind
        # 禁用态用「压暗的底 + 提亮的字」，和可点状态一眼能分清。
        # 以前禁用只把字调浅、底还留着亮蓝，用户看着像「按钮坏了/字是灰的」。
        self._off_bg = {"primary": "#2b5f9c", "danger": "#8c3a3a"}.get(kind, PANEL2)
        self._on = True
        self.bind("<Enter>", self._do_hover)
        self.bind("<Leave>", self._do_unhover)

    def _do_hover(self, _e=None):
        if self._on:
            self.config(bg=self._hover)

    def _do_unhover(self, _e=None):
        if self._on:
            self.config(bg=self._bg)

    def set_enabled(self, on):
        self._on = bool(on)
        if on:
            self.config(state="normal", bg=self._bg,
                        fg="#ffffff" if self._kind in ("primary", "danger") else INK2,
                        cursor="hand2")
        else:
            self.config(state="disabled", bg=self._off_bg,
                        fg="#d6e9ff" if self._kind in ("primary", "danger") else INK3,
                        cursor="arrow")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("%s v%s" % (APP_NAME, VERSION))
        self.configure(bg=BG)
        # v2.3.2：窗口尺寸按屏幕可用区域收一下。
        # 以前写死 1180x780，在 125%/150% 缩放的屏上物理尺寸会放大到 1475x975 甚至更大，
        # 底部那排（详情 / 提示 / 「清理选中项」按钮）就被顶到屏幕外面去了 ——
        # 用户看到「右下角一点灰色字」其实就是被裁剩的按钮残边。
        # 现在高度最多取可用高度的 86%，保证底部按钮永远在屏幕里。
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            w = min(1180, max(980, int(sw * 0.88)))
            h = min(780, max(640, int(sh * 0.86)))
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2 - 24)
            self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        except Exception:
            self.geometry("1180x780")
        self.minsize(980, 620)
        self.after(120, lambda: _dark_titlebar(self))
        # 窗口 + 任务栏图标：不设的话任务栏显示的是 Tk 自带的羽毛
        try:
            ico = resource_path("icon.ico")
            if os.path.exists(ico):
                self.iconbitmap(ico)
        except Exception:
            pass

        self._cfg = load_cfg()
        self.cancel_event = threading.Event()
        self.data = {k: [] for k, _, _ in TABS}        # 每页的行
        self.rows = {}                                  # 当前页 iid -> row
        self.checked = {k: set() for k, _, _ in TABS}   # 每页各自的勾选
        self.cur = "quick"
        self.busy = False
        self.tab_stats = {k: "" for k, _, _ in TABS}
        self._chat_cache = None      # QQ / 微信 只扫一次，快速清理页和聊天页共用

        self._build_ui()
        self.after(260, self.start_scan)

    # ---------------- UI ----------------
    def _build_ui(self):
        root = tk.Frame(self, bg=BG)
        root.pack(fill="both", expand=True, padx=22, pady=(14, 16))

        # 标题区
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x")
        tk.Label(head, text=APP_NAME, bg=BG, fg=INK, font=F_TITLE).pack(side="left")
        self.lab_disk = tk.Label(head, text="", bg=BG, fg=INK3, font=F_SMALL)
        self.lab_disk.pack(side="left", padx=(14, 0), pady=(6, 0))
        tk.Label(head, text="v" + VERSION, bg=BG, fg=INK3,
                 font=F_SMALL).pack(side="right", pady=(6, 0))

        self.lab_stat = tk.Label(root, text="准备扫描…", bg=BG, fg=INK2, font=F_SMALL,
                                 anchor="w")
        self.lab_stat.pack(fill="x", pady=(6, 10))

        # 页签
        tabbar = tk.Frame(root, bg=BG)
        tabbar.pack(fill="x")
        self.tab_btns = {}
        for key, label, _hint in TABS:
            b = tk.Button(tabbar, text=label, bg=BG, fg=INK3,
                          activebackground=PANEL2, activeforeground=INK,
                          bd=0, relief="flat", highlightthickness=0,
                          font=F_TAB, padx=18, pady=9, cursor="hand2",
                          command=lambda k=key: self.switch_tab(k))
            b.pack(side="left", padx=(0, 4))
            self.tab_btns[key] = b
        self.lab_hint = tk.Label(tabbar, text="", bg=BG, fg=INK3, font=F_SMALL)
        self.lab_hint.pack(side="left", padx=(14, 0), pady=(4, 0))

        tk.Frame(root, bg=LINE, height=1).pack(fill="x", pady=(2, 0))

        # 工具栏
        bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", pady=10)
        self.btn_scan = FlatButton(bar, "重新扫描", self.start_scan)
        self.btn_scan.pack(side="left")
        self.btn_safe = FlatButton(bar, "选中可清理项", self.check_safe)
        self.btn_safe.pack(side="left", padx=(8, 0))
        self.btn_invert = FlatButton(bar, "反选", self.invert_check)
        self.btn_invert.pack(side="left", padx=(8, 0))
        self.btn_none = FlatButton(bar, "全部取消", self.clear_check)
        self.btn_none.pack(side="left", padx=(8, 0))
        self.btn_open = FlatButton(bar, "打开位置", self.open_location)
        self.btn_open.pack(side="left", padx=(8, 0))

        admin_txt = "管理员权限" if is_admin() else "普通权限（系统目录可能清不掉）"
        tk.Label(bar, text=admin_txt, bg=BG,
                 fg=INK3 if is_admin() else WARN, font=F_SMALL).pack(side="right", pady=6)

        # 列表（wrap 故意等到最后才 pack —— 见底部区块的说明）
        wrap = tk.Frame(root, bg=BG)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "Treeview", background=PANEL, fieldbackground=PANEL, foreground=INK,
            borderwidth=0, rowheight=29, font=(FONT_UI, 10),
        )
        style.map("Treeview",
                  background=[("selected", SEL)],
                  foreground=[("selected", INK)])
        style.configure(
            "Treeview.Heading", background=BG, foreground=INK3,
            borderwidth=0, relief="flat", font=(FONT_UI, 9), padding=(8, 6),
        )
        style.map("Treeview.Heading", background=[("active", BG)])
        style.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=BG,
                        borderwidth=0, arrowsize=12, width=10)

        cols = ("check", "name", "size", "level", "cat")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 selectmode="browse")
        self.tree.heading("check", text="")
        self.tree.heading("name", text="项目", anchor="w")
        self.tree.heading("size", text="占用", anchor="e")
        self.tree.heading("level", text="处理建议", anchor="w")
        self.tree.heading("cat", text="来源 / 分类", anchor="w")

        self.tree.column("check", width=40, minwidth=40, stretch=False, anchor="center")
        self.tree.column("name", width=520, minwidth=240, stretch=True, anchor="w")
        self.tree.column("size", width=105, minwidth=80, stretch=False, anchor="e")
        self.tree.column("level", width=90, minwidth=80, stretch=False, anchor="w")
        self.tree.column("cat", width=250, minwidth=120, stretch=False, anchor="w")

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.tag_configure("caution", foreground=WARN)
        self.tree.tag_configure("view", foreground=INK3)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double)

        # 详情（先建好，统一在底部区块按 side="bottom" 从下往上 pack）
        line_detail = tk.Frame(root, bg=LINE, height=1)
        detail = tk.Frame(root, bg=BG)
        self.lab_path = tk.Label(detail,
                                 text="位置：双击任意一行可以直接打开文件夹，自己先看一眼再决定。",
                                 bg=BG, fg=INK3, font=F_SMALL, anchor="w", justify="left")
        self.lab_path.pack(fill="x")
        self.lab_desc = tk.Label(detail,
                                 text="选中上方任意一项，这里会说清楚它是什么、删了会怎样。",
                                 bg=BG, fg=INK2, font=F_SMALL, anchor="w",
                                 justify="left", wraplength=1100)
        self.lab_desc.pack(fill="x", pady=(4, 0))

        # 提示条：把「被占用也能清」写死在界面上，不用看说明文件
        hint = tk.Label(root,
                 text="提示：清理时遇到被占用（QQ / 微信 开着也算）的文件，会自动解除占用后再删；"
                      "仍删不掉的会登记为下次开机自动删除，不会再出现「被占用就清不掉」。",
                 bg=BG, fg=INK3, font=F_SMALL, anchor="w")

        # 底部
        line_foot = tk.Frame(root, bg=LINE, height=1)
        foot = tk.Frame(root, bg=BG)
        self.lab_sum = tk.Label(foot, text="已选 0 项 · 0 B", bg=BG, fg=INK,
                                font=(FONT_UI, 11))
        self.lab_sum.pack(side="left")

        # 两个偏好勾选框，存到 config.json，下次打开还是上次的选择
        self.var_autoexit = tk.BooleanVar(value=bool(self._cfg.get("auto_exit", False)))
        self.var_force = tk.BooleanVar(value=bool(self._cfg.get("force_clean", True)))
        self.cb_autoexit = tk.Checkbutton(
            foot, text="清理完自动退出软件", variable=self.var_autoexit,
            command=self._save_prefs, bg=BG, fg=INK,
            activebackground=BG, activeforeground=INK, selectcolor=PANEL2,
            bd=0, highlightthickness=0, font=F_SMALL, cursor="hand2")
        self.cb_autoexit.pack(side="left", padx=(18, 0))
        self.cb_force = tk.Checkbutton(
            foot, text="强制清理（自动解除占用）", variable=self.var_force,
            command=self._save_prefs, bg=BG, fg=INK2,
            activebackground=BG, activeforeground=INK, selectcolor=PANEL2,
            bd=0, highlightthickness=0, font=F_SMALL, cursor="hand2")
        self.cb_force.pack(side="left", padx=(14, 0))

        self.btn_cancel = FlatButton(foot, "取消清理", self.on_cancel, kind="danger")
        self.btn_clean = FlatButton(foot, "清理选中项", self.on_clean, kind="primary")
        self.btn_clean.pack(side="right")
        self.btn_clean.set_enabled(False)

        # ---- 底部区块统一 pack ----
        # 以前 wrap 用 expand=True 且第一个 pack，会把详情区 / 提示条 / 底部按钮栏
        # 全部挤出可视区域（用户看到的「右下角一点灰色字」其实就是被裁掉的
        # 「清理选中项」按钮）。正确做法：底部这些东西 side="bottom" 先占好位置，
        # 列表最后 pack 去吃掉剩下的中间区域。
        # side="bottom" 先 pack 的贴最底，所以顺序必须是 foot → 线 → 提示条 → 详情。
        foot.pack(side="bottom", fill="x", pady=(10, 0))
        line_foot.pack(side="bottom", fill="x", pady=(10, 0))
        hint.pack(side="bottom", fill="x", pady=(10, 0))
        detail.pack(side="bottom", fill="x", pady=(10, 0))
        line_detail.pack(side="bottom", fill="x", pady=(12, 0))
        wrap.pack(fill="both", expand=True)

        self._refresh_disk_label()

    def _refresh_disk_label(self):
        try:
            used, free, total = scanner.disk_free("C:\\")
            if total:
                self.lab_disk.config(
                    text="C 盘已用 %s / 剩 %s" % (fmt_size(used), fmt_size(free)))
        except Exception:
            pass

    # ---------------- 页签 ----------------
    def switch_tab(self, key):
        if key == self.cur and self.rows:
            return
        self._save_checks()
        self.cur = key
        for k, b in self.tab_btns.items():
            b.config(fg=INK if k == key else INK3,
                     bg=PANEL2 if k == key else BG,
                     font=(FONT_UI, 10, "bold") if k == key else F_TAB)
        for k, label, hint in TABS:
            if k == key:
                self.lab_hint.config(text=hint)
        self.render_rows()
        self.lab_stat.config(text=self.tab_stats.get(key) or "还没扫完，稍等…")

    def _save_checks(self):
        # checked 已经是当前页的集合对象，不用额外同步
        pass

    # ---------------- 扫描 ----------------
    def start_scan(self):
        if self.busy:
            return
        self.busy = True
        self.btn_scan.set_enabled(False)
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        for k in self.checked:
            self.checked[k].clear()
        self.data = {k: [] for k, _, _ in TABS}
        self.tab_stats = {k: "" for k, _, _ in TABS}
        self._chat_cache = None
        self.cancel_event.clear()
        self.lab_stat.config(text="正在扫描：QQ / 微信 聊天数据…")
        self.update_sum()
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        # 0) QQ / 微信先扫：快速清理页的聚合项要用，而且后面聊天页签直接复用，不重复扫盘
        self._safe_status("正在扫描：QQ / 微信 聊天数据…")
        chat_raw, chat_info = [], {"qq": [], "wx": [], "programs": []}
        try:
            chat_raw, chat_info = chatdata.scan()
        except Exception as e:
            self._safe_status("聊天数据扫描出错：%s" % e)
        self._chat_cache = (chat_raw, chat_info)

        # 1) 快速清理（固定项 + 聊天软件聚合项）
        self._safe_status("正在扫描：常见垃圾…")
        try:
            res = scanner.scan_all(ITEMS, progress=self._on_progress)
        except Exception as e:
            res = {}
            self._safe_status("快速清理扫描出错：%s" % e)
        rows1, stat1 = self._build_tab_quick(res, chat_raw)
        self.after(0, lambda: self._tab_ready("quick", rows1, stat1))

        # 2) C 盘占用
        self._safe_status("正在扫描：C 盘逐个软件拆账（十几秒）…")
        try:
            rows2, stat2 = self._build_tab_c(res)
        except Exception as e:
            rows2, stat2 = [], "C 盘扫描出错：%s" % e
        self.after(0, lambda: self._tab_ready("cdisk", rows2, stat2))

        # 3) 聊天记录（用上面已经扫好的结果）
        self._safe_status("正在整理：QQ / 微信 聊天数据分月…")
        try:
            rows3, stat3 = self._build_tab_chat()
        except Exception as e:
            rows3, stat3 = [], "聊天记录扫描出错：%s" % e
        self.after(0, lambda: self._tab_ready("chat", rows3, stat3))

        # 4) AI 残留
        self._safe_status("正在扫描：AI 软件残留…")
        try:
            rows4, stat4 = self._build_tab_ai()
        except Exception as e:
            rows4, stat4 = [], "AI 残留扫描出错：%s" % e
        self.after(0, lambda: self._tab_ready("ai", rows4, stat4))

        self.after(0, self._all_done)

    def _safe_status(self, text):
        try:
            self.after(0, lambda: self.lab_stat.config(text=text))
        except Exception:
            pass

    def _on_progress(self, done, total):
        try:
            self.after(0, lambda: self.lab_stat.config(
                text="正在扫描：常见垃圾 %d / %d …" % (done, total)))
        except Exception:
            pass

    def _tab_ready(self, key, rows, stat):
        rows = self._guard_rows(rows)
        self.data[key] = rows
        self.tab_stats[key] = stat
        self.checked[key] = {r["id"] for r in rows if r["level"] == "safe"}
        if key == self.cur:
            self.render_rows()
            self.lab_stat.config(text=stat)
            self.update_sum()

    def _guard_rows(self, rows):
        """
        v2.3.0：任何页签扫出来的行，只要实际路径落在 guard 保护范围
        （DSH / pnpm store / node_modules / 编辑器配置目录…），直接降成「不动」。
        这样它连勾都勾不上，不会出现「勾了清不掉」的怪体验。

        v2.3.1：通配项（如 %LOCALAPPDATA%\\*-updater）先展开再判断。
          全部命中 -> 整行降「不动」
          部分命中 -> 保持可清理，但说明里写明「其中 N 项受保护，清理时自动跳过」
          这样用户点「Electron 应用更新包残留」时心里有数，知道里面混着 DSH 的更新包。
        """
        import glob as _glob

        for r in rows:
            if r.get("level") == "view":
                continue
            total = 0
            protected_n = 0
            why_first = ""
            for p in (r.get("paths") or []):
                try:
                    pp = os.path.expandvars(p)
                    reals = _glob.glob(pp) if "*" in pp else [pp]
                except (OSError, ValueError):
                    continue
                if not reals:
                    total += 1
                    continue
                for real in reals:
                    total += 1
                    hit, why = guard.is_protected(real)
                    if hit:
                        protected_n += 1
                        if not why_first:
                            why_first = why
            if protected_n <= 0:
                continue
            old = (r.get("desc") or "").rstrip()
            if protected_n >= total:
                r["level"] = "view"
                r["desc"] = (old + "　（此项受保护，不参与清理：%s）" % why_first).strip()
            else:
                r["desc"] = (old + "　（其中 %d 项受保护，清理时自动跳过）" % protected_n).strip()
        return rows

    def _all_done(self):
        self.busy = False
        self.btn_scan.set_enabled(True)
        self._refresh_disk_label()
        self.render_rows()
        self.lab_stat.config(text=self.tab_stats.get(self.cur) or "扫描完成")
        self.update_sum()

    # ---------------- 各页数据 ----------------
    def _build_tab_quick(self, res, chat_raw=None):
        order = {"safe": 0, "caution": 1, "view": 2}
        items = []
        for it in ITEMS:
            info = res.get(it["id"], {})
            size = info.get("size", 0)
            if size <= 0:
                continue
            items.append((order.get(it["level"], 9), -size, it, info))
        items.sort(key=lambda x: (x[0], x[1]))

        rows = []
        for _o, _n, it, info in items:
            size = info.get("size", 0)
            paths = info.get("paths") or []
            rows.append(dict(
                id=it["id"], name=it["name"], category=it.get("category", ""),
                level=it["level"], kind=it.get("kind", "dir"),
                paths=list(it.get("paths") or paths), size=size,
                desc=it.get("desc", ""),
                _nominal=(it.get("kind") == "dism"),
                _info=dict(info, size=size, paths=paths),
            ))

        # 聊天软件（QQ / 微信）：现场探测出来，不是写死路径。
        # 以前这里只有一条「QQ 数据 41 GB · 不动 · 只看」，用户没法处理；
        # 现在拆成 缓存（可清）/ 聊天内容（需确认）/ 数据库（不动）三条。
        for g in chatdata.quick_groups(chat_raw or []):
            rows.append(dict(
                id=g["id"], name=g["name"], category=g["category"],
                level=g["level"], kind=g["kind"], paths=list(g["paths"]),
                size=g["size"], desc=g["desc"],
                _info=dict(size=g["size"], paths=list(g["paths"])),
            ))

        # 混进来之后按「可清理 → 需确认 → 不动」重排，同档按大小倒序
        rows.sort(key=lambda r: (order.get(r["level"], 9), -r["size"]))

        safe_total = sum(r["size"] for r in rows if r["level"] == "safe")
        view_total = sum(r["size"] for r in rows if r["level"] == "view")
        stat = "常见垃圾共 %d 项可清 %s" % (len(rows), fmt_size(safe_total))
        if view_total:
            stat += " · 另有仅展示项 %s（模拟器镜像 / 游戏本体等，不动）" % fmt_size(view_total)
        return rows, stat

    def _build_tab_c(self, quick_res=None):
        rows = []
        used, free, _total = scanner.disk_free("C:\\")

        # 这些缓存删了会触发「重新下几十 MB～几 GB 的模型」，别默认勾
        BIG_REDOWNLOAD = ("optguideondviceModel", "optguideondevicemodel",
                          "optimization_guide_model_store", "translatekit",
                          "hf_cache", "huggingface", "modelscope", "torch")

        def _is_big_redownload(path):
            low = path.lower()
            return any(k in low for k in
                       ("optguideondevicemodel", "optimization_guide_model_store",
                        "translatekit", "hf_cache", "huggingface", "modelscope"))

        # 1) 各软件的垃圾
        apps = deepscan.scan_app_dirs()
        clean_sum = 0
        for a in sorted(apps, key=lambda x: -x["clean"]):
            if a["clean"] < 5 * MB:
                continue
            safe_parts = [p for p in a["parts"] if not _is_big_redownload(p[0])]
            slow_parts = [p for p in a["parts"] if _is_big_redownload(p[0])]
            clean_sum += a["clean"]
            # 需要重下模型的那部分太小就别单列了，直接并进可清项，免得满屏碎行
            if sum(p[2] for p in slow_parts) < 20 * MB:
                safe_parts = safe_parts + slow_parts
                slow_parts = []

            for group, level, extra in (
                (safe_parts, "safe", ""),
                (slow_parts, "caution", "（这部分删了会重新下载模型，慢一点）"),
            ):
                if not group:
                    continue
                sz = sum(p[2] for p in group)
                if sz < 1 * MB:
                    continue
                paths = [p[0] for p in group]
                detail = "、".join(
                    "%s %s" % (os.path.basename(p[0].rstrip("\\")) or p[0], fmt_size(p[2]))
                    for p in group[:6])
                rows.append(dict(
                    id="c:clean:%s:%s" % (a["path"], level), name=a["label"] + extra,
                    category="软件垃圾 · " + a["category"], level=level,
                    kind="dir", paths=paths, size=sz,
                    desc=("这块是从 %s 里挑出来的纯缓存/日志/临时文件，合计 %s，"
                          "占该软件 %s 里的 %s。\n具体是：%s\n"
                          "删了不会影响软件本体和你的设置，最快也就是下次启动慢一点重新生成缓存。"
                          % (a["path"], fmt_size(sz), fmt_size(a["total"]),
                             "%d%%" % round(sz * 100.0 / max(a["total"], 1)), detail)),
                    _info=dict(size=sz, paths=paths),
                ))
            clean_sum += a["clean"]

        # 2) 散落垃圾
        loose = deepscan.find_loose(deepscan.loose_roots())
        for tag, level, note, lst in (
            ("断点 / 临时残片", "safe", "下载或安装中断留下的半截文件，纯垃圾。", loose["partial"]),
            ("大日志 / 崩溃转储", "caution", "软件崩溃或调试留下的日志和内存转储，没人看就是占地方。", loose["log"]),
            ("PyInstaller 残留", "safe", "Python 打包的 exe 被强杀后留下的解包目录，纯垃圾。", loose["mei"]),
        ):
            for p, sz in lst:
                if sz < 5 * MB:
                    continue
                rows.append(dict(
                    id="c:loose:%s" % p, name=os.path.basename(p.rstrip("\\")) or p,
                    category=tag, level=level, kind="dir" if os.path.isdir(p) else "file",
                    paths=[p], size=sz,
                    desc="%s\n位置：%s" % (note, p),
                    _info=dict(size=sz, paths=[p]),
                ))

        # 3) 系统大头（只展示）
        sysd_rows = deepscan.scan_system_heavy()
        for a in sysd_rows:
            rows.append(dict(
                id="c:sys:%s" % a["path"], name=a["name"],
                category="系统占用 · " + a["scope"], level="view",
                kind="dir", paths=[a["path"]], size=a["total"],
                desc=(a.get("note") or "系统目录，只做展示。") +
                     "\n位置：%s\n这一项不会删，只是让你知道 C 盘被什么吃掉了。" % a["path"],
                _info=dict(size=a["total"], paths=[a["path"]]),
            ))

        # 4) 装得最大又没垃圾可清的软件（只展示）
        for a in sorted(apps, key=lambda x: -x["total"])[:12]:
            if a["clean"] >= 5 * MB:
                continue
            rows.append(dict(
                id="c:big:%s" % a["path"], name=a["label"],
                category="占地方 · " + a["category"], level="view",
                kind="dir", paths=[a["path"]], size=a["total"],
                desc=("这块 %s 里没有可清的缓存，全是实打实的数据（模型、虚拟机镜像、"
                      "程序本体之类）。要省空间只能：要么卸载，要么在软件自己的界面里删。\n"
                      "位置：%s" % (fmt_size(a["total"]), a["path"])),
                _info=dict(size=a["total"], paths=[a["path"]]),
            ))

        # 盘级账本：直接用上面已经算好的各软件大小按父目录汇总，不再重复遍历一遍盘
        by_root = {}
        for a in apps:
            low = a["path"].lower()
            for key in ("c:\\users", "c:\\programdata",
                        "c:\\program files (x86)", "c:\\program files"):
                if low.startswith(key):
                    by_root[key] = by_root.get(key, 0) + a["total"]
                    break
        win_total = sum(x["total"] for x in sysd_rows if x.get("scope") == "Windows")

        stat = "C 盘已用 %s · 软件垃圾可清 %s · 共 %d 行" % (
            fmt_size(used), fmt_size(clean_sum), len(rows))
        parts = []
        for key, label in (("c:\\users", "Users"), ("c:\\windows", "Windows"),
                           ("c:\\programdata", "ProgramData"),
                           ("c:\\program files (x86)", "Program Files (x86)"),
                           ("c:\\program files", "Program Files")):
            v = win_total if key == "c:\\windows" else by_root.get(key, 0)
            if v >= 100 * MB:
                parts.append("%s %s" % (label, fmt_size(v)))
        if parts:
            stat = "C 盘已用 %s（%s）· 软件垃圾可清 %s · 共 %d 行" % (
                fmt_size(used), " / ".join(parts[:4]), fmt_size(clean_sum), len(rows))
        return rows, stat

    def _build_tab_chat(self):
        rows = []
        cached = self.__dict__.get("_chat_cache")
        if cached:
            raw, info = cached
        else:
            raw, info = chatdata.scan()
            self._chat_cache = (raw, info)
        for r in raw:
            rows.append(dict(
                id="chat:" + r["id"], name=r["name"], category=r["category"],
                level=r["level"], kind=r["kind"], paths=r["paths"], size=r["size"],
                desc=r["desc"], _info=dict(size=r["size"], paths=r["paths"]),
            ))
        if not rows:
            return [], "没有找到 QQ / 微信 的聊天数据目录。如果你装在别的盘，可能是目录名被改过。"

        qq_txt = "、".join("%s（%s）" % (a, fmt_size(s)) for a, s in info["qq"]) or "无"
        wx_txt = "、".join("%s（%s）" % (a[:18], fmt_size(s)) for a, s in info["wx"]) or "无"
        safe = sum(r["size"] for r in rows if r["level"] == "safe")
        stat = "QQ：%s · 微信：%s · 可安全清 %s · 共 %d 行" % (
            qq_txt, wx_txt, fmt_size(safe), len(rows))
        return rows, stat

    def _build_tab_ai(self):
        raw, info = aitrash.scan()
        rows = []
        for r in raw:
            rows.append(dict(
                id="ai:" + r["id"], name=r["name"], category=r["category"],
                level=r["level"], kind=r["kind"], paths=r["paths"], size=r["size"],
                desc=r["desc"], _info=dict(size=r["size"], paths=r["paths"]),
            ))
        if not rows:
            return [], "没找到 AI 软件的目录，也没有明显的残留。"
        safe = sum(r["size"] for r in rows if r["level"] == "safe")
        stat = "找到 %d 个 AI 软件（合计 %s）· 可清残留 %s · 共 %d 行" % (
            len(info["roots"]), fmt_size(info["total"]), fmt_size(safe), len(rows))
        return rows, stat

    # ---------------- 渲染 ----------------
    def render_rows(self):
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        rows = self.data.get(self.cur) or []
        ck = self.checked.setdefault(self.cur, set())
        for r in rows:
            if r["level"] == "view":
                # 旧配置里可能残留过勾选（比如 v2.2.0 的 pnpm_store / dsh_cache），
                # v2.3.0 改成只看，必须把残留勾选清掉，别算进合计
                ck.discard(r["id"])
            mark = "☑" if r["id"] in ck else "☐"
            if r["level"] == "view":
                mark = "—"
            self.tree.insert("", "end", iid=r["id"], tags=(r["level"],), values=(
                mark, r["name"], fmt_size(r["size"]),
                LEVEL_TEXT.get(r["level"], ""), r["category"],
            ))
            self.rows[r["id"]] = r
        if rows:
            try:
                self.tree.selection_set(rows[0]["id"])
            except Exception:
                pass
        self.update_sum()

    # ---------------- 勾选 ----------------
    def on_tree_click(self, event):
        if self.busy:
            return
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        row = self.rows.get(iid)
        if not row or row["level"] == "view":
            return
        if col == "#1":
            self.toggle(iid)

    def toggle(self, iid):
        ck = self.checked.setdefault(self.cur, set())
        if iid in ck:
            ck.discard(iid)
            self.tree.set(iid, "check", "☐")
        else:
            ck.add(iid)
            self.tree.set(iid, "check", "☑")
        self.update_sum()

    def check_safe(self):
        ck = self.checked.setdefault(self.cur, set())
        for iid, row in self.rows.items():
            if row["level"] == "safe":
                ck.add(iid)
                self.tree.set(iid, "check", "☑")
        self.update_sum()

    def clear_check(self):
        ck = self.checked.setdefault(self.cur, set())
        for iid in list(ck):
            if iid in self.rows:
                self.tree.set(iid, "check", "☐")
        ck.clear()
        self.update_sum()

    def invert_check(self):
        for iid, row in self.rows.items():
            if row["level"] == "view":
                continue
            self.toggle(iid)

    def _sum_of(self, row):
        # DISM 只能预测「通常省 1~3 GB」，别把 WinSxS 整个算进合计
        return 0 if row.get("_nominal") else row["size"]

    def selected_size(self):
        ck = self.checked.setdefault(self.cur, set())
        n = 0
        for iid in ck:
            row = self.rows.get(iid)
            if row:
                n += self._sum_of(row)
        return n

    def update_sum(self):
        ck = self.checked.setdefault(self.cur, set())
        total = self.selected_size()
        self.lab_sum.config(text="已选 %d 项 · %s" % (len(ck), fmt_size(total)))
        self.btn_clean.set_enabled(bool(ck) and not self.busy)

    def on_select(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        row = self.rows.get(sel[0])
        if not row:
            return
        paths = row.get("paths") or []
        if paths:
            show = paths[0] if len(paths) == 1 else "%s  等 %d 处" % (paths[0], len(paths))
        else:
            show = "—"
        self.lab_path.config(text="位置：" + show)
        self.lab_desc.config(text=row.get("desc", ""))

    def open_location(self):
        sel = self.tree.selection()
        if not sel:
            return
        row = self.rows.get(sel[0])
        if not row:
            return
        self._open_path((row.get("paths") or [None])[0])

    def on_double(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        row = self.rows.get(iid)
        if row:
            self._open_path((row.get("paths") or [None])[0])

    def _open_path(self, p):
        if not p:
            return
        try:
            if os.path.isfile(p):
                os.startfile(os.path.dirname(p))
            elif os.path.isdir(p):
                os.startfile(p)
        except Exception:
            pass

    # ---------------- 清理 ----------------
    def _save_prefs(self):
        self._cfg["auto_exit"] = bool(self.var_autoexit.get())
        self._cfg["force_clean"] = bool(self.var_force.get())
        save_cfg(self._cfg)

    def on_cancel(self):
        if not self.busy:
            return
        self.cancel_event.set()
        self.lab_stat.config(text="正在停止：等当前这一项收尾…")

    def on_clean(self):
        ck = self.checked.setdefault(self.cur, set())
        if self.busy or not ck:
            return
        picked = []
        for iid in ck:
            row = self.rows.get(iid)
            if not row:
                continue
            if row["level"] == "view":
                continue
            picked.append((row, row.get("_info") or
                           dict(size=row["size"], paths=row["paths"])))
        if not picked:
            return
        picked.sort(key=lambda x: -x[0]["size"])
        ConfirmDialog(self, picked, self._do_clean,
                      force=bool(self.var_force.get()))

    def _do_clean(self, picked):
        self._save_prefs()
        force = bool(self.var_force.get())
        self.busy = True
        self.cancel_event = threading.Event()
        self.btn_clean.set_enabled(False)
        self.btn_scan.set_enabled(False)
        self.btn_cancel.pack(side="right", padx=(0, 10))
        self.lab_stat.config(text="正在清理…")
        threading.Thread(target=self._clean_worker, args=(picked, force),
                         daemon=True).start()

    def _ui_status(self, text):
        try:
            self.after(0, lambda t=text: self.lab_stat.config(text=t))
        except Exception:
            pass

    def _clean_worker(self, picked, force):
        results = []
        for item, info in picked:
            if self.cancel_event.is_set():
                results.append(dict(id=item.get("id"), name=item.get("name"),
                                    freed=0, failed=0, ok=False,
                                    note="已取消", scheduled=0))
                break
            self._ui_status("正在清理：" + item["name"])
            try:
                r = cleaner.clean_item(item, info, force=force,
                                       progress=self._ui_status,
                                       cancel=self.cancel_event)
            except Exception as e:
                r = dict(id=item.get("id"), name=item.get("name"), freed=0,
                         failed=1, ok=False, note=str(e), scheduled=0)
            results.append(r)
        self.after(0, lambda: self._clean_done(results))

    def _clean_done(self, results):
        freed = sum(r.get("freed", 0) for r in results)
        sched = sum(r.get("scheduled", 0) for r in results)
        skipped = sum(r.get("skipped", 0) for r in results)
        failed = [r for r in results if not r.get("ok")]
        msg = "清理完成 · 释放 %s" % fmt_size(freed)
        if sched:
            msg += " · %d 个文件已登记重启后删除" % sched
        if skipped:
            msg += " · 跳过 %d 个受保护项" % skipped
        if failed:
            msg += " · %d 项没清干净" % len(failed)
        cleaner.log("=== 本次清理释放 %d 字节，失败 %d 项，登记重启删除 %d 个，受保护跳过 %d 个 ==="
                    % (freed, len(failed), sched, skipped))
        self.lab_stat.config(text=msg)
        self.busy = False
        self.btn_scan.set_enabled(True)
        self.btn_cancel.pack_forget()
        self._refresh_disk_label()

        # 没清干净的原因写到详情区，别只留个数字让人猜
        notes = [r for r in failed if r.get("note")]
        if notes:
            self.lab_desc.config(
                text="没清干净的原因：\n" + "\n".join(
                    "· %s：%s" % (r["name"], r["note"]) for r in notes[:6]))

        if self.var_autoexit.get():
            self.lab_sum.config(text="清理完自动退出，3 秒后关闭…")
            self.after(3000, self._quit)
        else:
            self.after(800, self.start_scan)

    def _quit(self):
        try:
            self.destroy()
        except Exception:
            pass


class ConfirmDialog(tk.Toplevel):
    """清理前确认：列清楚要删什么，caution 项单独标黄。"""

    def __init__(self, master, picked, on_ok, force=True):
        super().__init__(master)
        self.title("确认清理")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.on_ok = on_ok
        self.picked = picked
        self.force = force

        total = sum((it.get("size") or 0) for it, _ in picked)
        caution = [it for it, _ in picked if it["level"] == "caution"]

        body = tk.Frame(self, bg=BG, padx=24, pady=20)
        body.pack(fill="both", expand=True)

        foot = tk.Frame(body, bg=BG)
        foot.pack(side="bottom", fill="x", pady=(16, 0))
        FlatButton(foot, "取消", self.destroy).pack(side="right")
        FlatButton(foot, "开始清理", self._ok, kind="danger").pack(side="right", padx=(0, 10))

        if caution:
            tk.Label(body,
                     text="其中 %d 项属于「需确认」，删了不可逆，先看清楚是不是你要的。" % len(caution),
                     bg=BG, fg=WARN, font=F_SMALL, anchor="w",
                     wraplength=520, justify="left").pack(side="bottom", fill="x", pady=(10, 0))
        if force:
            tk.Label(body,
                     text="强制清理已开：被占用（QQ / 微信 开着也算）的文件会先自动解除占用，"
                          "还删不掉的就登记成下次开机自动删除。",
                     bg=BG, fg=INK3, font=F_SMALL, anchor="w",
                     wraplength=520, justify="left").pack(side="bottom", fill="x", pady=(6, 0))

        tk.Label(body, text="即将清理 %d 项，合计 %s" % (len(picked), fmt_size(total)),
                 bg=BG, fg=INK, font=(FONT_UI, 13, "bold")).pack(anchor="w")

        box = tk.Frame(body, bg=PANEL)
        box.pack(fill="both", expand=True, pady=(14, 0))

        shown = picked[:9]
        for it, _info in shown:
            row = tk.Frame(box, bg=PANEL)
            row.pack(fill="x", padx=14, pady=5)
            color = WARN if it["level"] == "caution" else INK
            tk.Label(row, text=it["name"], bg=PANEL, fg=color,
                     font=F_BODY, anchor="w").pack(side="left")
            tk.Label(row, text=fmt_size(it.get("size") or 0), bg=PANEL,
                     fg=INK2, font=F_SMALL).pack(side="right")

        if len(picked) > len(shown):
            tk.Label(box,
                     text="…… 另外 %d 项，点「开始清理」会一起清" % (len(picked) - len(shown)),
                     bg=PANEL, fg=INK3, font=F_SMALL, anchor="w").pack(
                         fill="x", padx=14, pady=(2, 10))

        self.update_idletasks()
        rows = min(len(picked), 9) + (1 if len(picked) > 9 else 0)
        w, h = 580, 250 + rows * 33
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - h) // 2
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        _dark_titlebar(self)

    def _ok(self):
        self.destroy()
        self.on_ok(self.picked)


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "DiskJunkCleaner.App")
    except Exception:
        pass
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
