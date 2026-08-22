$ErrorActionPreference = "Stop"
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifest = Get-Content (Join-Path $source "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$destinationName = "MamboTTS_Premiere_$($manifest.version)"
$uxpRoot = Join-Path $env:APPDATA "Adobe\UXP"
$destination = Join-Path $uxpRoot "Plugins\External\$destinationName"
$registry = Join-Path $uxpRoot "PluginsInfo\v1\premierepro.json"

if (Get-Process "Adobe Premiere Pro*" -ErrorAction SilentlyContinue) {
  Write-Host "Please close Premiere Pro before installing." -ForegroundColor Yellow
  exit 1
}

Get-Process "MamboTTSPreview" -ErrorAction SilentlyContinue | Stop-Process -Force

New-Item -ItemType Directory -Force -Path $destination | Out-Null
$pluginFiles = @(
  (Join-Path $source "manifest.json"),
  (Join-Path $source "index.html"),
  (Join-Path $source "index.js"),
  (Join-Path $source "main.js"),
  (Join-Path $source "styles.css")
)
Copy-Item -Force -Path $pluginFiles -Destination $destination

$helperSource = Join-Path $source "MamboTTSPreview.exe"
$helperOutput = Join-Path $destination "MamboTTSPreview.exe"
if (-not (Test-Path -LiteralPath $helperSource)) {
  throw "The background audio preview helper is missing."
}
Copy-Item -LiteralPath $helperSource -Destination $helperOutput -Force

New-Item -ItemType Directory -Force -Path (Split-Path $registry) | Out-Null
$data = if (Test-Path $registry) {
  Get-Content $registry -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
  $null
}
$plugins = @()
if ($data -and $data.plugins) {
  $plugins = @($data.plugins | Where-Object { $_.pluginId -ne $manifest.id })
}
$pluginPath = '$localPlugins\External\' + $destinationName
$plugins += [pscustomobject]([ordered]@{
  hostMinVersion = $manifest.host.minVersion
  name = $manifest.name
  path = $pluginPath
  pluginId = $manifest.id
  status = "enabled"
  type = "uxp"
  versionString = $manifest.version
})
[pscustomobject]([ordered]@{ plugins = $plugins }) |
  ConvertTo-Json -Depth 8 |
  Set-Content -Encoding UTF8 $registry

Write-Host "Installed. Open Premiere -> Window -> UXP Plugins -> MamboTTS" -ForegroundColor Green
