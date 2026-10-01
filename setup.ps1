param(
    [string]$PythonPath,
    [string]$DatasetArchive,
    [string]$Wheelhouse,
    [switch]$CheckOnly,
    [switch]$NonInteractive
)
$ErrorActionPreference = 'Stop'

function Test-AnalyzerPython([string]$Candidate) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
    # Store aliases can launch installation merely when probed; do not execute them.
    if ($Candidate -match 'Microsoft\\WindowsApps\\python(?:3)?\.exe$') { return $false }
    try {
        # Avoid nested quote literals: Windows PowerShell 5.1 strips them in native -c arguments.
        & $Candidate -I -c 'import sys,struct; sys.exit(int(sys.version_info[:2] != (3,14) or struct.calcsize(chr(80)) != 8))' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-AnalyzerPython {
    if ($PythonPath) {
        if (Test-AnalyzerPython $PythonPath) { return $PythonPath }
        throw 'The specified Python is unavailable or is not 64-bit Python 3.14.'
    }
    $candidates = @()
    foreach ($name in @('python','python3')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { $candidates += $command.Source }
    }
    $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe')
    foreach ($key in @('HKCU:\Software\Python\PythonCore\3.14\InstallPath','HKLM:\Software\Python\PythonCore\3.14\InstallPath')) {
        if (Test-Path $key) {
            $item = Get-ItemProperty $key
            if ($item.ExecutablePath) { $candidates += $item.ExecutablePath }
            elseif ($item.'(default)') { $candidates += (Join-Path $item.'(default)' 'python.exe') }
        }
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        # Inventory only: this does not request a runtime installation.
        $listed = & $launcher.Source --list-paths 2>$null
        foreach ($line in $listed) {
            if ($line -match '([A-Za-z]:\\.*python\.exe)\s*$') { $candidates += $Matches[1].Trim() }
        }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-AnalyzerPython $candidate) { return $candidate }
    }
    return $null
}

function Invoke-AnalyzerSetup {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'A 64-bit operating system is required.' }
    $python = Find-AnalyzerPython
    if (-not $python) {
        Write-Host '64-bit Python 3.14 was not found.'
        if ($NonInteractive -or $CheckOnly) {
            Write-Host 'Install Python 3.14 from https://www.python.org/downloads/ and rerun setup.'
            return 1
        }
        $answer = Read-Host 'Offer installation through the official Python Install Manager? [y/N]'
        if ($answer -ne 'y') { Write-Host 'Installation declined. No system components were changed.'; return 1 }
        $manager = Get-Command pymanager -ErrorAction SilentlyContinue
        if (-not $manager) {
            $winget = Get-Command winget -ErrorAction SilentlyContinue
            if (-not $winget) {
                Write-Host 'Automatic installation is unavailable. Install Python 3.14 from https://www.python.org/downloads/ and rerun setup.'
                return 1
            }
            & $winget.Source install --id 9NQ7512CXL7T --exact --accept-package-agreements
            if ($LASTEXITCODE -ne 0) { throw 'Python Install Manager installation failed.' }
            $manager = Get-Command pymanager -ErrorAction SilentlyContinue
            if (-not $manager) { Write-Host 'Close this window, reopen setup, and complete Python setup.'; return 1 }
        }
        & $manager.Source install 3.14
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.14 runtime installation failed.' }
        $python = Find-AnalyzerPython
        if (-not $python) { Write-Host 'Reopen setup after Python installation.'; return 1 }
    }
    Write-Host "Using Python: $python"
    $arguments = @((Join-Path $PSScriptRoot 'setup.py'))
    if ($DatasetArchive) { $arguments += @('--dataset-archive', $DatasetArchive) }
    if ($Wheelhouse) { $arguments += @('--wheelhouse', $Wheelhouse) }
    if ($CheckOnly) { $arguments += '--check-only' }
    & $python @arguments
    return $LASTEXITCODE
}

# Dot-sourcing exposes the small functions to tests without installing anything.
if ($MyInvocation.InvocationName -ne '.') {
    try { exit (Invoke-AnalyzerSetup) }
    catch { Write-Error $_; exit 1 }
}
