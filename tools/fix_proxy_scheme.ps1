<#
Fix the Windows registry proxy-scheme bug that breaks every httpx-based client
on this machine (openai SDK, httpx, requests) with
"APIConnectionError: Connection error." / "ConnectError: EOF occurred in
violation of protocol".

Root cause
----------
Clash Verge writes a bare `host:port` to the user registry value
`Software\Microsoft\Windows\CurrentVersion\Internet Settings\ProxyServer`.
CPython (`urllib/request.py:2685-2692`) then maps every scheme to
`<scheme>://<host:port>`, so the **https** proxy becomes
`https://127.0.0.1:7897` - a TLS connection to Clash's *plaintext* mixed port.

`urllib.request.getproxies()` prefers the environment over the registry, so
exporting an explicit `http://` proxy URL fixes it for Python, Node and curl
with no code change. Browsers read WinINET, not these variables, so they are
unaffected; Clash keeps owning the registry value.

Usage
-----
    pwsh -File tools/fix_proxy_scheme.ps1            # apply (default port 7897)
    pwsh -File tools/fix_proxy_scheme.ps1 -Port 7890
    pwsh -File tools/fix_proxy_scheme.ps1 -Remove    # undo
    pwsh -File tools/fix_proxy_scheme.ps1 -Status    # report only, change nothing

Caveat
------
These variables persist for the user, so if Clash is later turned OFF the
proxy target dies and the tools that read them fail. Use -Remove in that case.
This is why the fix is not applied automatically.
#>
param(
    [int]$Port = 7897,
    [switch]$Remove,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$proxy = "http://127.0.0.1:$Port"
$names = 'HTTP_PROXY', 'HTTPS_PROXY'

function Show-Current {
    Write-Host "Registry ProxyServer : $((Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name ProxyServer -ErrorAction SilentlyContinue).ProxyServer)"
    foreach ($n in $names) {
        $user = [Environment]::GetEnvironmentVariable($n, 'User')
        Write-Host ("{0,-12} (User)   : {1}" -f $n, ($(if ($user) { $user } else { '<unset>' })))
    }
    Write-Host ("getproxies() would map  https -> {0}" -f $(
        if ([Environment]::GetEnvironmentVariable('HTTPS_PROXY', 'User')) { 'http://... (CORRECT)' }
        else { 'https://... (BROKEN: TLS to a plaintext proxy port)' }))
}

if ($Status) {
    Write-Host '--- current state ---'
    Show-Current
    exit 0
}

if ($Remove) {
    foreach ($n in $names) { [Environment]::SetEnvironmentVariable($n, $null, 'User') }
    Write-Host "Removed $($names -join ', ') from the user environment."
} else {
    foreach ($n in $names) { [Environment]::SetEnvironmentVariable($n, $proxy, 'User') }
    Write-Host "Set $($names -join ', ') = $proxy (user environment)."
    Write-Host 'New shells and processes will pick it up; this shell still needs them set manually.'
}

Write-Host ''
Write-Host '--- current state ---'
Show-Current
