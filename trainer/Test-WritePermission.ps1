$ErrorActionPreference='Stop'
$files=@('Remote.cs','Compatibility.cs','RuntimeRules.cs','Bridge.cs','Growth.cs','WritePermissionTests.cs')
Add-Type -Path @($files|ForEach-Object {Join-Path $PSScriptRoot $_}) -ReferencedAssemblies @('System.dll','System.Core.dll')
exit ([WritePermissionTests]::Main())
