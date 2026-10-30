$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }

$SecureKey = Read-Host "Provider API key (hidden input)" -AsSecureString
$KeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)

try {
    $env:OPENAI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($KeyPointer)
    $env:OPENAI_MODEL = Read-Host "Tool-calling model name (DeepSeek example: deepseek-flash)"
    $BaseUrl = Read-Host "OpenAI-compatible base URL (DeepSeek: https://api.deepseek.com; official OpenAI: press Enter)"
    if (-not [string]::IsNullOrWhiteSpace($BaseUrl)) {
        $env:OPENAI_BASE_URL = $BaseUrl
    }

    & $Python (Join-Path $PSScriptRoot "generate_live_examples.py")
    $ExitCode = $LASTEXITCODE
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($KeyPointer)
    Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:OPENAI_MODEL -ErrorAction SilentlyContinue
    Remove-Item Env:OPENAI_BASE_URL -ErrorAction SilentlyContinue
}

exit $ExitCode

