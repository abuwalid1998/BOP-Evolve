<# : BOP Evolve one-click launcher for Windows. Double-click this file, or run: bop-evolve.bat help
@echo off
setlocal
title BOP Evolve launcher
set "BOP_SELF=%~f0"
set "BOP_ROOT=%~dp0"
set "BOP_ARGS=%*"
if defined BOP_ARGS if not "%BOP_ARGS:--no-pause=%"=="%BOP_ARGS%" set "BOP_NO_PAUSE=1"
where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo Windows PowerShell was not found. It is part of Windows 10 and 11; please repair Windows PowerShell.
  set "RC=1"
  goto :done
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$global:BopExitCode = 1; if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { Write-Host ('[FAIL] PowerShell runs in ' + $ExecutionContext.SessionState.LanguageMode + ' mode (IT policy). The launcher needs FullLanguage mode: ask IT for an exception, or start BOP Evolve manually with: docker compose up -d --build') -ForegroundColor Red; exit 1 }; & ([ScriptBlock]::Create((Get-Content -LiteralPath $env:BOP_SELF -Raw))); exit $global:BopExitCode"
set "RC=%ERRORLEVEL%"
:done
if not defined BOP_NO_PAUSE (
  echo.
  pause
)
exit /b %RC%
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
#    5. Builds and starts the containers, waits until they are healthy and
#       opens the browser (or the desktop app).
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

$script:WebPort = $DefaultWebPort
$script:ApiPort = $DefaultApiPort
$script:WslMissing = $false
$script:JustInstalledDocker = $false
$script:ListeningPorts = $null

# ----------------------------------------------------------------- arguments
$Command = 'start'
$AssumeYes = $false
$NoBrowser = $false
$argList = @()
if ($env:BOP_ARGS) { $argList = @($env:BOP_ARGS -split '\s+' | Where-Object { $_ }) }
$unknownArgs = @()
foreach ($a in $argList) {
    switch -Regex ($a.Trim('"').ToLowerInvariant()) {
        '^(-y|--yes|/y)$' { $AssumeYes = $true; continue }
        '^--no-browser$' { $NoBrowser = $true; continue }
        '^--no-pause$' { continue }
        '^(-h|--help|/\?|help)$' { $Command = 'help'; continue }
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
        Write-Ok 'Created .env from .env.example with a random local session secret'
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
    Write-Step 'Building and starting BOP Evolve (the first run downloads images and can take 5-10 minutes)'
    $code = Invoke-Compose @('up', '-d', '--build', '--remove-orphans')
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
    Write-Host "    Sign in      superadmin / $password   (other demo roles are listed on the sign-in page)" -ForegroundColor White
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
    foreach ($dir in @('frontend', 'desktop')) {
        $full = Join-Path $Root $dir
        if (Test-Path (Join-Path $full 'node_modules')) {
            Write-Ok "$dir dependencies are installed"
            continue
        }
        Write-Info "Installing $dir dependencies (npm ci)..."
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { & npm --prefix $full ci --no-audit --no-fund | Out-Host }
        finally { $ErrorActionPreference = $previous }
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed in $dir (exit code $LASTEXITCODE)." }
        Write-Ok "$dir dependencies installed"
    }
    $env:BOP_EVOLVE_SERVER_URL = "http://localhost:$($script:ApiPort)"
    Write-Info "Opening the desktop app in a new window (server $env:BOP_EVOLVE_SERVER_URL)..."
    $npm = (Get-Command npm).Source
    Start-Process -FilePath $npm -ArgumentList @('--prefix', ('"' + (Join-Path $Root 'desktop') + '"'), 'start') -WorkingDirectory $Root | Out-Null
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

    # start | desktop | reset
    $systemOk = Test-System
    if (-not $systemOk -and -not (Confirm-Action 'Some required checks failed. Continue anyway?')) {
        throw 'Stopped after failed system checks.'
    }
    [void](Initialize-Docker)
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
