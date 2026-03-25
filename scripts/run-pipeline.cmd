@echo off
setlocal

set "ROOT_DIR=%~dp0..\"

set "MEDIAMTX_EXE=%MEDIAMTX_EXE%"
if "%MEDIAMTX_EXE%"=="" set "MEDIAMTX_EXE=%ROOT_DIR%tools\mediamtx\mediamtx.exe"

set "FFMPEG_PATH=%FFMPEG_PATH%"
if "%FFMPEG_PATH%"=="" set "FFMPEG_PATH=%ROOT_DIR%tools\ffmpeg\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe"

set "CAMERA_RTSP_URL=%CAMERA_RTSP_URL%"
if "%CAMERA_RTSP_URL%"=="" set "CAMERA_RTSP_URL=rtsp://192.168.144.25:8554/main.264"

set "MEDIA_MTX_RTSP_URL=%MEDIA_MTX_RTSP_URL%"
if "%MEDIA_MTX_RTSP_URL%"=="" set "MEDIA_MTX_RTSP_URL=rtsp://127.0.0.1:8554/cam"

echo Stopping existing MediaMTX/FFmpeg (if any)...
taskkill /f /im mediamtx.exe >nul 2>&1
taskkill /f /im ffmpeg.exe >nul 2>&1

if not exist "%MEDIAMTX_EXE%" (
  echo MediaMTX not found: %MEDIAMTX_EXE%
  echo Run: powershell -ExecutionPolicy Bypass -File .\setup-mediamtx.ps1
  pause
  exit /b 1
)

if not exist "%FFMPEG_PATH%" (
  echo FFmpeg not found: %FFMPEG_PATH%
  echo Run: powershell -ExecutionPolicy Bypass -File .\setup-ffmpeg.ps1
  pause
  exit /b 1
)

start /b "MediaMTX" cmd /c "cd /d %ROOT_DIR% && "%MEDIAMTX_EXE%" "%ROOT_DIR%config\mediamtx.yml" >> "%ROOT_DIR%logs\mediamtx.log" 2>>&1"

start /b "FFmpeg" cmd /c "cd /d %ROOT_DIR% && set ""FFMPEG_PATH=%FFMPEG_PATH%"" && set ""CAMERA_RTSP_URL=%CAMERA_RTSP_URL%"" && set ""MEDIA_MTX_RTSP_URL=%MEDIA_MTX_RTSP_URL%"" && .\scripts\ffmpeg-supervisor.cmd >> "%ROOT_DIR%logs\ffmpeg.log" 2>>&1"

echo.
echo Pipeline started (background).
echo Logs:
echo - %ROOT_DIR%logs\mediamtx.log
echo - %ROOT_DIR%logs\ffmpeg.log
echo WHEP: http://127.0.0.1:8889/cam/whep
echo Test page: http://127.0.0.1:8090/index.html
echo.
pause
