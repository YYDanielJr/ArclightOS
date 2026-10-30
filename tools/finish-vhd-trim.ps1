# Historical 2026-10-30 fixed-path maintenance script; read AGENTS.md before reuse.
# Run only after successful guest TRIM and graceful shutdown.
# Merge only the automatic checkpoint created by this maintenance boot.
$ErrorActionPreference = 'Stop'
Import-Module Hyper-V
$workspace = Split-Path -Parent $PSScriptRoot
$recordDir = Join-Path $workspace 'maintenance\20261030'
$reportPath = Join-Path $recordDir 'checkpoint-merge.json'
$report = [ordered]@{started=(Get-Date).ToUniversalTime().ToString('o');status='starting'}
try {
    $before = Get-Content -LiteralPath (Join-Path $recordDir 'vhd-compaction-initial.json') -Raw | ConvertFrom-Json
    $boot = Get-Content -LiteralPath (Join-Path $recordDir 'trim-boot.json') -Raw | ConvertFrom-Json
    if ($before.status -ne 'passed' -or @($before.inventory).Count -ne 1 -or @($before.inventory[0].checkpoints).Count -ne 0) { throw 'Original checkpoint-free state not established.' }
    if ($boot.status -ne 'started-for-trim') { throw 'No successful maintenance boot record.' }
    $vm = Get-VM -Id ([guid]'B7B3525C-11AC-4305-9577-2D9AE782E8F4')
    if ($vm.State -ne 'Off') { throw 'Guest must shut down normally first.' }
    $snapshots = @(Get-VMSnapshot -VM $vm)
    if ($snapshots.Count -gt 1) { throw 'Unexpected additional checkpoints; refusing to merge.' }
    if ($snapshots.Count -eq 1) {
        $snapshot = $snapshots[0]
        $bootUtc = [DateTimeOffset]::Parse([string]$boot.started).UtcDateTime
        if ($snapshot.CreationTime.ToUniversalTime() -lt $bootUtc) { throw 'Checkpoint predates maintenance boot.' }
        $disk = @(Get-VMHardDiskDrive -VM $vm)
        if ($disk.Count -ne 1) { throw 'Unexpected disk configuration.' }
        $child = Get-VHD -Path $disk[0].Path
        if ($child.ParentPath -ne $before.disk -or $child.VhdType -ne 'Differencing') { throw 'Unexpected checkpoint parent.' }
        $report.checkpoint = $snapshot | Select-Object Name,Id,CreationTime
        $report.child = $child.Path
        $report.status = 'merging-maintenance-checkpoint'
        $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8
        Remove-VMSnapshot -VMSnapshot $snapshot -Confirm:$false
    }
    if (@(Get-VMSnapshot -VM $vm).Count -ne 0) { throw 'Checkpoint merge is incomplete.' }
    # Hyper-V may return from Remove-VMSnapshot before its background merge ends.
    $report.status = 'waiting-for-disk-merge'
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    for ($attempt=0; $attempt -lt 150; $attempt++) {
        $path = @(Get-VMHardDiskDrive -VM $vm | Select-Object -ExpandProperty Path)
        if ($path.Count -eq 1 -and $path[0] -eq $before.disk) { break }
        Start-Sleep -Seconds 2
    }
    if ($path.Count -ne 1 -or $path[0] -ne $before.disk) { throw 'Disk chain has not returned to the original standalone VHDX.' }
    $report.status = 'passed'
    & (Join-Path $PSScriptRoot 'compact-build-vhd.ps1')
} catch {
    $report.status='failed'; $report.error=$_.Exception.Message; throw
} finally {
    if ($boot -and $null -ne $boot.automatic_checkpoints_before -and $vm -and (Get-VM -Id $vm.Id).State -eq 'Off') {
        Set-VM -VM $vm -AutomaticCheckpointsEnabled ([bool]$boot.automatic_checkpoints_before)
        $report.automatic_checkpoints_restored = [bool]$boot.automatic_checkpoints_before
    }
    $report.finished=(Get-Date).ToUniversalTime().ToString('o')
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8
}
