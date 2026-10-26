<# : BOP Evolve one-click launcher for Windows. Double-click this file, or run: bop-evolve.bat help
@echo off
rem Keep this batch part minimal: no IF tests on variables (cmd expands them before testing, which
rem breaks on empty values). All logic, argument parsing and the final pause live in PowerShell below.
setlocal
title BOP Evolve launcher
set "BOP_SELF=%~f0"
set "BOP_ROOT=%~dp0"
set "BOP_ARGS=%*"
rem PowerShell and exit are on one line: cmd parses the whole line before running it, so it never
rem reads this file again after "update" replaces it.
where powershell.exe >nul 2>&1 || (echo [FAIL] Windows PowerShell was not found. It is part of Windows 10 and 11: please repair Windows PowerShell. & pause & exit /b 1)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$global:BopExitCode = 1; if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { Write-Host ('[FAIL] PowerShell runs in ' + $ExecutionContext.SessionState.LanguageMode + ' mode (IT policy). The launcher needs FullLanguage mode: ask IT for an exception, or start BOP Evolve manually with: docker compose up -d --build') -ForegroundColor Red; if ($env:BOP_ARGS -notmatch '--no-pause') { $null = Read-Host 'Press Enter to close' }; exit 1 }; & ([ScriptBlock]::Create((Get-Content -LiteralPath $env:BOP_SELF -Raw))); exit $global:BopExitCode" & exit /b
#>

# =============================================================================
#  BOP Evolve launcher - PowerShell part (Windows PowerShell 5.1 or PowerShell 7)
#
#  The lines above are a batch header: cmd.exe runs them and hands this file to
#  PowerShell, which treats the header as a comment. Keep this file ASCII-only.
#  The header also stops early, with an explanation, when IT policy runs
#  PowerShell in Constrained Language Mode (it would block the .NET calls below).
#
#  What it does (default "start"):
#    1. Checks the computer: Windows version, CPU, memory, disk, virtualization,
#       WSL 2, winget, internet access.
#    2. Installs what is missing (Docker Desktop, WSL 2; Node.js for "desktop")
#       with winget, after asking. Starts Docker Desktop and waits for it.
#    3. Prepares .env (from .env.example, with a random local session secret).
#    4. Detects free ports for the web UI and the API and saves them in .env.
#    5. Builds the images whose source changed (and only those), starts the
#       containers, waits until they are healthy and opens the browser (or
#       the desktop app).
#
#  "update" first brings this folder up to date with the GitHub main branch
#  (turning a ZIP download into a Git checkout the first time), then does the
#  same as "start". Demo data and .env are kept.
# =============================================================================

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$global:BopExitCode = 0

try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

$IsWindowsHost = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
if ($env:BOP_ROOT) { $Root = $env:BOP_ROOT.TrimEnd('\', '/') } else { $Root = (Get-Location).Path }
$EnvPath = Join-Path $Root '.env'
$CaCertPath = Join-Path $Root '.certs/extra-ca.pem'
$DefaultWebPort = 8080
$DefaultApiPort = 8000
$BuildStatePath = Join-Path $Root '.bop-build-state.json'
$BackupRoot = Join-Path $Root '.bop-backup'
$RepoUrl = 'https://github.com/abuwalid1998/BOP-Evolve.git'
if ($env:BOP_REPO_URL) { $RepoUrl = $env:BOP_REPO_URL }

$script:WebPort = $DefaultWebPort
$script:ApiPort = $DefaultApiPort
$script:WslMissing = $false
$script:JustInstalledDocker = $false
$script:ListeningPorts = $null

# ----------------------------------------------------------------- arguments
$Command = 'start'
$AssumeYes = $false
$NoBrowser = $false
$NoPause = ($env:BOP_NO_PAUSE -eq '1')
$ForceBuild = $false
$Branch = 'main'
$argList = @()
if ($env:BOP_ARGS) { $argList = @($env:BOP_ARGS -split '\s+' | Where-Object { $_ }) }
$unknownArgs = @()
foreach ($a in $argList) {
    switch -Regex ($a.Trim('"').ToLowerInvariant()) {
        '^(-y|--yes|/y)$' { $AssumeYes = $true; continue }
        '^--no-browser$' { $NoBrowser = $true; continue }
        '^--no-pause$' { $NoPause = $true; continue }
        '^(-h|--help|/\?|help)$' { $Command = 'help'; continue }
        '^--rebuild$' { $ForceBuild = $true; continue }
        '^--branch=(.+)$' { $Branch = $matches[1]; continue }
        '^(update|pull)$' { $Command = 'update'; continue }
        '^(start|desktop|stop|status|logs|reset|check)$' { $Command = $matches[0]; continue }
        default { $unknownArgs += $a }
    }
}

# ------------------------------------------------------------------- output
function Write-Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Magenta }
function Write-Ok([string]$Text) { Write-Host "  [ OK ] $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "  [WARN] $Text" -ForegroundColor Yellow }
function Write-Bad([string]$Text) { Write-Host "  [FAIL] $Text" -ForegroundColor Red }
function Write-Info([string]$Text) { Write-Host "         $Text" -ForegroundColor Gray }

function Write-Banner {
    Write-Host ''
    Write-Host '  ==========================================================' -ForegroundColor DarkMagenta
    Write-Host '   BOP Evolve  -  Learning from Every Mistake.' -ForegroundColor White
    Write-Host '                  Improving Every Generation.' -ForegroundColor White
    Write-Host '   Prototype with SYNTHETIC demo data only.' -ForegroundColor Gray
    Write-Host '  ==========================================================' -ForegroundColor DarkMagenta
}

function Show-Help {
    Write-Host @'

Usage: bop-evolve.bat [command] [options]

Commands
  start      Check the system, install what is missing, prepare .env, pick free
             ports, build and start BOP Evolve, open the browser. (default)
  desktop    Same as start, then install Node.js if needed and open the
             Electron desktop app instead of the browser.
  update     Get the latest version from GitHub (main branch) and restart.
             Only changed files are downloaded and only changed images are
             rebuilt. Demo data and .env are kept. The first time, a folder
             downloaded as a ZIP is turned into a Git checkout (Git is
             installed if needed; sign in to GitHub when the browser asks).
  check      Only run the system and Docker checks. Installs nothing.
  status     Show container status and the URLs in use.
  logs       Follow the container logs (Ctrl+C to stop following).
  stop       Stop BOP Evolve. Demo data is kept.
  reset      Stop BOP Evolve and DELETE its demo data, then start fresh.
  help       Show this help.

Options
  --yes, -y      Answer "yes" to install / reset questions (unattended use).
  --no-browser   Do not open the browser after starting.
  --no-pause     Do not wait for a key press before closing the window.
  --rebuild      Rebuild every image even if its source has not changed.
  --branch=NAME  Branch to update from (default: main).

Images are rebuilt only when their source changes (tracked in
.bop-build-state.json); dependencies are reinstalled only when
requirements.txt or package-lock.json change.

Ports: the web UI prefers 8080 and the API 8000. If a port is busy, the next
free one is chosen automatically and saved as WEB_PORT / API_PORT in .env, so
the same address is reused next time.

Behind a TLS-inspecting corporate proxy, put the proxy root CA (PEM) in
.certs\extra-ca.pem and it is used for image builds and npm automatically.
'@
}

function Confirm-Action([string]$Question) {
    if ($AssumeYes) { Write-Info "$Question -> yes (--yes)"; return $true }
    $answer = Read-Host "  $Question [Y/n]"
    return ($answer -eq '' -or $answer -match '^\s*(y|yes)\s*$')
}

function Get-LastLine([string]$Text) {
    $lines = @($Text -split "`r?`n" | Where-Object { $_.Trim() })
    if ($lines.Count -eq 0) { return '' }
    return $lines[$lines.Count - 1].Trim()
}

# Run a native command, capture its output and exit code without throwing.
function Invoke-Quiet([string]$File, [string[]]$Arguments = @()) {
    if (-not (Get-Command $File -ErrorAction SilentlyContinue)) {
        return [pscustomobject]@{ Code = 9009; Output = "$File was not found" }
    }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $global:LASTEXITCODE = 0
        $out = & $File @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } catch {
        $out = @("$_")
        $code = 1
    } finally {
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{ Code = $code; Output = ((@($out) -join "`n").Trim()) }
}

function Update-SessionPath {
    if (-not $IsWindowsHost) { return }
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user, $env:Path) | Where-Object { $_ }) -join ';'
    $dockerBin = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin'
    if ((Test-Path $dockerBin) -and ($env:Path -notlike "*$dockerBin*")) { $env:Path = "$env:Path;$dockerBin" }
}

