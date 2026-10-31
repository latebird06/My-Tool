@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在以调试模式启动划词翻译（关闭此窗口即退出程序）...
echo.
python main.py --debug
if errorlevel 1 (
    echo.
    echo 启动失败，请把上面的错误信息发给我。
)
pause
