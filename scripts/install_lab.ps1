# Install resistivity372 for lab/hardware use from a local checkout.
# Run in PowerShell from any directory:
#   .\scripts\install_lab.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

Set-Location $RepoRoot
python -m pip install --upgrade pip
python -m pip install -r requirements-lab.txt
python -m pip show MultiPyVu
python -m pip show resistivity372
