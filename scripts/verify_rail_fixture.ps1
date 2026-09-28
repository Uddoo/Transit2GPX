[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

function Get-ProcessDescendants {
    param(
        [Parameter(Mandatory)][int]$RootProcessId,
        [Parameter(Mandatory)][string]$ProjectDir
    )

    $allProcesses = @(Get-CimInstance Win32_Process)
    $knownIds = [System.Collections.Generic.HashSet[int]]::new()
    $null = $knownIds.Add($RootProcessId)
    $result = @()
    foreach ($depth in 1..8) {
        $children = @(
            $allProcesses | Where-Object {
                $knownIds.Contains([int]$_.ParentProcessId) -and
                -not $knownIds.Contains([int]$_.ProcessId)
            }
        )
        if (-not $children.Count) {
            break
        }
        foreach ($child in $children) {
            $commandLine = [string]$child.CommandLine
            $null = $knownIds.Add([int]$child.ProcessId)
            $scoped = $commandLine -and (
                $commandLine.Contains(
                    $ProjectDir,
                    [StringComparison]::OrdinalIgnoreCase
                ) -or
                $commandLine.Contains(
                    'openrailrouting.jar',
                    [StringComparison]::OrdinalIgnoreCase
                )
            )
            if ($scoped) {
                $result += [pscustomobject]@{
                    ProcessId = [int]$child.ProcessId
                    ParentProcessId = [int]$child.ParentProcessId
                    Name = [string]$child.Name
                    CommandLine = $commandLine
                    Depth = $depth
                }
            }
        }
    }
    return $result
}

if (-not $IsWindows) {
    throw '此验收脚本只支持 Windows。'
}

$projectDir = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$entrypoint = Join-Path $projectDir 'transit2fog.ps1'
$railRoot = Join-Path $projectDir 'data\rail-routing'
$graphMetadataPath = Join-Path (
    $railRoot
) 'graphs\fixture-cologne\transit2fog-graph.json'
foreach ($required in @(
    (Join-Path $railRoot 'dist\openrailrouting.jar'),
    $graphMetadataPath,
    (Join-Path $railRoot 'upstream\OpenRailRouting\files\cologne-railway.osm.pbf')
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "fixture 验收缺少文件：$required"
    }
}
foreach ($port in @(8989, 8990)) {
    $listeners = @(
        Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port `
            -State Listen -ErrorAction SilentlyContinue
    )
    if ($listeners.Count) {
        throw "端口 $port 已被 PID $($listeners[0].OwningProcess) 占用。"
    }
}

$timestamp = [DateTimeOffset]::Now.ToString('yyyyMMdd-HHmmss')
$stdoutPath = Join-Path $railRoot "fixture-sidecar-$timestamp.stdout.log"
$stderrPath = Join-Path $railRoot "fixture-sidecar-$timestamp.stderr.log"
$pwshPath = (
    Get-Command pwsh.exe -ErrorAction Stop | Select-Object -First 1
).Source
$sidecarHost = Start-Process -FilePath $pwshPath `
    -ArgumentList @(
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-File',
        $entrypoint,
        'rail-fixture-start'
    ) `
    -WorkingDirectory $projectDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru
$stoppedProcesses = @()
$result = $null

try {
    & $entrypoint rail-fixture-smoke
    $transitMetadata = Invoke-RestMethod `
        -Uri 'http://127.0.0.1:8989/transit2fog/metadata' `
        -TimeoutSec 10
    $legacyMetadata = Invoke-RestMethod `
        -Uri 'http://127.0.0.1:8989/metro2fog/metadata' `
        -TimeoutSec 10
    $info = Invoke-RestMethod -Uri 'http://127.0.0.1:8989/info' -TimeoutSec 10
    $localMetadata = Get-Content -LiteralPath $graphMetadataPath -Raw -Encoding utf8 |
        ConvertFrom-Json
    $identityFields = @(
        'graph_version',
        'pbf_sha256',
        'profile_version',
        'openrailrouting_commit'
    )
    foreach ($field in $identityFields) {
        if (
            [string]($transitMetadata.$field) -ne [string]($localMetadata.$field) -or
            [string]($legacyMetadata.$field) -ne [string]($localMetadata.$field)
        ) {
            throw "sidecar metadata 与本地图元数据不一致：$field"
        }
    }
    $result = [ordered]@{
        status = 'passed'
        graph_version = [string]($transitMetadata.graph_version)
        profile_version = [string]($transitMetadata.profile_version)
        pbf_sha256 = [string]($transitMetadata.pbf_sha256)
        profiles_reported = @($info.profiles).Count
        metadata_endpoints_equal = $true
        stdout_log = $stdoutPath
        stderr_log = $stderrPath
    }
}
finally {
    $descendants = @(
        Get-ProcessDescendants `
            -RootProcessId $sidecarHost.Id `
            -ProjectDir $projectDir
    )
    foreach ($target in @($descendants | Sort-Object Depth -Descending)) {
        Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
        $stoppedProcesses += $target
    }
    if (-not $sidecarHost.HasExited) {
        Stop-Process -Id $sidecarHost.Id -Force -ErrorAction SilentlyContinue
        $stoppedProcesses += [pscustomobject]@{
            ProcessId = $sidecarHost.Id
            ParentProcessId = $null
            Name = 'pwsh.exe'
            Depth = 0
        }
    }
    $null = $sidecarHost.WaitForExit(5000)
    $sidecarHost.Dispose()
}

Start-Sleep -Milliseconds 750
$portState = foreach ($port in @(8989, 8990)) {
    $listeners = @(
        Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port `
            -State Listen -ErrorAction SilentlyContinue
    )
    [pscustomobject]@{
        port = $port
        listener_count = $listeners.Count
        owning_pid = if ($listeners.Count) {
            $listeners[0].OwningProcess
        }
        else {
            $null
        }
    }
}
if (@($portState | Where-Object { $_.listener_count -ne 0 }).Count) {
    throw 'sidecar 验收后端口未完全释放。'
}
$result['stopped_processes'] = @(
    $stoppedProcesses | Select-Object ProcessId, ParentProcessId, Name, Depth
)
$result['ports_after_cleanup'] = $portState
$result | ConvertTo-Json -Depth 6
