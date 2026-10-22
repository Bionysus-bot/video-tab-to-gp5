$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot '.runtime\server.json'
if (!(Test-Path -LiteralPath $pidFile)) { Write-Output 'Server is not running.'; return }
$saved = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
$process = Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq $saved.startedAtTicks) {
    # Windows virtual-environment launchers can have a Python child process.
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($process.Id)"
    foreach ($child in $children) {
        if ($child.Name -eq 'python.exe' -and $child.CommandLine -like '*uvicorn app.main:app*') {
            Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
        }
    }
    Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
    Write-Output 'Server stopped.'
} else { Write-Output 'Server is already stopped.' }
Remove-Item -LiteralPath $pidFile
