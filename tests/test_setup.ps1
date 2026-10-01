$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $root 'setup.ps1')
$checks = 0
function Assert-Setup([bool]$Value, [string]$Message) {
    if (-not $Value) { throw "FAIL: $Message" }
    $script:checks++
    Write-Host "PASS: $Message"
}
# Real discovery/probing is read-only.
$discovered = Find-AnalyzerPython
Assert-Setup ([bool]$discovered) 'Installed supported Python discovered'
Assert-Setup (Test-AnalyzerPython $discovered) 'Version and architecture probe'
Assert-Setup (-not (Test-AnalyzerPython 'C:\missing-python\python.exe')) 'Missing executable rejected'
Assert-Setup (-not (Test-AnalyzerPython "$env:LOCALAPPDATA\Microsoft\WindowsApps\python.exe")) 'Store alias is not executed'
$PythonPath = 'C:\missing-python\python.exe'
$rejected = $false
try { Find-AnalyzerPython | Out-Null } catch { $rejected = $true }
Assert-Setup $rejected 'Invalid explicit Python path rejected'
$PythonPath = $null
# Mock absent prerequisites without uninstalling software on this computer.
function Find-AnalyzerPython { return $null }
$NonInteractive = $true
Assert-Setup ((Invoke-AnalyzerSetup) -eq 1) 'Absent Python noninteractive branch exits without installing'
$NonInteractive = $false
function Read-Host { return 'n' }
Assert-Setup ((Invoke-AnalyzerSetup) -eq 1) 'Declined Python installation does not mutate system'
function Read-Host { return 'y' }
function Get-Command { return $null }
Assert-Setup ((Invoke-AnalyzerSetup) -eq 1) 'No installer/WinGet gives manual instructions'
Write-Host "$checks setup checks passed; system installation branches were mocked, not a clean-machine test."
