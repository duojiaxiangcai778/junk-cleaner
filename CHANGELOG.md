# CHANGELOG

## v2.3.2 — 2026-11-04

### 提速：删除 2 万小文件从「明显卡」到 6.61 秒

三处白烧的开销：
- `_rm_tree` 对**每个文件**调 `guard.is_protected`，里面又 `os.path.abspath` 一次；
  入口其实已经判过整棵树了。
- `_empty_dir` 每个子目录 → `_rm_tree` → `is_protected_root` 要查
  `.git`/`package.json`/`node_modules`/`manifest.json`/`pyproject.toml` **5 次 `os.path.exists`**。
- 空目录靠第二趟遍历收。

改法：受保护判断只做在**目录**上（纯字符串，零 stat），`check_root=False` 省掉重复
struct 检查，`all_dirs` 逆序 rmdir 一趟收完，`progress` 每 500 个文件报一次
「已处理 N 个文件」。

实测：20000 个文件 **6.61 秒 / 3026 个每秒**（造文件本身 7.44 秒，已到 SSD IO 极限）。

### 修（真漏洞）：受保护目录「保护晚一步」

旧代码用 `os.walk(topdown=False)`（自底向上）：**先钻进子目录把文件删光**，
等回头处理到 `node_modules` / `.dsh` 目录本身时才发现它该受保护 —— 里面的东西早没了。
改成 `topdown=True` + `dirs[:]` 过滤，命中保护**直接不下钻**。

回归验证：`sub\node_modules\pkg\index.js` 保住、同级 `junk.txt` 照删，`skipped=1`。

### 修：底部按钮栏被挤出屏幕（用户说「右下角字是灰的」）

`winfo_*` 量出来的结论：**布局本身没错**，底部栏在客户区 `y=716 h=34` 贴底。
看不见是因为窗口被移到副屏时被 `SetWindowPos` 拉成 1536×864，叠上 DPI 缩放后
物理高度超出屏幕。

- 窗口尺寸不再写死 `1180x780`，改成按屏幕可用区域收（宽 ≤88%、高 ≤86%）并居中偏上。
- 底部区块（foot / 线 / 提示条 / 详情 / 线）统一 `side="bottom"` 先占位，
  `wrap` 最后 pack 吃中间剩余 —— 双保险。
- 「清理选中项」禁用态由「亮蓝底 + 浅蓝字」改成**暗蓝底 `#2b5f9c` + 亮字 `#d6e9ff`**，
  和启用态（`#4a9eff` + `#ffffff`）一眼分清；禁用时不再跟着鼠标 hover 变色。

### 改：「清理完自动退出软件」

该选项一直存在（`config.json` 的 `auto_exit`，实测当前为 True），只是跟着底部栏一起被挤出屏幕。
文字由「清理完自动退出」改成「清理完自动退出软件」，字色由 `INK2` 提到 `INK`。

### 验证

- `selftest_guard.py` **66 通过 / 0 失败**
- 真实 10 个关键目录喂 `clean_item`：全部 `skipped=1 / freed=0 / 目录仍在`
- 窗口 1180×780 @ 2560×1440，按钮底边 1101 < 1440（在屏幕内）
- exe 12,190,155 字节，15:31:33

详见 `工作记录\2026-11-04-v232-删除提速与界面修复.md`。

---

## v2.3.1 — 2026-11-04

### 修（口径错）：QQ / 微信不该被 guard 保护

v2.3.0 把 `\Tencent Files` / `\xwechat_files` / `\WeChat Files` 加进了保护清单，
后果是**「聊天记录」页签被整个废掉** —— 那个页签要清的正是
`Tencent Files\...\Pic\*\Ori` 这类子目录。

用户明确：QQ / 微信聊天记录本来就是要删的；不能删的是 DSH / ZCode 的
**记忆、插件、技能**。

已删掉那三条。QQ 文字数据库 `nt_db` 的「不动」仍由 `chatdata.py` 定成 `view` 级来守，
不归 guard 管。

### 改：通配项显示层先展开再判断

`_guard_rows` 原来拿 `%LOCALAPPDATA%\*-updater` 这种字面量去比对，永远比不中。
现在先 `glob` 展开：
- 全部命中 → 整行降「不动」
- 部分命中 → 保持可清理，说明里写「其中 N 项受保护，清理时自动跳过」

