@echo off
REM ========================================
REM 启动视频处理系统 - 使用 Python 3.10
REM ========================================

echo.
echo ========================================
echo BotDog 视频处理系统 (Python 3.10)
echo ========================================
echo.

REM 使用 Python 3.10 激活虚拟环境
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo ✅ 虚拟环境已激活 (Python 3.10)
) else (
    echo ❌ 虚拟环境不存在
    echo 请先运行安装脚本
    pause
    exit /b 1
)

echo.

REM 快速检查
where gst-inspect-1.0 >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ GStreamer 未安装
    echo 请先运行: install_gstreamer.bat
    pause
    exit /b 1
)

REM 检查插件
gst-inspect-1.0 d3d11h265dec >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ d3d11h265dec 插件不可用
    pause
    exit /b 1
)

echo ========================================
echo 启动系统...
echo ========================================
echo.

python backend/main.py

echo.
echo ========================================
echo 系统已停止
echo ========================================
echo.

pause
