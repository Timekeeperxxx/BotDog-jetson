@echo off
REM ========================================
REM Python 依赖自动安装脚本
REM ========================================

echo.
echo ========================================
echo Python 依赖安装脚本
echo ========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ 未找到 Python
    echo 请先安装 Python 3.9+
    pause
    exit /b 1
)

echo ✅ Python 已安装
python --version
echo.

REM 检查是否有虚拟环境
if exist "venv\" (
    echo ✅ 虚拟环境已存在
    echo.

    REM 激活虚拟环境
    call venv\Scripts\activate.bat
) else (
    echo 🔧 创建虚拟环境...
    python -m venv venv
    if %errorLevel% neq 0 (
        echo ❌ 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo ✅ 虚拟环境创建成功
    echo.

    REM 激活虚拟环境
    call venv\Scripts\activate.bat
)

echo ✅ 虚拟环境已激活
echo.

REM 升级 pip
echo 🔧 升级 pip...
python -m pip install --upgrade pip >nul 2>&1
echo ✅ pip 已升级
echo.

REM 安装依赖
echo ========================================
echo 安装 Python 依赖
echo ========================================
echo.
echo 这可能需要几分钟...
echo.

pip install -r requirements.txt
if %errorLevel% neq 0 (
    echo ❌ 依赖安装失败
    pause
    exit /b 1
)

echo.
echo ✅ Python 依赖安装完成!
echo.

REM 验证关键依赖
echo ========================================
echo 验证关键依赖
echo ========================================
echo.

python -c "import cv2; print('✅ OpenCV:', cv2.__version__)" 2>nul
if %errorLevel% neq 0 echo ❌ OpenCV 安装失败

python -c "import numpy; print('✅ NumPy:', numpy.__version__)" 2>nul
if %errorLevel% neq 0 echo ❌ NumPy 安装失败

python -c "import av; print('✅ PyAV:', av.__version__)" 2>nul
if %errorLevel% neq 0 echo ❌ PyAV 安装失败

python -c "import aiortc; print('✅ aiortc: 已安装')" 2>nul
if %errorLevel% neq 0 echo ❌ aiortc 安装失败

echo.
echo ========================================
echo 安装完成!
echo ========================================
echo.
echo 下一步:
echo 1. 运行: verify_install.bat
echo 2. 如果验证通过，运行: start_video.bat
echo.
echo ========================================
echo.

pause