# Plain HTTP probe that ignores any system proxy (localhost checks only).
function Test-Url([string]$Url) {
    try {
        $request = [Net.HttpWebRequest]::Create($Url)
        $request.Proxy = $null
        $request.Timeout = 4000
        $response = $request.GetResponse()
        $status = [int]$response.StatusCode
        $response.Close()
        return ($status -ge 200 -and $status -lt 300)
    } catch {
        return $false
    }
}

# ------------------------------------------------------------- system checks
function Test-System {
    Write-Step 'Checking this computer'
    $allGood = $true
    $cs = $null
    $cpu = $null

    if ($IsWindowsHost) {
        $version = [Environment]::OSVersion.Version
        $caption = 'Windows'
        try {
            $caption = (Get-CimInstance Win32_OperatingSystem).Caption
            $cs = Get-CimInstance Win32_ComputerSystem
            $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
        } catch { }
        if ($version.Major -lt 10 -or $version.Build -lt 19041) {
            Write-Bad "$caption (build $($version.Build)): Docker Desktop needs Windows 10 build 19041+ or Windows 11."
            $allGood = $false
        } elseif ($version.Build -lt 19045) {
            Write-Warn "$caption (build $($version.Build)): update to Windows 10 22H2 or Windows 11 for current Docker Desktop releases."
        } else {
            Write-Ok "$caption (build $($version.Build))"
        }

        $arch = $env:PROCESSOR_ARCHITEW6432
        if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
        if ($arch -eq 'AMD64' -or $arch -eq 'ARM64') { Write-Ok "64-bit CPU ($arch)" }
        else { Write-Bad "CPU architecture $arch is not supported; a 64-bit (x64 or ARM64) Windows is required."; $allGood = $false }
    } else {
        Write-Warn "This launcher targets Windows; detected $([Environment]::OSVersion.VersionString). Continuing with the Docker steps."
    }

    # Memory
    $memGb = $null
    if ($cs -and $cs.TotalPhysicalMemory) { $memGb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1) }
    elseif (Test-Path '/proc/meminfo') {
        $line = Get-Content '/proc/meminfo' | Where-Object { $_ -match '^MemTotal:\s+(\d+)' } | Select-Object -First 1
        if ($line -match '(\d+)') { $memGb = [math]::Round([double]$matches[1] / 1MB, 1) }
    }
    if ($null -eq $memGb) { Write-Warn 'Could not read the amount of memory.' }
    elseif ($memGb -lt 4) { Write-Bad "$memGb GB of memory: at least 4 GB is required (8 GB recommended)."; $allGood = $false }
    elseif ($memGb -lt 8) { Write-Warn "$memGb GB of memory: it will work, 8 GB or more is recommended." }
    else { Write-Ok "$memGb GB of memory" }

    # Disk
    try {
        $drive = New-Object System.IO.DriveInfo([IO.Path]::GetPathRoot($Root))
        $freeGb = [math]::Round($drive.AvailableFreeSpace / 1GB, 1)
        if ($freeGb -lt 4) { Write-Bad "Only $freeGb GB free on $($drive.Name): at least 4 GB is required (10 GB recommended)."; $allGood = $false }
        elseif ($freeGb -lt 10) { Write-Warn "$freeGb GB free on $($drive.Name): 10 GB or more is recommended for Docker images." }
        else { Write-Ok "$freeGb GB free on $($drive.Name)" }
    } catch { Write-Warn 'Could not read free disk space.' }

    if ($IsWindowsHost) {
        # Virtualization (firmware flag reads False once Hyper-V is running, so accept either signal)
        if (($cs -and $cs.HypervisorPresent) -or ($cpu -and $cpu.VirtualizationFirmwareEnabled)) {
            Write-Ok 'Hardware virtualization is available'
        } else {
            Write-Warn 'Hardware virtualization looks disabled. If Docker fails to start, enable Intel VT-x / AMD-V (SVM) in the BIOS/UEFI.'
        }

        $wsl = Invoke-Quiet 'wsl.exe' @('--status')
        if ($wsl.Code -eq 0) { Write-Ok 'WSL 2 is installed' }
        else { $script:WslMissing = $true; Write-Warn 'WSL 2 is not set up yet (Docker Desktop needs it). It can be installed in the next step.' }

        if (Get-Command winget -ErrorAction SilentlyContinue) { Write-Ok 'winget is available for installing dependencies' }
        else { Write-Warn 'winget is not available. Install "App Installer" from the Microsoft Store, or install missing tools manually.' }
    }

    # Internet access to the Docker registry (only needed to download images)
    try {
        $request = [Net.HttpWebRequest]::Create('https://registry-1.docker.io/v2/')
        $request.Timeout = 8000
        $request.GetResponse().Close()
        Write-Ok 'Docker Hub is reachable'
    } catch [Net.WebException] {
        if ($_.Exception.Response) { Write-Ok 'Docker Hub is reachable' }
        else { Write-Warn 'Docker Hub is not reachable. The first start needs internet access (or a configured proxy) to download images.' }
    } catch {
        Write-Warn 'Could not test internet access.'
    }

    return $allGood
}

