[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        'help',
        'doctor',
        'doctor-rail',
        'setup-java',
        'setup',
        'dev',
        'dev-rail',
        'build',
        'start',
        'check',
        'backend-check',
        'frontend-check',
        'test',
        'e2e',
        'db-upgrade',
        'backup',
        'validate-real-data',
        'rail-bootstrap',
        'rail-fixture',
        'rail-fixture-start',
        'rail-fixture-smoke',
        'rail-fixture-verify',
        'rail-build-graph',
        'rail-yangtze-data',
        'rail-yangtze-graph',
        'rail-yangtze-start',
        'rail-yangtze-validate',
        'rail-yangtze-activate',
        'rail-china-data',
        'rail-china-graph',
        'rail-china-start',
        'rail-china-validate',
        'rail-china-activate',
        'rail-rollback',
        'clean'
    )]
    [string]$Command = 'help',

    [string]$CptondDir,
    [string]$OutputPath = 'transit2fog-backup.zip',
    [string]$PbfPath,
    [string]$GraphVersion
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$script:ProjectDir = $PSScriptRoot
$script:BackendDir = Join-Path $script:ProjectDir 'backend'
$script:FrontendDir = Join-Path $script:ProjectDir 'frontend'
$script:RailDir = Join-Path $script:ProjectDir 'rail-routing'
$script:DefaultRailWorkDir = Join-Path $script:ProjectDir 'data\rail-routing'

function Write-Usage {
    @'
Transit2Fog Windows 原生命令入口（PowerShell 7）

核心命令：
  .\transit2fog.ps1 doctor
  .\transit2fog.ps1 setup-java
  .\transit2fog.ps1 setup
  .\transit2fog.ps1 dev
  .\transit2fog.ps1 build
  .\transit2fog.ps1 start
  .\transit2fog.ps1 check
  .\transit2fog.ps1 e2e

数据与维护：
  .\transit2fog.ps1 db-upgrade
  .\transit2fog.ps1 backup -OutputPath <zip-path>
  .\transit2fog.ps1 validate-real-data -CptondDir <dataset-directory>

铁路命令：
  .\transit2fog.ps1 doctor-rail
  .\transit2fog.ps1 rail-bootstrap
  .\transit2fog.ps1 rail-fixture-verify
  .\transit2fog.ps1 rail-yangtze-data
  .\transit2fog.ps1 rail-yangtze-graph
  .\transit2fog.ps1 rail-yangtze-start
  .\transit2fog.ps1 rail-yangtze-activate
  .\transit2fog.ps1 dev-rail

全国图把命令中的 yangtze 替换为 china。自定义图可使用：
  .\transit2fog.ps1 rail-build-graph -PbfPath <file.osm.pbf> -GraphVersion <version>

铁路工作目录可通过 RAIL_WORK_DIR 覆盖，图目录可通过 RAIL_GRAPH_ROOT 覆盖。
'@ | Write-Host
}

function Get-RequiredCommand {
    param([Parameter(Mandatory)][string]$Name)

    $resolved = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $resolved) {
        throw "缺少必需命令：$Name"
    }
    return $resolved.Source
}

function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $script:ProjectDir
    )

    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "命令失败（退出码 $LASTEXITCODE）：$FilePath $($Arguments -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

function Invoke-WithEnvironment {
    param(
        [Parameter(Mandatory)][hashtable]$Variables,
        [Parameter(Mandatory)][scriptblock]$Action
    )

    $previous = @{}
    foreach ($name in $Variables.Keys) {
        $item = Get-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        $previous[$name] = if ($null -eq $item) { $null } else { $item.Value }
        Set-Item -LiteralPath "Env:$name" -Value ([string]$Variables[$name])
    }
    try {
        & $Action
    }
    finally {
        foreach ($name in $Variables.Keys) {
            if ($null -eq $previous[$name]) {
                Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item -LiteralPath "Env:$name" -Value $previous[$name]
            }
        }
    }
}

function Test-VersionAtLeast {
    param(
        [Parameter(Mandatory)][string]$Version,
        [Parameter(Mandatory)][int]$RequiredMajor,
        [Parameter(Mandatory)][int]$RequiredMinor
    )

    $match = [regex]::Match($Version.Trim(), '^v?(\d+)\.(\d+)')
    if (-not $match.Success) {
        return $false
    }
    $major = [int]$match.Groups[1].Value
    $minor = [int]$match.Groups[2].Value
    return $major -gt $RequiredMajor -or (
        $major -eq $RequiredMajor -and $minor -ge $RequiredMinor
    )
}

function Get-RailWorkDir {
    if ($env:RAIL_WORK_DIR) {
        return [System.IO.Path]::GetFullPath($env:RAIL_WORK_DIR)
    }
    return $script:DefaultRailWorkDir
}

function Get-RailGraphRoot {
    if ($env:RAIL_GRAPH_ROOT) {
        return [System.IO.Path]::GetFullPath($env:RAIL_GRAPH_ROOT)
    }
    return Join-Path (Get-RailWorkDir) 'graphs'
}

function Get-RailVersions {
    $versionsPath = Join-Path $script:RailDir 'versions.env'
    $versions = @{}
    foreach ($line in Get-Content -LiteralPath $versionsPath -Encoding utf8) {
        if ($line -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
            $versions[$matches[1]] = $matches[2]
        }
    }
    return $versions
}

