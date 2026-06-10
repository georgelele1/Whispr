$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path "$PSScriptRoot\.."
$RuntimeDir = Join-Path $RootDir "runtime"
$VenvDir = Join-Path $RuntimeDir "venv"
$ReqFile = Join-Path $RootDir "backend\requirements.txt"

Write-Host "Project root: $RootDir"

# Prefer Python 3.11 from py launcher, fallback to python
$PythonCmd = $null

try {
    py -3.11 --version | Out-Null
    $PythonCmd = "py -3.11"
    Write-Host "Using Python: py -3.11"
}
catch {
    try {
        python --version | Out-Null
        $PythonCmd = "python"
        Write-Host "Using Python: python"
    }
    catch {
        Write-Host "Error: Python not found."
        Write-Host "Please install Python 3.11 for Windows first."
        exit 1
    }
}

if (!(Test-Path $ReqFile)) {
    Write-Host "Error: requirements.txt not found at:"
    Write-Host "  $ReqFile"
    exit 1
}

if (Test-Path $VenvDir) {
    Remove-Item $VenvDir -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

Write-Host "Creating virtual environment..."
Invoke-Expression "$PythonCmd -m venv `"$VenvDir`""

$PipPath = Join-Path $VenvDir "Scripts\pip.exe"
$PythonPath = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "Installing dependencies..."
& $PipPath install --upgrade pip setuptools wheel
& $PipPath install -r $ReqFile

Write-Host "Testing runtime..."
& $PythonPath "$RootDir\backend\app.py" cli get-language

Write-Host ""
Write-Host "Runtime setup complete."
Write-Host "Python: $PythonPath"