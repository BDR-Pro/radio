#Requires -Version 5.1
<#
.SYNOPSIS
    SDR Kid — one-click Windows setup.

.DESCRIPTION
    Downloads and unpacks every command-line tool SDR Kid can use,
    puts them under C:\Users\<you>\sdr-kid-tools\, and adds each
    folder to your User PATH (no admin needed).

    Tools handled:
      * rtl-sdr        (rtl_test.exe, rtl_fm.exe, rtl_sdr.exe, …)
      * SoX            (audio playback for FM / ATC / NOAA)
      * AIS-catcher    (ship tracker)
      * dump1090       (airplane tracker — your antenna)
      * noaa-apt       (weather-satellite image decoder)
      * Zadig          (one-time USB driver replacement, opens installer)

.PARAMETER InstallRoot
    Where everything lives. Default: $env:USERPROFILE\sdr-kid-tools

.PARAMETER SkipZadig
    Don't download Zadig. Pass this if you already ran it once.

.PARAMETER DryRun
    Print what would happen — don't download or edit PATH.

.EXAMPLE
    # Run it directly from GitHub:
    irm https://raw.githubusercontent.com/BDR-Pro/radio/main/scripts/install-windows.ps1 | iex

.EXAMPLE
    # Or if you cloned the repo:
    powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
#>
param(
    [string]$InstallRoot = "$env:USERPROFILE\sdr-kid-tools",
    [switch]$SkipZadig,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# --- pretty printers ---------------------------------------------------------

function Say($msg, $color = 'Cyan')    { Write-Host $msg -ForegroundColor $color }
function Ok($msg)                       { Say "  ✔ $msg" 'Green' }
function Warn($msg)                     { Say "  ! $msg" 'Yellow' }
function Fail($msg)                     { Say "  ✘ $msg" 'Red' }

# --- catalog of downloads ----------------------------------------------------
# Each item:
#   name        friendly name
#   url         zip URL to download
#   folder      subfolder name under $InstallRoot
#   pathHint    subpath within extracted folder to add to PATH (optional)
#   check       command to test after install (bare word, no args)
$catalog = @(
    @{
        name     = 'rtl-sdr'
        url      = 'https://github.com/rtlsdrblog/rtl-sdr-blog/releases/download/1.35/Release.zip'
        folder   = 'rtl-sdr'
        pathHint = 'x64'
        check    = 'rtl_test'
        why      = 'talk to the RTL-SDR dongle (rtl_test / rtl_fm / rtl_sdr)'
    },
    @{
        name     = 'AIS-catcher'
        url      = 'https://github.com/jvde-github/AIS-catcher/releases/latest/download/AIS-catcher-win64.zip'
        folder   = 'ais-catcher'
        pathHint = ''
        check    = 'AIS-catcher'
        why      = 'decode ships (AIS) into NMEA sentences'
    },
    @{
        name     = 'dump1090'
        url      = 'https://github.com/mutability/dump1090/releases/download/v1.15~dev/dump1090.win.1.15.zip'
        folder   = 'dump1090'
        pathHint = ''
        check    = 'dump1090'
        why      = 'decode airplanes (ADS-B) from your antenna'
    },
    @{
        name     = 'noaa-apt'
        url      = 'https://github.com/martinber/noaa-apt/releases/download/v1.4.0/noaa-apt-1.4.0-x86_64-windows-gnu.zip'
        folder   = 'noaa-apt'
        pathHint = ''
        check    = 'noaa-apt'
        why      = 'turn weather-satellite audio into images'
    }
)

# SoX and Zadig are single executables (installer / GUI) — handled separately.
$soxUrl   = 'https://sourceforge.net/projects/sox/files/sox/14.4.2/sox-14.4.2-win32.exe/download'
$zadigUrl = 'https://zadig.akeo.ie/downloads/zadig-2.9.exe'

# --- helpers ---------------------------------------------------------------

function Add-ToUserPath([string]$folder) {
    $folder = $folder.TrimEnd('\')
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($null -eq $current) { $current = '' }
    $parts = $current.Split(';') | Where-Object { $_ -ne '' }
    if ($parts -contains $folder) {
        return $false     # already there
    }
    if ($DryRun) {
        Say "    (dry-run) would add: $folder" 'DarkGray'
        return $true
    }
    $new = ($parts + $folder) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $new, 'User')
    $env:Path = "$env:Path;$folder"     # apply to THIS shell too
    return $true
}

function Download-And-Extract($item) {
    $dest = Join-Path $InstallRoot $item.folder
    if (Test-Path $dest -PathType Container) {
        Ok "$($item.name) already unpacked at $dest"
    }
    else {
        if ($DryRun) {
            Say "    (dry-run) would download $($item.url)" 'DarkGray'
            Say "    (dry-run) would extract to  $dest"      'DarkGray'
            return $dest
        }
        $tmp = Join-Path ([IO.Path]::GetTempPath()) ("sdrkid-" + [Guid]::NewGuid() + ".zip")
        try {
            Say "  ↓ downloading $($item.name)…" 'Cyan'
            Invoke-WebRequest -Uri $item.url -OutFile $tmp -UseBasicParsing
            Say "  ↳ extracting to $dest" 'Cyan'
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
            Expand-Archive -Path $tmp -DestinationPath $dest -Force
            Ok "$($item.name) installed"
        }
        catch {
            Fail "$($item.name) download or extract failed: $($_.Exception.Message)"
            return $null
        }
        finally {
            Remove-Item -Force $tmp -ErrorAction SilentlyContinue
        }
    }
    # Some zips extract a single subfolder; find the folder that actually
    # contains the .exe we want and use THAT for PATH.
    $target = $dest
    if ($item.pathHint) {
        $candidate = Join-Path $dest $item.pathHint
        if (Test-Path $candidate) { $target = $candidate }
    }
    $exe = Get-ChildItem -Path $dest -Recurse -Filter "$($item.check).exe" -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if ($exe) { $target = Split-Path $exe.FullName -Parent }
    return $target
}

# --- go ---------------------------------------------------------------------

Say '' 'White'
Say '======================================================' 'Magenta'
Say '   SDR Kid — Windows one-click installer'              'Magenta'
Say '======================================================' 'Magenta'
Say "InstallRoot : $InstallRoot" 'DarkGray'
if ($DryRun) { Warn "DRY RUN — nothing will actually be downloaded or written." }

if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
}

