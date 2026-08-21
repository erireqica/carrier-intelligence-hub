[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot 'backend'
$frontendRoot = Join-Path $repoRoot 'frontend'
$python = Join-Path $backendRoot '.venv\Scripts\python.exe'
$vite = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'
$runtime = Join-Path $repoRoot '.runtime'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Backend virtual environment is missing. Complete the README setup first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'node_modules'))) {
    throw 'Frontend dependencies are missing. Run npm install in frontend first.'
}
$node = (Get-Command node -ErrorAction Stop).Source

function Test-DevelopmentPort {
    param([Parameter(Mandatory)][int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $attempt = $client.ConnectAsync('localhost', $Port)
        return $attempt.Wait(500) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

$busyPorts = 5173, 8000 | Where-Object { Test-DevelopmentPort -Port $_ }
if ($busyPorts.Count -gt 0) {
    throw 'Port 5173 or 8000 is already in use. Stop the existing development processes first.'
}
$duplicateWorker = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'app\.workers\.pipeline' }
if ($duplicateWorker) {
    throw 'A Carrier Hub pipeline worker is already running. Stop it before using this launcher.'
}

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$children = @()
try {
    $children += Start-Process -FilePath $python -ArgumentList @(
        '-m', 'uvicorn', 'app.main:app', '--host', 'localhost', '--port', '8000'
    ) -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'dev-api.out.log') `
        -RedirectStandardError (Join-Path $runtime 'dev-api.err.log')
    $children += Start-Process -FilePath $python -ArgumentList @(
        '-m', 'app.workers.pipeline'
    ) -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'dev-pipeline.out.log') `
        -RedirectStandardError (Join-Path $runtime 'dev-pipeline.err.log')
    $children += Start-Process -FilePath $node -ArgumentList @(
        $vite, '--host', 'localhost', '--port', '5173', '--strictPort'
    ) -WorkingDirectory $frontendRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime 'dev-frontend.out.log') `
        -RedirectStandardError (Join-Path $runtime 'dev-frontend.err.log')

    Start-Sleep -Seconds 3
    $failed = $children | Where-Object { $_.HasExited }
    if ($failed) {
        throw 'A development process exited during startup. Check .runtime/dev-*.err.log.'
    }
    Write-Host 'Carrier Hub is running at http://localhost:5173'
    Write-Host 'FastAPI, the automatic Gmail pipeline, and Vite are active. Press Ctrl+C to stop all three.'
    while ($true) {
        Start-Sleep -Seconds 1
        $failed = $children | Where-Object { $_.HasExited }
        if ($failed) {
            throw 'A development process stopped unexpectedly. Check .runtime/dev-*.err.log.'
        }
    }
}
finally {
    foreach ($child in $children) {
        if (-not $child.HasExited) {
            Stop-Process -Id $child.Id -ErrorAction SilentlyContinue
        }
    }
    Write-Host 'Carrier Hub development processes stopped.'
}
