"""桌面划词翻译（mouse-translate）。

模块划分：
    config      配置读写
    icons       托盘/程序图标生成
    win32api    Win32 钩子、托盘、热键、剪贴板、输入注入
    capture     选区抓取与文本清洗
    translate   多免费引擎翻译
    popup       tkinter 浮窗与启动对话框
    app         控制器（状态机 + 事件分发）
"""