# -------------------------------------------------------------------- docker
function Get-DockerState {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return 'missing' }
    $info = Invoke-Quiet 'docker' @('info', '--format', '{{.OSType}}')
    if ($info.Code -ne 0) { return 'stopped' }
    if ((Get-LastLine $info.Output) -eq 'windows') { return 'windows-engine' }
    return 'ready'
}

function Install-DockerDesktop {
    if (-not $IsWindowsHost) {
        throw 'Docker is not installed. Install Docker Engine with Compose v2 (https://docs.docker.com/engine/install/) and run again.'
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Docker Desktop is not installed and winget is unavailable. Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and run this file again.'
    }
    if (-not (Confirm-Action 'Docker Desktop is not installed. Install it now with winget (administrator approval needed)?')) {
        throw 'Docker Desktop is required. Install it and run this file again.'
    }
    if ($script:WslMissing) {
        Write-Info 'Installing WSL 2 first (approve the administrator prompt)...'
        try {
            $p = Start-Process -FilePath 'wsl.exe' -ArgumentList @('--install', '--no-distribution') -Verb RunAs -Wait -PassThru
            Write-Info "WSL setup finished (exit code $($p.ExitCode)). Windows may ask for a restart."
        } catch {
            Write-Warn "WSL setup did not run: $($_.Exception.Message). Docker Desktop's installer will try to enable it."
        }
    }
    Write-Info 'Installing Docker Desktop with winget (this can take several minutes)...'
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & winget install --exact --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements | Out-Host }
    finally { $ErrorActionPreference = $previous }
    $code = $LASTEXITCODE
    # -1978335189 (0x8A15002B): already installed / no applicable upgrade
    if ($code -ne 0 -and $code -ne -1978335189) { throw "winget could not install Docker Desktop (exit code $code)." }
    $script:JustInstalledDocker = $true
    Update-SessionPath
}

function Start-DockerEngine {
    if ($IsWindowsHost) {
        $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
        if (Test-Path $exe) { Write-Info 'Starting Docker Desktop...'; Start-Process -FilePath $exe | Out-Null }
        else { Write-Warn "Docker Desktop was not found at $exe. Start Docker manually." }
    } else {
        Write-Warn 'The Docker daemon is not running. Start it (for example: sudo systemctl start docker).'
    }
}

function Wait-Docker([int]$Seconds = 240) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    Write-Host '         Waiting for the Docker engine' -NoNewline
    while ((Get-Date) -lt $deadline) {
        $state = Get-DockerState
        if ($state -eq 'ready' -or $state -eq 'windows-engine') { Write-Host ''; return $state }
        Write-Host '.' -NoNewline
        Start-Sleep -Seconds 3
    }
    Write-Host ''
    return (Get-DockerState)
}

function Initialize-Docker([switch]$CheckOnly) {
    Write-Step 'Checking Docker'
    Update-SessionPath
    $state = Get-DockerState
    if ($CheckOnly) {
        switch ($state) {
            'missing' { Write-Bad 'Docker is not installed. Run "bop-evolve.bat" to install Docker Desktop.' }
            'stopped' { Write-Warn 'Docker is installed but the engine is not running. "bop-evolve.bat" starts it.' }
            'windows-engine' { Write-Warn 'Docker is in Windows-containers mode; BOP Evolve needs Linux containers.' }
        }
        if ($state -ne 'ready') { return $false }
    } else {
        if ($state -eq 'missing') { Install-DockerDesktop; $state = Get-DockerState }
        if ($state -eq 'missing') {
            throw 'Docker was installed, but the docker command is not available in this window yet. Sign out and back in (or restart Windows), then run this file again.'
        }
        if ($state -eq 'stopped') { Start-DockerEngine; $state = Wait-Docker }
        if ($state -eq 'windows-engine' -and $IsWindowsHost) {
            $cli = Join-Path $env:ProgramFiles 'Docker\Docker\DockerCli.exe'
            Write-Warn 'Docker is in Windows-containers mode; switching to Linux containers...'
            if (Test-Path $cli) { & $cli -SwitchLinuxEngine | Out-Null; $state = Wait-Docker 120 }
        }
        if ($state -ne 'ready') {
            $message = 'The Docker engine is not running.'
            if ($script:JustInstalledDocker) {
                $message += ' Docker Desktop was just installed: restart Windows if asked, open Docker Desktop once to accept its terms, then run this file again.'
            } else {
                $message += ' Open Docker Desktop, wait until it shows "Engine running", then run this file again.'
            }
            throw $message
        }
    }

    $server = Invoke-Quiet 'docker' @('version', '--format', '{{.Server.Version}}')
    Write-Ok "Docker engine $(Get-LastLine $server.Output) is running (Linux containers)"
    $compose = Invoke-Quiet 'docker' @('compose', 'version', '--short')
    if ($compose.Code -ne 0) {
        if ($CheckOnly) { Write-Bad 'Docker Compose v2 is missing (it ships with Docker Desktop).'; return $false }
        throw 'Docker Compose v2 is missing. Update Docker Desktop (Compose is included) and run again.'
    }
    Write-Ok "Docker Compose $(Get-LastLine $compose.Output)"
    $mem = Invoke-Quiet 'docker' @('info', '--format', '{{.MemTotal}}')
    [long]$bytes = 0
    if ([long]::TryParse((Get-LastLine $mem.Output), [ref]$bytes) -and $bytes -gt 0) {
        $gb = [math]::Round($bytes / 1GB, 1)
        if ($gb -lt 3) { Write-Warn "Docker can use only $gb GB of memory; allow at least 4 GB (Docker Desktop > Settings > Resources)." }
        else { Write-Ok "Docker can use $gb GB of memory" }
    }
    return $true
}

