$ErrorActionPreference='Stop'
$testSources=@('Remote.cs','Compatibility.cs','RuntimeRules.cs','Bridge.cs','Growth.cs','Tests.cs')|ForEach-Object {Join-Path $PSScriptRoot $_}
Add-Type -Path $testSources -ReferencedAssemblies @('System.dll','System.Core.dll')
$testResult=[Tests]::Main()
exit $testResult
