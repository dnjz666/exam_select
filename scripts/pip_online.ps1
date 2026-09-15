<#
.SYNOPSIS
    Online pip install for backend. Proxy may stay ON (ADR-007 addendum 2026-09-14).

.DESCRIPTION
    Two deterministic paths, chosen explicitly. Never relies on the WinINET
    registry proxy fallback, which is what made the original incident
    non-reproducible:

    default    tuna mirror, DIRECT connection. Clears HTTP(S)_PROXY and sets
               NO_PROXY to an explicit host list. requests matches no_proxy by
               suffix; do NOT rely on the '*' wildcard (its meaning depends on
               the stdlib proxy_bypass fallback path, not first-class logic).
    -ViaProxy  explicit env proxy http://127.0.0.1:7897 (clash-verge /
               verge-mihomo). Explicit env beats the registry proxy; NO_PROXY
               keeps loopback direct.

    pip timeouts are pinned (PIP_DEFAULT_TIMEOUT / PIP_RETRIES) so a dead proxy
    node fails in seconds instead of stalling for 10+ minutes (the ADR-007
    incident pattern).

    Target interpreter: backend\.venv if present (ADR-001 fixed venv path),
    otherwise the `py -3.11` launcher. Never bare `python` / `python3`.

    NOTE: this script must run in a real terminal, NOT inside a DSH agent
    session - the session sandbox denies writes inside mkdtemp-created
    directories, and every pip temp dir is mkdtemp'd (ADR-007 addendum item 6).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\pip_online.ps1
    powershell -ExecutionPolicy Bypass -File scripts\pip_online.ps1 -ViaProxy
    powershell -ExecutionPolicy Bypass -File scripts\pip_online.ps1 -NoDev
#>
param(
    # Route pip through the local clash proxy instead of direct tuna access.
    [switch]$ViaProxy,
    # Install without the [dev] extra.
    [switch]$NoDev
)

$ErrorActionPreference = "Stop"

$root    = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$venvPy  = Join-Path $backend ".venv\Scripts\python.exe"

if (Test-Path $venvPy) {
    $exe = $venvPy
    $pipPre = @("-m", "pip")
    Write-Host "[pip-online] interpreter: venv python ($venvPy)"
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $exe = "py"
    $pipPre = @("-3.11", "-m", "pip")
    Write-Host "[pip-online] interpreter: py -3.11 (backend\.venv not found)"
}
else {
    throw "Neither backend\.venv\Scripts\python.exe nor the py launcher was found (see ADR-001)."
}

if ($ViaProxy) {
    # Path B: explicit proxy. Env vars beat the WinINET registry proxy, so the
    # effective route no longer depends on clash's system-proxy toggle.
    $env:HTTPS_PROXY = "http://127.0.0.1:7897"
    $env:HTTP_PROXY  = "http://127.0.0.1:7897"
    $env:NO_PROXY    = "localhost,127.0.0.1"
    $indexArgs = @()
    Write-Host "[pip-online] path B: explicit proxy 127.0.0.1:7897, default index (pypi.org)"
}
else {
    # Path A: tuna mirror, direct. Host-list NO_PROXY only; no '*' wildcard.
    Remove-Item Env:HTTP_PROXY  -ErrorAction SilentlyContinue
    Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
    $env:NO_PROXY = "pypi.tuna.tsinghua.edu.cn,pypi.org,files.pythonhosted.org,mirrors.aliyun.com,localhost,127.0.0.1"
    $indexArgs = @("-i", "https://pypi.tuna.tsinghua.edu.cn/simple")
    Write-Host "[pip-online] path A: tuna mirror, direct connection (system proxy untouched for other apps)"
}

# Fail fast instead of hanging (ADR-007: two >10 min stalls during M0).
$env:PIP_DEFAULT_TIMEOUT           = "15"
$env:PIP_RETRIES                   = "2"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

$spec = if ($NoDev) { $backend } else { "{0}[dev]" -f $backend }
Write-Host "[pip-online] target: pip install -e $spec"

& $exe @pipPre install @indexArgs -e $spec
exit $LASTEXITCODE
