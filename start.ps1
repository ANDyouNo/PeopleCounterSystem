# =============================================================
#  People Counter System - startup script (Windows PowerShell)
#  Usage:  .\start.ps1 [dev|prod]   (or via start.bat)
# =============================================================
param([string]$Mode = "prod")

$Root = $PSScriptRoot
Set-Location $Root

# ── Helpers ───────────────────────────────────────────────────
function OK($msg)   { Write-Host "[OK] $msg"    -ForegroundColor Green  }
function INFO($msg) { Write-Host "[..] $msg"    -ForegroundColor Cyan   }
function ERR($msg)  { Write-Host "[ERROR] $msg" -ForegroundColor Red    }
function WARN($msg) { Write-Host "[WARN] $msg"  -ForegroundColor Yellow }

function Abort($msg) {
    ERR $msg
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  People Counter System  v4.0"            -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# =============================================================
#  Python
# =============================================================
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Abort "Python not found. Please install Python 3.10+  https://www.python.org"
}
OK "Python: $(python --version 2>&1)"

# -- Virtual environment --
if (-not (Test-Path ".venv")) {
    INFO "Creating virtual environment .venv..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Abort "Failed to create virtual environment" }
}
& "$Root\.venv\Scripts\Activate.ps1"
OK "venv activated"

# -- Python dependencies --
python -c "import fastapi" 2>$null
if ($LASTEXITCODE -ne 0) {
    INFO "Installing Python dependencies..."
    pip install -r requirements.txt -q
    if ($LASTEXITCODE -ne 0) { Abort "pip install failed" }
    OK "Python dependencies installed"
} else {
    OK "Python dependencies OK"
}

# -- Data directory --
New-Item -ItemType Directory -Force -Path "data" | Out-Null
OK "data/ OK"

# =============================================================
#  YOLOv8 model check
# =============================================================
$hasPt   = Test-Path "yolov8n.pt"
$hasOnnx = Test-Path "yolov8n.onnx"

if (-not $hasPt -and -not $hasOnnx) {
    INFO "YOLOv8n model not found. Downloading (~6 MB)..."
    python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
    if ($LASTEXITCODE -ne 0) { Abort "Failed to download model. Check internet connection." }
    $hasPt = $true
    OK "Model downloaded: yolov8n.pt"
}

if ($hasOnnx) {
    OK "Model: yolov8n.onnx  (ONNX - recommended for Intel CPU)"
} else {
    OK "Model: yolov8n.pt"
    Write-Host ""
    Write-Host "  For better performance on Intel CPU, export the model to ONNX." -ForegroundColor Yellow
    $choice = Read-Host "  Export yolov8n.pt to ONNX now? [y/N]"
    if ($choice -match "^[Yy]$") {
        INFO "Exporting model to ONNX..."
        python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')"
        if ($LASTEXITCODE -eq 0) {
            OK "yolov8n.onnx created. Set inference_backend=onnx in Settings."
        } else {
            WARN "Export failed. Continuing with .pt"
        }
    }
}
Write-Host ""

# =============================================================
#  Node.js + npm
# =============================================================
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Abort "Node.js not found. Install Node.js 18+ from https://nodejs.org"
}
OK "Node.js: $(node --version)"

INFO "npm install (frontend)..."
Push-Location "$Root\frontend"
npm install
$npmExit = $LASTEXITCODE
Pop-Location
if ($npmExit -ne 0) { Abort "npm install failed. See errors above." }
OK "npm dependencies OK"

$env:PYTHONPATH = $Root

# =============================================================
#  Launch
# =============================================================
if ($Mode -eq "dev") {

    Write-Host ""
    Write-Host "  Backend : http://localhost:8000"             -ForegroundColor Cyan
    Write-Host "  Frontend: http://localhost:5173  <- browser" -ForegroundColor Cyan
    Write-Host "  API docs: http://localhost:8000/docs"        -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Ctrl+C to stop backend. Close the frontend window separately." -ForegroundColor Yellow
    Write-Host ""

    # Open frontend in a new PowerShell window
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "npm run dev" `
        -WorkingDirectory "$Root\frontend"

    python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

} else {

    if (-not (Test-Path "frontend\dist")) {
        INFO "Building frontend (tsc + vite)..."
        Push-Location "$Root\frontend"
        npm run build
        $buildExit = $LASTEXITCODE
        Pop-Location
        if ($buildExit -ne 0) { Abort "Frontend build failed. See errors above." }
        OK "Frontend built successfully"
    } else {
        OK "Frontend: existing build found in frontend\dist\"
    }

    Write-Host ""
    Write-Host "  URL: http://localhost:8000" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Ctrl+C to stop" -ForegroundColor Yellow
    Write-Host ""

    python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

    Write-Host ""
    WARN "Server stopped."
}

Write-Host ""
Read-Host "Press Enter to close"
