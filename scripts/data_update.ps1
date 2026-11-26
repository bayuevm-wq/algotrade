# Jalankan `algotrade data update` dan simpan log ke data\logs. Dipakai oleh Task Scheduler.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("data_update_{0:yyyy-MM-dd}.log" -f (Get-Date))

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
if (-not (Test-Path -LiteralPath $uv)) {
    "uv tidak ditemukan." | Out-File -FilePath $log -Append -Encoding utf8
    exit 1
}

$env:PYTHONUTF8 = "1"
"=== mulai {0:yyyy-MM-dd HH:mm:ss}" -f (Get-Date) | Out-File -FilePath $log -Append -Encoding utf8
& $uv run algotrade data update 2>&1 |
    ForEach-Object { "$_" } |
    Out-File -FilePath $log -Append -Encoding utf8
$code = $LASTEXITCODE
"=== selesai {0:yyyy-MM-dd HH:mm:ss}, kode {1}" -f (Get-Date), $code |
    Out-File -FilePath $log -Append -Encoding utf8

# Simpan log 30 hari saja
Get-ChildItem -LiteralPath $logDir -Filter "data_update_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force
exit $code
