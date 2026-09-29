[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\Transit2GPX')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$source = [System.IO.Path]::GetFullPath($PSScriptRoot)
$destinationPath = [System.IO.Path]::GetFullPath($Destination)
if ($source -eq $destinationPath) {
    Write-Host "Transit2GPX 已安装在 $destinationPath"
    exit 0
}

$parent = Split-Path -Parent $destinationPath
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$staging = Join-Path $parent ".Transit2GPX.install.$([guid]::NewGuid().ToString('N'))"
$backup = Join-Path $parent ".Transit2GPX.backup.$([guid]::NewGuid().ToString('N'))"
try {
    New-Item -ItemType Directory -Path $staging | Out-Null
    Copy-Item -Path (Join-Path $source '*') -Destination $staging -Recurse -Force
    if (Test-Path -LiteralPath $destinationPath) {
        Move-Item -LiteralPath $destinationPath -Destination $backup
    }
    Move-Item -LiteralPath $staging -Destination $destinationPath
    if (Test-Path -LiteralPath $backup) {
        Remove-Item -LiteralPath $backup -Recurse -Force
    }
}
catch {
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    if ((Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $destinationPath)) {
        Move-Item -LiteralPath $backup -Destination $destinationPath
    }
    throw
}

$shortcutDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$shortcutPath = Join-Path $shortcutDir 'Transit2GPX.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $destinationPath 'Transit2GPX.exe'
$shortcut.WorkingDirectory = $destinationPath
$shortcut.Description = 'Transit2GPX local transit journey tool'
$shortcut.Save()
$railShortcut = $shell.CreateShortcut((Join-Path $shortcutDir 'Transit2GPX Railway.lnk'))
$railShortcut.TargetPath = Join-Path $destinationPath 'Transit2GPX.exe'
$railShortcut.Arguments = '--rail'
$railShortcut.WorkingDirectory = $destinationPath
$railShortcut.Description = 'Transit2GPX with managed railway routing sidecar'
$railShortcut.Save()

Write-Host "Transit2GPX 已安装到 $destinationPath"
Write-Host '用户数据库与铁路图保存在独立应用数据目录，升级安装不会覆盖。'