function Get-ComposeFiles {
    $files = @('-f', 'docker-compose.yml')
    if (Test-Path $CaCertPath) {
        $files += @('-f', 'docker-compose.proxy.yml')
        $env:EXTRA_CA_CERT = './.certs/extra-ca.pem'
    }
    return $files
}

function Invoke-Compose([string[]]$Arguments) {
    $all = @('compose') + (Get-ComposeFiles) + $Arguments
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $global:LASTEXITCODE = 0
        & docker @all | Out-Host
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

# ------------------------------------------------------- incremental builds
# Each image is rebuilt only when the files it is built from change. A content hash of
# those files is kept in .bop-build-state.json after every successful build.
$ImagePlan = @(
    @{ Name = 'backend'; Dir = 'backend'; Image = 'bop-evolve/backend:local'; Service = 'backend' },
    @{ Name = 'frontend'; Dir = 'frontend'; Image = 'bop-evolve/frontend:local'; Service = 'frontend' }
)

function Read-BuildState {
    $state = @{}
    if (Test-Path $BuildStatePath) {
        try {
            $json = [IO.File]::ReadAllText($BuildStatePath) | ConvertFrom-Json
            foreach ($prop in $json.PSObject.Properties) { $state[$prop.Name] = [string]$prop.Value }
        } catch {
            Write-Warn 'Ignoring an unreadable .bop-build-state.json (everything will be checked again).'
        }
    }
    return $state
}

function Save-BuildState($State) {
    $ordered = New-Object 'System.Collections.Specialized.OrderedDictionary'
    foreach ($key in ($State.Keys | Sort-Object)) { $ordered[$key] = $State[$key] }
    $json = New-Object psobject -Property $ordered | ConvertTo-Json
    [IO.File]::WriteAllText($BuildStatePath, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-TextHash([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $bytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)) } finally { $sha.Dispose() }
    return (-join ($bytes | ForEach-Object { $_.ToString('x2') }))
}

# Hash of every file that goes into an image (same exclusions as the .dockerignore files).
function Get-SourceHash([string]$Dir) {
    $base = (Resolve-Path -LiteralPath (Join-Path $Root $Dir)).Path
    $skip = '[\\/](node_modules|dist|__pycache__|\.venv|\.pytest_cache|\.ruff_cache)([\\/]|$)'
    $lines = New-Object 'System.Collections.Generic.List[string]'
    $files = Get-ChildItem -LiteralPath $base -Recurse -File -Force -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($base.Length).Replace('\', '/')
        if ($rel -match $skip -or $f.Name -match '\.(pyc|db|log)$' -or $f.Name -eq '.env') { continue }
        $hash = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
        $lines.Add("$rel`t$hash")
    }
    $lines.Sort([StringComparer]::Ordinal)
    return (Get-TextHash ($lines -join "`n"))
}

function Test-ImageExists([string]$Image) {
    return ((Invoke-Quiet 'docker' @('image', 'inspect', '--format', '{{.Id}}', $Image)).Code -eq 0)
}

function Update-Images {
    Write-Step 'Checking which images need rebuilding'
    $state = Read-BuildState
    $built = 0
    foreach ($item in $ImagePlan) {
        $hash = Get-SourceHash $item.Dir
        if ($ForceBuild) { $reason = 'rebuild requested (--rebuild)' }
        elseif (-not (Test-ImageExists $item.Image)) { $reason = 'image not built yet' }
        elseif (-not $state.ContainsKey($item.Name)) { $reason = 'no build record yet (one-time check; cached layers are reused)' }
        elseif ($state[$item.Name] -ne $hash) { $reason = 'source files changed' }
        else {
            Write-Ok "$($item.Name): up to date, no rebuild needed"
            continue
        }
        Write-Info "$($item.Name): building ($reason). Dependencies are reinstalled only if their lock file changed."
        $code = Invoke-Compose @('build', $item.Service)
        if ($code -ne 0) { throw "Building the $($item.Name) image failed (exit code $code). See the messages above." }
        $state[$item.Name] = $hash
        Save-BuildState $state
        Write-Ok "$($item.Name): image rebuilt"
        $built++
    }
    if ($built -eq 0) { Write-Info 'Nothing to rebuild: starting the existing images.' }
}

# ----------------------------------------------------------- .env and files
function Read-DotEnv {
    $map = @{}
    if (Test-Path $EnvPath) {
        foreach ($line in [IO.File]::ReadAllLines($EnvPath)) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { $map[$matches[1]] = $matches[2].Trim().Trim('"') }
        }
    }
    return $map
}

