$ErrorActionPreference = "Stop"
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifest = Get-Content (Join-Path $source "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$destinationName = "MamboTTS_Premiere_$($manifest.version)"
$uxpRoot = Join-Path $env:APPDATA "Adobe\UXP"
$destination = Join-Path $uxpRoot "Plugins\External\$destinationName"
$registry = Join-Path $uxpRoot "PluginsInfo\v1\premierepro.json"

if (Get-Process "Adobe Premiere Pro*" -ErrorAction SilentlyContinue) {
  Write-Host "Please close Premiere Pro before uninstalling." -ForegroundColor Yellow
  exit 1
}

Get-Process "MamboTTSPreview" -ErrorAction SilentlyContinue | Stop-Process -Force

if (Test-Path $destination) {
  Remove-Item -LiteralPath $destination -Recurse -Force
}

if (Test-Path $registry) {
  try {
    $data = Get-Content -LiteralPath $registry -Raw -Encoding UTF8 | ConvertFrom-Json
    $plugins = @($data.plugins | Where-Object {
      $_.pluginId -ne $manifest.id -and $_.path -ne ('$localPlugins\External\' + $destinationName)
    })
    [pscustomobject]([ordered]@{ plugins = $plugins }) |
      ConvertTo-Json -Depth 8 |
      Set-Content -LiteralPath $registry -Encoding UTF8
  } catch {
    Write-Warning "Could not update the Premiere UXP registry: $($_.Exception.Message)"
  }
}

Write-Host "MamboTTS plugin files and registry entry removed." -ForegroundColor Green
