# =============================================================================
# build_windows.ps1 — Build single-file Mongosync Insights executables for Windows
#
# Produces one self-contained .exe per CPU architecture (no Python on the target PC).
# Must be run ON WINDOWS — PyInstaller cannot cross-compile from macOS or Linux.
#
# Prerequisites (Windows build machine or CI runner):
#   - Python 3.11+ (64-bit) from python.org or the Microsoft Store
#   - For --Arch arm64: a separate ARM64 Python on Windows on ARM
#
# Usage (PowerShell):
#   cd migration\mongosync_insights
#   .\build_windows.ps1
#   .\build_windows.ps1 -Arch all
#   .\build_windows.ps1 -Arch x86_64
#   .\build_windows.ps1 -Arch arm64
#
# Or double-click / cmd:
#   build_windows.bat
#
# Output (examples):
#   dist\mongosync-insights-0.8.2.8-windows-x86_64.exe
#   dist\mongosync-insights-0.8.2.8-windows-arm64.exe
# =============================================================================
#Requires -Version 5.1
param(
    [Parameter()]
    [ValidateSet("native", "x86_64", "arm64", "all")]
    [string]$Arch = "native"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Show-Help {
    Get-Content $MyInvocation.MyCommand.Path -TotalCount 24 | ForEach-Object {
        $_ -replace '^# ?', ''
    }
}

if ($args -contains "-h" -or $args -contains "--help") {
    Show-Help
    exit 0
}

if ($env:OS -ne "Windows_NT") {
    Write-Error "build_windows.ps1 must be run on Windows (or windows-latest CI). PyInstaller cannot build Windows .exe files from macOS or Linux."
}

function Get-AppVersion {
    $content = Get-Content -Raw -Path "lib\app_config.py"
    if ($content -match 'APP_VERSION\s*=\s*"([^"]+)"') {
        return $Matches[1]
    }
    throw "APP_VERSION not found in lib\app_config.py"
}

function Normalize-Arch {
    param([string]$Machine)
    switch ($Machine.ToUpperInvariant()) {
        "AMD64" { "x86_64" }
        "ARM64" { "arm64" }
        "X86_64" { "x86_64" }
        default { $Machine.ToLowerInvariant() }
    }
}

function Get-PythonMachine {
    param([string]$PythonExe)
    $out = & $PythonExe -c "import platform; print(platform.machine())"
    if ($LASTEXITCODE -ne 0) { throw "Failed to query Python architecture" }
    return Normalize-Arch $out.Trim()
}

function Test-PythonVersion {
    param([string]$PythonExe)
    & $PythonExe -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

function Resolve-PythonExe {
    param([string]$TargetArch)

    $candidates = @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3.11") },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() },
        @{ Exe = "python3"; Args = @() }
    )

    foreach ($c in $candidates) {
        $exe = $c.Exe
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }

        try {
            if ($c.Args.Count -gt 0) {
                $py = & $exe @($c.Args + "-c", "import sys; print(sys.executable)") 2>$null
            } else {
                $py = & $exe -c "import sys; print(sys.executable)" 2>$null
            }
            if (-not $py -or $LASTEXITCODE -ne 0) { continue }
            $py = $py.Trim().Trim('"')
            if (-not (Test-Path $py)) { continue }

            $actual = Get-PythonMachine $py
            if ($actual -eq $TargetArch -and (Test-PythonVersion $py)) {
                return $py
            }
        } catch {
            continue
        }
    }

  if ($TargetArch -eq "x86_64") {
        Write-Error @"
No 64-bit Python 3.11+ (AMD64) found in PATH.
Install from https://www.python.org/downloads/windows/ and enable 'Add python.exe to PATH'.
"@
    }
    if ($TargetArch -eq "arm64") {
        Write-Error @"
No ARM64 Python 3.11+ found in PATH.
On Windows on ARM, install the ARM64 build from python.org. On Intel/AMD Windows, arm64 builds are not supported.
"@
    }
    throw "No matching Python for architecture $TargetArch"
}

function Get-HostArch {
    foreach ($candidate in @("x86_64", "arm64")) {
        try {
            $py = Resolve-PythonExe $candidate
            return Get-PythonMachine $py
        } catch {
            continue
        }
    }
    throw "No Python 3.11+ found in PATH"
}

function Get-ArchsToBuild {
    switch ($Arch) {
        "native" { return @(Get-HostArch) }
        "x86_64" { return @("x86_64") }
        "arm64" { return @("arm64") }
        "all" { return @("x86_64", "arm64") }
    }
}

function Build-One {
    param([string]$TargetArch)

    $pythonExe = Resolve-PythonExe $TargetArch
    $actualArch = Get-PythonMachine $pythonExe
    Write-Host ""
    Write-Host "==> Building for $TargetArch (Python $actualArch)"

    $venvDir = Join-Path $ScriptDir ".build_venv_windows_$TargetArch"
    if (Test-Path $venvDir) { Remove-Item -Recurse -Force $venvDir }
    & $pythonExe -m venv $venvDir

    $activate = Join-Path $venvDir "Scripts\Activate.ps1"
    . $activate

    python -m pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
    pip install pyinstaller

    if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
    $distExe = Join-Path "dist" "mongosync-insights.exe"
    if (Test-Path $distExe) { Remove-Item -Force $distExe }

    pyinstaller --clean --noconfirm mongosync_insights_onefile.spec

    deactivate 2>$null

    if (-not (Test-Path $distExe)) {
        throw "PyInstaller did not produce dist\mongosync-insights.exe"
    }

    Remove-Item -Recurse -Force $venvDir -ErrorAction SilentlyContinue

    $appVersion = Get-AppVersion
    $distName = "mongosync-insights-$appVersion-windows-$TargetArch.exe"
    $outputPath = Join-Path $ScriptDir "dist\$distName"
    Move-Item -Force $distExe $outputPath

    Write-Host "==> Built: $outputPath"
}

$appVersion = Get-AppVersion
Write-Host "==> Building Mongosync Insights v$appVersion for Windows"

$built = 0
$skipped = 0
$failed = $false

foreach ($targetArch in (Get-ArchsToBuild)) {
    try {
        Build-One $targetArch
        $built++
    } catch {
        Write-Warning $_.Exception.Message
        if ($Arch -eq "all") {
            Write-Host "==> Skipping $targetArch (see errors above)" -ForegroundColor Yellow
            $skipped++
        } else {
            $failed = $true
        }
    }
}

Write-Host ""
if ($built -eq 0) {
    Write-Error "No binaries were built."
}

Write-Host "==> Done. $built binary/binaries in $ScriptDir\dist\"
if ($skipped -gt 0) {
    Write-Host "    ($skipped architecture(s) skipped — install the matching Python to build them)"
}

if ($failed) { exit 1 }

Write-Host ""
Write-Host "Run (pick the .exe that matches the target PC):"
Write-Host "  .\dist\mongosync-insights-$appVersion-windows-x86_64.exe   # most PCs (Intel/AMD 64-bit)"
Write-Host "  .\dist\mongosync-insights-$appVersion-windows-arm64.exe    # Windows on ARM"
Write-Host ""
Write-Host '  $env:MI_HOST="127.0.0.1"; $env:MI_PORT="3030"; .\dist\mongosync-insights-...exe'