function Set-DotEnvValue([string]$Key, [string]$Value) {
    $lines = New-Object 'System.Collections.Generic.List[string]'
    if (Test-Path $EnvPath) { $lines.AddRange([string[]][IO.File]::ReadAllLines($EnvPath)) }
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^\s*' + [regex]::Escape($Key) + '\s*=')) { $lines[$i] = "$Key=$Value"; $found = $true }
    }
    if (-not $found) { $lines.Add("$Key=$Value") }
    # UTF-8 without BOM: a BOM would corrupt the first key for Docker Compose.
    [IO.File]::WriteAllLines($EnvPath, $lines.ToArray(), (New-Object System.Text.UTF8Encoding($false)))
}

function Get-IntOr($Value, [int]$Fallback) {
    [int]$parsed = 0
    if ($Value -and [int]::TryParse([string]$Value, [ref]$parsed) -and $parsed -ge 1 -and $parsed -le 65535) { return $parsed }
    return $Fallback
}

function Initialize-Project {
    Write-Step 'Preparing the project'
    if (-not (Test-Path $EnvPath)) {
        $example = Join-Path $Root '.env.example'
        if (Test-Path $example) { Copy-Item -LiteralPath $example -Destination $EnvPath }
        else { [IO.File]::WriteAllText($EnvPath, '') }
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($bytes)
        $rng.Dispose()
        Set-DotEnvValue 'JWT_SECRET' (-join ($bytes | ForEach-Object { $_.ToString('x2') }))
        $keyBytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($keyBytes)
        $rng.Dispose()
        Set-DotEnvValue 'CONFIG_SECRET_KEY' ([Convert]::ToBase64String($keyBytes).Replace('+', '-').Replace('/', '_'))
        Write-Ok 'Created .env from .env.example with random local secrets'
    } else {
        Write-Ok 'Using the existing .env'
    }
    $config = Read-DotEnv
    if ($config['APP_ENV'] -eq 'production') {
        Write-Warn 'APP_ENV=production in .env: the API refuses mock sign-in in production. Use development for this prototype.'
    }

    # Shell scripts run inside Linux containers and must keep LF line endings.
    $entry = Join-Path $Root 'backend/scripts/entrypoint.sh'
    if (Test-Path $entry) {
        $text = [IO.File]::ReadAllText($entry)
        if ($text.Contains("`r")) {
            [IO.File]::WriteAllText($entry, $text.Replace("`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))
            Write-Warn 'Converted backend/scripts/entrypoint.sh to LF line endings (it was saved with Windows line endings).'
        }
    }

    if (Test-Path $CaCertPath) {
        Write-Ok 'Corporate proxy CA found (.certs/extra-ca.pem): image builds and npm will trust it'
        $env:NODE_EXTRA_CA_CERTS = $CaCertPath
    }
}

# --------------------------------------------------------------------- ports
function Get-ListeningPorts {
    if ($null -ne $script:ListeningPorts) { return $script:ListeningPorts }
    $ports = @()
    if ($IsWindowsHost -and (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)) {
        try { $ports = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.LocalPort } | Sort-Object -Unique) } catch { }
    }
    $script:ListeningPorts = $ports
    return $ports
}

# A port is free when nothing listens on it and it can be bound on all interfaces
# and loopback. The bind test also catches ports reserved by Windows (Hyper-V /
# WSL "excluded port ranges"), which Docker cannot publish either.
function Test-PortFree([int]$Port) {
    if ((Get-ListeningPorts) -contains $Port) { return $false }
    foreach ($address in @([Net.IPAddress]::Any, [Net.IPAddress]::Loopback)) {
        $listener = $null
        try {
            $listener = New-Object System.Net.Sockets.TcpListener($address, $Port)
            if ($IsWindowsHost) { $listener.ExclusiveAddressUse = $true }
            $listener.Start()
        } catch {
            return $false
        } finally {
            if ($listener) { try { $listener.Stop() } catch { } }
        }
    }
    return $true
}

function Find-FreePort([int]$Preferred, [int[]]$Avoid = @()) {
    $last = [math]::Min(65535, $Preferred + 200)
    for ($port = $Preferred; $port -le $last; $port++) {
        if ($Avoid -contains $port) { continue }
        if (Test-PortFree $port) { return $port }
    }
    # Last resort: let the operating system choose any free port.
    $listener = New-Object System.Net.Sockets.TcpListener([Net.IPAddress]::Any, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    return $port
}

function Get-PublishedPort([string]$Service, [int]$ContainerPort) {
    $result = Invoke-Quiet 'docker' (@('compose') + (Get-ComposeFiles) + @('port', $Service, "$ContainerPort"))
    if ($result.Code -ne 0) { return $null }
    foreach ($line in ($result.Output -split "`r?`n")) {
        if ($line -match ':(\d+)\s*$' -and [int]$matches[1] -gt 0) { return [int]$matches[1] }
    }
    return $null
}

function Resolve-Ports {
    Write-Step 'Choosing ports'
    $config = Read-DotEnv
    $wantWeb = Get-IntOr $config['WEB_PORT'] $DefaultWebPort
    $wantApi = Get-IntOr $config['API_PORT'] $DefaultApiPort

    # If BOP Evolve is already running, keep the ports it publishes.
    $runningWeb = Get-PublishedPort 'frontend' 8080
    $runningApi = Get-PublishedPort 'backend' 8000
    if ($runningWeb -and $runningApi) {
        $web = $runningWeb
        $api = $runningApi
        Write-Ok "BOP Evolve is already running on web port $web and API port $api"
    } else {
        $web = Find-FreePort $wantWeb
        if ($web -eq $wantWeb) { Write-Ok "Web UI port $web is free" }
        else { Write-Warn "Port $wantWeb is in use; the web UI will use port $web" }
        $api = Find-FreePort $wantApi @($web)
        if ($api -eq $wantApi) { Write-Ok "API port $api is free" }
        else { Write-Warn "Port $wantApi is in use; the API will use port $api" }
    }

    Set-DotEnvValue 'WEB_PORT' "$web"
    Set-DotEnvValue 'API_PORT' "$api"
    $env:WEB_PORT = "$web"
    $env:API_PORT = "$api"
    $script:WebPort = $web
    $script:ApiPort = $api
    Write-Info 'Saved WEB_PORT and API_PORT in .env'
}

# ----------------------------------------------------------------- run / stop
function Wait-Healthy([int]$Seconds = 360) {
    Write-Host '         Waiting for migrations, demo data and health checks' -NoNewline
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if ((Test-Url "http://127.0.0.1:$($script:ApiPort)/api/health") -and (Test-Url "http://127.0.0.1:$($script:WebPort)/healthz")) {
            Write-Host ''
            Write-Ok 'All services are healthy'
            return
        }
        Write-Host '.' -NoNewline
        Start-Sleep -Seconds 3
    }
    Write-Host ''
    throw "BOP Evolve did not become healthy within $Seconds seconds. Run 'bop-evolve.bat logs' to see why."
}

