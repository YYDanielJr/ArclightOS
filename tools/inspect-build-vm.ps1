# Historical 2026-10-30 fixed-path maintenance script; read AGENTS.md before reuse.
$ErrorActionPreference = 'Stop'
Import-Module Hyper-V
$workspace = Split-Path -Parent $PSScriptRoot
$vm = Get-VM -Id ([guid]'B7B3525C-11AC-4305-9577-2D9AE782E8F4')
[ordered]@{
    time=(Get-Date).ToUniversalTime().ToString('o')
    vm=$vm | Select-Object Name,State,Status,MemoryAssigned,Uptime
    network=@(Get-VMNetworkAdapter -VM $vm | Select-Object SwitchName,MacAddress,IPAddresses,Status)
    disks=@(Get-VMHardDiskDrive -VM $vm | Select-Object Path)
    memory=Get-VMMemory -VM $vm | Select-Object Startup,Maximum,DynamicMemoryEnabled
    checkpoints=@(Get-VMSnapshot -VM $vm | ForEach-Object { [ordered]@{name=$_.Name;id=$_.Id.ToString();creation=$_.CreationTime.ToString('o');kind=$_.CreationTime.Kind.ToString();utc=$_.CreationTime.ToUniversalTime().ToString('o')} })
    integration=@(Get-VMIntegrationService -VM $vm | Select-Object Name,Enabled,PrimaryStatusDescription)
} | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $workspace 'maintenance\20261030\vm-state.json') -Encoding UTF8
