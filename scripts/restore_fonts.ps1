$ErrorActionPreference = "Stop"

# Restore the original self-hosted variable fonts referenced by index.html.
$repoRoot = Split-Path -Parent $PSScriptRoot
$fontDir = Join-Path $repoRoot "musicmaster\web\static\fonts"
New-Item -ItemType Directory -Force -Path $fontDir | Out-Null

$base = "https://cdn.jsdelivr.net/fontsource/fonts"
$version = "5.3.0"
$fonts = @(
    @{ Name = "fraunces-normal.woff2"; Url = ($base + "/fraunces:vf@" + $version + "/latin-wght-normal.woff2") },
    @{ Name = "fraunces-italic.woff2"; Url = ($base + "/fraunces:vf@" + $version + "/latin-wght-italic.woff2") },
    @{ Name = "inter-normal.woff2"; Url = ($base + "/inter:vf@" + $version + "/latin-wght-normal.woff2") },
    @{ Name = "jetbrains-mono.woff2"; Url = ($base + "/jetbrains-mono:vf@" + $version + "/latin-wght-normal.woff2") }
)

foreach ($font in $fonts) {
    $destination = Join-Path $fontDir $font.Name
    Write-Host ("Downloading " + $font.Name + " ...")
    Invoke-WebRequest -Uri $font.Url -OutFile $destination -UseBasicParsing
    $bytes = [System.IO.File]::ReadAllBytes($destination)
    $signature = [System.Text.Encoding]::ASCII.GetString($bytes, 0, [Math]::Min(4, $bytes.Length))
    if ($bytes.Length -lt 10000 -or $signature -ne "wOF2") {
        Remove-Item $destination -Force -ErrorAction SilentlyContinue
        throw ("Font validation failed: " + $font.Name + ". Check the network and retry.")
    }
    Write-Host ("OK: {0} ({1:N0} bytes)" -f $font.Name, $bytes.Length)
}

Write-Host ""
Write-Host "All four font files downloaded and passed WOFF2 signature checks."
Write-Host ("Font directory: " + $fontDir)