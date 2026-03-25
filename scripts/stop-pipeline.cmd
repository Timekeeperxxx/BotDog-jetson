@echo off
setlocal

echo Stopping MediaMTX/FFmpeg (if any)...
taskkill /f /im mediamtx.exe >nul 2>&1
taskkill /f /im ffmpeg.exe >nul 2>&1

echo Done.
