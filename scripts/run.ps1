[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Workspace,
    [ValidateSet('http', 'stdio')][string]$Transport = 'http',
    [ValidateRange(1, 65535)][int]$Port = 8091,
    [string]$Name = 'codesearch-local',
    [string]$DataVolume = '',
    [string]$WslDistribution = 'Ubuntu-24.04',
    [switch]$Build
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = (Resolve-Path -LiteralPath $Workspace).Path
if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) { throw 'Workspace must be a directory.' }
$nativePodman = Get-Command podman -ErrorAction SilentlyContinue
$useWsl = $null -eq $nativePodman
function Invoke-Podman {
    param([string[]]$PodmanArgs)
    if ($useWsl) { & wsl.exe -d $WslDistribution --exec podman @PodmanArgs }
    else { & $nativePodman.Source @PodmanArgs }
    if ($LASTEXITCODE -ne 0) { throw "Podman failed (exit $LASTEXITCODE)." }
}
if ($useWsl) {
    $mountedRoot = & wsl.exe -d $WslDistribution --exec wslpath -a -u $sourceRoot.Replace('\', '/')
    if ($LASTEXITCODE -ne 0) { throw 'Could not translate workspace path into WSL.' }
    $mountedRoot = $mountedRoot.Trim()
    $buildRoot = & wsl.exe -d $WslDistribution --exec wslpath -a -u $projectRoot.Replace('\', '/')
    if ($LASTEXITCODE -ne 0) { throw 'Could not translate project path into WSL.' }
    $buildRoot = $buildRoot.Trim()
} else {
    $mountedRoot = $sourceRoot
    $buildRoot = $projectRoot
}
if ($mountedRoot.Contains(',')) { throw 'Workspace paths containing commas are unsupported by the mount syntax.' }
$sha = [Security.Cryptography.SHA256]::Create()
try { $identity = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($mountedRoot)))).Replace('-', '').ToLowerInvariant() }
finally { $sha.Dispose() }
if (-not $DataVolume) { $DataVolume = "codesearch-$($identity.Substring(0, 12))" }
if ($Build) { Invoke-Podman -PodmanArgs @('build', '--format', 'docker', '--quiet', '-t', 'localhost/codesearch:latest', '-f', "$buildRoot/Containerfile", $buildRoot) | Out-Null }
if ($Transport -eq 'http') {
    $nameFilter = 'name=^' + [regex]::Escape($Name) + '$'
    $existingIds = @(Invoke-Podman -PodmanArgs @('ps', '--all', '--filter', $nameFilter, '--format', '{{.ID}}'))
    if ($existingIds.Count -gt 1) { throw "More than one container matched $Name; refusing to stop them." }
    if ($existingIds.Count -eq 1) {
        $existing = (Invoke-Podman -PodmanArgs @('container', 'inspect', $existingIds[0]) | Out-String | ConvertFrom-Json)[0]
        $isCodeSearchImage = $existing.ImageName -match '^localhost/codesearch(?::[^/]+|@sha256:[a-f0-9]+)$'
        $isManaged = $existing.Config.Labels.'io.codesearch.managed' -eq 'true'
        $isCodeSearchCommand = ($existing.Config.Entrypoint -join ' ') -eq 'codesearch'
        if (-not $isCodeSearchCommand -or -not ($isCodeSearchImage -or $isManaged)) {
            throw "Container '$Name' is not a recognized codeSearch instance; refusing to stop it. Choose another -Name."
        }
        # Verify the replacement image before interrupting the existing service.
        Invoke-Podman -PodmanArgs @('image', 'inspect', 'localhost/codesearch:latest', '--format', '{{.Id}}') | Out-Null
        Write-Host "Replacing codeSearch container '$Name'; its data volume will be preserved."
        if ($existing.State.Running) {
            Invoke-Podman -PodmanArgs @('stop', '--time', '10', $existing.Id) | Out-Null
        }
        # --rm containers disappear on stop; retained containers must release the name.
        Invoke-Podman -PodmanArgs @('rm', '--ignore', $existing.Id) | Out-Null
    }
    # WSL forwarding can take a moment to release the old Windows listener.
    $portDeadline = [DateTime]::UtcNow.AddSeconds($(if ($existingIds.Count) { 5 } else { 0 }))
    do {
        $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        if (-not $listeners.Count -or [DateTime]::UtcNow -ge $portDeadline) { break }
        Start-Sleep -Milliseconds 250
    } while ($true)
    if ($listeners.Count) {
        $ownerIds = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
        throw "Host port $Port is already in use (PID: $ownerIds). Choose another -Port and update the MCP client URL."
    }
}
$runArgs = @(
    'run', '--rm', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
    '--userns=keep-id:uid=10001,gid=10001',
    '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
    '--mount', "type=bind,source=$mountedRoot,destination=/workspace,ro",
    '--volume', "${DataVolume}:/data",
    '--env', "CODESEARCH_WORKSPACE_ID=$identity"
)
if ($Transport -eq 'http') {
    $runArgs += @('--detach', '--name', $Name, '--label', 'io.codesearch.managed=true', '--publish', "127.0.0.1:${Port}:8090",
                  'localhost/codesearch:latest', '--transport', 'http', '--host', '0.0.0.0')
    Invoke-Podman -PodmanArgs $runArgs
    Write-Host "MCP: http://127.0.0.1:$Port/mcp"
    Write-Host "Health: http://127.0.0.1:$Port/health"
} else {
    $runArgs += @('--interactive', '--network=none', '--no-healthcheck', 'localhost/codesearch:latest', '--transport', 'stdio')
    Invoke-Podman -PodmanArgs $runArgs
}
