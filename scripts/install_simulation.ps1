# Install resistivity372 for simulation/development use from a local checkout.
# Run in PowerShell from any directory:
#   .\scripts\install_simulation.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

Set-Location $RepoRoot
python -m pip install --upgrade pip
python -m pip install -r requirements-sim.txt
python -m pip show resistivity372
