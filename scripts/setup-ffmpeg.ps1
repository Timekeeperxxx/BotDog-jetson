param(
  [string]$Destination = "$PSScriptRoot\\tools\\ffmpeg"
)

$ProgressPreference = 'SilentlyContinue'

if (!(Test-Path $Destination)) {
  New-Item -ItemType Directory -Path $Destination | Out-Null
}

$downloadUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$zipPath = Join-Path $Destination "ffmpeg-release-essentials.zip"

Write-Host "Downloading $downloadUrl"
Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath

Expand-Archive -Path $zipPath -DestinationPath $Destination -Force
Remove-Item $zipPath

$binPath = Get-ChildItem -Path $Destination -Directory | Select-Object -First 1 | ForEach-Object { Join-Path $_.FullName "bin" }
Write-Host "FFmpeg extracted to $binPath"
Write-Host "Add $binPath to PATH or set FFMPEG_PATH to $binPath\\ffmpeg.exe"