function Start-Stack {
    Update-Images
    Write-Step 'Starting BOP Evolve (containers are recreated only when their image or settings changed)'
    $code = Invoke-Compose @('up', '-d', '--no-build', '--remove-orphans')
    if ($code -ne 0) { throw "docker compose up failed (exit code $code). See the messages above, or run 'bop-evolve.bat logs'." }
    Wait-Healthy
}

function Show-Summary {
    $config = Read-DotEnv
    $password = $config['DEMO_PASSWORD']
    if (-not $password) { $password = 'Evolve#Demo2026' }
    Write-Host ''
    Write-Host '  BOP Evolve is running.' -ForegroundColor Green
    Write-Host "    Web app      http://localhost:$($script:WebPort)" -ForegroundColor White
    Write-Host "    API docs     http://localhost:$($script:ApiPort)/docs" -ForegroundColor White
    $hrPassword = $config['HR_CHIEF_PASSWORD']
    if (-not $hrPassword) { $hrPassword = '123' }
    Write-Host "    Sign in      superadmin / $password   (other demo roles are listed on the sign-in page)" -ForegroundColor White
    Write-Host "                 hr.chief / $hrPassword   (Chief HR Officer, starts with the guided tour)" -ForegroundColor White
    Write-Host '    Stop         bop-evolve.bat stop      Logs: bop-evolve.bat logs      Status: bop-evolve.bat status' -ForegroundColor Gray
    Write-Host '    Demo data is synthetic. Never connect this prototype to production systems.' -ForegroundColor Gray
}

function Get-NodeMajor {
    $result = Invoke-Quiet 'node' @('-v')
    if ($result.Code -eq 0 -and $result.Output -match 'v(\d+)\.') { return [int]$matches[1] }
    return 0
}

function Initialize-Node {
    Write-Step 'Checking Node.js (needed for the desktop app)'
    Update-SessionPath
    $major = Get-NodeMajor
    if ($major -lt 20) {
        if ($major -gt 0) { Write-Warn "Node.js $major is installed; version 20 or newer is needed." }
        else { Write-Warn 'Node.js is not installed.' }
        if (-not $IsWindowsHost -or -not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw 'Install Node.js 22 LTS from https://nodejs.org/ and run this file again.'
        }
        if (-not (Confirm-Action 'Install Node.js LTS with winget?')) { throw 'Node.js is required for the desktop app.' }
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { & winget install --exact --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements | Out-Host }
        finally { $ErrorActionPreference = $previous }
        Update-SessionPath
        $major = Get-NodeMajor
        if ($major -lt 20) { throw 'Node.js was installed but is not on PATH in this window yet. Close it and run the file again.' }
    }
    Write-Ok "Node.js $(Get-LastLine (Invoke-Quiet 'node' @('-v')).Output)"
}

function Start-Desktop {
    Initialize-Node
    Write-Step 'Preparing the desktop app'
    $state = Read-BuildState
    foreach ($dir in @('frontend', 'desktop')) {
        $full = Join-Path $Root $dir
        $lock = Join-Path $full 'package-lock.json'
        $lockHash = ''
        if (Test-Path $lock) { $lockHash = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash }
        $key = "npm:$dir"
        $installed = Join-Path $full 'node_modules/.package-lock.json'
        $current = $false
        if (Test-Path $installed) {
            if ($state.ContainsKey($key)) { $current = ($state[$key] -eq $lockHash) }
            else {
                # No record yet: npm's own install marker is newer than the lock file when it is current.
                $current = ((Get-Item -LiteralPath $installed).LastWriteTimeUtc -ge (Get-Item -LiteralPath $lock).LastWriteTimeUtc)
                if ($current) { $state[$key] = $lockHash; Save-BuildState $state }
            }
        }
        if ($current) {
            Write-Ok "$dir dependencies are up to date"
            continue
        }
        Write-Info "Installing $dir dependencies (npm ci; package-lock.json changed or first install)..."
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { & npm --prefix $full ci --no-audit --no-fund | Out-Host }
        finally { $ErrorActionPreference = $previous }
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed in $dir (exit code $LASTEXITCODE)." }
        $state[$key] = $lockHash
        Save-BuildState $state
        Write-Ok "$dir dependencies installed"
    }
    $env:BOP_EVOLVE_SERVER_URL = "http://localhost:$($script:ApiPort)"
    Write-Info "Opening the desktop app in a new window (server $env:BOP_EVOLVE_SERVER_URL)..."
    $npm = (Get-Command npm).Source
    Start-Process -FilePath $npm -ArgumentList @('--prefix', ('"' + (Join-Path $Root 'desktop') + '"'), 'start') -WorkingDirectory $Root | Out-Null
}