$installed = @()   # (name, folder-added-to-path, exe-check)

foreach ($item in $catalog) {
    Say ''
    Say "-- $($item.name) --  ($($item.why))" 'White'
    $target = Download-And-Extract $item
    if ($null -eq $target) { continue }
    $added = Add-ToUserPath $target
    if ($added) { Ok "PATH: added $target" } else { Ok "PATH: already contained $target" }
    $installed += [pscustomobject]@{
        Tool = $item.name
        Path = $target
        Exe  = $item.check
    }
}

# --- SoX (installer, needs GUI click) ---------------------------------------

Say ''
Say '-- SoX --  (audio playback for FM / ATC)' 'White'
$soxDefault = 'C:\Program Files (x86)\sox-14-4-2'
if (Test-Path (Join-Path $soxDefault 'sox.exe')) {
    Ok "SoX already installed at $soxDefault"
    $added = Add-ToUserPath $soxDefault
    if ($added) { Ok "PATH: added $soxDefault" } else { Ok "PATH: already contained $soxDefault" }
    $installed += [pscustomobject]@{ Tool = 'SoX'; Path = $soxDefault; Exe = 'sox' }
}
else {
    if ($DryRun) {
        Say "    (dry-run) would download SoX installer from $soxUrl" 'DarkGray'
    }
    else {
        $soxExe = Join-Path $InstallRoot 'sox-installer.exe'
        try {
            Say "  ↓ downloading SoX installer…" 'Cyan'
            Invoke-WebRequest -Uri $soxUrl -OutFile $soxExe -UseBasicParsing
            Warn "SoX ships as a GUI installer — clicking through it now."
            Warn "Accept the default install path so this script can find it."
            Start-Process -FilePath $soxExe -Wait
            if (Test-Path (Join-Path $soxDefault 'sox.exe')) {
                Ok "SoX installed"
                Add-ToUserPath $soxDefault | Out-Null
                Ok "PATH: added $soxDefault"
                $installed += [pscustomobject]@{ Tool = 'SoX'; Path = $soxDefault; Exe = 'sox' }
            }
            else {
                Warn "Couldn't find sox.exe at the default location. Add its folder to PATH by hand."
            }
        }
        catch {
            Fail "SoX download failed: $($_.Exception.Message)"
        }
    }
}

# --- Zadig (driver swap, launched separately) -------------------------------

if (-not $SkipZadig) {
    Say ''
    Say '-- Zadig --  (one-time USB driver swap — required)' 'White'
    if ($DryRun) {
        Say "    (dry-run) would download Zadig from $zadigUrl" 'DarkGray'
    }
    else {
        $zadigExe = Join-Path $InstallRoot 'zadig.exe'
        try {
            if (-not (Test-Path $zadigExe)) {
                Say "  ↓ downloading Zadig…" 'Cyan'
                Invoke-WebRequest -Uri $zadigUrl -OutFile $zadigExe -UseBasicParsing
            }
            Ok "Zadig at $zadigExe"
            Warn "Now:"
            Warn "  1. Plug in the RTL-SDR dongle."
            Warn "  2. Launch:  $zadigExe"
            Warn "  3. Options → List All Devices"
            Warn "  4. Pick 'Bulk-In, Interface (Interface 0)'."
            Warn "  5. Confirm target driver is WinUSB, click Replace Driver."
        }
        catch {
            Fail "Zadig download failed: $($_.Exception.Message)"
        }
    }
}

# --- summary ----------------------------------------------------------------

Say ''
Say '======================================================' 'Magenta'
Say '   All done — summary' 'Magenta'
Say '======================================================' 'Magenta'
if ($installed.Count -eq 0) {
    Warn "Nothing was installed. Check the errors above."
}
else {
    $installed | Format-Table -AutoSize | Out-Host
}
Say ''
Say 'Open a NEW PowerShell window (PATH changes only apply to fresh shells)' 'Yellow'
Say 'and try:' 'Yellow'
Say '    rtl_test.exe -t                         # should find your dongle' 'Cyan'
Say '    sox -n -t waveaudio -d synth 1 sine 440 # should beep' 'Cyan'
Say '    python -m sdr_kid                       # play!' 'Cyan'
Say ''
