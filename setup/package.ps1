param(
    [Parameter(Mandatory=$true)][string]$RuntimeZip,
    [Parameter(Mandatory=$true)][string]$PythonPackages,
    [Parameter(Mandatory=$true)][string]$AvatarPath,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot
$trainerRoot = if (Test-Path -LiteralPath (Join-Path $project 'trainer/Build.ps1')) { Join-Path $project 'trainer' } else { $project }
$output = [IO.Path]::GetFullPath($OutputDirectory)
$runtime = Join-Path $output 'gallery/runtime'
$code = Join-Path $output 'gallery/code'
$lib = Join-Path $runtime 'Lib'
if ((Get-FileHash -LiteralPath $RuntimeZip).Hash -ne '1EC066FB61BA5E8C73E29E048CD07C26850F74585E3A116005135B31B8004890') {
    throw 'Expected the official CPython 3.13.11 x64 embeddable archive.'
}
foreach ($dir in @($runtime, $lib, $code)) {
    [IO.Directory]::CreateDirectory($dir) | Out-Null
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (-not (Test-Path -LiteralPath (Join-Path $runtime 'python.exe'))) {
    [IO.Compression.ZipFile]::ExtractToDirectory((Resolve-Path -LiteralPath $RuntimeZip).Path, $runtime)
}
foreach ($pkg in Get-ChildItem -LiteralPath $PythonPackages) {
    if ($pkg.Name -notin @('bin','Scripts','__pycache__')) {
        Copy-Item -LiteralPath $pkg.FullName -Destination $lib -Recurse -Force
    }
}
# Confine imports to the redistributable runtime, dependencies and gallery sources.
[IO.File]::WriteAllText((Join-Path $runtime 'python313._pth'), "python313.zip`r`n.`r`nLib`r`n../code`r`n", [Text.Encoding]::ASCII)
foreach ($name in @('GallerySetup','gallery_builder')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot ($name+'.py')) -Destination $code -Force
}
$titleModules = @('catalog_ui','build_title','catalog_crc','scene_render','ui_art','title_bindings')
foreach ($name in $titleModules) {
    Copy-Item -LiteralPath (Join-Path $project ('title/'+$name+'.py')) -Destination $code -Force
}
$catalogModules = @('addressables','backgrounds','backgrounds_metrics','backgrounds_render',
    'backgrounds_render_assets','build_catalog','compatible_content','inspect_game','links','story_order')
foreach ($name in $catalogModules) {
    Copy-Item -LiteralPath (Join-Path $project ('catalog/'+$name+'.py')) -Destination $code -Force
}
Copy-Item -LiteralPath (Join-Path $project 'catalog/backgrounds_assets.json') -Destination $code -Force
Copy-Item -LiteralPath (Join-Path $project 'catalog/gallery.json') -Destination $code -Force
$csc = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
& $csc /nologo /optimize+ /platform:x64 /target:exe ('/out:'+(Join-Path $output 'GallerySetup.exe')) (Join-Path $PSScriptRoot 'GalleryLauncher.cs')
if ($LASTEXITCODE -ne 0) { throw 'GallerySetup launcher compilation failed.' }
$exeName = '勇者小队全灭了修改器-v1.4.exe'
Copy-Item -LiteralPath (Join-Path $trainerRoot 'Trainer.exe') -Destination (Join-Path $output $exeName) -Force
$shortcut = "@echo off`r`nchcp 65001 >nul`r`nstart `"`" `"%~dp0$exeName`" --gallery`r`n"
[IO.File]::WriteAllText((Join-Path $output 'CG鉴赏设置.cmd'), $shortcut, [Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath $AvatarPath -Destination (Join-Path $output '魔法师头像.png') -Force
foreach ($doc in '更新说明.txt','使用说明.txt','验证记录.txt') {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $doc) -Destination $output -Force
}
foreach ($group in 'trainer','setup','title','catalog') {
    $sourceDir = Join-Path $output ('源码/'+$group)
    [IO.Directory]::CreateDirectory($sourceDir) | Out-Null
    $sourceFiles = switch ($group) {
        'trainer' { Get-ChildItem -LiteralPath $trainerRoot -File | Where-Object {$_.Extension -in '.cs','.ico','.manifest','.ps1'} }
        'setup' { Get-ChildItem -LiteralPath $PSScriptRoot -File | Where-Object {$_.Extension -in '.py','.ps1','.cs','.txt'} }
        'title' { foreach ($name in ($titleModules + 'verify_title')) { Get-Item -LiteralPath (Join-Path $project ('title/'+$name+'.py')) }; Get-ChildItem -LiteralPath (Join-Path $project 'title') -File -Filter 'test_*.py' }
        'catalog' { Get-ChildItem -LiteralPath (Join-Path $project $group) -File | Where-Object {$_.Extension -in '.py','.json'} }
    }
    foreach ($srcFile in $sourceFiles) { Copy-Item -LiteralPath $srcFile.FullName -Destination $sourceDir -Force }
    if ($group -eq 'trainer') {
        $fixtureDir = Join-Path $sourceDir 'tests'
        [IO.Directory]::CreateDirectory($fixtureDir) | Out-Null
        Copy-Item -LiteralPath (Join-Path $trainerRoot 'tests/GallerySetupFixture.cs') -Destination $fixtureDir -Force
    }
}
Write-Output $output
