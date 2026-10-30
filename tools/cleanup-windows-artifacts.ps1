# Historical 2026-10-30 fixed-path maintenance script; read AGENTS.md before reuse.
# One-time, bounded cleanup authorized for the 2026-10-30 handoff.
# Keep the complete latest release manifest and convenient current package outputs.
[CmdletBinding()]
param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).ProviderPath
$expected = 'E:\vm\raspios_hyperv\debian_yydaniel_src'
if ($root -ne $expected) { throw 'This one-time cleanup is restricted to its original workspace.' }
$recordDir = Join-Path $root 'maintenance\20261030'
New-Item -ItemType Directory -Path $recordDir -Force | Out-Null
function Assert-Bounded([string]$path) {
    $resolved = (Resolve-Path -LiteralPath $path).ProviderPath
    if (-not $resolved.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Outside workspace: $resolved" }
    $item = Get-Item -LiteralPath $resolved -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point: $resolved" }
    if ($item.PSIsContainer) {
        if (@(Get-ChildItem -LiteralPath $resolved -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "Reparse point inside: $resolved" }
    }
    return $resolved
}
$dist = Join-Path $root 'dist'
$keep = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
[void]$keep.Add('astgenne-release.sha256')
foreach ($line in Get-Content -LiteralPath (Join-Path $dist 'astgenne-release.sha256')) {
    if ($line -notmatch '^([0-9a-f]{64})  ([^/\\]+)$') { throw 'Unexpected manifest entry.' }
    $digest = $Matches[1]; $name = $Matches[2]
    [void]$keep.Add($name)
    $file = Assert-Bounded (Join-Path $dist $name)
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $digest) { throw "Release hash mismatch: $name" }
}
foreach ($name in @(
    'astesia-kernel_7.3-3+astgenne1_amd64.deb',
    'yydanielkernel_7.3-3+astgenne1_amd64.deb',
    'linux-image-7.3.0-yydanielkernel_7.3-2+yydaniel1_amd64.deb',
    'linux-headers-7.3.0-yydanielkernel_7.3-2+yydaniel1_amd64.deb',
    'linux-upstream_7.3-2+yydaniel1_amd64.buildinfo',
    'linux-upstream_7.3-2+yydaniel1_amd64.changes',
    'config-7.3.0-yydanielkernel',
    'yydaniel-desktop_0.3.2_amd64.deb',
    'yydaniel-desktop_0.3.2_amd64.buildinfo',
    'yydaniel-desktop_0.3.2_amd64.changes',
    'yydaniel-desktop_0.3.2.dsc',
    'yydaniel-desktop_0.3.2.tar.xz',
    'astgenne-branding_0.1.0_all.deb'
)) { [void]$keep.Add($name) }
$targets = @()
if (Test-Path -LiteralPath (Join-Path $root 'build')) { $targets += Join-Path $root 'build' }
$targets += @(Get-ChildItem -LiteralPath $dist -File -Force | Where-Object { -not $keep.Contains($_.Name) } | Select-Object -ExpandProperty FullName)
$targets += @(Get-ChildItem -LiteralPath (Join-Path $root '.local') -Force | Where-Object { $_.Name -notin @('python','known_hosts') } | Select-Object -ExpandProperty FullName)
$targets = @($targets | ForEach-Object { Assert-Bounded $_ })
$files = @(foreach ($path in $targets) {
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer) { Get-ChildItem -LiteralPath $path -Recurse -Force -File }
    else { $item }
})
$plan = [ordered]@{
    date=(Get-Date).ToUniversalTime().ToString('o'); workspace=$root
    free_before=(Get-PSDrive E).Free
    file_bytes=($files | Measure-Object Length -Sum).Sum; file_count=$files.Count
    targets=$targets; retained_dist=@($keep | Sort-Object)
    deleted_files=@($files | Select-Object @{n='path';e={$_.FullName.Substring($root.Length+1)}},Length)
    executed=$false
}
$plan | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $recordDir 'windows-cleanup.json') -Encoding UTF8
if (-not $Execute) { [pscustomobject]$plan | Select-Object file_bytes,file_count,executed | ConvertTo-Json; exit }
$verification = Join-Path $root 'build\astgenne-release-host-verification.json'
if (Test-Path -LiteralPath $verification) { Copy-Item -LiteralPath $verification -Destination (Join-Path $recordDir 'release-verification-original.json') }
foreach ($path in $targets) {
    $null = Assert-Bounded $path
    Remove-Item -LiteralPath $path -Recurse -Force
    if (Test-Path -LiteralPath $path) { throw "Cleanup incomplete: $path" }
}
$plan.executed = $true
$plan.free_after = (Get-PSDrive E).Free
$plan | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $recordDir 'windows-cleanup.json') -Encoding UTF8
[pscustomobject]$plan | Select-Object file_bytes,file_count,free_before,free_after,executed | ConvertTo-Json
