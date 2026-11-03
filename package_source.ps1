$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$version = (Get-Content (Join-Path $root 'VERSION') -Raw).Trim()
$releaseDir = Join-Path $root 'release'
$zipPath = Join-Path $releaseDir ("PeopleLens-{0}-source.zip" -f $version)
$stage = Join-Path $env:TEMP ("pl_source_" + [guid]::NewGuid().ToString('N'))

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$files = @(
    '.gitignore',
    'app_paths.py',
    'BUILD_WINDOWS11.md',
    'build_windows11.bat',
    'main.py',
    'package_source.bat',
    'package_source.ps1',
    'PeopleLens.spec',
    'README.md',
    'requirements-build.txt',
    'requirements.txt',
    'run_windows.bat',
    'VERSION',
    'version_info.txt'
)

foreach ($name in $files) {
    $source = Join-Path $root $name
    if (-not (Test-Path $source)) {
        throw "Missing required source file: $name"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $stage $name) -Force
}

foreach ($dirName in @('assets', 'core', 'database', 'tests', 'ui')) {
    $sourceDir = Join-Path $root $dirName
    if (-not (Test-Path $sourceDir)) {
        throw "Missing required source directory: $dirName"
    }
    $dirFiles = Get-ChildItem -LiteralPath $sourceDir -Recurse -File | Where-Object {
        $_.FullName -notmatch '\\(__pycache__|\.pytest_cache)\\' -and
        $_.Extension -notin @('.pyc', '.pyo')
    }
    foreach ($file in $dirFiles) {
        $relative = $file.FullName.Substring($root.Length).TrimStart('\')
        $destination = Join-Path $stage $relative
        $parent = Split-Path -Parent $destination
        if (-not (Test-Path $parent)) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
    }
}

if (Test-Path $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stage,
    $zipPath,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false
)

$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
$entries = $zip.Entries
$bad = $entries | Where-Object {
    $_.FullName -match '(?i)(^|/)(\.venv|\.build-venv|build|dist|release|__pycache__)(/|$)' -or
    $_.FullName -match '(?i)(\.pyc$|\.db$|\.db-wal$|\.db-shm$|\.log$|settings\.json$)'
}
$count = $entries.Count
$zip.Dispose()
Remove-Item -LiteralPath $stage -Recurse -Force

if ($bad) {
    throw "Source archive contains forbidden entries: $($bad.FullName -join ', ')"
}

Write-Output ("Source archive: {0}" -f $zipPath)
Write-Output ("Entries: {0}" -f $count)
