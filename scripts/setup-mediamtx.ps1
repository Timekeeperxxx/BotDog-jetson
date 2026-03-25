param(
  [string]$Version = "latest",
  [string]$Destination = "$PSScriptRoot\\tools\\mediamtx"
)

$ProgressPreference = 'SilentlyContinue'

if (!(Test-Path $Destination)) {
  New-Item -ItemType Directory -Path $Destination | Out-Null
}

if ($Version -eq "latest") {
  try {
    $tag = (Invoke-RestMethod -Uri "https://api.github.com/repos/bluenviron/mediamtx/releases/latest").tag_name
  } catch {
    Write-Host "Failed to fetch latest tag, please pass -Version vX.Y.Z"
    throw
  }
} else {
  $tag = $Version
}

if (-not $tag.StartsWith("v")) {
  $tag = "v$tag"
}

$asset = "mediamtx_${tag}_windows_amd64.zip"
$downloadUrl = "https://github.com/bluenviron/mediamtx/releases/download/$tag/$asset"
$zipPath = Join-Path $Destination $asset

Write-Host "Downloading $downloadUrl"
Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath

Expand-Archive -Path $zipPath -DestinationPath $Destination -Force
Remove-Item $zipPath

Write-Host "MediaMTX extracted to $Destination"
Write-Host "Add $Destination to PATH or set MEDIAMTX_EXE to $Destination\\mediamtx.exe"