function Get-RailJava {
    $javaPath = $null
    $jarPath = $null
    if ($env:RAIL_JAVA_HOME) {
        $javaPath = Join-Path $env:RAIL_JAVA_HOME 'bin\java.exe'
        $jarPath = Join-Path $env:RAIL_JAVA_HOME 'bin\jar.exe'
        if (-not (Test-Path -LiteralPath $javaPath -PathType Leaf)) {
            throw "RAIL_JAVA_HOME 不包含 bin\java.exe：$env:RAIL_JAVA_HOME"
        }
        if (-not (Test-Path -LiteralPath $jarPath -PathType Leaf)) {
            throw "RAIL_JAVA_HOME 不包含 bin\jar.exe：$env:RAIL_JAVA_HOME"
        }
    }
    else {
        $portableJavaHome = Join-Path (Get-RailWorkDir) 'tools\temurin-21'
        $portableJava = Join-Path $portableJavaHome 'bin\java.exe'
        $portableJar = Join-Path $portableJavaHome 'bin\jar.exe'
        $portableJavaExists = Test-Path -LiteralPath $portableJava -PathType Leaf
        $portableJarExists = Test-Path -LiteralPath $portableJar -PathType Leaf
        if ($portableJavaExists -or $portableJarExists) {
            if (-not $portableJavaExists -or -not $portableJarExists) {
                throw "项目内便携 JDK 不完整：$portableJavaHome"
            }
            $javaPath = $portableJava
            $jarPath = $portableJar
        }
        else {
            $javaPath = Get-RequiredCommand 'java.exe'
            $jarPath = Get-RequiredCommand 'jar.exe'
        }
    }

    $versionText = (& $javaPath -XshowSettings:properties -version 2>&1 | Out-String)
    $match = [regex]::Match($versionText, 'java\.specification\.version\s*=\s*([0-9]+)')
    if (-not $match.Success -or [int]$match.Groups[1].Value -lt 17) {
        throw '铁路能力需要 Java 17+；Java 21 是当前验证基线。'
    }
    return [pscustomobject]@{
        Java = $javaPath
        Jar = $jarPath
        Home = Split-Path -Parent (Split-Path -Parent $javaPath)
        Major = [int]$match.Groups[1].Value
    }
}

function Get-RailJavaOptions {
    $value = if ($env:RAIL_JAVA_OPTS) {
        $env:RAIL_JAVA_OPTS
    }
    else {
        '-Xms256m -Xmx2500m'
    }
    return @($value -split '\s+' | Where-Object { $_ })
}

function Get-RailSelectorVersion {
    param(
        [Parameter(Mandatory)][string]$GraphRoot,
        [Parameter(Mandatory)][ValidateSet('active', 'previous')][string]$Name,
        [switch]$Optional
    )

    $legacyPath = Join-Path $GraphRoot $Name
    $item = Get-Item -LiteralPath $legacyPath -Force -ErrorAction SilentlyContinue
    if ($null -ne $item) {
        if ($item.LinkType -ne 'SymbolicLink') {
            throw "铁路 selector 不是符号链接：$legacyPath"
        }
        $target = [string]$item.Target
        if (-not $target -or $target -match '[/\\]' -or $target.StartsWith('.')) {
            throw "铁路 selector 目标不安全：$legacyPath"
        }
        return $target
    }

    $selectorPath = Join-Path $GraphRoot "$Name.json"
    if (Test-Path -LiteralPath $selectorPath -PathType Leaf) {
        $payload = Get-Content -LiteralPath $selectorPath -Raw -Encoding utf8 |
            ConvertFrom-Json
        $version = [string]$payload.graph_version
        if ($version -notmatch '^[A-Za-z0-9._-]+$' -or $version.StartsWith('.')) {
            throw "铁路 selector 包含无效版本：$selectorPath"
        }
        return $version
    }

    if ($Optional) {
        return $null
    }
    throw "铁路 selector 不存在：$selectorPath"
}

