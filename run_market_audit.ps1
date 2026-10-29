param(
    [string]$PythonPath,
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if (Test-Path -LiteralPath $bundledPython) {
        $PythonPath = $bundledPython
    } else {
        $candidate = Get-Command python -ErrorAction SilentlyContinue
        if ($candidate -and $candidate.Source -notmatch 'WindowsApps') {
            $PythonPath = $candidate.Source
        } else {
            throw 'Supply -PythonPath with a working Python 3.12+ executable. The Windows Store alias is insufficient.'
        }
    }
}
if (-not $OutputDirectory) {
    $runName = 'market_audit_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8)
    $OutputDirectory = Join-Path $PSScriptRoot ('results/' + $runName)
}
& $PythonPath -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or later is required.' }
& $PythonPath -m unittest discover -s (Join-Path $PSScriptRoot 'tests') -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; audit not started.' }
& $PythonPath (Join-Path $PSScriptRoot 'src/audit_market_data.py') --output $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Audit failed; see the incomplete-run directory.' }
& $PythonPath (Join-Path $PSScriptRoot 'src/verify_market_audit.py') $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Real-data verification failed; audit is not verified.' }
Write-Output ('Verified audit: ' + $OutputDirectory)
