param([ValidateRange(1024, 65535)][int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$runtime = Join-Path $root '.runtime'
$pidFile = Join-Path $runtime 'server.json'
if (!(Test-Path -LiteralPath $python)) { throw 'Install backend dependencies in backend/.venv first (see README).' }
if (!(Test-Path -LiteralPath (Join-Path $root 'frontend\dist\index.html'))) { throw 'Build the frontend first: cd frontend; npm run build' }
foreach ($tool in @('ffmpeg', 'ffprobe')) {
    if (!(Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing dependency: $tool" }
}
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
if (Test-Path -LiteralPath $pidFile) {
    $saved = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
    $existing = Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
    if ($existing -and $existing.StartTime.ToUniversalTime().Ticks -eq $saved.startedAtTicks) {
        Write-Output "Already running: http://127.0.0.1:$($saved.port)"
        return
    }
}
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
try { $listener.Start() } finally { $listener.Stop() }
$previousEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONIOENCODING = 'utf-8'
    $process = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port") -WorkingDirectory (Join-Path $root 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'server.log') -RedirectStandardError (Join-Path $runtime 'server-error.log') -PassThru
} finally { $env:PYTHONIOENCODING = $previousEncoding }
@{ pid = $process.Id; port = $Port; startedAtTicks = $process.StartTime.ToUniversalTime().Ticks } | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Seconds 1
    $process.Refresh()
    if ($process.HasExited) { throw "Server exited. Check $runtime\server-error.log" }
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        if ($health.status -eq 'ok') {
            Write-Output "Running: http://127.0.0.1:$Port"
            return
        }
    } catch { }
}
throw "Server startup timed out. Check $runtime\server-error.log"