function Remove-DirectChildDirectory {
    param(
        [Parameter(Mandatory)][string]$Parent,
        [Parameter(Mandatory)][string]$Target
    )

    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    $targetFull = [System.IO.Path]::GetFullPath($Target).TrimEnd('\', '/')
    if ([System.IO.Path]::GetDirectoryName($targetFull) -ne $parentFull) {
        throw "拒绝删除不在预期父目录中的路径：$targetFull"
    }
    if (Test-Path -LiteralPath $targetFull) {
        Remove-Item -LiteralPath $targetFull -Recurse -Force
    }
}

function Invoke-Doctor {
    param([switch]$Rail)

    $failures = 0
    $warnings = 0
    function Write-Pass([string]$Message) { Write-Host "通过  $Message" }
    function Write-Warn([string]$Message) {
        Write-Host "提醒  $Message"
        $script:doctorWarnings++
    }
    function Write-Fail([string]$Message) {
        Write-Host "失败  $Message"
        $script:doctorFailures++
    }
    $script:doctorFailures = 0
    $script:doctorWarnings = 0

    Write-Host 'Transit2Fog Windows 环境检查'
    Write-Host "项目：$script:ProjectDir"
    Write-Host

    if ($IsWindows) {
        Write-Pass 'Windows：使用原生 PowerShell 适配入口'
    }
    else {
        Write-Fail '此入口仅用于 Windows；macOS/Linux 请继续使用 Makefile'
    }
    if ($PSVersionTable.PSVersion.Major -ge 7) {
        Write-Pass "PowerShell $($PSVersionTable.PSVersion)（要求 7+）"
    }
    else {
        Write-Fail "PowerShell $($PSVersionTable.PSVersion)；要求 7+"
    }

    foreach ($tool in @(
        @{ Name = 'uv'; Required = '0.9'; Major = 0; Minor = 9 },
        @{ Name = 'node'; Required = '22'; Major = 22; Minor = 0 },
        @{ Name = 'npm'; Required = '10'; Major = 10; Minor = 0 }
    )) {
        $resolved = Get-Command ($tool.Name) -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -eq $resolved) {
            Write-Fail "缺少 $($tool.Name) $($tool.Required)+"
            continue
        }
        $versionArgs = @('--version')
        $version = (& ($resolved.Source) @versionArgs 2>$null | Out-String).Trim()
        if ($tool.Name -eq 'uv') {
            $version = ($version -split '\s+')[1]
        }
        if (Test-VersionAtLeast $version ($tool.Major) ($tool.Minor)) {
            Write-Pass "$($tool.Name) $version（要求 $($tool.Required)+）"
        }
        else {
            Write-Fail "$($tool.Name) $version；要求 $($tool.Required)+"
        }
    }

    $venvPython = Join-Path $script:BackendDir '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
        Write-Pass '后端依赖已安装'
    }
    else {
        Write-Warn '尚未发现 backend\.venv；首次运行前执行 .\transit2fog.ps1 setup'
    }
    if (Test-Path -LiteralPath (Join-Path $script:FrontendDir 'node_modules')) {
        Write-Pass '前端依赖已安装'
    }
    else {
        Write-Warn '尚未发现 frontend\node_modules；首次运行前执行 .\transit2fog.ps1 setup'
    }

    if ($Rail) {
        Write-Host
        Write-Host '铁路附加检查'
        foreach ($toolName in @('git.exe', 'curl.exe', 'tar.exe')) {
            if (Get-Command $toolName -ErrorAction SilentlyContinue) {
                Write-Pass "$toolName：铁路准备工具"
            }
            else {
                Write-Fail "缺少 $toolName：铁路准备工具"
            }
        }
        try {
            $java = Get-RailJava
            Write-Pass "Java $($java.Major)（$($java.Java)；要求 17+，验证基线为 21）"
            if ($java.Major -ne 21) {
                Write-Warn '当前 Java 不是验证基线 21；如遇构建差异，请设置 RAIL_JAVA_HOME'
            }
        }
        catch {
            Write-Fail $_.Exception.Message
        }

        if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
            try {
                & $venvPython -c 'import osmium' 2>$null
                Write-Pass 'Python osmium：可合并区域 PBF'
            }
            catch {
                Write-Warn '尚不能导入 Python osmium；执行 setup 后再检查'
            }
        }
        else {
            Write-Warn '尚不能检查 Python osmium；执行 setup 后再检查'
        }

        $projectDrive = (Get-Item -LiteralPath $script:ProjectDir).PSDrive
        if ($null -ne $projectDrive -and $null -ne $projectDrive.Free) {
            $freeGiB = [math]::Floor($projectDrive.Free / 1GB)
            if ($freeGiB -ge 5) {
                Write-Pass "可用磁盘约 $freeGiB GiB（全国图建议至少 5 GiB）"
            }
            elseif ($freeGiB -ge 3) {
                Write-Warn "可用磁盘约 $freeGiB GiB：可尝试长三角图，全国图建议至少 5 GiB"
            }
            else {
                Write-Fail "可用磁盘约 $freeGiB GiB；长三角图建议至少 3 GiB"
            }
        }
        else {
            Write-Warn '无法读取可用磁盘空间'
        }

        $railWorkDir = Get-RailWorkDir
        $railGraphRoot = Get-RailGraphRoot
        if (Test-Path -LiteralPath (Join-Path $railWorkDir 'dist\openrailrouting.jar')) {
            Write-Pass 'sidecar JAR 已构建'
        }
        else {
            Write-Warn 'sidecar JAR 尚未构建；首次使用执行 rail-bootstrap'
        }
        try {
            $active = Get-RailSelectorVersion $railGraphRoot active -Optional
            if ($active) {
                Write-Pass "已激活铁路图：$active"
            }
            else {
                Write-Warn '尚未发现 active 铁路图；完成构建和固定样本验证后再激活'
            }
        }
        catch {
            Write-Fail $_.Exception.Message
        }
    }

    $failures = $script:doctorFailures
    $warnings = $script:doctorWarnings
    Write-Host
    if ($failures -gt 0) {
        Write-Host "检查完成：$failures 项失败，$warnings 项提醒。"
        exit 1
    }
    Write-Host "检查完成：无失败，$warnings 项提醒。"
}

function Invoke-Setup {
    $uv = Get-RequiredCommand 'uv'
    $npm = Get-RequiredCommand 'npm'
    Invoke-Native $uv @('sync', '--project', $script:BackendDir, '--dev')
    Invoke-Native $npm @('ci', '--prefix', $script:FrontendDir)
}

function Invoke-DbUpgrade {
    $uv = Get-RequiredCommand 'uv'
    Invoke-Native $uv @('run', 'alembic', 'upgrade', 'head') $script:BackendDir
}

function Invoke-Build {
    $npm = Get-RequiredCommand 'npm'
    Invoke-Native $npm @('run', 'build', '--prefix', $script:FrontendDir)
}

