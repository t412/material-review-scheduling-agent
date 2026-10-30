$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $VenvPython) {
    & $VenvPython (Join-Path $PSScriptRoot "generate_examples.py")
} else {
    python (Join-Path $PSScriptRoot "generate_examples.py")
}

exit $LASTEXITCODE

