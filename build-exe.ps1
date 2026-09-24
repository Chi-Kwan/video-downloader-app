[CmdletBinding()]
param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$PythonPath = if ($PythonPath) { $PythonPath } else { Join-Path $Root ".venv\Scripts\python.exe" }
$Entry = Join-Path $Root "app.py"
$Dist = Join-Path $Root "dist"
$Build = Join-Path $Root ".exe-build"

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python build environment not found: $PythonPath"
}
if (-not (Test-Path -LiteralPath $Entry -PathType Leaf)) {
    throw "GUI entry point not found: $Entry"
}

New-Item -ItemType Directory -Force -Path $Dist, $Build | Out-Null
$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "VideoDownloader",
    "--distpath", $Dist,
    "--workpath", $Build,
    "--specpath", $Build,
    "--collect-all", "yt_dlp",
    "--collect-all", "webview",
    "--collect-all", "clr_loader",
    $Entry
)
& $PythonPath @PyInstallerArgs

if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
$Exe = Join-Path $Dist "VideoDownloader.exe"
if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "Build completed but EXE was not found." }
Get-Item -LiteralPath $Exe | Select-Object FullName, Length, LastWriteTime