实测 `*-updater` 展开 16 个目录，只有 `dsh-desktop-updater` 被拦，其余 15 个照删。

### 验证

`selftest_guard.py` 由 36 条扩到 **66 条**（DSH/ZCode 技能记忆插件逐条列；QQ/微信 8 条必须放行）。
真实扫描 30 个聊天记录清理项，被 guard 拦 **0** 个。

---

## v2.3.0 — 2026-11-04

### 修（事故级）：清理工具把 DSH 的插件设置清了

2026-11-04 用户打开 DSH，插件设置全丢。取证见
`工作记录\2026-11-04-误删DSH插件设置-根因与保护机制.md`。

根因：`pnpm_store` 项被标成「可清理（默认勾选）」，2026-11-03 17:02 清掉了
`%LOCALAPPDATA%\pnpm\store`（1.85 GB）和 `D:\.pnpm-store`（422 MB）。
DSH 的插件依赖全部由 pnpm 装在 `.generations\live\*\node_modules`，
store 没了 → pnpm 校验失败 → node_modules 被清空 → manifest 读不到 → **Safe Mode 禁用全部插件**。

顺带还清了 `dsh-desktop-updater`（282 MB）和 `%APPDATA%\dsh-desktop\Cache`（282 MB）。

关键认知：**pnpm store 和被装好的 node_modules 是同一份磁盘数据的两个名字（硬链接），
删 store 几乎不回收空间，却能让所有用 pnpm 装插件的 Electron 应用（DSH / Trae /
Cursor / ZCode / WorkBuddy）集体失效。** 这一项收益接近 0、风险极高，属设计错误。

### 新：`src/guard.py` 受保护路径守卫

删除动作的最后一道闸，不管清单怎么配、通配符怎么展开，命中就跳过并写日志：

```
\dsh-desktop  \.dsh  \.mnemon  \pnpm\store  \.pnpm-store  \node_modules
\.workbuddy   \.zcode  \.codex  \.cursor  \.trae  \.claude  \.gemini  \.antigravity
\deepseek-harness  \Tencent Files  \xwechat_files  \WeChat Files
```
外加结构判断：目录里直接含 `.git` / `package.json` / `node_modules` / `manifest.json` /
`pyproject.toml` ＝ 软件或项目本体，整棵不删；以及「本程序自己的 `_MEIPASS`」。

接入点：`_rm_tree` 入口整棵判断 + 逐项判断、`_empty_dir` 每个 entry、
`_clean_item_inner` 每个命中路径、**`_retry_after_unlock` 入口再过滤（受保护文件绝不登记重启后删除）**。

### 改：清理项降级

- `pnpm_store`：`safe` → `view`（不动），名字改「pnpm 包存储（禁止清理）」；
- `dsh_cache`：`safe` → `view`；
- `temp_user`（`%LOCALAPPDATA%\Temp`）：`safe` → `caution`（正在运行的软件状态也在里面）；
- `updater_residue`：说明注明 DSH 等编辑器更新目录自动跳过。

### 改：显示层同步降级

`Main._guard_rows()` 在 `_tab_ready()` 统一跑一遍，四个页签扫出来的行只要实际路径命中
guard 就降成「不动」并追加理由，避免「勾得上却清不掉」；`render_rows()` 把 `view` 项从
勾选集合里剔除（清 v2.2.0 旧配置残留）；`aitrash._row()` 同样处理。

### 新：`src/selftest_guard.py` 回归脚本

36 条断言，改 `guard.py` / `junk_items.py` 后先跑：`python src\selftest_guard.py`。

### 恢复情况（必须说清）

