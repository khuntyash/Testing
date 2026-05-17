$ErrorActionPreference = "Stop"

param(
  [string]$DbPath = "/var/lib/docker/volumes/app_data/_data/labelhub.db",
  [string]$OutDir = "./backups"
)

if (!(Test-Path $DbPath)) {
  throw "Database file not found: $DbPath"
}

if (!(Test-Path $OutDir)) {
  New-Item -ItemType Directory -Path $OutDir | Out-Null
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outFile = Join-Path $OutDir "labelhub_$stamp.sqlite3.gz"

$bytes = [System.IO.File]::ReadAllBytes($DbPath)
$fileStream = [System.IO.File]::Create($outFile)
try {
  $gzip = New-Object System.IO.Compression.GzipStream($fileStream, [System.IO.Compression.CompressionLevel]::Optimal)
  try {
    $gzip.Write($bytes, 0, $bytes.Length)
  } finally {
    $gzip.Dispose()
  }
} finally {
  $fileStream.Dispose()
}

$hash = Get-FileHash -Path $outFile -Algorithm SHA256
$hash.Path + " " + $hash.Hash | Set-Content -Path "$outFile.sha256"

Write-Host "Backup created: $outFile"
Write-Host "Checksum file: $outFile.sha256"
