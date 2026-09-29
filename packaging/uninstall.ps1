[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\Transit2GPX')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$destinationPath = [System.IO.Path]::GetFullPath($Destination)
$shortcutDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
Remove-Item -LiteralPath (Join-Path $shortcutDir 'Transit2GPX.lnk') -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $shortcutDir 'Transit2GPX Railway.lnk') -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $destinationPath -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'Transit2GPX 程序文件已移除。用户数据库、备份和铁路图未被删除。'
