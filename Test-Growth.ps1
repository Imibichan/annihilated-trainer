$ErrorActionPreference='Stop'
$files=@('Remote.cs','Bridge.cs','GrowthTests.cs')
if(Test-Path -LiteralPath (Join-Path $PSScriptRoot 'Growth.cs')){$files+='Growth.cs'}
Add-Type -Path @($files|ForEach-Object {Join-Path $PSScriptRoot $_}) -ReferencedAssemblies @('System.dll','System.Core.dll')
exit ([GrowthTests]::Main())
