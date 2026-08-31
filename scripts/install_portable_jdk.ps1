[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

function Assert-DirectChild {
    param(
        [Parameter(Mandatory)][string]$Parent,
        [Parameter(Mandatory)][string]$Target
    )

    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    $targetFull = [System.IO.Path]::GetFullPath($Target).TrimEnd('\', '/')
    if ([System.IO.Path]::GetDirectoryName($targetFull) -ne $parentFull) {
        throw "路径不在预期父目录内：$targetFull"
    }
    return $targetFull
}

function Test-CompleteJdk {
    param([Parameter(Mandatory)][string]$JavaHome)

    return (
        (Test-Path -LiteralPath (Join-Path $JavaHome 'bin\java.exe') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $JavaHome 'bin\jar.exe') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $JavaHome 'release') -PathType Leaf)
    )
}

if (-not $IsWindows) {
    throw '此安装脚本只支持 Windows。'
}

$projectDir = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$manifestPath = Join-Path $projectDir 'rail-routing\jdk-windows.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 |
    ConvertFrom-Json
if (
    [string]($manifest.operating_system) -ne 'windows' -or
    [string]($manifest.architecture) -ne 'x64' -or
    [string]($manifest.image_type) -ne 'jdk' -or
    [string]($manifest.release_name) -notmatch '^jdk-21\.' -or
    [string]($manifest.sha256) -notmatch '^[0-9a-f]{64}$'
) {
    throw "JDK manifest 无效：$manifestPath"
}

$workDir = if ($env:RAIL_WORK_DIR) {
    [System.IO.Path]::GetFullPath($env:RAIL_WORK_DIR)
}
else {
    Join-Path $projectDir 'data\rail-routing'
}
$toolsRoot = [System.IO.Path]::GetFullPath((Join-Path $workDir 'tools')).TrimEnd('\')
$finalHome = Assert-DirectChild $toolsRoot (Join-Path $toolsRoot 'temurin-21')
$javaPath = Join-Path $finalHome 'bin\java.exe'
$jarPath = Join-Path $finalHome 'bin\jar.exe'

if (Test-Path -LiteralPath $finalHome) {
    if (-not (Test-CompleteJdk $finalHome)) {
        throw "项目内便携 JDK 目录已存在但不完整：$finalHome"
    }
    $versionOutput = (& $javaPath -version 2>&1 | Out-String).Trim()
    [ordered]@{
        status = 'already-installed'
        java_home = $finalHome
        release_name = [string]$manifest.release_name
        java_version = $versionOutput
    } | ConvertTo-Json
    return
}

$null = New-Item -ItemType Directory -Path $toolsRoot -Force
$token = [guid]::NewGuid().ToString('N')
$temporaryRoot = Assert-DirectChild $toolsRoot (
    Join-Path $toolsRoot ".temurin-21-install-$token"
)
$archivePath = Assert-DirectChild $toolsRoot (
    Join-Path $toolsRoot ".temurin-21-$token.zip"
)
$createdFinal = $false
$completed = $false
$null = New-Item -ItemType Directory -Path $temporaryRoot

try {
    $publishedChecksumText = (
        Invoke-RestMethod -Uri ([string]$manifest.checksum_url) -TimeoutSec 30 |
            Out-String
    ).Trim()
    $publishedChecksum = (($publishedChecksumText -split '\s+')[0]).ToLowerInvariant()
    $expectedChecksum = ([string]$manifest.sha256).ToLowerInvariant()
    if ($publishedChecksum -ne $expectedChecksum) {
        throw '固定 manifest 与发布方 checksum 文件不一致。'
    }

    $curl = Join-Path $env:WINDIR 'System32\curl.exe'
    & $curl --fail --location --retry 3 --retry-all-errors `
        --output $archivePath ([string]$manifest.archive_url)
    if ($LASTEXITCODE -ne 0) {
        throw "JDK 下载失败，退出码：$LASTEXITCODE"
    }
    $actualChecksum = (
        Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($actualChecksum -ne $expectedChecksum) {
        throw "JDK SHA-256 不匹配：$actualChecksum"
    }

    Expand-Archive -LiteralPath $archivePath -DestinationPath $temporaryRoot
    $extractedRoots = @(Get-ChildItem -LiteralPath $temporaryRoot -Directory)
    if ($extractedRoots.Count -ne 1) {
        throw "JDK 压缩包应只有一个根目录，实际为：$($extractedRoots.Count)"
    }
    $extractedHome = $extractedRoots[0].FullName
    if (-not (Test-CompleteJdk $extractedHome)) {
        throw '解压后的 JDK 缺少 java.exe、jar.exe 或 release。'
    }

    Move-Item -LiteralPath $extractedHome -Destination $finalHome
    $createdFinal = $true
    [ordered]@{
        distribution = [string]$manifest.distribution
        release_name = [string]$manifest.release_name
        archive_name = [string]$manifest.archive_name
        archive_url = [string]$manifest.archive_url
        sha256 = $actualChecksum
        size_bytes = [long]$manifest.size_bytes
        installed_at = [DateTimeOffset]::UtcNow.ToString('o')
    } | ConvertTo-Json | Set-Content `
        -LiteralPath (Join-Path $finalHome 'transit2fog-install.json') `
        -Encoding utf8NoBOM
    $completed = $true
}
finally {
    if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    if (Test-Path -LiteralPath $temporaryRoot) {
        $verifiedTemporaryRoot = Assert-DirectChild $toolsRoot $temporaryRoot
        Remove-Item -LiteralPath $verifiedTemporaryRoot -Recurse -Force
    }
    if (-not $completed -and $createdFinal -and (Test-Path -LiteralPath $finalHome)) {
        $verifiedFinalHome = Assert-DirectChild $toolsRoot $finalHome
        Remove-Item -LiteralPath $verifiedFinalHome -Recurse -Force
    }
}

if (-not $completed -or -not (Test-CompleteJdk $finalHome)) {
    throw '项目内便携 JDK 安装未完成。'
}
$versionOutput = (& $javaPath -version 2>&1 | Out-String).Trim()
[ordered]@{
    status = 'installed'
    java_home = $finalHome
    release_name = [string]$manifest.release_name
    sha256 = [string]$manifest.sha256
    java_version = $versionOutput
} | ConvertTo-Json
