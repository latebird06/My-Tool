# 桌面划词翻译

选中英文 → 松开鼠标 → 自动弹出中文译文。常驻托盘，可随时切换到「挂机」暂停监听。
纯 Python 标准库实现（tkinter + ctypes），**无需安装任何第三方包**。

---

## 1. 启动方式

| 方式 | 说明 |
| --- | --- |
| 双击桌面「划词翻译」快捷方式 | 正常使用（无控制台窗口） |
| `pythonw main.py` | 同上，命令行启动 |
| `python main.py --debug` | 调试模式，日志同时输出到控制台 |
| `python main.py --selftest` | 自检（配置/图标/文本处理/剪贴板/引擎），不启动 GUI |
| `python main.py --smoke` | 冒烟测试：起托盘 3 秒后自动退出 |

启动时会弹窗选择 **常驻** 或 **挂机**；勾选「记住选择」后下次直接进入上次的状态。
托盘右键可随时切换，左键单击快速切换。

## 2. 常驻 vs 挂机

| 状态 | 行为 |
| --- | --- |
| 常驻 | 安装全局鼠标钩子 + 注册热键；拖选文字后自动翻译 |
| 挂机 | 卸载钩子、注销热键；只留托盘图标，CPU 占用≈0 |

## 3. 使用

1. 进入常驻，用鼠标拖选一段英文（浏览器、Word、PDF 阅读器、CAD 说明文字等）；
2. 松开鼠标后约 0.3 秒，光标旁弹出译文浮窗；
3. 浮窗可以：**复制译文**、**重新翻译**、**固定**（固定后点击外部不会自动关闭）、拖动标题栏移动位置；
4. `Esc` 或点击浮窗外部关闭；不点「固定」时点外部即关。

托盘菜单：

- 常驻 / 挂机（单选）
- 翻译剪贴板内容（热键 `Ctrl+Alt+T`）
- 测试翻译引擎（逐个探测，结果弹窗）
- 重新载入配置
- 打开配置文件夹
- 退出

## 4. 翻译引擎

按 `config.json` 里 `providers` 的顺序依次尝试，第一个成功的生效：

| 引擎 | 说明 |
| --- | --- |
| `bing` | 必应网页翻译（`cn.bing.com`，国内可直连，速度 1~3 秒，长文质量好）**默认主力** |
| `mymemory` | MyMemory 免费接口，单次 450 字符，作兜底；有每日匿名额度限制 |
| `google` | Google gtx 接口，仅在能访问 Google 的网络下可用 |

想调整顺序就改 `providers`，例如 `["mymemory", "bing"]`。

## 5. 配置

位置：`%APPDATA%\MouseTranslate\config.json`，改完在托盘点「重新载入配置」即可生效。

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `mode` | `"on"` | 上次选择的状态：`on` 常驻 / `idle` 挂机 |
| `ask_mode_on_start` | `true` | 启动时是否弹选择窗 |
| `auto_translate` | `true` | 松开鼠标即翻译；`false` 时只响应托盘/热键 |
| `min_chars` | `4` | 少于该字数的选区忽略 |
| `max_chars` | `20000` | 超过则截断（浮窗底部会提示） |
| `min_drag_px` | `6` | 拖动像素阈值，低于该值视为点击 |
| `cooldown_ms` | `700` | 两次自动翻译的最小间隔 |
| `skip_if_cjk` | `true` | 中文为主的选区不翻译（避免中译中） |
| `providers` | `["bing","mymemory","google"]` | 引擎顺序 |
| `source_lang` | `"auto"` | 源语言，`auto` 自动识别 |
| `target_lang` | `"zh-CN"` | 目标语言 |
| `request_timeout_s` | `9` | 单请求超时 |
| `restore_clipboard` | `true` | 抓取后还原原剪贴板文本 |
| `popup_width` | `640` | 浮窗宽度（像素） |
| `popup_max_height` | `560` | 浮窗最大高度（像素） |
| `font_family` | `"Microsoft YaHei UI"` | 字体 |
| `font_size_px` | `-15` | 字号（负数=像素） |
| `cache_size` | `200` | 译文缓存条数 |

日志：`%APPDATA%\MouseTranslate\logs\app.log`（1 MB 滚动，保留 2 份）。

## 6. 已知限制

1. **管理员权限的窗口**（部分 CAD / ANSYS / 以管理员运行的程序）会忽略本程序注入的
   `Ctrl+C`，需要本程序也以管理员身份运行；
2. **终端、部分 PDF 阅读器**里 `Ctrl+C` 不是"复制"，抓不到文字（可用
   `Ctrl+Alt+T` 先自行复制再翻译剪贴板）；
3. 全屏独占游戏窗口不触发钩子；
4. 抓取依赖剪贴板：若原剪贴板里是图片/文件（非文本），该内容无法还原；
5. 免费接口可能被限流或临时失效，用「测试翻译引擎」能立刻看出是哪个引擎的问题；
6. 首次启动若 Windows 询问网络访问（防火墙），请允许，否则翻译会失败。

## 7. 目录结构

```
mouse-translate/
  main.py                 入口（单实例、自检、冒烟）
  app/
    config.py             配置读写
    icons.py              图标生成（纯代码画 ICO）
    win32api.py           钩子/托盘/热键/剪贴板/SendInput
    capture.py            选区抓取 + 文本清洗
    translate.py          必应 / MyMemory / Google 引擎
    popup.py              翻译浮窗 + 启动选择窗
    app.py                控制器
  assets/                 tray_on.ico / tray_off.ico / app.ico
  tools/
    make_icons.py         预生成图标
  install_shortcut.ps1    创建/重建桌面快捷方式
  启动调试.cmd            带控制台的调试启动
```

开发期的临时诊断脚本（`debug_*.py`、`test_*.py`）只保留在源码工作副本里，
发布目录不包含，可随时删除。

## 8. 重建桌面快捷方式

```powershell
powershell -ExecutionPolicy Bypass -File .\install_shortcut.ps1
# 开机自启：
powershell -ExecutionPolicy Bypass -File .\install_shortcut.ps1 -Startup
```

## 9. 卸载

1. 托盘右键 → 退出；
2. 删除 `mouse-translate` 目录、桌面快捷方式；
3. 删除 `%APPDATA%\MouseTranslate`（配置与日志）。
