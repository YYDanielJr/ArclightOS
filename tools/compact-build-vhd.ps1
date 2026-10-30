# Historical 2026-10-30 fixed-path maintenance script; read AGENTS.md before reuse.
# Run in an elevated Windows PowerShell session. Does not start or delete a VM.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$recordDir = Join-Path $workspace 'maintenance\20261030'
New-Item -ItemType Directory -Path $recordDir -Force | Out-Null
$reportPath = Join-Path $recordDir 'vhd-compaction.json'
$diskPath = 'E:\vm\raspios_hyperv\RaspiOS Trixie\Virtual Hard Disks\RaspiOS Trixie.vhdx'
$vmId = [guid]'B7B3525C-11AC-4305-9577-2D9AE782E8F4'
$report = [ordered]@{ started = (Get-Date).ToUniversalTime().ToString('o'); status = 'starting'; disk = $diskPath }
function Save-Report { $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8 }
Save-Report
$mountedByUs = $false
try {
    Import-Module Hyper-V
    $vms = @(Get-VM)
    $report.inventory = @($vms | ForEach-Object {
        [ordered]@{ name=$_.Name; id=$_.Id.ToString(); state=$_.State.ToString();
            disks=@(Get-VMHardDiskDrive -VM $_ | Select-Object -ExpandProperty Path);
            checkpoints=@(Get-VMSnapshot -VM $_ | Select-Object Name,Id) }
    })
    Save-Report
    $vm = Get-VM -Id $vmId
    if ($vm.State -ne 'Off') { throw 'Build VM must be Off, not Running, Paused or Saved.' }
    if (@(Get-VMSnapshot -VM $vm).Count -ne 0) { throw 'Checkpoints exist; do not compact a checkpoint chain.' }
    $resolved = (Resolve-Path -LiteralPath $diskPath).ProviderPath
    if ($resolved -ne $diskPath) { throw 'Unexpected resolved VHDX path.' }
    $attachedPaths = @(Get-VMHardDiskDrive -VM $vm | Select-Object -ExpandProperty Path)
    if ($diskPath -notin $attachedPaths) { throw 'Expected build disk is not attached to the expected VM.' }
    $before = Get-VHD -Path $diskPath
    if ($before.VhdType -ne 'Dynamic' -or $before.ParentPath -or $before.Attached) { throw 'Expected an unmounted standalone dynamic VHDX.' }
    if (@(Get-ChildItem -LiteralPath (Split-Path -Parent $diskPath) -Filter '*.avhdx' -File).Count) { throw 'Differencing files exist beside build disk.' }
    if (-not (Test-VHD -Path $diskPath)) { throw 'VHD validation failed before compaction.' }
    $report.before = $before | Select-Object FileSize,Size,MinimumSize,VhdType,Attached
    $report.free_before = (Get-PSDrive E).Free
    $report.status = 'compacting-readonly-full'
    Save-Report
    Mount-VHD -Path $diskPath -ReadOnly -NoDriveLetter
    $mountedByUs = $true
    Optimize-VHD -Path $diskPath -Mode Full
    Dismount-VHD -Path $diskPath
    $mountedByUs = $false
    $after = Get-VHD -Path $diskPath
    if (-not (Test-VHD -Path $diskPath)) { throw 'VHD validation failed after compaction.' }
    if ($after.Size -ne $before.Size -or $after.Attached) { throw 'Unexpected size or attachment state after compaction.' }
    if ((Get-VM -Id $vmId).State -ne 'Off') { throw 'Unexpected VM state after compaction.' }
    $report.after = $after | Select-Object FileSize,Size,MinimumSize,VhdType,Attached
    $report.reclaimed_vhd_bytes = $before.FileSize - $after.FileSize
    $report.free_after = (Get-PSDrive E).Free
    $report.status = 'passed'
} catch {
    $report.status = 'failed'
    $report.error = $_.Exception.Message
    throw
} finally {
    if ($mountedByUs) { Dismount-VHD -Path $diskPath -ErrorAction Continue }
    $report.finished = (Get-Date).ToUniversalTime().ToString('o')
    Save-Report
}
