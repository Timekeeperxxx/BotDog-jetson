@echo off
REM ========================================
REM 快速启动视频处理系统
REM ========================================

echo.
echo ========================================
echo BotDog 视频处理系统
echo ========================================
echo.

REM 检查虚拟环境
if exist "venv\Scripts\activate.bat" (
    echo [1/4] 激活虚拟环境...
    call venv\Scripts\activate.bat
    echo ✓ 虚拟环境已激活
) else (
    echo ✗ 虚拟环境不存在
    echo 请先创建虚拟环境: python -m venv venv
    pause
    exit /b 1
)

REM 检查 GStreamer
echo.
echo [2/4] 检查 GStreamer...
where gst-inspect-1.0 >nul 2>&1
if %errorLevel% equ 0 (
    echo ✓ GStreamer 已安装
    gst-inspect-1.0 --version
) else (
    echo ✗ GStreamer 未找到
    echo 请先安装 GStreamer 并运行 setup_gstreamer_env.bat
    pause
    exit /b 1
)

REM 检查关键插件
echo.
echo [3/4] 检查 GStreamer 插件...
gst-inspect-1.0 d3d11h265dec >nul 2>&1
if %errorLevel% equ 0 (
    echo ✓ d3d11h265dec 插件可用
) else (
    echo ✗ d3d11h265dec 插件不可用
    echo 请安装完整的 GStreamer 插件包
    pause
    exit /b 1
)

gst-inspect-1.0 x264enc >nul 2>&1
if %errorLevel% equ 0 (
    echo ✓ x264enc 插件可用
) else (
    echo ✗ x264enc 插件不可用
    echo 请安装 gst-plugins-ugly
    pause
    exit /b 1
)

REM 启动系统
echo.
echo [4/4] 启动视频处理系统...
echo.
echo ========================================
echo.

python backend/main.py

echo.
echo ========================================
echo 系统已停止
echo ========================================
echo.

pause