function Invoke-BackendCheck {
    $uv = Get-RequiredCommand 'uv'
    Invoke-Native $uv @(
        'run', '--project', $script:BackendDir,
        'ruff', 'check',
        (Join-Path $script:BackendDir 'app'),
        (Join-Path $script:BackendDir 'tests'),
        (Join-Path $script:BackendDir 'migrations'),
        (Join-Path $script:ProjectDir 'scripts')
    )
    Invoke-Native $uv @(
        'run', '--project', $script:BackendDir,
        'ruff', 'format', '--check',
        (Join-Path $script:BackendDir 'app'),
        (Join-Path $script:BackendDir 'tests'),
        (Join-Path $script:BackendDir 'migrations'),
        (Join-Path $script:ProjectDir 'scripts')
    )
    Invoke-Native $uv @(
        'run', '--project', $script:BackendDir,
        'mypy', (Join-Path $script:BackendDir 'app')
    )
    Invoke-Native $uv @(
        'run', '--project', $script:BackendDir,
        'pytest', (Join-Path $script:BackendDir 'tests'),
        '--cov=backend/app', '--cov-report=term-missing'
    ) $script:ProjectDir
}

function Invoke-FrontendCheck {
    $npm = Get-RequiredCommand 'npm'
    Invoke-Native $npm @('run', 'lint', '--prefix', $script:FrontendDir)
    Invoke-Native $npm @('run', 'test', '--prefix', $script:FrontendDir)
    Invoke-Native $npm @('run', 'build', '--prefix', $script:FrontendDir)
}

function Invoke-Tests {
    $uv = Get-RequiredCommand 'uv'
    $npm = Get-RequiredCommand 'npm'
    Invoke-Native $uv @(
        'run', '--project', $script:BackendDir,
        'pytest', (Join-Path $script:BackendDir 'tests')
    )
    Invoke-Native $npm @('run', 'test', '--prefix', $script:FrontendDir)
}

function Start-BackendProcess {
    param([switch]$Rail)

    $uv = Get-RequiredCommand 'uv'
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $uv
    $startInfo.WorkingDirectory = $script:BackendDir
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    foreach ($argument in @('run', 'python', '-m', 'app')) {
        $null = $startInfo.ArgumentList.Add($argument)
    }
    $startInfo.Environment['TRANSIT2FOG_ENVIRONMENT'] = 'development'
    if ($Rail) {
        $startInfo.Environment['TRANSIT2FOG_RAIL_ENABLED'] = 'true'
        $startInfo.Environment['TRANSIT2FOG_RAIL_GRAPH_VERSION'] = 'active'
        $startInfo.Environment['TRANSIT2FOG_RAIL_GRAPH_ROOT'] = Get-RailGraphRoot
        $startInfo.Environment['TRANSIT2FOG_RAIL_SIDECAR_URL'] = 'http://127.0.0.1:8989'
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw '无法启动 Transit2Fog 后端进程。'
    }
    return $process
}

function Invoke-Dev {
    param([switch]$Rail)

    Invoke-DbUpgrade
    $backend = Start-BackendProcess -Rail:$Rail
    try {
        Start-Sleep -Milliseconds 750
        if ($backend.HasExited) {
            throw "后端启动失败（退出码 $($backend.ExitCode)）。"
        }
        $npm = Get-RequiredCommand 'npm'
        Invoke-Native $npm @('run', 'dev') $script:FrontendDir
    }
    finally {
        if (-not $backend.HasExited) {
            $backend.Kill($true)
            $backend.WaitForExit(5000)
        }
        $backend.Dispose()
    }
}

function Invoke-Start {
    Invoke-Build
    Invoke-DbUpgrade
    $uv = Get-RequiredCommand 'uv'
    Invoke-WithEnvironment @{ TRANSIT2FOG_ENVIRONMENT = 'production' } {
        Invoke-Native $uv @('run', 'python', '-m', 'app') $script:BackendDir
    }
}

