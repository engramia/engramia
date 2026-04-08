# SPDX-License-Identifier: BUSL-1.1
#
# ci-check.ps1 - Hourly CI watchdog for engramia/engramia
#
# Checks whether the latest CI run on main is red and idle.
#
# -AutoRepair (primary mode):
#   1. Fetches failure logs from GitHub Actions
#   2. Calls Claude Code with the logs as context
#   3. Claude Code analyzes, fixes the code, commits and pushes
#   4. Waits for the new CI run to complete
#   5. If still red, repeats from step 1 (up to -MaxRetries times, default 5)
#
# -Fix (fallback for transient failures only):
#   Blind re-run of failed jobs without code changes.
#   Use only for infrastructure issues (flaky runner, network timeout).
#
# Requirements:
#   - gh CLI installed and authenticated (gh auth login)
#   - claude CLI installed (for -AutoRepair)
#
# Usage:
#   .\scripts\ci-check.ps1                                    # dry-run: report status only
#   .\scripts\ci-check.ps1 -AutoRepair                        # fix-wait-retry loop (max 5)
#   .\scripts\ci-check.ps1 -AutoRepair -MaxRetries 3 -Quiet   # custom retries, quiet
#   .\scripts\ci-check.ps1 -Fix                               # blind re-run (transient)
#
# Exit codes:
#   0 - CI is green (possibly after N fixes)
#   1 - CI is red after all retries / dry-run / unrecoverable
#   2 - Script error

param(
    [switch]$Fix,
    [switch]$AutoRepair,
    [switch]$Quiet,
    [int]$MaxRetries = 5,
    [int]$PollIntervalSec = 60
)

$ErrorActionPreference = "Stop"

$Repo           = "engramia/engramia"
$Branch         = "main"
$Workflow       = "CI"
$MaxAgeHours    = 24
$LogFile        = "$env:USERPROFILE\.engramia-ci-check.log"
$MaxLogLines    = 150   # lines of CI log to pass to Claude Code
$RepoRoot       = $PSScriptRoot | Split-Path -Parent

# -- Helpers ------------------------------------------------------------------

function Write-Log {
    param([string]$Message, [switch]$AlwaysShow)
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Add-Content -Path $LogFile -Value $line
    if (-not $Quiet -or $AlwaysShow) {
        Write-Host $line
    }
}

function Exit-Error {
    param([string]$Message)
    Write-Log "ERROR: $Message" -AlwaysShow
    exit 2
}

# -- Preflight ----------------------------------------------------------------

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Exit-Error "gh CLI not found. Install: winget install GitHub.cli"
}

$null = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Exit-Error "gh CLI not authenticated. Run: gh auth login"
}

$claudeCmd = "claude"
if ($AutoRepair) {
    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
        # Claude Code desktop app installs to a versioned path not in PATH - find it
        $found = Get-ChildItem "$env:LOCALAPPDATA\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code\*\claude.exe" `
            -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($found) {
            $claudeCmd = $found.FullName
            Write-Log "Found claude at: $claudeCmd"
        } else {
            Exit-Error "claude CLI not found. Install Claude Code or add it to PATH."
        }
    }
}

# -- Fetch latest CI runs -----------------------------------------------------

Write-Log "Checking CI for $Repo (branch: $Branch, workflow: $Workflow)"

$ghArgs = @(
    "run", "list",
    "--repo",     $Repo,
    "--branch",   $Branch,
    "--workflow", $Workflow,
    "--limit",    "5",
    "--json",     "databaseId,status,conclusion,createdAt,displayTitle,headSha"
)

$runsJson = gh @ghArgs 2>&1
if ($LASTEXITCODE -ne 0) {
    Exit-Error "Failed to fetch CI runs: $runsJson"
}

$runs = $runsJson | ConvertFrom-Json

if (-not $runs -or $runs.Count -eq 0) {
    Write-Log "No CI runs found for workflow '$Workflow' on branch '$Branch'."
    exit 0
}

# -- Inspect the latest run ---------------------------------------------------

$latest     = $runs[0]
$runId      = $latest.databaseId
$status     = $latest.status
$conclusion = $latest.conclusion
$title      = $latest.displayTitle
$sha        = $latest.headSha.Substring(0, 8)
$createdAt  = [datetime]$latest.createdAt
$ageHours   = [math]::Floor(([datetime]::UtcNow - $createdAt.ToUniversalTime()).TotalHours)

Write-Log "Run #$runId | status=$status | conclusion=$conclusion | sha=$sha | age=${ageHours}h | $title"

# -- Decision logic -----------------------------------------------------------

if ($status -eq "in_progress" -or $status -eq "queued") {
    Write-Log "CI is currently running (status=$status). Nothing to do."
    exit 0
}

if ($ageHours -gt $MaxAgeHours) {
    Write-Log "Latest run is ${ageHours}h old (>${MaxAgeHours}h threshold). Skipping." -AlwaysShow
    exit 0
}

if ($conclusion -eq "success") {
    Write-Log "CI is GREEN"
    exit 0
}

if ($conclusion -eq "cancelled") {
    Write-Log "CI run #$runId was CANCELLED. Skipping." -AlwaysShow
    exit 1
}

# -- CI is red ----------------------------------------------------------------

Write-Log "CI is RED - run #$runId concluded: $conclusion" -AlwaysShow

# Collect failed job names for the log
$jobsJson = gh run view $runId --repo $Repo --json jobs 2>&1
$failedJobNames = @()
if ($LASTEXITCODE -eq 0) {
    $failedJobNames = ($jobsJson | ConvertFrom-Json).jobs |
        Where-Object { $_.conclusion -eq "failure" } |
        ForEach-Object { $_.name }
    if ($failedJobNames) {
        $jobList = ($failedJobNames | ForEach-Object { "  - $_" }) -join "`n"
        Write-Log ("Failed jobs:`n" + $jobList) -AlwaysShow
    }
}