回收站只有 1 个无关文件（`XelLauncher.v0.3.3-Portable.zip`）；系统还原点 0 个；
`vssadmin list shadows` 返回 No items found；本工具全程 `os.remove`，**永久删除不进回收站**。
→ **这几次删掉的东西没有任何渠道可以恢复。** DSH 的插件与依赖是 11-04 14:22～14:52
由 pnpm 重装自救回来的，记忆系统 `.mnemon\runtime\` 完好；QQ 聊天记录的多媒体本体约 13 GB
是永久丢失。

## v2.2.0 — 2026-11-04

### 修：清理到 WinSxS 就卡死

2026-11-03 23:27 现场：日志在「DISM 组件清理」前断掉，`CBS.log` 停在
`Beginning Null-Delta compression of boot-recovery components`，TiWorker CPU 冻住。
老版用 `subprocess.run(timeout=1800)` 干等 DISM，界面只有一行「正在清理」，看着就是卡死。

现在 `dism_component_cleanup()` 改 Popen + 线程读输出：实时百分比、可取消、
连续 300 秒无输出判卡死并终止；每项清理外面再加一层超时（普通 600 秒、DISM 1800 秒），
卡住就跳过这一项、记日志继续下一项，不再让整个软件陪葬。

### 新：强制清理（自动解除占用）

新增 `src/unlocker.py`：Restart Manager 定位占用进程 → 全系统句柄表 →
`DuplicateHandle` + `GetFinalPathNameByHandleW` 比对路径 →
`CreateRemoteThread` 在占用进程里跑 `CloseHandle` 关掉句柄 → 重试删除 →
仍失败则 `MoveFileEx` 登记重启后删除。32 位（WOW64）进程跳过，不冒险。
Restart Manager 对个别路径会卡住不返回，所以单文件 1.5 秒超时、整轮 20 秒预算。

界面底部新增「强制清理（自动解除占用）」勾选，**默认开**；确认框里写明。
底部常驻提示条把这件事写在脸上，不用翻说明。

### 修：回收站清不掉

`SHEmptyRecycleBinW` 只清当前用户的回收站，其它 SID 的 `$Recycle.Bin`
它根本不动、失败还不写日志（本机 E 盘 16 GB 就是这么剩下来的）。
现在 Shell 之后补一刀管理员直删 `X:\$Recycle.Bin\*`。

### 修：任务栏图标 / 按钮字色 / 自动退出

- `iconbitmap(resource_path("icon.ico"))` + 打包 `--add-data icon.ico;.`，
  任务栏不再显示 Tk 默认羽毛；
- 主按钮改白字（原来 `#08121f` 深蓝近黑，`set_enabled(True)` 还会覆盖成灰色，
  看着像点不了）；禁用态 `#9fc4ee`；
- 「清理完自动退出」可勾选，清理结果显示 3 秒后自动关窗；
- 两个勾选存 `%LOCALAPPDATA%\DiskJunkCleaner\config.json`，下次打开保持；
- 清理中显示「取消清理」，当前项收尾即停。

### 补完卡住时没做完的清理

QQ 缓存 + 聊天内容 37.93 GB（用户那次）+ safe 项 8.31 GB + 回收站 16.10 GB +
GUI 实测 4.85 GB。C 盘可用 92.85 GB → 99.28 GB。caution 项未动。
WinSxS 的 DISM 清理因 TiWorker 僵尸态需重启后再跑。

详见 `工作记录\2026-11-04-卡死修复与强制清理.md`。

## v2.1.0 — 2026-11-03

### 修：QQ / 微信从「只看」变成「能清」

用户原话：「这昨天写的清理软件，为什么 QQ 数据只看呢？我要你能清理呀！不清理，
我让你把它加进去干啥？就看着待着，就在这恶心我。顺便把微信也加进去，QQ、微信都是要能清理的」

v2.0.0 里快速清理页只有一条 `qq_data`，`level="view"`，写死在 `junk_items.py`，
显示「QQ 数据 41.02 GB · 不动 · 只看」——能看不能动，等于没做。微信压根没进快速清理页。

这版把这条 `view` 项**删掉**，改成 `chatdata.py` 现场探测后聚合出的可勾选行。

### 快速清理页新增（QQ / 微信各三到四行）