function Invoke-RailBootstrap {
    $versions = Get-RailVersions
    $java = Get-RailJava
    $git = Get-RequiredCommand 'git.exe'
    $curl = Get-RequiredCommand 'curl.exe'
    $tar = Get-RequiredCommand 'tar.exe'
    $workDir = Get-RailWorkDir
    $toolsDir = Join-Path $workDir 'tools'
    $upstreamDir = Join-Path $workDir 'upstream\OpenRailRouting'
    $graphHopperDir = Join-Path $workDir 'upstream\GraphHopper'
    $buildRoot = Join-Path $workDir 'build'
    $distDir = Join-Path $workDir 'dist'
    $mavenDir = Join-Path $toolsDir "apache-maven-$($versions.MAVEN_VERSION)"
    $mavenArchive = Join-Path $toolsDir "apache-maven-$($versions.MAVEN_VERSION)-bin.tar.gz"
    $mavenCommand = Join-Path $mavenDir 'bin\mvn.cmd'
    $jarName = "railway_routing-$($versions.OPENRAILROUTING_ARTIFACT_VERSION).jar"

    foreach ($directory in @($toolsDir, (Join-Path $workDir 'upstream'), $buildRoot, $distDir)) {
        $null = New-Item -ItemType Directory -Path $directory -Force
    }
    if (-not (Test-Path -LiteralPath $mavenCommand -PathType Leaf)) {
        if (-not (Test-Path -LiteralPath $mavenArchive -PathType Leaf)) {
            Invoke-Native $curl @(
                '--fail', '--location', '--retry', '3',
                '--output', $mavenArchive, $versions.MAVEN_ARCHIVE_URL
            )
        }
        $actualSha = (Get-FileHash -LiteralPath $mavenArchive -Algorithm SHA512).Hash.ToLowerInvariant()
        if ($actualSha -ne $versions.MAVEN_ARCHIVE_SHA512.ToLowerInvariant()) {
            throw 'Maven 压缩包 SHA-512 不匹配。'
        }
        Invoke-Native $tar @('-xzf', $mavenArchive, '-C', $toolsDir)
    }

    foreach ($checkout in @(
        @{ Path = $upstreamDir; Repository = $versions.OPENRAILROUTING_REPOSITORY },
        @{ Path = $graphHopperDir; Repository = $versions.GRAPHHOPPER_REPOSITORY }
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $checkout.Path '.git'))) {
            $null = New-Item -ItemType Directory -Path ($checkout.Path) -Force
            Invoke-Native $git @('-C', $checkout.Path, 'init')
            Invoke-Native $git @('-C', $checkout.Path, 'remote', 'add', 'origin', $checkout.Repository)
        }
        $trackedChanges = (& $git -C ($checkout.Path) status --porcelain `
            --untracked-files=no | Out-String).Trim()
        if ($trackedChanges) {
            throw "拒绝替换存在修改的上游 checkout：$($checkout.Path)"
        }
    }

    Invoke-Native $git @('-C', $upstreamDir, 'fetch', '--depth', '1', 'origin', $versions.OPENRAILROUTING_COMMIT)
    Invoke-Native $git @('-C', $upstreamDir, 'checkout', '--detach', 'FETCH_HEAD')
    Invoke-Native $git @('-C', $graphHopperDir, 'fetch', '--depth', '1', 'origin', $versions.GRAPHHOPPER_COMMIT)
    Invoke-Native $git @('-C', $graphHopperDir, 'checkout', '--detach', 'FETCH_HEAD')

    Invoke-WithEnvironment @{ JAVA_HOME = $java.Home } {
        Invoke-Native $mavenCommand @(
            '--batch-mode', '-f', (Join-Path $graphHopperDir 'pom.xml'),
            '-DskipTests', '-pl', 'core,web-api,map-matching,web-bundle,web',
            '-am', 'install'
        )
    }

    $temporaryBuild = Join-Path $buildRoot "OpenRailRouting.$([guid]::NewGuid().ToString('N'))"
    $archivePath = Join-Path $buildRoot "OpenRailRouting.$([guid]::NewGuid().ToString('N')).tar"
    $null = New-Item -ItemType Directory -Path $temporaryBuild
    try {
        Invoke-Native $git @(
            '-C', $upstreamDir, 'archive', '--format=tar',
            "--output=$archivePath", $versions.OPENRAILROUTING_COMMIT
        )
        Invoke-Native $tar @('-xf', $archivePath, '-C', $temporaryBuild)
        Invoke-Native $git @('-C', $temporaryBuild, 'init')
        foreach ($patch in @(
            '0001-metro2fog-metadata-endpoint.patch',
            '0002-transit2fog-metadata-endpoint.patch',
            '0003-randomize-dropwizard-test-ports.patch'
        )) {
            Invoke-Native $git @(
                '-C', $temporaryBuild, 'apply', '--whitespace=nowarn',
                (Join-Path $script:RailDir "patches\$patch")
            )
        }
        Invoke-WithEnvironment @{ JAVA_HOME = $java.Home } {
            Invoke-Native $mavenCommand @(
                '--batch-mode', '-f', (Join-Path $temporaryBuild 'pom.xml'),
                'clean', 'package'
            )
        }
        Copy-Item -LiteralPath (Join-Path $temporaryBuild "target\$jarName") `
            -Destination (Join-Path $distDir 'openrailrouting.jar') -Force
    }
    finally {
        if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
            Remove-Item -LiteralPath $archivePath -Force
        }
        Remove-DirectChildDirectory $buildRoot $temporaryBuild
    }

    $builtJar = Join-Path $distDir 'openrailrouting.jar'
    $entries = (& ($java.Jar) tf $builtJar | Out-String)
    foreach ($requiredClass in @(
        'de/geofabrik/railway_routing/http/Metro2FogMetadataResource.class',
        'de/geofabrik/railway_routing/http/Transit2FogMetadataResource.class'
    )) {
        if ($entries -notmatch [regex]::Escape($requiredClass)) {
            throw "构建的 JAR 缺少资源：$requiredClass"
        }
    }
    Write-Host "OpenRailRouting $($versions.OPENRAILROUTING_COMMIT) 已构建：$builtJar"
}

