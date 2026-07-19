$hostsPath = "C:\Windows\System32\drivers\etc\hosts"
$content = Get-Content $hostsPath -Raw

foreach ($line in @"
127.0.0.1 github.com
127.0.0.1 api.github.com
127.0.0.1 gist.github.com
127.0.0.1 raw.github.com
127.0.0.1 pages.github.com
127.0.0.1 education.github.com
"@ -split "`n" | Where-Object { $_.Trim() -ne "" }) {
    $content = $content.Replace($line, "# $line")
}

Set-Content $hostsPath -Value $content -NoNewline
Write-Host "Done. Checking..."
Select-String -Path $hostsPath -Pattern "^127\.0\.0\.1 github" | ForEach-Object { Write-Host $_.Line }
