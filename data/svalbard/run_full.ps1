# Run all eligible AIS trajectories. Results go into a new timestamped directory.
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$pipelinePath = Join-Path $PSScriptRoot 'code\run_pipeline.py'
& $pythonPath $pipelinePath --limit 0 --clusters 16 --window 20 --stride 10 --backend hnsw
if ($LASTEXITCODE -ne 0) {
    throw "HYDRA pipeline failed with exit code $LASTEXITCODE. Check the console output."
}