if (-not $AutoRepair -and -not $Fix) {
    Write-Log "Dry-run mode - pass -AutoRepair to fix, or -Fix for blind re-run." -AlwaysShow
    exit 1
}

# -- Fetch failure logs -------------------------------------------------------

Write-Log "Fetching failure logs..." -AlwaysShow

$failedLogs = gh run view $runId --repo $Repo --log-failed 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Log "Could not fetch failure logs: $failedLogs" -AlwaysShow
    $failedLogs = "(logs unavailable)"
}

$logLines     = ($failedLogs -split "`n") | Select-Object -Last $MaxLogLines
$truncatedLog = $logLines -join "`n"

$failedJobsSummary = if ($failedJobNames) {
    "Failed jobs: " + ($failedJobNames -join ", ")
} else {
    "Failed jobs: unknown"
}

# -- Helper: Wait for latest CI run to complete and return conclusion ---------

function Wait-CIRun {
    param([string]$AfterSha)
    Write-Log "Waiting for CI run on commit $AfterSha to appear..." -AlwaysShow

    # Wait for a new run to appear (up to 5 min)
    $newRunId = $null
    for ($w = 0; $w -lt 20; $w++) {
        Start-Sleep -Seconds 15
        $pollJson = gh run list --repo $Repo --branch $Branch --workflow $Workflow --limit 1 `
            --json "databaseId,status,conclusion,headSha" 2>&1
        if ($LASTEXITCODE -ne 0) { continue }
        $pollRun = ($pollJson | ConvertFrom-Json)[0]
        if ($pollRun.headSha -and $pollRun.headSha.StartsWith($AfterSha.Substring(0, 7))) {
            $newRunId = $pollRun.databaseId
            Write-Log "Found CI run #$newRunId for $AfterSha"
            break
        }
    }

    if (-not $newRunId) {
        Write-Log "No CI run found for commit $AfterSha after 5 min." -AlwaysShow
        return "unknown"
    }

    # Poll until the run completes (up to 30 min)
    Write-Log "Waiting for run #$newRunId to complete..." -AlwaysShow
    for ($p = 0; $p -lt ([math]::Ceiling(1800 / $PollIntervalSec)); $p++) {
        Start-Sleep -Seconds $PollIntervalSec
        $statusJson = gh run view $newRunId --repo $Repo --json "status,conclusion" 2>&1
        if ($LASTEXITCODE -ne 0) { continue }
        $runInfo = $statusJson | ConvertFrom-Json
        if ($runInfo.status -eq "completed") {
            Write-Log "Run #$newRunId completed: $($runInfo.conclusion)" -AlwaysShow
            return $runInfo.conclusion
        }
        Write-Log "Run #$newRunId still $($runInfo.status)... (poll $($p+1))"
    }

    Write-Log "Run #$newRunId did not complete within 30 min." -AlwaysShow
    return "timeout"
}

# -- AutoRepair: Claude Code analyzes logs, fixes code, pushes ----------------

if ($AutoRepair) {
    $attempt = 0

    while ($attempt -lt $MaxRetries) {
        $attempt++
        Write-Log "=== AutoRepair attempt $attempt / $MaxRetries ===" -AlwaysShow

        # Re-fetch failure info on retries (first iteration uses data from above)
        if ($attempt -gt 1) {
            $runsJson = gh run list --repo $Repo --branch $Branch --workflow $Workflow --limit 1 `
                --json "databaseId,status,conclusion,createdAt,displayTitle,headSha" 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Log "Failed to re-fetch CI runs: $runsJson" -AlwaysShow
                exit 2
            }
            $latest     = ($runsJson | ConvertFrom-Json)[0]
            $runId      = $latest.databaseId
            $status     = $latest.status
            $conclusion = $latest.conclusion
            $sha        = $latest.headSha.Substring(0, 8)

            Write-Log "Run #$runId | status=$status | conclusion=$conclusion | sha=$sha"

            if ($conclusion -eq "success") {
                Write-Log "CI is GREEN after $($attempt - 1) fix(es)!" -AlwaysShow
                exit 0
            }

            # Re-fetch failed job names
            $jobsJson = gh run view $runId --repo $Repo --json jobs 2>&1
            $failedJobNames = @()
            if ($LASTEXITCODE -eq 0) {
                $failedJobNames = ($jobsJson | ConvertFrom-Json).jobs |
                    Where-Object { $_.conclusion -eq "failure" } |
                    ForEach-Object { $_.name }
            }

            # Re-fetch failure logs
            $failedLogs = gh run view $runId --repo $Repo --log-failed 2>&1
            if ($LASTEXITCODE -ne 0) { $failedLogs = "(logs unavailable)" }
            $logLines     = ($failedLogs -split "`n") | Select-Object -Last $MaxLogLines
            $truncatedLog = $logLines -join "`n"

            $failedJobsSummary = if ($failedJobNames) {
                "Failed jobs: " + ($failedJobNames -join ", ")
            } else {
                "Failed jobs: unknown"
            }
        }

        Write-Log "Calling Claude Code to analyze and fix CI failure..." -AlwaysShow

        # Save logs to a temp file so Claude Code can read them without shell escaping issues
        $logTempFile = Join-Path $env:TEMP "engramia-ci-failure.log"
        $truncatedLog | Out-File -FilePath $logTempFile -Encoding utf8

        $retryContext = ""
        if ($attempt -gt 1) {
            $retryContext = @"

IMPORTANT: This is retry attempt $attempt of $MaxRetries.
The previous fix attempt did NOT resolve the CI failure.
Look carefully at the NEW error — it may be different from before.
Do NOT repeat the same fix. Analyze the fresh logs below.

"@
        }

        $claudePrompt = @"