| 行 | 档位 | 路径 |
|---|---|---|
| QQ 缓存（缩略图 / 表情 / 日志 / 临时） | safe，默认勾 | `Pic\*\Thumb`、`Video\*\Thumb`、`Emoji`、`log`、`nt_temp`、`avatar`、各 `*Temp` |
| QQ 聊天内容（原图 / 视频 / 语音 / 文件） | caution | `Pic\*\Ori`、`Video\*\Ori`、`Ptt`、`File` |
| QQ 接收文件夹里的散落文件 | caution | 接收目录根下的散落文件，逐个删 |
| QQ 聊天记录数据库 | view | `nt_db` |
| 微信 缓存（图片缓存 / 临时 / 日志） | safe，默认勾 | `cache`、`temp`、`apm_record` |
| 微信 聊天内容（图片 / 视频 / 文件） | caution | `msg\attach`（按月合并）、`msg\video`、`msg\file` |
| 微信 数据库 / 小程序数据 | view | `db_storage`、`business`、`resource` |

实测（2026-11-03，用户本机 D 盘那份 41 GB QQ 数据）：
`QQ 缓存 22.64 GB` / `QQ 聊天内容 14.95 GB` / `QQ 散落文件 1.03 GB（96 个）` /
`QQ 数据库 1.97 GB`；`微信 缓存 78.8 MB` / `微信 聊天内容 174.7 MB` / `微信 数据库 72.4 MB`。
其中大头是 `Pic\*\Thumb` 缩略图 **17.83 GB**（2026-10 单月 7.74 GB、2026-09 单月 7.25 GB）。

### 改 `chatdata.py`

