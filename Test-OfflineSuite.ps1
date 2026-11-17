param([Parameter(Mandatory=$true)][string]$Suite)
$ErrorActionPreference='Stop'
Push-Location $PSScriptRoot
$previousDirectory=[Environment]::CurrentDirectory
[Environment]::CurrentDirectory=$PSScriptRoot
try {
 $files=@('Remote.cs','Compatibility.cs','RuntimeRules.cs','Bridge.cs','Growth.cs','Trainer.cs','SaveTools.cs','SavePanel.cs','HiddenRouteGuide.cs',($Suite+'.cs'))
 $types=Add-Type -Path @($files|ForEach-Object {Join-Path $PSScriptRoot $_}) -ReferencedAssemblies @('System.dll','System.Core.dll','System.Windows.Forms.dll','System.Drawing.dll','System.Web.Extensions.dll') -PassThru
 $testType=$types | Where-Object {$_.Name -eq $Suite} | Select-Object -First 1
 if($null -eq $testType){throw 'Test type not found'}
 $main=$testType.GetMethod('Main',[Reflection.BindingFlags]'Static,Public,NonPublic')
 $arguments=$null
 if($main.GetParameters().Length -eq 1){$arguments=New-Object object[] 1;$arguments[0]=[string[]]@()}
 $result=$main.Invoke($null,$arguments)
 if($null -ne $result -and $result -ne 0){exit 1}
} finally {[Environment]::CurrentDirectory=$previousDirectory;Pop-Location}
