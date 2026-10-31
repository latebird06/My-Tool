# 划词翻译（mouse-translate）

Windows 桌面小工具：**选中英文 → 松开鼠标 → 光标旁弹出中文译文**。
常驻系统托盘，可随时切到「挂机」暂停监听。

纯 Python 标准库实现（tkinter + ctypes），**无需安装任何第三方包**。

## 运行

```bat
pythonw main.py
```

首次运行可执行 `install_shortcut.ps1` 生成桌面快捷方式：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_shortcut.ps1
```

## 用法

1. 启动后选择 **常驻**（勾「记住选择」则下次直接进入）；
2. 用鼠标拖选一段英文，松手后约 0.3 秒弹出译文；
3. 点浮窗外部或 Esc 关闭；托盘右键可切换常驻/挂机、翻译剪贴板（`Ctrl+Alt+T`）、测试引擎、退出。

## 翻译引擎

按 `bing → mymemory → google` 顺序自动降级，全部免 key：

| 引擎 | 说明 |
| --- | --- |
| `bing` | 必应网页翻译，国内直连，1~3 秒 |
| `mymemory` | MyMemory，单次 450 字符，兜底 |
| `google` | 仅在能访问 Google 的网络可用 |

## 配置

`%APPDATA%\MouseTranslate\config.json`，修改后在托盘点「重新载入配置」。
常用项：`providers`（引擎顺序）、`auto_translate`、`min_chars`、`popup_width`。

## 自检

```bat
python main.py --selftest
```

## 已知限制

- 以管理员权限运行的窗口抓不到选区（需本程序也以管理员身份运行）；
- 终端、部分 PDF 阅读器里 `Ctrl+C` 不是复制，抓不到文字（可先自行复制，再按 `Ctrl+Alt+T`）。