- `_discover()` 补 `Tencent Files\nt_qq\global`（没绑账号的全局缓存，旧版漏掉 0.29 GB）
- 新增 `_month_dirs(parent, depth=2)`：微信 4.x 的 `msg\attach\<hash>\<YYYY-MM>\` 是两层，
  旧 `_months()` 只看一层所以整个 attach 落成一行 174.7 MB；现在钻一层找月份并**按月份合并**
- 新增 `fmt()` / `_cat_brief()` / `QUICK_DEFS` / `quick_groups(rows)`：把明细聚合成可清理行，
  desc 里自动写「构成：图片 17.83 GB、表情 2.14 GB…」
- 新增 `_qq_homes()` / `loose_files()`：抓接收目录根下散落的文件（96 个 / 1.03 GB）
- `_row_size()` 补 `os.path.isfile` 分支 —— 对文件调 `_sub_size()` 会因 `scandir` 抛
  `NotADirectoryError` 返回 0，导致散落文件那行被 `size > 0` 过滤掉
- `CAT_ORDER` 加 `"QQ·散落": 8`

### 改 `main.py`

- `VERSION` → `2.1.0`
- `_scan_worker()` 改成**先扫 QQ/微信**再扫固定项：聊天数据只扫一次，快速清理页和聊天记录页
  共用 `self._chat_cache`，总耗时没变（1.4s 聊天 + 30s 固定项）
- `_build_tab_quick(res, chat_raw)` 追加 `chatdata.quick_groups()` 的行，并按
  `(level, -size)` 重排，QQ 缓存 22.64 GB 直接排到第一行
- `_build_tab_chat()` 优先用缓存；`self.__dict__.get("_chat_cache")` 不用 `getattr`，
  避免 tkinter 的 `__getattr__` 在未初始化时递归爆栈

### 改 `junk_items.py`

- 删掉 `id="qq_data"` 那条 `view` 项（就是用户截图里恶心人的「41.02 GB · 不动 · 只看」）

### 验证

- headless（真实用户数据）：`chatdata.scan()` 1.4 s / 116 行；快速清理页 36 行、
  状态栏「常见垃圾共 36 项可清 43.17 GB」；row id 全唯一（Treeview iid 无冲突）
- GUI 实机：新 exe 启动后窗口标题 `磁盘垃圾清理 v2.1.0`，快速清理页第一行
  `☑ QQ 缓存（缩略图 / 表情 / 日志 / 临时）22.65 GB 可清理`、第五行
  `☑ 微信 缓存（图片缓存 / 临时 / 日志）78.8 MB 可清理`，均已默认勾选
- 未做「实删 22 GB」测试：清理走的是没改过的 `cleaner._empty_dir`，v2.0.0 已验证；
  真实删除留给用户点

---

## v2.0.0 — 2026-11-03

### 大改：从「一张表」变成「四个页签」

用户原话：「C 盘 300G 现在就剩 69G 了，怎么可能占用这么大呢？我什么软件都没往里装……
需要把 C 盘里软件产生的东西都细化一下，比如哪个软件产生的垃圾、缓存什么的」
「QQ、微信的聊天记录占用的数据量非常恐怖……都需要细化清理」
「我装的 AI 软件都在 D 盘，它们在工作过程中可能乱拉文件……比如工作日志、
下载没删的软件，还有那种被打断的、干了一半的绘画文件」

旧版只有一张 45 项的表，看不到「哪个软件吃了多少」，也看不到聊天记录和 AI 残留。
这版拆成四页，新增三个现场扫描模块，全部**不写死路径**（原来的路径都写在
`junk_items.py`，软件一改安装位置就失效）。

### 新增 `deepscan.py` —— C 盘逐个软件拆账

- `scan_app_dirs()`：扫 Local / Roaming / 用户目录下每个点目录 / ProgramData /
  Program Files 里的**每个**软件目录，现场判断哪些子目录是缓存/日志/临时/崩溃转储，
  算出「这个软件总共占多少 / 其中多少能清」。实测 5.5 秒扫完 204 个软件，
  合计 146.2 GB，可清 28.5 GB
- `scan_system_heavy()`：Windows 顶层目录 + C 盘根大文件，每项带中文说明
  （WinSxS 为什么不能删、Installer 为什么不能手动动）
- `find_loose()`：全盘找工作区外散落的断点残片、大日志、PyInstaller `_MEI*` 残留
- 页签顶部直接给出盘级账本：`C 盘已用 209.07 GB（Users 84.4 / Windows 38.93 /
  ProgramData 20.09 / Program Files (x86) 14.17）`

### 新增 `chatdata.py` —— QQ / 微信聊天数据细分

- 自动探测：按名字在本地固定盘里深度 ≤3 找 `Tencent Files` / `xwechat_files`，
  不写死 `D:\D\QQ数据`
- QQ NT 版：`nt_data\Pic\<月>\{Ori,Thumb,ThumbTemp}`、`Video\<月>\{Ori,Thumb}`、
  `Ptt\<月>`、`Emoji\{emoji-recv\<月>,personal_emoji,marketface,系统资源}`、
  `File`、`log`、`nt_temp`、`nt_db`
- 微信 4.x：`cache`、`temp`、`msg\attach`、`msg\video`、`msg\file`、`db_storage` 等
- **按月份拆行**，每行可独立勾；缩略图/临时残留标「可清理」，
  原图/视频原片/语音/文件标「需确认」，聊天记录数据库标「不动」
- 实测：QQ 39.54 GB（图片缩略图 2026-10 单月 7.74 GB）、微信 326 MB

### 新增 `aitrash.py` —— AI 软件残留

- 按 `AI_HINTS` 关键词现场识别 19 个 AI 软件目录（ComfyUI / Saber-Translator /
  IndexTTS / Trae / ZCode / WorkBuddy / dsh-desktop / realesrgan …），
  合计 167 GB
- 拆出：各软件的缓存/日志/`__pycache__`/`.git`、产出目录（output/input）、
  模型目录（标「不动」）
- 专门的 AI 助手隐藏工作区清单：`.cache\codex-runtimes` 3.07 GB、
  `.zcode\workspace` 5.72 GB、`.workbuddy\workspace` 2.82 GB、
  `.codex\.tmp` 153.8 MB、`ms-playwright` 1.37 GB …
- 半成品：0 字节图片/视频、`.tmp/.part/.crdownload` 断点、装完没删的解压安装包

### 修了一个会删错盘的 bug

Windows 上 Python 的 `is_dir(follow_symlinks=False)` 对**目录联接（junction）
仍然返回 True**，导致：

1. 统计时把联接目标算进当前盘 —— `C:\...\Android\Sdk` 实际联到 `D:\D\android-sdk`，
   C 盘因此虚报了 11.7 GB（修完 146.2 GB → 133.0 GB 才是对的）
2. **更要命的是清理时会跟进去删** —— 清 C 盘的目录可能删掉 D 盘上的真实文件

修法：`deepscan._is_link_entry()` / `scanner.path_size()` / `cleaner._is_link()`
统一检查 `FILE_ATTRIBUTE_REPARSE_POINT`，统计跳过、删除跳过。
`_rm_tree` 的 `os.walk` 也显式剔除联接目录。

### 新增清理项（快速清理页 45 → 61 项）

- 系统级临时目录 `C:\Windows\SystemTemp`（2.77 GB，里面躺着一个
  **2.7 GB 的 Chrome BITS 更新残片** `BITBC64.tmp`）
- Electron 应用更新包残留 `%LOCALAPPDATA%\*-updater`（17 个目录 3.16 GB）
- PyInstaller 打包残留 `_MEI*`（35 个 1.02 GB）
- Codex 运行时缓存 `~\.cache\codex-runtimes`（3.07 GB）、`~\.codex\.tmp`
- Playwright 浏览器内核（1.37 GB，标需确认）
- 罗技 G HUB 缓存和更新包（1.43 GB）
- Slimjet 站点数据 Service Worker（1.43 GB，标需确认）
- Android 模拟器镜像 AVD（5.77 GB，标需确认）
- Windows 搜索索引（2.12 GB，标需确认）
- Windows Installer 补丁缓存（5.74 GB，标需确认，说明里写明别手动删）
- WinSxS 组件仓库 → 新增 `kind="dism"`，走 `DISM /StartComponentCleanup`
  （11.45 GB，实际能腾多少跑完才知道，所以不参与「已选合计」）
- 新增 E 盘、L 盘回收站（**E 盘回收站实测 16.4 GB**，是这次最大的单项收获）
- NVIDIA DLSS 模型 NGX、系统页面文件 → 归入「只看」

### 界面

- 自绘页签（不用 ttk.Notebook，深色主题下 Notebook 样式太丑）
- 每页独立的勾选状态，切页不串
- 新增「打开位置」按钮 + **双击任意一行直接打开文件夹**
- 顶部常驻显示 C 盘已用/剩余，清完自动刷新
- 名称列加宽到 520（自适应拉伸），分类列宽度调整，不挤在一堆

---

## v1.0.1 — 2026-11-02

### 换图标

- 原图标是灰白线条垃圾桶，没颜色记忆点，跟"清理"软件的辨识度不够
- 新图标：深色圆角底 + 蓝色实心垃圾桶 + 白色桶盖 + 右上白色四角星（表示清理后焕新）
- **多尺寸分级绘制**：16 / 24 / 32 用简化版（去掉竖纹和星星，线加粗、桶加大），
  48 以上用完整版。不靠缩放糊出来，小尺寸下依然认得出是个垃圾桶
- ICO 手工打包 7 档（16/24/32/48/64/128/256），每档单独渲染 PNG 再写进 ico
- exe 资源图标已验证：提取出来是蓝桶

---

## v1.0.0 — 2026-11-02

### 首版

- 扫描 C、D 两盘，共 45 条清理项定义（实际能扫出 41 项有内容）
- 三类处理建议：可清理 / 需确认 / 不动
- 每项带完整说明：是什么、删了会怎样、实际路径
- 选中行在下方详情区展开说明
- 支持全选安全项、反选、全部取消、重新扫描
- 清理前二次确认（列出前 9 项 + 其余项数汇总）
- 清理后自动重扫，状态栏报告释放量
- 清理日志落到 `%LOCALAPPDATA%\DiskJunkCleaner\log\`
- 单文件 exe，双击即用，自动请求管理员权限
- 深色界面，标题栏一并压成深色

### 收录的清理项

**临时文件**：用户 Temp、Windows Temp、缩略图缓存、崩溃转储、小内存转储、Prefetch、系统日志

**回收站**：C 盘、D 盘

**开发缓存**：pnpm store、npm、NuGet/VS、pip、Electron 下载缓存

**浏览器缓存**：Slimjet、Chrome、Edge、赶稿浏览器、风之影（D 盘）、Steam 网页缓存

**应用缓存**：NVIDIA 着色器、剪映、钉钉、豆包、阿里云盘、ZCode、DSH 桌面端、Chromaprint3D、OhMyMeme、Games、哔哩哔哩直播姬、PlatformProcess、AnycubicSlicer 各版本、弹弹play、MaaEnd

**需确认**：系统还原点、Package Cache、UWP 应用数据、WPS 数据、腾讯管家

**只看**：MuMu 模拟器虚拟磁盘、雷电模拟器、鹰角、QQ 数据、Steam 游戏库
