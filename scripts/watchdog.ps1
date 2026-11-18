# サーバー死活監視
#
# タスクスケジューラから定期実行する想定。
# /healthへの応答が無ければrun_all.pyを起動する。
# run_all.py自身が多重起動防止のロックを持つため、
# 既に起動中の場合はこのスクリプトから重ねて起動しても安全。

$RepoPath = "C:\git\ClaudeManagementTower"
$PythonExe = Join-Path $RepoPath ".venv\Scripts\python.exe"

$healthy = $false
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 5
    $healthy = ($response.StatusCode -eq 200)
} catch {
    $healthy = $false
}

if (-not $healthy) {
    Start-Process -FilePath $PythonExe -ArgumentList "-u", "run_all.py" -WorkingDirectory $RepoPath -WindowStyle Hidden
}
