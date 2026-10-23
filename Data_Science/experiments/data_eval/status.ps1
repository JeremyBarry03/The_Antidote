param(
    [ValidateRange(1, 300)]
    [int]$RefreshSeconds = 5,
    [switch]$Once
)

# Read-only monitor. Run in PowerShell; Ctrl+C stops the monitor, not training.
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$taskOutput = Join-Path $taskRoot 'artifacts/data_eval'

function Read-TaskJson([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    }
    return $null
}

do {
    try {
        $taskState = Read-TaskJson (Join-Path $taskOutput 'job_status.json')
        $taskRun = Read-TaskJson (Join-Path $taskOutput 'run_manifest.json')
        $taskJob = Read-TaskJson (Join-Path $taskOutput 'job_process.json')
        $taskReplay = Read-TaskJson (Join-Path $taskOutput 'optimized/manifest.json')
        $taskActive = $false
        if ($null -ne $taskJob) {
            $taskActive = $null -ne (Get-Process -Id $taskJob.pid -ErrorAction SilentlyContinue)
        }
        if (-not $Once) { Clear-Host }
        Write-Output ('A/B/C retraining | {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
        Write-Output ('Status: {0} | Process active: {1}' -f $taskState.status, $taskActive)
        if ($null -ne $taskRun) {
            Write-Output ('Stage: {0} | Completed stages: {1}/7' -f $taskRun.current_stage, @($taskRun.completed_stages).Count)
        }

        $taskLines = @()
        $taskLog = Join-Path $taskOutput 'pipeline.log'
        if (Test-Path -LiteralPath $taskLog) {
            $taskLines = @(Get-Content -LiteralPath $taskLog -Tail 300)
        }
        $taskView = $null
        $taskSplit = $null
        if ($taskRun.current_stage -eq 'optimized') {
            if (-not (Test-Path (Join-Path $taskOutput 'optimized/views/training.json'))) {
                $taskView = 'training'
                $taskSplit = 'train'
            } elseif (-not (Test-Path (Join-Path $taskOutput 'optimized/views/development.json'))) {
                $taskView = 'development'
                $taskSplit = 'validation'
            } else {
                Write-Output 'Feature preparation complete; fitting model C and its internal controls.'
            }
        } elseif ($taskRun.current_stage -in @('calibrate', 'evaluate')) {
            $taskView = if ($taskRun.current_stage -eq 'calibrate') { 'calibration_nominal' } else { 'evaluation_nominal' }
            $taskSplit = if ($taskRun.current_stage -eq 'calibrate') { 'calibration' } else { 'evaluation' }
        }
        if ($null -ne $taskView -and $null -ne $taskReplay) {
            $taskTotal = [int]$taskReplay.split_counts.$taskSplit.approaches
            if (Test-Path (Join-Path $taskOutput ('optimized/views/{0}.json' -f $taskView))) {
                Write-Output ('{0}: {1}/{1} approaches prepared; scoring and diagnostics in progress.' -f $taskView, $taskTotal)
            } else {
                $taskPrepared = 0
                $taskPattern = [regex]::Escape($taskView) + ': prepared (\d+) approaches'
                foreach ($taskLine in $taskLines) {
                    if ($taskLine -match $taskPattern) { $taskPrepared = [int]$Matches[1] }
                }
                $taskPercent = if ($taskTotal -gt 0) { 100.0 * $taskPrepared / $taskTotal } else { 0 }
                Write-Output ('{0}: {1}/{2} approaches ({3:N1}%)' -f $taskView, $taskPrepared, $taskTotal, $taskPercent)
                Write-Output 'Counts update every 25 approaches; this percentage describes the current preparation step.'
            }
        }
        Write-Output ''
        Write-Output 'Recent log:'
        $taskLines | Select-Object -Last 5 | Write-Output
        if ($taskState.status -eq 'failed') { Write-Output ('Error: {0}' -f $taskState.error) }
        if ($taskState.status -eq 'complete') { Write-Output ('Report: {0}' -f $taskState.report) }
    } catch {
        # A status file may be between writes. Retry on the next refresh.
        Write-Output ('Status temporarily unavailable: {0}' -f $_.Exception.Message)
    }
    if ($Once -or $taskState.status -in @('complete', 'failed')) { break }
    Start-Sleep -Seconds $RefreshSeconds
} while ($true)