function Invoke-RailBuildGraph {
    param(
        [Parameter(Mandatory)][string]$InputPbf,
        [Parameter(Mandatory)][string]$Version
    )

    if ($Version -notmatch '^[A-Za-z0-9._-]+$' -or $Version.StartsWith('.')) {
        throw 'Graph 版本只能包含字母、数字、点、下划线和连字符。'
    }
    $resolvedPbf = (Resolve-Path -LiteralPath $InputPbf).Path
    if (-not $resolvedPbf.EndsWith('.osm.pbf', [StringComparison]::OrdinalIgnoreCase)) {
        throw "需要 .osm.pbf 输入：$resolvedPbf"
    }
    $workDir = Get-RailWorkDir
    $graphRoot = Get-RailGraphRoot
    $jarPath = Join-Path $workDir 'dist\openrailrouting.jar'
    if (-not (Test-Path -LiteralPath $jarPath -PathType Leaf)) {
        throw '缺少 sidecar JAR；请先运行 rail-bootstrap。'
    }
    $finalGraph = Join-Path $graphRoot $Version
    if (Test-Path -LiteralPath $finalGraph) {
        throw "拒绝覆盖已有图版本：$finalGraph"
    }
    $null = New-Item -ItemType Directory -Path $graphRoot -Force
    $temporaryGraph = Join-Path $graphRoot ".$Version.$([guid]::NewGuid().ToString('N'))"
    $null = New-Item -ItemType Directory -Path $temporaryGraph
    try {
        $java = Get-RailJava
        $arguments = @()
        $arguments += Get-RailJavaOptions
        $arguments += @(
            "-Ddw.graphhopper.datareader.file=$resolvedPbf",
            "-Ddw.graphhopper.graph.location=$temporaryGraph",
            '-jar', $jarPath, 'import', (Join-Path $script:RailDir 'config.yml')
        )
        Invoke-Native ($java.Java) $arguments $script:RailDir
        Move-Item -LiteralPath $temporaryGraph -Destination $finalGraph
        $temporaryGraph = $null

        $versions = Get-RailVersions
        $metadata = [ordered]@{
            graph_version = $Version
            pbf_filename = [System.IO.Path]::GetFileName($resolvedPbf)
            pbf_sha256 = (Get-FileHash -LiteralPath $resolvedPbf -Algorithm SHA256).Hash.ToLowerInvariant()
            source_url = if ($env:RAIL_SOURCE_URL) { $env:RAIL_SOURCE_URL } else { $null }
            source_timestamp = if ($env:RAIL_SOURCE_TIMESTAMP) { $env:RAIL_SOURCE_TIMESTAMP } else { $null }
            extract_region = if ($env:RAIL_EXTRACT_REGION) { $env:RAIL_EXTRACT_REGION } else { $null }
            openrailrouting_commit = $versions.OPENRAILROUTING_COMMIT
            graphhopper_version = $versions.GRAPHHOPPER_FORK_VERSION
            profile_version = $versions.RAIL_PROFILE_VERSION
            license = 'ODbL-1.0'
            built_at = [DateTimeOffset]::UtcNow.ToString('o')
        }
        $metadata | ConvertTo-Json | Set-Content `
            -LiteralPath (Join-Path $finalGraph 'transit2fog-graph.json') `
            -Encoding utf8NoBOM
    }
    finally {
        if ($temporaryGraph) {
            Remove-DirectChildDirectory $graphRoot $temporaryGraph
        }
    }
    Write-Host "铁路图 '$Version' 已就绪：$finalGraph"
}

function Invoke-RailStart {
    param(
        [Parameter(Mandatory)][string]$RequestedVersion,
        [Parameter(Mandatory)][string]$InputPbf
    )

    $resolvedPbf = (Resolve-Path -LiteralPath $InputPbf).Path
    $workDir = Get-RailWorkDir
    $graphRoot = Get-RailGraphRoot
    $actualVersion = if ($RequestedVersion -eq 'active') {
        Get-RailSelectorVersion $graphRoot active
    }
    else {
        $RequestedVersion
    }
    if ($actualVersion -notmatch '^[A-Za-z0-9._-]+$' -or $actualVersion.StartsWith('.')) {
        throw '请求的铁路图版本无效。'
    }
    $graphPath = Join-Path $graphRoot $actualVersion
    $jarPath = Join-Path $workDir 'dist\openrailrouting.jar'
    if (-not (Test-Path -LiteralPath $jarPath -PathType Leaf)) {
        throw '缺少 sidecar JAR；请先运行 rail-bootstrap。'
    }
    $metadataPath = Join-Path $graphPath 'transit2fog-graph.json'
    if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
        $metadataPath = Join-Path $graphPath 'metro2fog-graph.json'
    }
    if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
        throw "图版本缺少元数据：$graphPath"
    }
    $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding utf8 |
        ConvertFrom-Json
    foreach ($field in @('graph_version', 'pbf_sha256', 'profile_version', 'openrailrouting_commit')) {
        if (-not [string]($metadata.$field)) {
            throw "图元数据缺少字段：$field"
        }
    }
    if ([string]($metadata.graph_version) -ne $actualVersion) {
        throw '图元数据版本与选中目录不一致。'
    }
    $actualPbfSha = (Get-FileHash -LiteralPath $resolvedPbf -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualPbfSha -ne ([string]$metadata.pbf_sha256).ToLowerInvariant()) {
        throw '所选 PBF checksum 与图元数据不匹配。'
    }

    $java = Get-RailJava
    $applicationPort = if ($env:RAIL_SIDECAR_PORT) { $env:RAIL_SIDECAR_PORT } else { '8989' }
    $adminPort = if ($env:RAIL_SIDECAR_ADMIN_PORT) { $env:RAIL_SIDECAR_ADMIN_PORT } else { '8990' }
    $arguments = @()
    $arguments += Get-RailJavaOptions
    foreach ($prefix in @('transit2fog', 'metro2fog')) {
        $arguments += @(
            "-D$prefix.graph.version=$($metadata.graph_version)",
            "-D$prefix.pbf.sha256=$($metadata.pbf_sha256)",
            "-D$prefix.profile.version=$($metadata.profile_version)",
            "-D$prefix.openrailrouting.commit=$($metadata.openrailrouting_commit)"
        )
    }
    $arguments += @(
        "-Ddw.graphhopper.datareader.file=$resolvedPbf",
        "-Ddw.graphhopper.graph.location=$graphPath",
        "-Ddw.server.application_connectors[0].port=$applicationPort",
        "-Ddw.server.admin_connectors[0].port=$adminPort",
        '-jar', $jarPath, 'serve', (Join-Path $script:RailDir 'config.yml')
    )
    Invoke-Native ($java.Java) $arguments $script:RailDir
}

