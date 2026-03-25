@echo off
setlocal enabledelayedexpansion

REM Configuration
set "CAMERA_RTSP_URL=%CAMERA_RTSP_URL%"
if "%CAMERA_RTSP_URL%"=="" set "CAMERA_RTSP_URL=rtsp://192.168.144.25:8554/main.264"

set "MEDIA_MTX_RTSP_URL=%MEDIA_MTX_RTSP_URL%"
if "%MEDIA_MTX_RTSP_URL%"=="" set "MEDIA_MTX_RTSP_URL=rtsp://192.168.144.30:8554/cam"

set "FFMPEG_PATH=%FFMPEG_PATH%"
if "%FFMPEG_PATH%"=="" set "FFMPEG_PATH=%~dp0..\tools\ffmpeg\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe"

set "FFMPEG_RETRY_DELAY_S=%FFMPEG_RETRY_DELAY_S%"
if "%FFMPEG_RETRY_DELAY_S%"=="" set "FFMPEG_RETRY_DELAY_S=1"

set "CAMERA_RTSP_HOST=%CAMERA_RTSP_HOST%"
if "%CAMERA_RTSP_HOST%"=="" set "CAMERA_RTSP_HOST=192.168.144.25"

set "CAMERA_RTSP_PORT=%CAMERA_RTSP_PORT%"
if "%CAMERA_RTSP_PORT%"=="" set "CAMERA_RTSP_PORT=8554"

set "TARGET_FPS=%TARGET_FPS%"
if "%TARGET_FPS%"=="" set "TARGET_FPS=30"

set "TARGET_WIDTH=%TARGET_WIDTH%"
if "%TARGET_WIDTH%"=="" set "TARGET_WIDTH=1260"

set "TARGET_HEIGHT=%TARGET_HEIGHT%"
if "%TARGET_HEIGHT%"=="" set "TARGET_HEIGHT=720"

set "FFMPEG_WATCHDOG_INTERVAL_S=%FFMPEG_WATCHDOG_INTERVAL_S%"
if "%FFMPEG_WATCHDOG_INTERVAL_S%"=="" set "FFMPEG_WATCHDOG_INTERVAL_S=5"
set "FFMPEG_WATCHDOG_IDLE_COUNT=%FFMPEG_WATCHDOG_IDLE_COUNT%"
if "%FFMPEG_WATCHDOG_IDLE_COUNT%"=="" set "FFMPEG_WATCHDOG_IDLE_COUNT=6"
set "FFMPEG_LOG=%~dp0..\logs\ffmpeg_watchdog.log"

:loop
echo [FFmpeg] Pulling %CAMERA_RTSP_URL% and publishing to %MEDIA_MTX_RTSP_URL%
if exist "%FFMPEG_LOG%" del /f /q "%FFMPEG_LOG%"
start "" /b cmd /c ""%FFMPEG_PATH%" -rtsp_transport tcp -rtsp_flags prefer_tcp -timeout 5000000 -fflags +genpts+discardcorrupt+nobuffer -flags low_delay -avioflags direct -max_delay 0 -reorder_queue_size 0 -use_wallclock_as_timestamps 1 -analyzeduration 500000 -probesize 131072 -i "%CAMERA_RTSP_URL%" -an -vf "fps=%TARGET_FPS%,scale=%TARGET_WIDTH%:%TARGET_HEIGHT%" -vsync 0 -c:v libx264 -preset ultrafast -tune zerolatency -profile:v baseline -level 4.1 -pix_fmt yuv420p -g %TARGET_FPS% -keyint_min %TARGET_FPS% -bf 0 -x264-params "keyint=%TARGET_FPS%:min-keyint=%TARGET_FPS%:scenecut=0:sync-lookahead=0:vbv-maxrate=6000:vbv-bufsize=6000" -muxdelay 0 -muxpreload 0 -f rtsp -rtsp_transport tcp "%MEDIA_MTX_RTSP_URL%" > "%FFMPEG_LOG%" 2>&1"

set "LAST_SIZE=0"
set "IDLE_COUNT=0"

:monitor
timeout /t %FFMPEG_WATCHDOG_INTERVAL_S% /nobreak >nul
if exist "%FFMPEG_LOG%" (
  for %%A in ("%FFMPEG_LOG%") do set "CUR_SIZE=%%~zA"
) else (
  set "CUR_SIZE=0"
)
if "!CUR_SIZE!"=="!LAST_SIZE!" (
  set /a IDLE_COUNT+=1
) else (
  set "IDLE_COUNT=0"
  set "LAST_SIZE=!CUR_SIZE!"
)

tasklist /fi "imagename eq ffmpeg.exe" | find /i "ffmpeg.exe" >nul
if errorlevel 1 goto ended
if !IDLE_COUNT! GEQ %FFMPEG_WATCHDOG_IDLE_COUNT% (
  echo [FFmpeg] No output detected. Restarting...
  taskkill /im ffmpeg.exe /f >nul 2>nul
  goto ended
)

goto monitor

:ended
echo [FFmpeg] Stream ended. Reconnecting in %FFMPEG_RETRY_DELAY_S% seconds...
Timeout /t %FFMPEG_RETRY_DELAY_S% /nobreak >nul

goto loop
