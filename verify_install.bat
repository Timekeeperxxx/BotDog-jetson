@echo off
REM ========================================
REM 安装验证脚本
REM ========================================

echo.
echo ========================================
echo 环境验证工具
echo ========================================
echo.

REM 激活虚拟环境
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo ✅ 虚拟环境已激活
) else (
    echo ⚠️  虚拟环境不存在
    echo 请先运行: install_python_deps.bat
    pause
    exit /b 1
)

echo.
echo ========================================
echo 检查 GStreamer
echo ========================================
echo.

where gst-inspect-1.0 >nul 2>&1
if %errorLevel% equ 0 (
    echo ✅ GStreamer 已安装
    gst-inspect-1.0 --version
) else (
    echo ❌ GStreamer 未找到
    echo 请运行: install_gstreamer.bat
    goto :end
)

echo.
echo 检查关键插件...
echo.

gst-inspect-1.0 d3d11h265dec >nul 2>&1
if %errorLevel% equ 0 (
    echo ✅ d3d11h265dec (D3D11 硬件解码器)
) else (
    echo ❌ d3d11h265dec 插件缺失
    echo 请重新安装 GStreamer (Complete 安装)
)

gst-inspect-1.0 x264enc >nul 2>&1
if %errorLevel% equ 0 (
    echo ✅ x264enc (H.264 编码器)
) else (
    echo ❌ x264enc 插件缺失
    echo 请安装 gst-plugins-ugly
)

echo.
echo ========================================
echo 检查 Python 依赖
echo ========================================
echo.

python -c "import cv2; print('✅ OpenCV', cv2.__version__)" 2>nul
if %errorLevel% neq 0 echo ❌ OpenCV 未安装

python -c "import numpy; print('✅ NumPy', numpy.__version__)" 2>nul
if %errorLevel% neq 0 echo ❌ NumPy 未安装

python -c "import av; print('✅ PyAV', av.__version__)" 2>nul
if %errorLevel% neq 0 echo ❌ PyAV 未安装

python -c "import aiortc; print('✅ aiortc 已安装')" 2>nul
if %errorLevel% neq 0 echo ❌ aiortc 未安装

echo.
echo ========================================
echo 运行诊断测试
echo ========================================
echo.

python diagnose_environment.py

echo.
echo ========================================
echo 验证完成
echo ========================================
echo.

:end
pause
