param(
    [string]$BackendUrl = "",
    [string]$PytestArgs = "backend\tests -q",
    [int]$Port = 8011
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$testArtifacts = Join-Path $repoRoot ".test-artifacts"
$serverProcess = $null

function Wait-ForApi([string]$Url, [int]$TimeoutSeconds = 45) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri "$Url/docs" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "A API de homologacao nao iniciou em $Url dentro de $TimeoutSeconds segundos."
}

try {
    if ($BackendUrl) {
        $env:VITE_BACKEND_URL = $BackendUrl.TrimEnd("/")
    } elseif (-not $env:VITE_BACKEND_URL -and -not $env:REACT_APP_BACKEND_URL) {
        New-Item -ItemType Directory -Path $testArtifacts -Force | Out-Null
        $env:ENVIRONMENT = "test"
        $env:MONGO_URL = "mongodb://127.0.0.1:27017"
        $env:DB_NAME = "kuryos_http_homolog"
        $env:JWT_SECRET = "Kuryos-HTTP-Homolog-JWT-Strong-Secret-2026"
        $env:SEED_DEMO_USERS = "true"
        $env:RESET_SEEDED_PASSWORDS = "true"
        $env:WRITE_TEST_CREDENTIALS = "false"
        $env:ALLOW_DESTRUCTIVE_TEST_RESET = "true"
        $env:ADMIN_EMAIL = "admin@kuryos.com"
        $env:ADMIN_PASSWORD = "Kuryos-Test-Admin-2026!"
        $env:ROLE_USERS_PASSWORD = "Kuryos-Test-Roles-2026!"
        $env:TEST_ADMIN_EMAIL = $env:ADMIN_EMAIL
        $env:TEST_ADMIN_PASSWORD = $env:ADMIN_PASSWORD
        $env:TEST_ROLE_USERS_PASSWORD = $env:ROLE_USERS_PASSWORD
        $env:VITE_BACKEND_URL = "http://127.0.0.1:$Port"

        $stdout = Join-Path $testArtifacts "http-homolog.out.log"
        $stderr = Join-Path $testArtifacts "http-homolog.err.log"
        $serverProcess = Start-Process -FilePath "python" `
            -ArgumentList "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "$Port" `
            -WorkingDirectory $backendDir `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr `
            -WindowStyle Hidden `
            -PassThru
        Wait-ForApi $env:VITE_BACKEND_URL
    } elseif (-not $env:VITE_BACKEND_URL) {
        $env:VITE_BACKEND_URL = $env:REACT_APP_BACKEND_URL.TrimEnd("/")
    }

    Write-Host "Executando testes HTTP contra $env:VITE_BACKEND_URL"
    $argsList = $PytestArgs -split "\s+"
    & python -m pytest @argsList
    $pytestExitCode = $LASTEXITCODE
} finally {
    if ($serverProcess -and -not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force
        $serverProcess.WaitForExit()
    }
}

exit $pytestExitCode