function Invoke-RailSmoke {
    $baseUrl = if ($env:RAIL_SIDECAR_URL) { $env:RAIL_SIDECAR_URL.TrimEnd('/') } else { 'http://127.0.0.1:8989' }
    $profile = if ($env:RAIL_SMOKE_PROFILE) { $env:RAIL_SMOKE_PROFILE } else { 'china_conventional' }
    $fromLat = if ($env:RAIL_SMOKE_FROM_LAT) { $env:RAIL_SMOKE_FROM_LAT } else { '50.85139337895494' }
    $fromLon = if ($env:RAIL_SMOKE_FROM_LON) { $env:RAIL_SMOKE_FROM_LON } else { '6.908898310661318' }
    $toLat = if ($env:RAIL_SMOKE_TO_LAT) { $env:RAIL_SMOKE_TO_LAT } else { '50.94193447111784' }
    $toLon = if ($env:RAIL_SMOKE_TO_LON) { $env:RAIL_SMOKE_TO_LON } else { '6.960010517835617' }

    $ready = $false
    foreach ($attempt in 1..30) {
        try {
            $null = Invoke-RestMethod -Uri "$baseUrl/info" -TimeoutSec 2
            $ready = $true
            break
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $ready) {
        throw "铁路 sidecar 未在 $baseUrl 就绪。"
    }
    $query = @(
        "point=$([uri]::EscapeDataString("$fromLat,$fromLon"))",
        "point=$([uri]::EscapeDataString("$toLat,$toLon"))",
        "profile=$([uri]::EscapeDataString($profile))",
        'points_encoded=false',
        'instructions=false',
        'details=osm_way_id'
    ) -join '&'
    $payload = Invoke-RestMethod -Uri "$baseUrl/route?$query" -TimeoutSec 30
    $messageProperty = $payload.PSObject.Properties['message']
    if ($null -ne $messageProperty -and $messageProperty.Value) {
        throw "rail route failed: $($messageProperty.Value)"
    }
    $paths = @($payload.paths)
    if ($paths.Count -eq 0) {
        throw 'rail route response contains no path'
    }
    $path = $paths[0]
    $coordinates = @($path.points.coordinates)
    if ($coordinates.Count -lt 2 -or [double]$path.distance -le 0) {
        throw 'rail route has invalid distance or geometry'
    }
    Write-Host ('rail smoke passed: profile={0} distance_m={1:N1} points={2}' -f `
        $profile, [double]$path.distance, $coordinates.Count)
}

function Invoke-RailData {
    param([Parameter(Mandatory)][ValidateSet('yangtze', 'china')][string]$Region)

    $uv = Get-RequiredCommand 'uv'
    $manifest = if ($Region -eq 'yangtze') {
        Join-Path $script:RailDir 'data\yangtze-20260815.json'
    }
    else {
        Join-Path $script:RailDir 'data\china-20260815.json'
    }
    Invoke-Native $uv @(
        'run', '--project', $script:BackendDir, 'python',
        (Join-Path $script:ProjectDir 'scripts\rail_prepare_region.py'),
        $manifest, (Join-Path (Get-RailWorkDir) 'regions')
    )
}

function Get-RegionConfig {
    param([Parameter(Mandatory)][ValidateSet('yangtze', 'china', 'fixture')][string]$Region)

    switch ($Region) {
        'yangtze' {
            return [pscustomobject]@{
                Version = 'yangtze-20260815-r0.1'
                Pbf = Join-Path (Get-RailWorkDir) 'regions\yangtze-20260815\yangtze-20260815.osm.pbf'
                Acceptance = Join-Path $script:RailDir 'data\yangtze-acceptance-routes.json'
                Validation = Join-Path (Get-RailWorkDir) 'regions\yangtze-20260815\route-validation.json'
                SourceTimestamp = '2026-08-15T22:41:00Z'
                ExtractRegion = 'Shanghai+Jiangsu+Zhejiang+Anhui'
            }
        }
        'china' {
            return [pscustomobject]@{
                Version = 'china-20260815-r3.1'
                Pbf = Join-Path (Get-RailWorkDir) 'regions\china-20260815\china-20260815.osm.pbf'
                Acceptance = Join-Path $script:RailDir 'data\china-acceptance-routes.json'
                Validation = Join-Path (Get-RailWorkDir) 'regions\china-20260815\route-validation.json'
                SourceTimestamp = '2026-08-15T22:38:00Z'
                ExtractRegion = 'China'
            }
        }
        'fixture' {
            return [pscustomobject]@{
                Version = 'fixture-cologne'
                Pbf = Join-Path (Get-RailWorkDir) 'upstream\OpenRailRouting\files\cologne-railway.osm.pbf'
                Acceptance = $null
                Validation = $null
                SourceTimestamp = $null
                ExtractRegion = $null
            }
        }
    }
}

function Invoke-RailValidate {
    param([Parameter(Mandatory)][ValidateSet('yangtze', 'china')][string]$Region)

    $config = Get-RegionConfig $Region
    $uv = Get-RequiredCommand 'uv'
    Invoke-Native $uv @(
        'run', '--project', $script:BackendDir, 'python',
        (Join-Path $script:ProjectDir 'scripts\rail_validate_routes.py'),
        $config.Acceptance, '--output', $config.Validation
    )
}

function Invoke-RailActivate {
    param([Parameter(Mandatory)][ValidateSet('yangtze', 'china')][string]$Region)

    Invoke-RailValidate $Region
    $config = Get-RegionConfig $Region
    $uv = Get-RequiredCommand 'uv'
    Invoke-Native $uv @(
        'run', '--project', $script:BackendDir, 'python',
        (Join-Path $script:ProjectDir 'scripts\rail_activate_graph.py'),
        '--graph-root', (Get-RailGraphRoot),
        'activate', $config.Version,
        '--validation-report', $config.Validation
    )
}

switch ($Command) {
    'help' { Write-Usage }
    'doctor' { Invoke-Doctor }
    'doctor-rail' { Invoke-Doctor -Rail }
    'setup-java' {
        & (Join-Path $script:ProjectDir 'scripts\install_portable_jdk.ps1')
    }
    'setup' { Invoke-Setup }
    'dev' { Invoke-Dev }
    'dev-rail' { Invoke-Dev -Rail }
    'build' { Invoke-Build }
    'start' { Invoke-Start }
    'check' { Invoke-BackendCheck; Invoke-FrontendCheck }
    'backend-check' { Invoke-BackendCheck }
    'frontend-check' { Invoke-FrontendCheck }
    'test' { Invoke-Tests }
    'e2e' {
        Invoke-Build
        $npm = Get-RequiredCommand 'npm'
        Invoke-Native $npm @('run', 'test:e2e', '--prefix', $script:FrontendDir)
    }
    'db-upgrade' { Invoke-DbUpgrade }
    'backup' {
        $uv = Get-RequiredCommand 'uv'
        $resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputPath)) {
            [System.IO.Path]::GetFullPath($OutputPath)
        }
        else {
            Join-Path $script:ProjectDir $OutputPath
        }
        Invoke-Native $uv @(
            'run', '--project', $script:BackendDir, 'python',
            (Join-Path $script:ProjectDir 'scripts\backup.py'), $resolvedOutput
        )
    }
    'validate-real-data' {
        if (-not $CptondDir) { throw '请通过 -CptondDir 指定 CPTOND 数据目录。' }
        $uv = Get-RequiredCommand 'uv'
        Invoke-Native $uv @(
            'run', '--project', $script:BackendDir, 'python',
            (Join-Path $script:ProjectDir 'scripts\validate_cptond.py'),
            (Resolve-Path -LiteralPath $CptondDir).Path
        )
    }
    'rail-bootstrap' { Invoke-RailBootstrap }
    'rail-fixture' {
        Invoke-RailBootstrap
        $config = Get-RegionConfig fixture
        Invoke-RailBuildGraph ($config.Pbf) ($config.Version)
    }
    'rail-fixture-start' {
        $config = Get-RegionConfig fixture
        Invoke-RailStart ($config.Version) ($config.Pbf)
    }
    'rail-fixture-smoke' { Invoke-RailSmoke }
    'rail-fixture-verify' {
        & (Join-Path $script:ProjectDir 'scripts\verify_rail_fixture.ps1')
    }
    'rail-build-graph' {
        if (-not $PbfPath -or -not $GraphVersion) {
            throw 'rail-build-graph 需要 -PbfPath 和 -GraphVersion。'
        }
        Invoke-RailBuildGraph $PbfPath $GraphVersion
    }
    'rail-yangtze-data' { Invoke-RailData yangtze }
    'rail-yangtze-graph' {
        Invoke-RailBootstrap
        Invoke-RailData yangtze
        $config = Get-RegionConfig yangtze
        Invoke-WithEnvironment @{
            RAIL_SOURCE_URL = 'https://download.geofabrik.de/asia/china.html'
            RAIL_SOURCE_TIMESTAMP = $config.SourceTimestamp
            RAIL_EXTRACT_REGION = $config.ExtractRegion
        } { Invoke-RailBuildGraph ($config.Pbf) ($config.Version) }
    }
    'rail-yangtze-start' {
        $config = Get-RegionConfig yangtze
        Invoke-RailStart ($config.Version) ($config.Pbf)
    }
    'rail-yangtze-validate' { Invoke-RailValidate yangtze }
    'rail-yangtze-activate' { Invoke-RailActivate yangtze }
    'rail-china-data' { Invoke-RailData china }
    'rail-china-graph' {
        Invoke-RailBootstrap
        Invoke-RailData china
        $config = Get-RegionConfig china
        Invoke-WithEnvironment @{
            RAIL_SOURCE_URL = 'https://download.geofabrik.de/asia/china.html'
            RAIL_SOURCE_TIMESTAMP = $config.SourceTimestamp
            RAIL_EXTRACT_REGION = $config.ExtractRegion
        } { Invoke-RailBuildGraph ($config.Pbf) ($config.Version) }
    }
    'rail-china-start' {
        $config = Get-RegionConfig china
        Invoke-RailStart ($config.Version) ($config.Pbf)
    }
    'rail-china-validate' { Invoke-RailValidate china }
    'rail-china-activate' { Invoke-RailActivate china }
    'rail-rollback' {
        $uv = Get-RequiredCommand 'uv'
        Invoke-Native $uv @(
            'run', '--project', $script:BackendDir, 'python',
            (Join-Path $script:ProjectDir 'scripts\rail_activate_graph.py'),
            '--graph-root', (Get-RailGraphRoot), 'rollback'
        )
    }
    'clean' {
        foreach ($target in @(
            (Join-Path $script:FrontendDir 'dist'),
            (Join-Path $script:FrontendDir 'playwright-report'),
            (Join-Path $script:FrontendDir 'test-results')
        )) {
            Remove-DirectChildDirectory $script:FrontendDir $target
        }
    }
}
