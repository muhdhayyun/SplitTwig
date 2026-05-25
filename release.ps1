# release.ps1 - bump version, commit, tag, push.
# Usage:  .\release.ps1 patch "fix balance overflow"
#         .\release.ps1 minor "add /paid command"
#         .\release.ps1 major "rewrite splits"

param(
    [Parameter(Mandatory=$true)][ValidateSet("major", "minor", "patch")][string]$Bump,
    [Parameter(Mandatory=$true)][string]$Message
)

# Find the latest v* tag, or start fresh if none exist
$tags = & git tag --list "v*" --sort=-v:refname
$lastTag = if ($tags) { @($tags)[0] } else { $null }

if (-not $lastTag) {
    $major = 0; $minor = 0; $patch = 0
} else {
    $parts = ($lastTag -replace "^v", "").Split(".")
    $major = [int]$parts[0]; $minor = [int]$parts[1]; $patch = [int]$parts[2]
}

switch ($Bump) {
    "major" { $major++; $minor = 0; $patch = 0 }
    "minor" { $minor++; $patch = 0 }
    "patch" { $patch++ }
}

$tag = "v$major.$minor.$patch"
Write-Host "Releasing $tag - $Message" -ForegroundColor Cyan

& git add .
if ($LASTEXITCODE -ne 0) { Write-Host "git add failed" -ForegroundColor Red; exit 1 }

& git commit -m "${tag}: $Message"
if ($LASTEXITCODE -ne 0) { Write-Host "git commit failed (nothing to commit?)" -ForegroundColor Red; exit 1 }

& git tag -a $tag -m $Message
if ($LASTEXITCODE -ne 0) { Write-Host "git tag failed" -ForegroundColor Red; exit 1 }

& git push --follow-tags
if ($LASTEXITCODE -ne 0) { Write-Host "git push failed" -ForegroundColor Red; exit 1 }

Write-Host "Pushed $tag" -ForegroundColor Green
