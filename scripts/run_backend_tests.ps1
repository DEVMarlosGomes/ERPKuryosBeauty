param(
    [string]$BackendUrl = "",
    [string]$PytestArgs = "backend\tests -q"
)

$ErrorActionPreference = "Stop"

if ($BackendUrl) {
    $env:REACT_APP_BACKEND_URL = $BackendUrl.TrimEnd("/")
}

if (-not $env:REACT_APP_BACKEND_URL) {
    $frontendEnv = Join-Path (Get-Location) "frontend\.env"
    if (Test-Path $frontendEnv) {
        foreach ($line in Get-Content $frontendEnv) {
            if ($line -match "^REACT_APP_BACKEND_URL=(.+)$") {
                $env:REACT_APP_BACKEND_URL = $Matches[1].Trim().Trim("'").Trim('"').TrimEnd("/")
                break
            }
        }
    }
}

if ($env:REACT_APP_BACKEND_URL) {
    Write-Host "Running backend tests against $env:REACT_APP_BACKEND_URL"
} else {
    Write-Host "REACT_APP_BACKEND_URL not set; integration tests will be skipped."
}

$argsList = $PytestArgs -split "\s+"
python -m pytest @argsList