The GitHub Actions CI for the engramia/engramia repository is RED on main.
$retryContext
Run ID: $runId
Run URL: https://github.com/$Repo/actions/runs/$runId
$failedJobsSummary

The full failure logs are saved at: $logTempFile
Read that file first, then:

1. Analyze the logs to identify the root cause of the failure.
2. If this is a CODE problem (lint, test, type error, missing file, etc.):
   a. Fix the issue by editing the relevant source files.
   b. Verify the fix looks correct (read affected files, check for related issues).
   c. Run the specific failing check locally if possible (e.g. ruff check, pytest -x on the failing test).
   d. Commit the fix with a message like: fix(ci): <what was broken and why>
   e. Push to main so a new CI run triggers automatically.
3. If this is a TRANSIENT infrastructure issue (network timeout, GitHub outage, flaky runner, etc.):
   a. Do NOT change any code.
   b. Re-run the failed jobs with: gh run rerun $runId --repo $Repo --failed
   c. Exit cleanly.

Important:
- Work in the repository at: $RepoRoot
- Only fix what the logs indicate is broken - do not refactor unrelated code.
- Do not skip or weaken any CI checks (no lowering coverage thresholds, no ignoring lint rules).
"@

        Push-Location $RepoRoot
        try {
            & $claudeCmd --print $claudePrompt
            $claudeExit = $LASTEXITCODE
        } finally {
            Pop-Location
        }

        # Clean up temp file
        Remove-Item -Path $logTempFile -ErrorAction SilentlyContinue

        if ($claudeExit -ne 0) {
            Write-Log "Claude Code exited with code $claudeExit on attempt $attempt." -AlwaysShow
            if ($attempt -ge $MaxRetries) {
                Write-Log "Max retries ($MaxRetries) exhausted. Manual intervention needed." -AlwaysShow
                exit 1
            }
            continue
        }

        # Get the HEAD sha after Claude's push
        Push-Location $RepoRoot
        $headSha = (git rev-parse HEAD 2>&1).Substring(0, 8)
        Pop-Location

        Write-Log "Claude Code pushed fix (sha=$headSha). Waiting for CI..." -AlwaysShow

        $result = Wait-CIRun -AfterSha $headSha

        if ($result -eq "success") {
            Write-Log "CI is GREEN after $attempt fix(es)!" -AlwaysShow
            exit 0
        }

        if ($result -eq "timeout" -or $result -eq "unknown") {
            Write-Log "Could not determine CI result ($result). Manual check needed." -AlwaysShow
            exit 1
        }

        Write-Log "CI still RED after attempt $attempt (conclusion: $result)." -AlwaysShow
    }

    Write-Log "Max retries ($MaxRetries) exhausted. CI is still RED. Manual intervention needed." -AlwaysShow
    exit 1
}

# -- Fix (blind re-run without code fix, only for transient issues) -----------

if ($Fix) {
    Write-Log "Triggering blind re-run of failed jobs for run #$runId..." -AlwaysShow
    Write-Log "Note: this only helps for transient failures. Use -AutoRepair for code fixes." -AlwaysShow

    $rerunOutput = gh run rerun $runId --repo $Repo --failed 2>&1

    if ($LASTEXITCODE -eq 0) {
        Write-Log "Re-run triggered. Monitor: https://github.com/$Repo/actions/runs/$runId" -AlwaysShow
        exit 0
    } else {
        Write-Log "Failed to trigger re-run: $rerunOutput" -AlwaysShow
        exit 1
    }
}
