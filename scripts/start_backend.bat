@echo off
REM BotDog Backend 启动脚本 (Windows)

echo ======================================
echo BotDog Backend 启动中...
echo ======================================
echo.

REM 启动后端
.\.venv\Scripts\python.exe run_backend.py

pause
