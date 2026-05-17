$ErrorActionPreference = "Stop"

param(
  [string]$BackupFile,
  [string]$DbPath = "/var/lib/docker/volumes/app_data/_data/labelhub.db"
)

if ([string]::IsNullOrWhiteSpace($BackupFile)) {
  throw "Provide -BackupFile path to a .sqlite3.gz file."
}
if (!(Test-Path $BackupFile)) {
  throw "Backup file not found: $BackupFile"
}

$dbDir = Split-Path -Path $DbPath -Parent
if (!(Test-Path $dbDir)) {
  New-Item -ItemType Directory -Path $dbDir | Out-Null
}

$tmpFile = "$DbPath.tmp_restore"
$in = [System.IO.File]::OpenRead($BackupFile)
$out = [System.IO.File]::Create($tmpFile)
try {
  $gzip = New-Object System.IO.Compression.GzipStream($in, [System.IO.Compression.CompressionMode]::Decompress)
  try {
    $buffer = New-Object byte[] 8192
    while (($read = $gzip.Read($buffer, 0, $buffer.Length)) -gt 0) {
      $out.Write($buffer, 0, $read)
    }
  } finally {
    $gzip.Dispose()
  }
} finally {
  $in.Dispose()
  $out.Dispose()
}

Move-Item -Path $tmpFile -Destination $DbPath -Force
Write-Host "Restore completed to $DbPath"
