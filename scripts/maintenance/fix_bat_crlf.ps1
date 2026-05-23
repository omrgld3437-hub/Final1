# Windows: .bat dosyalarini CRLF satir sonuna cevirir (Mac'ten kopyalaninca bozulabiliyor).
# Kullanim: PowerShell'de proje kokunde: .\scripts\fix_bat_crlf.ps1
# Veya: powershell -ExecutionPolicy Bypass -File scripts\fix_bat_crlf.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$count = 0
Get-ChildItem -Path $root -Filter "*.bat" -Recurse -File | ForEach-Object {
    $content = [System.IO.File]::ReadAllText($_.FullName)
    $crlf = $content -replace "`r`n", "`n" -replace "`n", "`r`n"
    [System.IO.File]::WriteAllText($_.FullName, $crlf)
    Write-Host "CRLF: $($_.FullName)"
    $count++
}
Write-Host ""
Write-Host "Tamamlandi: $count .bat dosyasi CRLF yapildi."
