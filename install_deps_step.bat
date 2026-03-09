@echo off
REM ========================================
REM 分步安装 Python 依赖
REM ========================================

echo.
echo ========================================
echo Python 依赖安装脚本（分步版本）
echo ========================================
echo.

REM 激活虚拟环境
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo ❌ 虚拟环境不存在，正在创建...
    python -m venv venv
    call venv\Scripts\activate.bat
)

echo ✅ 虚拟环境已激活
echo.

echo ========================================
echo 安装基础依赖（不需要编译）
echo ========================================
echo.

REM 安装基础包
pip install annotated-doc annotated-types anyio click exceptiongroup
pip install fastapi fastcrc greenlet h11 httptools
pip install idna loguru lxml
pip install pydantic pydantic-settings pydantic-core
pip install pymavlink pyserial python-dotenv PyYAML
pip install SQLAlchemy aiosqlite starlette
pip install typing-inspection typing_extensions
pip install uvicorn watchfiles websockets

echo.
echo ✅ 基础依赖安装完成
echo.

echo ========================================
echo 安装 OpenCV 和 NumPy
echo ========================================
echo.

pip install opencv-python numpy
echo ✅ OpenCV 和 NumPy 安装完成
echo.

echo ========================================
echo 安装测试依赖
echo ========================================
echo.

pip install pytest pytest-asyncio httpx pytest-cov
echo ✅ 测试依赖安装完成
echo.

echo ========================================
echo 尝试安装 av 和 aiortc
echo ========================================
echo.

echo 注意: 如果 av 或 aiortc 安装失败，可能需要安装 Microsoft C++ Build Tools
echo 下载地址: https://visualstudio.microsoft.com/visual-cpp-build-tools/
echo.

pip install av aiortc
if %errorLevel% neq 0 (
    echo.
    echo ⚠️  av 或 aiortc 安装失败
    echo.
    echo 解决方案:
    echo 1. 安装 Microsoft C++ Build Tools
    echo 2. 或者使用较旧的 Python 版本（如 Python 3.11 或 3.12）
    echo.
)

echo.
echo ========================================
echo 安装完成
echo ========================================
echo.

pause