# ------------------------------------------------------------------- update
function Initialize-Git {
    Update-SessionPath
    $gitCmd = ''
    if ($IsWindowsHost -and $env:ProgramFiles) { $gitCmd = Join-Path $env:ProgramFiles 'Git\cmd' }
    if ($gitCmd -and (Test-Path $gitCmd) -and ($env:Path -notlike "*$gitCmd*")) { $env:Path = "$env:Path;$gitCmd" }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        if (-not $IsWindowsHost -or -not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw 'Git is not installed. Install Git for Windows from https://git-scm.com/download/win and run this file again.'
        }
        if (-not (Confirm-Action 'Git is needed to download updates. Install Git for Windows with winget?')) {
            throw 'Git is required for "update".'
        }
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { & winget install --exact --id Git.Git --accept-package-agreements --accept-source-agreements | Out-Host }
        finally { $ErrorActionPreference = $previous }
        Update-SessionPath
        if ($gitCmd -and (Test-Path $gitCmd) -and ($env:Path -notlike "*$gitCmd*")) { $env:Path = "$env:Path;$gitCmd" }
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            throw 'Git was installed but is not on PATH in this window yet. Close it and run the file again.'
        }
    }
    Write-Ok "$(Get-LastLine (Invoke-Quiet 'git' @('--version')).Output)"
}

# Git command whose output is only needed by the script.
function Invoke-GitQuiet([string[]]$Arguments) {
    return (Invoke-Quiet 'git' (@('-c', 'core.quotepath=off') + $Arguments))
}

