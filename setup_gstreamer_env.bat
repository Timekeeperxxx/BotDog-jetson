@echo off
REM ========================================
REM GStreamer Windows 环境设置脚本
REM ========================================

echo.
echo ========================================
echo GStreamer 环境变量设置
echo ========================================
echo.

REM 检查是否以管理员身份运行
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo 警告: 建议以管理员身份运行此脚本
    echo.
    set /p continue="是否继续? (Y/N): "
    if /i not "%continue%"=="Y" exit /b 1
)

REM 设置 GStreamer 根目录
echo [1/3] 设置 GStreamer 根目录...
setx GSTREAMER_1_0_ROOT_MSVC_X86_64 "C:\gstreamer\1.0\msvc_x86_64" /M
if %errorLevel% equ 0 (
    echo ✓ GSTREAMER_1_0_ROOT_MSVC_X86_64 = C:\gstreamer\1.0\msvc_x86_64
) else (
    echo ✗ 设置失败，可能需要管理员权限
)

REM 添加 GStreamer 到 PATH
echo.
echo [2/3] 添加 GStreamer 到系统 PATH...
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "CurrentPath=%%b"
echo %CurrentPath% | findstr /i gstreamer >nul
if %errorLevel% equ 0 (
    echo ✓ GStreamer 已在 PATH 中
) else (
    setx PATH "%PATH%;C:\gstreamer\1.0\msvc_x86_64\bin" /M
    if %errorLevel% equ 0 (
        echo ✓ 已添加 C:\gstreamer\1.0\msvc_x86_64\bin 到 PATH
    ) else (
        echo ✗ 添加失败，可能需要管理员权限
    )
)

REM 设置当前会话的环境变量
echo.
echo [3/3] 设置当前会话环境变量...
set GSTREAMER_1_0_ROOT_MSVC_X86_64=C:\gstreamer\1.0\msvc_x86_64
set PATH=%PATH%;C:\gstreamer\1.0\msvc_x86_64\bin
echo ✓ 当前会话环境变量已设置

echo.
echo ========================================
echo 安装完成!
echo ========================================
echo.
echo 环境变量已设置，但需要重启命令提示符才能生效
echo.
echo 下一步:
echo 1. 关闭此命令提示符
echo 2. 打开新的命令提示符
echo 3. 运行: gst-inspect-1.0 --version
echo 4. 运行: python test_opencv_gst.py
echo.
echo ========================================
echo.

pause
