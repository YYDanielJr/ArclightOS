# Historical 2026-10-30 fixed-path maintenance script; read AGENTS.md before reuse.
# One-time maintenance helper; enforces the user's 12000 MB memory ceiling.
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$reportPath = Join-Path $workspace 'maintenance\20261030\trim-boot.json'
$report = [ordered]@{ started=(Get-Date).ToUniversalTime().ToString('o'); status='starting' }
try {
    Import-Module Hyper-V
    $vm = Get-VM -Id ([guid]'B7B3525C-11AC-4305-9577-2D9AE782E8F4')
    if ($vm.State -ne 'Off') { throw 'Expected the build VM to be Off.' }
    if (@(Get-VMSnapshot -VM $vm).Count) { throw 'TRIM maintenance requires a standalone disk without checkpoints.' }
    $memory = Get-VMMemory -VM $vm
    $report.memory = $memory | Select-Object DynamicMemoryEnabled,Startup,Maximum
    if ($memory.Startup -gt 12000MB -or $memory.Minimum -gt 12000MB) { throw 'VM startup/minimum exceeds the user-approved 12000 MB memory ceiling.' }
    $os = Get-CimInstance Win32_OperatingSystem
    if (($os.FreePhysicalMemory * 1KB) -lt ($memory.Startup + 3GB)) { throw 'Insufficient free host RAM for the maintenance boot plus 3 GiB host reserve.' }
    if ($memory.DynamicMemoryEnabled -and $memory.Maximum -gt 12000MB) {
        Set-VMMemory -VM $vm -MaximumBytes 12000MB
        $report.memory_after = Get-VMMemory -VM $vm | Select-Object DynamicMemoryEnabled,Startup,Maximum
    }
    $report.automatic_checkpoints_before = $vm.AutomaticCheckpointsEnabled
    Set-VM -VM $vm -AutomaticCheckpointsEnabled $false
    Start-VM -VM $vm
    $report.status = 'started-for-trim'
} catch {
    $report.status = 'failed'; $report.error=$_.Exception.Message; throw
} finally {
    $report.finished=(Get-Date).ToUniversalTime().ToString('o')
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding UTF8
}
