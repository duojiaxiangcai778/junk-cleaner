# -*- coding: utf-8 -*-
"""
磁盘垃圾项定义 —— 以后要增减清理项 / 改说明，只改这个文件，然后重新打包。

字段说明
--------
id        唯一标识，清理日志里会用它
name      列表里显示的名字
category  分类，用于分组显示
paths     路径列表；支持 %ENVVAR% 环境变量和 * 通配符
kind      dir     清空目录里的内容（保留目录本身）
          file    删除文件
          recycle 清空指定盘的回收站
level     safe    可安全清理，默认勾选
          caution 有代价，默认不勾，要你手动点
          view    只展示，不可删（比如游戏本体、模拟器虚拟磁盘）
desc      完整说明，显示在下方详情区。写清楚「这是啥 / 删了会怎样」

想加新项：照抄一条，把 id 换成没重复的，路径和说明填上即可。
"""

ITEMS = [
    # ========== 临时文件 ==========
    dict(
        id="temp_user", name="用户临时文件", category="临时文件", level="caution",
        kind="dir", paths=[r"%LOCALAPPDATA%\Temp"],
        desc=r"位置 C:\Users\Administrator\AppData\Local\Temp。程序运行、安装包解压、软件更新时丢的临时文件。"
             r"⚠️ v2.3.0 起改成「需确认」：这个目录不全是垃圾 —— 正在运行的软件、"
             r"安装到一半的程序、部分 Electron 应用的运行状态都放在这，全清可能让它们丢未保存的东西。"
             r"被占用的文件本来就会自动跳过；想清就自己勾，不建议天天清。",
    ),
    dict(
        id="temp_win", name="Windows 临时文件", category="临时文件", level="safe",
        kind="dir", paths=[r"C:\Windows\Temp"],
        desc=r"位置 C:\Windows\Temp。系统服务和安装程序用的临时目录。可清，个别文件被系统占用时会跳过。",
    ),
    dict(
        id="thumb_cache", name="缩略图 / 图标缓存", category="临时文件", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db",
                           r"%LOCALAPPDATA%\Microsoft\Windows\Explorer\iconcache_*.db"],
        desc=r"资源管理器为了秒开文件夹而生成的图片/图标缩略图缓存。删了下次浏览文件夹会重新生成，"
             r"只是第一次会稍慢一点点。注意要关掉资源管理器才删得干净，删不掉会自动跳过。",
    ),
    dict(
        id="crashdump", name="程序崩溃转储", category="临时文件", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\CrashDumps"],
        desc=r"位置 %LOCALAPPDATA%\CrashDumps。软件崩溃时生成的内存转储文件，用于排查问题。"
             r"你不需要给谁做技术支持，直接删。",
    ),
    dict(
        id="minidump", name="系统小内存转储", category="临时文件", level="safe",
        kind="dir", paths=[r"C:\Windows\Minidump", r"C:\Windows\MEMORY.DMP"],
        desc=r"蓝屏时系统自动写下的崩溃内存镜像。除非你要人帮你看蓝屏原因，否则没用，可删。",
    ),
    dict(
        id="prefetch", name="预读文件 Prefetch", category="临时文件", level="safe",
        kind="dir", paths=[r"C:\Windows\Prefetch"],
        desc=r"Windows 记录程序启动时读了哪些文件，下次启动同款程序能快一点。删了会自动重建，"
             r"代价是之后几天软件首次启动稍慢。嫌占地方就清。",
    ),
    dict(
        id="sys_logs", name="系统日志", category="临时文件", level="safe",
        kind="dir", paths=[r"C:\Windows\Logs\CBS", r"C:\Windows\Logs\DISM", r"C:\Windows\Logs\MoSetup"],
        desc=r"系统更新、组件安装时写的日志。你要排查更新失败才有用，平时就是纯占地方。可删。",
    ),

    dict(
        id="temp_system", name="系统级临时目录 SystemTemp", category="临时文件", level="safe",
        kind="dir", paths=[r"C:\Windows\SystemTemp"],
        desc=r"位置 C:\Windows\SystemTemp。比 C:\Windows\Temp 更底层，Windows 更新、"
             r"浏览器组件自动更新（Chrome / Edge 的 BITS 下载）都往这里丢。"
             r"实测里面躺着一个 2.7 GB 的浏览器更新残片，纯垃圾。可清。",
    ),
    dict(
        id="updater_residue", name="Electron 应用更新包残留", category="临时文件", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\*-updater", r"%LOCALAPPDATA%\*Updater"],
        desc=r"位置 %LOCALAPPDATA%\*-updater。各种 Electron 桌面端（Cursor / Trae / ZCode / "
             r"WorkBuddy / Upscayl / Vortex 等十几个）更新时下载的完整安装包，装完从不自己删。"
             r"实测 17 个目录合计 3.16 GB。删了完全没影响，下次更新重新下。"
             r"注意：DSH 等编辑器的更新目录会自动跳过，不动它们。",
    ),
    dict(
        id="mei_residue", name="PyInstaller 打包残留（_MEI*）", category="临时文件", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\EmuToolCache\_MEI*",
                           r"%LOCALAPPDATA%\AutoShutdownToolCache\_MEI*",
                           r"%LOCALAPPDATA%\Temp\_MEI*"],
        desc=r"Python 打包成 exe（PyInstaller）的软件运行时会把内部文件解压到 _MEI****** 目录，"
             r"正常退出会自己删，但被强杀 / 崩溃过就留下了。实测 35 个目录约 1 GB。纯垃圾。",
    ),

    # ========== 回收站 ==========
    dict(
        id="recycle_c", name="C 盘回收站", category="回收站", level="safe",
        kind="recycle", paths=["C:\\"],
        desc=r"你删除过、但还没真正消失的文件。清空后没法恢复，删之前想清楚里面有没有还要的东西。",
    ),
    dict(
        id="recycle_d", name="D 盘回收站", category="回收站", level="safe",
        kind="recycle", paths=["D:\\"],
        desc=r"同上，D 盘的回收站。清空后不可恢复。",
    ),
    dict(
        id="recycle_e", name="E 盘回收站", category="回收站", level="safe",
        kind="recycle", paths=["E:\\"],
        desc=r"同上，E 盘的回收站。清空后不可恢复。",
    ),
    dict(
        id="recycle_l", name="L 盘回收站", category="回收站", level="safe",
        kind="recycle", paths=["L:\\"],
        desc=r"同上，L 盘的回收站。清空后不可恢复。",
    ),

    # ========== 开发缓存 ==========
    dict(
        id="pnpm_store", name="pnpm 包存储（禁止清理）", category="开发缓存", level="view",
        kind="dir", paths=[r"%LOCALAPPDATA%\pnpm\store", r"D:\.pnpm-store"],
        desc=r"这里放 pnpm 下载过的 npm 包。"
             r"⚠️ v2.3.0 起改成「不动」，原因有两个："
             r"① 这些包和 node_modules 是同一个磁盘数据的两份名字（硬链接），删了这份几乎不释放空间；"
             r"② DSH / Trae / Cursor / ZCode 这些 Electron 应用的插件全都用 pnpm 装，"
             r"store 一旦被清，它们下次启动会校验失败、清空自己的 node_modules，"
             r"插件全部失效（2026-11-03 已经真实踩过一次）。所以只展示，不清理。",
    ),
    dict(
        id="npm_cache", name="npm 缓存", category="开发缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\npm-cache"],
        desc=r"npm 下载包的缓存。删了不影响已装的包，只影响下次安装速度。",
    ),
    dict(
        id="nuget_cache", name="NuGet / Visual Studio 缓存", category="开发缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\NuGet\v3-cache", r"%LOCALAPPDATA%\NuGet\Cache"],
        desc=r"Visual Studio / .NET 项目下载过的 NuGet 包缓存。删了下次编译会重新拉，网络好就没痛感。",
    ),
    dict(
        id="pip_cache", name="pip 缓存", category="开发缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\pip\Cache"],
        desc=r"pip 装的 Python 包安装包缓存。删了不影响已装的库，只是下次 pip install 要重新下载。",
    ),
    dict(
        id="electron_cache", name="Electron 下载缓存", category="开发缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\electron\Cache"],
        desc=r"Electron 运行时（Chromium 内核包）的下载缓存。做过 Electron 项目才会用到，删了下次构建重新下。",
    ),
    dict(
        id="codex_runtimes", name="Codex 运行时缓存", category="开发缓存", level="safe",
        kind="dir", paths=[r"%USERPROFILE%\.cache\codex-runtimes"],
        desc=r"位置 %USERPROFILE%\.cache\codex-runtimes。Codex CLI 每跑一次就下载一份新的 "
             r"Node / Python 运行时，旧的从来不清，实测 3.07 GB。删了下次运行会重新下。",
    ),
    dict(
        id="codex_tmp", name="Codex 临时文件", category="开发缓存", level="safe",
        kind="dir", paths=[r"%USERPROFILE%\.codex\.tmp"],
        desc=r"位置 %USERPROFILE%\.codex\.tmp。Codex 执行命令时的中转文件，实测 153 MB。纯垃圾。",
    ),
    dict(
        id="playwright_cache", name="Playwright 浏览器内核", category="开发缓存", level="caution",
        kind="dir", paths=[r"%LOCALAPPDATA%\ms-playwright"],
        desc=r"位置 %LOCALAPPDATA%\ms-playwright。Python / Node 的自动化测试框架会下载好几套 Chromium、"
             r"Firefox、WebKit 内核，实测 1.4 GB。你还跑自动化脚本就别清，只是普通浏览的话清了没事，"
             r"下次跑脚本会自己重新下。",
    ),

    # ========== 浏览器 ==========
    dict(
        id="slimjet_cache", name="Slimjet 浏览器缓存", category="浏览器缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\Slimjet\User Data\Default\Cache",
                           r"%LOCALAPPDATA%\Slimjet\User Data\Default\Code Cache",
                           r"%LOCALAPPDATA%\Slimjet\User Data\Default\GPUCache"],
        desc=r"风之影浏览器（Slimjet）的网页缓存和 JS 代码缓存。删了网页要重新下资源，"
             r"登录状态、书签、密码都不受影响。",
    ),
    dict(
        id="chrome_cache", name="Chrome 浏览器缓存", category="浏览器缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache",
                           r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Code Cache"],
        desc=r"Chrome 网页缓存。删了不影响登录状态和书签，只是常逛的网站第一次加载慢一点。",
    ),
    dict(
        id="edge_cache", name="Edge 浏览器缓存", category="浏览器缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache",
                           r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Code Cache"],
        desc=r"Edge 网页缓存。删了同样不影响登录和收藏。",
    ),
    dict(
        id="genpao_cache", name="赶稿浏览器缓存", category="浏览器缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\GenPaoBrowser_Data\EBWebView\Default\Cache"],
        desc=r"赶稿浏览器（Electron 内核）的网页缓存。可删。",
    ),
    dict(
        id="fengzhiying_cache", name="风之影浏览器缓存（D 盘）", category="浏览器缓存", level="safe",
        kind="dir", paths=[r"D:\E\风之影浏览器 (64bit)\default\Cache",
                           r"D:\E\风之影浏览器 (64bit)\default\Code Cache"],
        desc=r"D 盘那份风之影浏览器的缓存。同样是网页缓存，删了不影响使用。",
    ),
    dict(
        id="steam_htmlcache", name="Steam 网页缓存", category="浏览器缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\Steam\htmlcache\Default\Cache"],
        desc=r"Steam 客户端内置浏览器的缓存。删了 Steam 商店页首次加载慢一点，游戏库不受影响。",
    ),

    # ========== 应用缓存 ==========
    dict(
        id="nvidia_dxcache", name="NVIDIA 着色器缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\NVIDIA\DXCache", r"%LOCALAPPDATA%\NVIDIA\GLCache"],
        desc=r"显卡把游戏/软件的着色器编译结果存这里，下次进游戏少卡一点。删了会自动重建，"
             r"代价是清完后第一次进游戏或视频软件会卡顿一下重新编译。",
    ),
    dict(
        id="jianying_cache", name="剪映缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\JianyingPro\User Data\Cache"],
        desc=r"剪映的素材预览缓存。删了不影响已保存的工程，只是打开工程要重新生成预览。",
    ),
    dict(
        id="dingtalk_cache", name="钉钉缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%APPDATA%\DingTalk\cache", r"%APPDATA%\DingTalk\Cache"],
        desc=r"钉钉的图片、文件预览缓存。删了不影响聊天记录（那在服务端和另一个目录），"
             r"只是旧图片要重新加载。",
    ),
    dict(
        id="doubao_cache", name="豆包缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\DoubaoWork\User Data\Default\Cache",
                           r"%LOCALAPPDATA%\DoubaoWork\User Data\Default\Code Cache"],
        desc=r"豆包桌面端（Electron 内核）的网页缓存。可删。",
    ),
    dict(
        id="adrive_cache", name="阿里云盘缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%APPDATA%\aDrive\Cache"],
        desc=r"阿里云盘客户端的缩略图和文件列表缓存。删了要重新拉一次云端列表，不影响已下载的文件。",
    ),
    dict(
        id="zcode_cache", name="ZCode 缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%APPDATA%\ZCode\session\Partitions\zcode-embedded-browser\Cache",
                           r"%APPDATA%\ZCode\session\Partitions\zcode-embedded-browser\Code Cache"],
        desc=r"ZCode 内置浏览器的缓存。可删，不影响 ZCode 的会话记录。",
    ),
    dict(
        id="dsh_cache", name="DSH 桌面端缓存（禁止清理）", category="应用缓存", level="view",
        kind="dir", paths=[r"%APPDATA%\dsh-desktop\Cache", r"%APPDATA%\dsh-desktop\Code Cache"],
        desc=r"DSH Desktop 的网页缓存。v2.3.0 起改成「不动」：这 200 多 MB 清了也没多少收益，"
             r"而 DSH 运行中清它的 Cache 会失败、还可能让界面重载，"
             r"连带把它整个数据目录（harness / profiles / 插件 / 会话）划进危险区不值当。"
             r"只展示，不清理。",
    ),
    dict(
        id="chromaprint_cache", name="Chromaprint3D 缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%APPDATA%\chromaprint3d\Cache"],
        desc=r"Chromaprint3D 的网页缓存。可删。",
    ),
    dict(
        id="ohmy_meme_cache", name="OhMyMeme 缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\OhMyMeme\cache"],
        desc=r"OhMyMeme 的图片缓存。删了表情包要重新加载，不影响你存的收藏。",
    ),
    dict(
        id="games_cache", name="Games 目录缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\Games\*\cache"],
        desc=r"某些小游戏 / 网页游戏在本机留的缓存。删了游戏要重新加载资源。",
    ),
    dict(
        id="bililive_cache", name="哔哩哔哩直播姬缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\bililive\User Data\Cache"],
        desc=r"直播姬的网页缓存。删了不影响你的直播配置和录制文件。",
    ),
    dict(
        id="platform_cache", name="PlatformProcess 缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\PlatformProcess\Cache"],
        desc=r"某个带内置浏览器的客户端留下的通用缓存目录。可删。",
    ),
    dict(
        id="anycubic_cache", name="AnycubicSlicer 各版本缓存", category="应用缓存", level="safe",
        kind="dir", paths=[r"%LOCALAPPDATA%\AnycubicSlicerNext\*\EBWebView\Default\Cache",
                           r"%LOCALAPPDATA%\AnycubicSlicerNext\*\EBWebView\Default\Code Cache"],
        desc=r"Anycubic 切片软件每个版本自带的浏览器缓存（1.4.1.2 / 2.0.0.x 各一份）。"
             r"只清缓存，不碰你的切片文件和打印参数。旧版本整个目录也可以删，但这里只清缓存最稳。",
    ),
    dict(
        id="dandanplay_cache", name="弹弹play 缓存（D 盘）", category="应用缓存", level="safe",
        kind="dir", paths=[r"D:\D\弹弹play\Cache"],
        desc=r"弹弹play 的弹幕和视频缓存。删了不影响已建库的收藏，只是重新播放要重新拉弹幕。",
    ),
    dict(
        id="maaend_cache", name="MaaEnd 缓存（D 盘）", category="应用缓存", level="safe",
        kind="dir", paths=[r"D:\E\MaaEnd-win\cache"],
        desc=r"MaaEnd 的运行时缓存。可删，下次启动自动重建。",
    ),

    dict(
        id="lghub_cache", name="罗技 G HUB 缓存和更新包", category="应用缓存", level="safe",
        kind="dir", paths=[r"C:\ProgramData\LGHUB\cache", r"C:\ProgramData\LGHUB\depots"],
        desc=r"罗技 G HUB 的固件/驱动缓存和更新包 depot，实测各 713 MB。删了不影响你设的侧键宏"
             r"和 DPI 配置（那些存在别处），下次打开软件会按需重新下。",
    ),
    dict(
        id="slimjet_sw", name="Slimjet 站点数据（Service Worker）", category="需谨慎", level="caution",
        kind="dir", paths=[r"%LOCALAPPDATA%\Slimjet\User Data\Default\Service Worker",
                           r"%LOCALAPPDATA%\Slimjet\User Data\Default\IndexedDB"],
        desc=r"Slimjet（风之影）的离线网页数据和站点数据库，实测 1.43 GB。删了常逛的网站"
             r"第一次打开要重新加载，个别站点的离线功能要重新授权。登录状态不受影响。",
    ),
    dict(
        id="android_avd", name="Android 模拟器镜像（AVD）", category="需谨慎", level="caution",
        kind="dir", paths=[r"%USERPROFILE%\.android\avd"],
        desc=r"位置 %USERPROFILE%\.android\avd。Android Studio 建的虚拟手机镜像，实测 5.6 GB。"
             r"你要用 Android Studio 调试 App 就得留着；只是以前装过 Android Studio 现在不用了，"
             r"整个清掉能省一大块。清之前先在 Android Studio 的 Device Manager 里确认。",
    ),
    dict(
        id="search_index", name="Windows 搜索索引", category="需谨慎", level="caution",
        kind="dir", paths=[r"C:\ProgramData\Microsoft\Search\Data"],
        desc=r"Windows 给文件、邮件、开始菜单做全文搜索的索引库，实测 2.1 GB。删了系统会重建"
             r"（重建期间 CPU 会忙一阵），搜索功能会暂时不可用。不常用开始菜单搜索的可以清。",
    ),
    dict(
        id="windows_installer", name="Windows Installer 补丁缓存", category="需谨慎", level="caution",
        kind="dir", paths=[r"C:\Windows\Installer"],
        desc=r"位置 C:\Windows\Installer，实测 5.6 GB。MSI 安装包的补丁/回滚缓存。"
             r"⚠️ 这个目录绝对不要手动删文件 —— 删错会导致已装软件无法卸载、无法修复。"
             r"这里只提供「看」和清理工具自动识别的孤立补丁包，真正的安全做法是用"
             r"微软官方工具 PatchCleaner，或者干脆别动。默认不勾。",
    ),
    dict(
        id="winsxs", name="WinSxS 组件仓库（DISM 清理）", category="需谨慎", level="caution",
        kind="dism", paths=[],
        desc=r"C:\Windows\WinSxS，实测 11.2 GB，是 C 盘最大的单个目录。里面是系统更新留下的旧版本"
             r"组件。⚠️ 直接删 = 系统报废。安全的做法是跑 DISM 的组件清理，它会删掉"
             r"「被新版本取代、且已过回滚期」的旧组件，通常能省 1～3 GB。要几十秒，期间别关。",
    ),

    # ========== 需谨慎 ==========
    dict(
        id="vss_restore", name="系统还原点", category="需谨慎", level="caution",
        kind="vss", paths=[],
        desc=r"Windows 系统保护自动拍的系统快照，出问题能回滚到这个状态。"
             r"这是 C 盘最大的单个可清项。删掉就彻底失去回滚能力 —— 你要是从不用系统还原，清了最划算。",
    ),
    dict(
        id="package_cache", name="VS / 安装程序包缓存", category="需谨慎", level="caution",
        kind="dir", paths=[r"C:\ProgramData\Package Cache"],
        desc=r"Visual Studio、SDK 等安装器留下的原始安装包。删了省空间，但以后修复安装或卸载"
             r"对应软件时，安装器会要求你重新提供安装包。",
    ),
    dict(
        id="uwp_packages", name="UWP 应用数据", category="需谨慎", level="caution",
        kind="dir", paths=[r"%LOCALAPPDATA%\Packages\*\LocalCache"],
        desc=r"微软商店应用（UWP）的本地缓存。只清 LocalCache 子目录相对安全，但个别应用会丢登录态"
             r"或要重新加载数据。默认不勾，自己判断。",
    ),
    dict(
        id="wps_data", name="WPS Office 数据（D 盘）", category="需谨慎", level="caution",
        kind="dir", paths=[],
        desc=r"D:\D\WPS Office 整个目录。里面可能有文档备份、模板、云文档缓存。"
             r"这里只做展示不做清理 —— 要清请自己在 WPS 里清备份中心。",
    ),
    dict(
        id="tencent_pc_manager", name="腾讯管家（D 盘）", category="需谨慎", level="caution",
        kind="dir", paths=[],
        desc=r"D:\D\腾讯管家 整个目录，是程序本体 + 日志。要省空间就在控制面板卸载，"
             r"直接删目录会留一堆注册表残渣和开机启动项。这里只展示不清理。",
    ),

    # ========== 只看（不动） ==========
    dict(
        id="nvidia_ngx", name="NVIDIA DLSS 模型 NGX", category="只看", level="view",
        kind="dir", paths=[r"C:\ProgramData\NVIDIA\NGX"],
        desc=r"C:\ProgramData\NVIDIA\NGX，实测 4.2 GB。这是 DLSS 超分/帧生成的 AI 模型文件，"
             r"所有支持 DLSS 的游戏共用。删了下次进游戏会重新拉，不划算，别动。",
    ),
    dict(
        id="pagefile", name="系统页面文件", category="只看", level="view",
        kind="dir", paths=[r"C:\pagefile.sys", r"C:\hiberfil.sys", r"C:\swapfile.sys"],
        desc=r"C 盘根目录的 pagefile.sys（虚拟内存，实测 8 GB）、hiberfil.sys（休眠文件）、"
             r"swapfile.sys。都不是垃圾。嫌 C 盘紧可以：把虚拟内存挪到别的盘、"
             r"用管理员 CMD 跑 powercfg /h off 关掉休眠（能立刻释放几 GB）。别手动删。",
    ),

    dict(
        id="mumu_vms", name="MuMu 模拟器虚拟磁盘", category="只看", level="view",
        kind="dir", paths=[r"D:\E\MuMu Player 12\vms"],
        desc=r"D:\E\MuMu Player 12\vms，几个安卓模拟器实例的虚拟硬盘（data.vdi）。"
             r"这是模拟器里的系统和你装的 App，不是缓存。要删请在 MuMu 多开器里删实例，别在这删。",
    ),
    dict(
        id="ldplayer_vms", name="雷电模拟器虚拟磁盘", category="只看", level="view",
        kind="dir", paths=[r"D:\E\LDPlayer9\vms"],
        desc=r"D:\E\LDPlayer9\vms，雷电模拟器的安卓虚拟硬盘。同上，要清请在雷电多开器里删实例。",
    ),
    dict(
        id="arknights", name="鹰角（游戏本体）", category="只看", level="view",
        kind="dir", paths=[r"D:\E\鹰角"],
        desc=r"D:\E\鹰角，明日方舟 / 终末地相关文件。游戏本体，不删。",
    ),
    dict(
        id="steam_lib", name="Steam 游戏库", category="只看", level="view",
        kind="dir", paths=[r"D:\E\steam\steamapps"],
        desc=r"D:\E\steam\steamapps，已安装的游戏本体。要腾空间请在 Steam 里卸载不要的游戏。",
    ),
]
