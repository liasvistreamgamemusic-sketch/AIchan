# AIちゃん ランチャー(PowerShell)。右クリック→PowerShellで実行、または run.bat を使用。
Set-Location -Path $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv が見つかりません。インストールします..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "依存を同期しています(初回は時間がかかります)..."
uv sync --extra full
if ($LASTEXITCODE -ne 0) { Write-Host "同期に失敗"; Read-Host "Enterで終了"; exit 1 }

Write-Host "すみれを起動します..."
uv run python -m aichan.main
