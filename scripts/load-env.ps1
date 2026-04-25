# Load environment variables from a `.env` file into the current
# PowerShell session.
#
# PowerShell does not auto-load `.env` files. Source this script
# before running benchmarks or anything else that expects
# `OPENAI_API_KEY` (or other env vars defined in `.env`) to be set.
#
# Usage from Core repo root:
#
#     . .\scripts\load-env.ps1                # default: .\.env
#     . .\scripts\load-env.ps1 .\.env.staging  # explicit path
#
# The leading `.` is the dot-source operator — it runs the script in
# the current scope so the env-var assignments persist after the
# script exits. Without it the assignments would vanish.
#
# After sourcing, verify the key is set:
#
#     if ($env:OPENAI_API_KEY) { "set, $($env:OPENAI_API_KEY.Length) chars" } else { "unset" }

[CmdletBinding()]
param(
    [string]$Path = '.env'
)

if (-not (Test-Path -LiteralPath $Path)) {
    Write-Error "load-env.ps1: file not found: $Path"
    return
}

$count = 0
foreach ($rawLine in Get-Content -LiteralPath $Path) {
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith('#')) { continue }
    $idx = $line.IndexOf('=')
    if ($idx -lt 1) {
        Write-Warning "load-env.ps1: skipping malformed line: $line"
        continue
    }
    $name = $line.Substring(0, $idx).Trim()
    $value = $line.Substring($idx + 1).Trim()
    # Strip surrounding single or double quotes if present.
    if ($value.Length -ge 2) {
        $first = $value[0]
        $last = $value[$value.Length - 1]
        if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
            $value = $value.Substring(1, $value.Length - 2)
        }
    }
    Set-Item -Path "env:$name" -Value $value
    $count++
}
Write-Host "load-env.ps1: loaded $count variable(s) from $Path"
