@echo off
REM ========================================
REM GStreamer 1.24.0 自动下载和安装脚本
REM ========================================

echo.
echo ========================================
echo GStreamer 自动安装脚本
echo ========================================
echo.

REM 检查是否已安装
where gst-inspect-1.0 >nul 2>&1
if %errorLevel% equ 0 (
    echo ✅ GStreamer 已安装
    gst-inspect-1.0 --version
    echo.
    goto :setup_env
)

echo 📥 GStreamer 未安装，开始自动下载...
echo.

REM 下载 URL
set GST_URL=https://gstreamer.freedesktop.org/download/pkg/windows/1.24.0/msvc/gstreamer-1.0-msvc-x86_64.msi

echo 下载地址: %GST_URL%
echo.

REM 检查是否有 curl
where curl >nul 2>&1
if %errorLevel% equ 0 (
    echo 使用 curl 下载...
    curl -L -o gstreamer-1.0-msvc-x86_64.msi %GST_URL%
    if %errorLevel% neq 0 (
        echo ❌ 下载失败
        goto :manual_download
    )
) else (
    echo ❌ 未找到 curl，请手动下载
    goto :manual_download
)

echo.
echo ✅ 下载完成
echo.

REM 安装
echo 🔧 开始安装 GStreamer...
echo.
msiexec /i gstreamer-1.0-msvc-x86_64.msi /qb
if %errorLevel% neq 0 (
    echo ❌ 自动安装失败，请手动运行安装程序
    pause
    exit /b 1
)

echo ✅ GStreamer 安装完成
echo.
goto :setup_env

:manual_download
echo.
echo ========================================
echo 手动下载说明
echo ========================================
echo.
echo 请按照以下步骤手动安装:
echo.
echo 1. 访问下载页面:
echo    https://gstreamer.freedesktop.org/download/
echo.
echo 2. 下载文件:
echo    gstreamer-1.0-msvc-x86_64.msi
echo    (推荐版本: 1.24.0 或更新)
echo.
echo 3. 运行安装程序
echo.
echo 4. 重新运行此脚本
echo.
pause
exit /b 1

:setup_env
echo ========================================
echo 配置环境变量
echo ========================================
echo.

REM 设置 GStreamer 根目录
setx GSTREAMER_1_0_ROOT_MSVC_X86_64 "C:\gstreamer\1.0\msvc_x86_64" /M >nul 2>&1

REM 添加到 PATH
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "CurrentPath=%%b"
echo %CurrentPath% | findstr /i gstreamer >nul
if %errorLevel% neq 0 (
    setx PATH "%PATH%;C:\gstreamer\1.0\msvc_x86_64\bin" /M >nul 2>&1
)

REM 设置当前会话
set GSTREAMER_1_0_ROOT_MSVC_X86_64=C:\gstreamer\1.0\msvc_x86_64
set PATH=%PATH%;C:\gstreamer\1.0\msvc_x86_64\bin

echo ✅ 环境变量已配置
echo.

REM 验证安装
echo ========================================
echo 验证安装
echo ========================================
echo.

gst-inspect-1.0 --version
if %errorLevel% neq 0 (
    echo ❌ GStreamer 验证失败
    echo 请重启命令提示符后重试
    pause
    exit /b 1
)

echo.
echo ✅ GStreamer 安装和配置完成!
echo.
echo ========================================
echo 下一步:
echo ========================================
echo.
echo 1. 关闭此命令提示符
echo 2. 打开新的命令提示符
echo 3. 运行: install_python_deps.bat
echo.
echo ========================================
echo.

pause
