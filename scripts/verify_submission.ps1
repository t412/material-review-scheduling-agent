$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $PSScriptRoot "verify_submission.py"

if (Test-Path -LiteralPath $VenvPython) {
    & $VenvPython $ScriptPath
} else {
    python $ScriptPath
}

exit $LASTEXITCODE

