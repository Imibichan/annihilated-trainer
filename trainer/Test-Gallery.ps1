$ErrorActionPreference = 'Stop'
$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('AnnihilatedGalleryTest-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($fixtureRoot) | Out-Null
try {
    $fixture = Join-Path $PSScriptRoot 'tests/GallerySetupFixture.cs'
    Add-Type -Path $fixture -OutputAssembly (Join-Path $fixtureRoot 'GallerySetup.exe') -OutputType ConsoleApplication
    $sources = @('GalleryRunner.cs', 'GalleryLocation.cs', 'GalleryPanel.cs', 'GalleryTests.cs') | ForEach-Object { Join-Path $PSScriptRoot $_ }
    Add-Type -Path $sources -ReferencedAssemblies @('System.dll','System.Core.dll','System.Drawing.dll','System.Windows.Forms.dll')
    [GalleryTests]::Run($fixtureRoot)
} finally {
    $tempParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $resolved = (Get-Item -LiteralPath $fixtureRoot).FullName
    if ([IO.Path]::GetDirectoryName($resolved) -eq $tempParent -and
        [IO.Path]::GetFileName($resolved) -match '^AnnihilatedGalleryTest-[0-9a-f]{32}$') {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
