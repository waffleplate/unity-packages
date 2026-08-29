# PreToolUse hook: block edits to .cs files while Unity is in Play Mode.
#
# Why: with Preferences > Script Changes While Playing = "Recompile After Finished Playing",
# touching a .cs during Play holds the recompile until play ends, and the editor API
# ExitPlaymode is then rejected as "compiling" - the editor can only be recovered by pressing
# Stop by hand. This hook stops that accident before it happens.
#
# Source of truth is the marker written by the playmode-bridge package:
#   <project>/Library/PlayModeBridge/playmode.json   (heartbeat every 2s, deleted on exit)
# The project root comes from the hook payload's `cwd`, so one copy of this script serves
# every project. Where no marker exists (any non-Unity project) this hook always passes.
#
# Covered tool shapes:
#   Edit / Write / MultiEdit -> tool_input.file_path  (exact: any .cs target)
#   Bash                     -> tool_input.command    (heuristic: .cs mentioned AND a write verb)
# The Bash arm needs both signals so read-only commands that merely name .cs files
# (grep / ls / git diff over *.cs) keep working. Naming an interpreter counts as a write
# signal on its own, because a script handed to python/node/perl/ruby/powershell writes
# without any shell write verb (a heredoc fed to python, `python -c`, `node -e`). That also
# blocks merely reading a .cs through one of them, which is the safe side to err on: reading
# is what Read and Grep are for. This stops accidents, not a determined bypass - an
# obfuscated writer still slips through.
#
# Freshness: a crashed editor leaves the marker behind, so a marker older than 10s is treated
# as dead. That threshold is the one recommended by the playmode-bridge README (measured
# heartbeat max was ~2.1s, so 10s is about 5x the observed upper bound).
#
# Fail-open on unparsable input (never obstruct normal edits); fail-safe (block) when the
# marker exists but its age cannot be read. Block via exit 2 + stderr.
#
# ASCII-only on purpose: Windows PowerShell 5.1 reads .ps1 as the system ANSI code page
# (e.g. cp932 on Japanese Windows), so any non-ASCII byte breaks parsing.

$ErrorActionPreference = 'Stop'

try {
    $raw = [Console]::In.ReadToEnd()
    $payload = $raw | ConvertFrom-Json
} catch {
    exit 0
}

$filePath = ''
$command = ''
$projectDir = ''
try { $filePath = [string]$payload.tool_input.file_path } catch { $filePath = '' }
try { $command = [string]$payload.tool_input.command } catch { $command = '' }
try { $projectDir = [string]$payload.cwd } catch { $projectDir = '' }

if (-not $projectDir) { $projectDir = [string]$env:CLAUDE_PROJECT_DIR }
if (-not $projectDir) { $projectDir = (Get-Location).Path }

# '.cs' must not match a prefix of .csproj / .csv / .css
$csToken = '\.cs(?![a-zA-Z0-9])'

$reason = ''
if ($filePath -match $csToken) {
    $reason = 'a .cs file edit'
} elseif ($command -match $csToken) {
    # Redirection covers `> x.cs`, `>> x.cs` and `cat > x.cs` fed by a heredoc. A heredoc
    # on its own is `<<`, so it matches here only when paired with a redirect to the .cs.
    $redirect = '>>?\s*[^|;&<>]*' + $csToken
    $verbs = '\b(cp|mv|rm|tee|touch|rsync|install|patch|truncate|unlink)\b'
    $sedInPlace = '\bsed\b[^|;&]*\s-i'
    $interpreters = '\b(python3?|py|node|perl|ruby|pwsh|powershell)\b'
    if (($command -match $redirect) -or ($command -match $verbs) -or
        ($command -match $sedInPlace) -or ($command -match $interpreters)) {
        $reason = 'a shell command that can write a .cs file'
    }
}

if (-not $reason) { exit 0 }

$marker = Join-Path $projectDir 'Library/PlayModeBridge/playmode.json'
if (-not (Test-Path -LiteralPath $marker)) { exit 0 }

# Unreadable age -> assume alive (the marker exists only while playing).
$ageSeconds = 0
try {
    $ageSeconds = ((Get-Date) - (Get-Item -LiteralPath $marker).LastWriteTime).TotalSeconds
} catch {
    $ageSeconds = 0
}

if ($ageSeconds -gt 10) { exit 0 }  # stale marker left behind by a crashed editor

[Console]::Error.WriteLine("[PlayModeGuard] Blocked $reason while Unity is in Play Mode. With deferred recompile the rebuild is held until play ends and even ExitPlaymode gets blocked, leaving the editor recoverable only by pressing Stop by hand. Stop Play Mode first, then retry.")
exit 2