# Git command that may need the person (for example a GitHub sign-in window).
function Invoke-GitLive([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $global:LASTEXITCODE = 0
        & git @Arguments 2>&1 | ForEach-Object { Write-Info "$_" }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Get-Lines([string]$Text) {
    return @($Text -split "`r?`n" | Where-Object { $_.Trim() })
}

function Invoke-Fetch {
    Write-Info "Downloading changes from $RepoUrl ($Branch). If a GitHub sign-in window opens, sign in with an account that can access the repository."
    $code = Invoke-GitLive @('fetch', '--prune', 'origin', $Branch)
    if ($code -ne 0) {
        throw "Could not download from GitHub (exit code $code). Check the internet connection and that your GitHub account has access to $RepoUrl, then run 'bop-evolve.bat update' again."
    }
}

# Move files out of the working tree into .bop-backup\<time>\, keeping their paths.
function Backup-Files([string[]]$Paths, [string]$Folder, [switch]$Move) {
    foreach ($rel in $Paths) {
        $source = Join-Path $Root $rel
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue }
        $target = Join-Path $Folder $rel
        $parent = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        if ($Move) { Move-Item -LiteralPath $source -Destination $target -Force }
        else { Copy-Item -LiteralPath $source -Destination $target -Force }
    }
}

# First update of a folder that was downloaded as a ZIP: connect it to GitHub in place.
function Convert-ToCheckout {
    Write-Info 'This folder is not a Git checkout (it was probably downloaded as a ZIP).'
    Write-Info 'It will be connected to GitHub so that future updates download only what changed.'
    Write-Info 'Your .env, .certs and demo data are kept. Files that are replaced, or that no longer exist'
    Write-Info 'in the new version, are moved to .bop-backup first.'
    if (-not (Confirm-Action "Connect this folder to $RepoUrl and update it to the latest $Branch?")) { throw 'Update cancelled.' }
    $gitDir = Join-Path $Root '.git'
    if ((Invoke-GitQuiet @('init', '-q')).Code -ne 0) { throw 'git init failed in this folder.' }
    [void](Invoke-GitQuiet @('remote', 'add', 'origin', $RepoUrl))
    try {
        Invoke-Fetch
    } catch {
        Remove-Item -LiteralPath $gitDir -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
    # Load the new version into the index, then compare it with the files on disk.
    if ((Invoke-GitQuiet @('read-tree', "origin/$Branch")).Code -ne 0) { throw "Could not read origin/$Branch." }
    $changed = Get-Lines (Invoke-GitQuiet @('diff', '--name-only')).Output
    $extra = Get-Lines (Invoke-GitQuiet @('ls-files', '--others', '--exclude-standard', '--', '.', ':(exclude).bop-backup', ':(exclude).bop-build-state.json')).Output
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $folder = Join-Path $BackupRoot $stamp
    if ($changed.Count -gt 0) { Backup-Files $changed $folder }
    if ($extra.Count -gt 0) { Backup-Files $extra $folder -Move }
    $code = Invoke-GitLive @('checkout', '-f', '-B', $Branch, "origin/$Branch")
    if ($code -ne 0) { throw "git checkout failed (exit code $code). Your previous files are in $folder." }
    [void](Invoke-GitQuiet @('branch', "--set-upstream-to=origin/$Branch", $Branch))
    Write-Ok "Folder connected to GitHub and updated to $Branch"
    if ($changed.Count -gt 0 -or $extra.Count -gt 0) {
        Write-Info "$($changed.Count) file(s) updated and $($extra.Count) old file(s) removed; previous copies are in .bop-backup\$stamp"
    }
}

function Update-Checkout {
    $dirty = Get-Lines (Invoke-GitQuiet @('status', '--porcelain', '--untracked-files=no')).Output
    if ($dirty.Count -gt 0) {
        Write-Warn 'These project files were changed on this computer:'
        $dirty | Select-Object -First 15 | ForEach-Object { Write-Info "  $_" }
        if (-not (Confirm-Action 'Put these changes aside with "git stash" (you can restore them later with "git stash pop") and continue?')) {
            throw 'Update cancelled: local changes were left untouched.'
        }
        $code = Invoke-GitLive @('stash', 'push', '-m', "bop-evolve update $(Get-Date -Format 'yyyy-MM-dd HH:mm')")
        if ($code -ne 0) { throw 'git stash failed; nothing was changed.' }
        Write-Ok 'Local changes saved with git stash'
    }
    $remotes = Get-Lines (Invoke-GitQuiet @('remote')).Output
    if ($remotes -notcontains 'origin') { [void](Invoke-GitQuiet @('remote', 'add', 'origin', $RepoUrl)) }
    Invoke-Fetch
    $current = Get-LastLine (Invoke-GitQuiet @('rev-parse', '--abbrev-ref', 'HEAD')).Output
    if ($current -ne $Branch) {
        $hasLocal = (Invoke-GitQuiet @('rev-parse', '--verify', '--quiet', "refs/heads/$Branch")).Code -eq 0
        if ($hasLocal) { $code = Invoke-GitLive @('checkout', $Branch) }
        else { $code = Invoke-GitLive @('checkout', '-b', $Branch, '--track', "origin/$Branch") }
        if ($code -ne 0) { throw "Could not switch to the $Branch branch." }
    }
    $head = Get-LastLine (Invoke-GitQuiet @('rev-parse', 'HEAD')).Output
    $remote = Get-LastLine (Invoke-GitQuiet @('rev-parse', "origin/$Branch")).Output
    if ($head -eq $remote) {
        Write-Ok "Already up to date with $Branch"
        return
    }
    if ((Invoke-GitQuiet @('merge-base', '--is-ancestor', "origin/$Branch", 'HEAD')).Code -eq 0) {
        Write-Warn "This copy has commits that are not on GitHub yet; nothing to download."
        return
    }
    $code = Invoke-GitLive @('merge', '--ff-only', "origin/$Branch")
    if ($code -ne 0) {
        throw "This copy and GitHub have both changed (diverged), so it cannot be updated automatically. Ask a developer to merge, or move this folder aside and run update in a fresh download."
    }
    Write-Ok "Updated to the latest $Branch"
    Write-Host ''
    Write-Info 'What changed:'
    Get-Lines (Invoke-GitQuiet @('log', '--oneline', '--no-decorate', '-n', '15', "$head..HEAD")).Output | ForEach-Object { Write-Info "  $_" }
    $stat = Get-LastLine (Invoke-GitQuiet @('diff', '--shortstat', $head, 'HEAD')).Output
    if ($stat) { Write-Info "  $stat" }
    $launcher = Get-Lines (Invoke-GitQuiet @('diff', '--name-only', $head, 'HEAD', '--', 'bop-evolve.bat')).Output
    if ($launcher.Count -gt 0) { Write-Info '  The launcher itself was updated; the new version is used from the next run.' }
}

function Update-Code {
    Write-Step "Getting the latest version from GitHub ($Branch)"
    Initialize-Git
    if (Test-Path (Join-Path $Root '.git')) { Update-Checkout } else { Convert-ToCheckout }
}

function Open-Browser {
    $url = "http://localhost:$($script:WebPort)"
    try { Start-Process $url | Out-Null; Write-Info "Opened $url in your browser" }
    catch { Write-Info "Open $url in your browser" }
}

# ---------------------------------------------------------------------- main
function Invoke-Main {
    Set-Location -LiteralPath $Root
    Write-Banner
    foreach ($a in $unknownArgs) { Write-Warn "Ignoring unknown argument '$a' (see: bop-evolve.bat help)" }
    if (-not (Test-Path (Join-Path $Root 'docker-compose.yml'))) {
        throw "docker-compose.yml was not found next to this file ($Root). Keep bop-evolve.bat in the BOP-Evolve folder."
    }

    switch ($Command) {
        'help' { Show-Help; return }
        'check' {
            $systemOk = Test-System
            $dockerOk = Initialize-Docker -CheckOnly
            Write-Host ''
            if ($systemOk -and $dockerOk) { Write-Ok 'This computer is ready for BOP Evolve.' }
            else { Write-Warn 'Some checks need attention (see above). Running "bop-evolve.bat" fixes what it can.'; $global:BopExitCode = 2 }
            return
        }
        'stop' {
            [void](Initialize-Docker)
            Write-Step 'Stopping BOP Evolve (demo data is kept)'
            if ((Invoke-Compose @('down')) -ne 0) { throw 'docker compose down failed.' }
            Write-Ok 'Stopped'
            return
        }
        'status' {
            [void](Initialize-Docker)
            Write-Step 'Status'
            [void](Invoke-Compose @('ps'))
            $web = Get-PublishedPort 'frontend' 8080
            $api = Get-PublishedPort 'backend' 8000
            if ($web -and $api) {
                Write-Info "Web app  http://localhost:$web"
                Write-Info "API docs http://localhost:$api/docs"
            } else {
                Write-Info 'BOP Evolve is not running. Start it with: bop-evolve.bat'
            }
            return
        }
        'logs' {
            [void](Initialize-Docker)
            Write-Step 'Following logs (Ctrl+C to stop following)'
            [void](Invoke-Compose @('logs', '-f', '--tail', '200'))
            return
        }
    }

    if ($Command -eq 'update') {
        # Get the code first: if downloading fails, the running version is left untouched.
        Update-Code
        [void](Initialize-Docker)
    } else {
        # start | desktop | reset
        $systemOk = Test-System
        if (-not $systemOk -and -not (Confirm-Action 'Some required checks failed. Continue anyway?')) {
            throw 'Stopped after failed system checks.'
        }
        [void](Initialize-Docker)
    }
    Initialize-Project
    if ($Command -eq 'reset') {
        Write-Step 'Reset'
        if (-not (Confirm-Action 'Delete ALL local BOP Evolve demo data and start fresh?')) { throw 'Reset cancelled.' }
        if ((Invoke-Compose @('down', '-v', '--remove-orphans')) -ne 0) { throw 'docker compose down -v failed.' }
        Write-Ok 'Containers and demo data removed'
    }
    Resolve-Ports
    Start-Stack
    Show-Summary
    if ($Command -eq 'desktop') { Start-Desktop }
    elseif (-not $NoBrowser) { Open-Browser }
}

$transcript = $false
if ($Command -ne 'logs') {
    try { Start-Transcript -Path (Join-Path $Root 'bop-evolve-launcher.log') -Append | Out-Null; $transcript = $true } catch { }
}
try {
    Invoke-Main
} catch {
    Write-Host ''
    Write-Bad $_.Exception.Message
    Write-Info 'A log of this run is in bop-evolve-launcher.log'
    $global:BopExitCode = 1
} finally {
    if ($transcript) { try { Stop-Transcript | Out-Null } catch { } }
}

# Keep a double-clicked window open so the result can be read.
if (-not $NoPause) {
    Write-Host ''
    try { $null = Read-Host '  Press Enter to close this window' } catch { }
}
