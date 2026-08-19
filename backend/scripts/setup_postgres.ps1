[CmdletBinding()]
param(
    [string]$DatabaseHost = "localhost",
    [int]$DatabasePort = 5433,
    [string]$Administrator = "postgres"
)

$ErrorActionPreference = "Stop"
$applicationRole = "carrier_hub_app"
$developmentDatabase = "carrier_intelligence_hub"
$testDatabase = "carrier_intelligence_hub_test"
$backendRoot = Split-Path -Parent $PSScriptRoot
$environmentPath = Join-Path $backendRoot ".env"
$psql = Get-Command psql -ErrorAction Stop

function ConvertFrom-SecureValue([Security.SecureString]$Value) {
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

Write-Host "Carrier Intelligence Hub PostgreSQL setup"
Write-Host "This creates only $applicationRole, $developmentDatabase, and $testDatabase."
$administratorSecret = Read-Host "PostgreSQL password for $Administrator" -AsSecureString
$demoSecret = Read-Host "Password for the three synthetic demo login accounts" -AsSecureString
$administratorPassword = ConvertFrom-SecureValue $administratorSecret
$demoPassword = ConvertFrom-SecureValue $demoSecret

if ([string]::IsNullOrWhiteSpace($administratorPassword)) {
    throw "The PostgreSQL administrator password cannot be empty."
}
if ($demoPassword.Length -lt 8) {
    throw "The demo login password must be at least 8 characters."
}

$randomBytes = [byte[]]::new(32)
[Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
$applicationPassword = [Convert]::ToBase64String($randomBytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
$sqlPassword = $applicationPassword.Replace("'", "''")

$sqlTemplate = @'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'carrier_hub_app') THEN
        CREATE ROLE carrier_hub_app LOGIN PASSWORD '__APPLICATION_PASSWORD__';
    ELSE
        ALTER ROLE carrier_hub_app WITH LOGIN PASSWORD '__APPLICATION_PASSWORD__';
    END IF;
END
$$;

SELECT format('CREATE DATABASE %I OWNER %I', 'carrier_intelligence_hub', 'carrier_hub_app')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'carrier_intelligence_hub')\gexec

SELECT format('CREATE DATABASE %I OWNER %I', 'carrier_intelligence_hub_test', 'carrier_hub_app')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'carrier_intelligence_hub_test')\gexec

ALTER DATABASE carrier_intelligence_hub OWNER TO carrier_hub_app;
ALTER DATABASE carrier_intelligence_hub_test OWNER TO carrier_hub_app;
'@

$sql = $sqlTemplate.Replace("__APPLICATION_PASSWORD__", $sqlPassword)
$previousPassword = $env:PGPASSWORD
try {
    $env:PGPASSWORD = $administratorPassword
    $sql | & $psql.Source -h $DatabaseHost -p $DatabasePort -U $Administrator -d postgres -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL setup failed. No environment file was written."
    }
}
finally {
    if ($null -eq $previousPassword) {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
    else {
        $env:PGPASSWORD = $previousPassword
    }
    $administratorPassword = $null
    $administratorSecret.Dispose()
}

$encodedApplicationPassword = [Uri]::EscapeDataString($applicationPassword)
$escapedDemoPassword = $demoPassword.Replace("\", "\\").Replace('"', '\"').Replace("`r", '\r').Replace("`n", '\n')
$environmentFile = @"
APP_NAME=Carrier Intelligence API
ENVIRONMENT=development
API_V1_PREFIX=/api/v1
FRONTEND_ORIGIN=http://localhost:5173
DATABASE_URL=postgresql+psycopg://${applicationRole}:${encodedApplicationPassword}@${DatabaseHost}:${DatabasePort}/${developmentDatabase}
TEST_DATABASE_URL=postgresql+psycopg://${applicationRole}:${encodedApplicationPassword}@${DatabaseHost}:${DatabasePort}/${testDatabase}
DEMO_SEED_PASSWORD="$escapedDemoPassword"
SESSION_COOKIE_SECURE=false
"@

[IO.File]::WriteAllText($environmentPath, $environmentFile, [Text.UTF8Encoding]::new($false))
$demoPassword = $null
$demoSecret.Dispose()
$applicationPassword = $null

Write-Host "PostgreSQL development and test databases are ready."
Write-Host "Wrote the ignored local configuration to backend/.env."
