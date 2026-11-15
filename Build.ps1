param([string]$Target='Trainer')
$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
$sourceFiles=@((Join-Path $taskRoot 'Remote.cs'),(Join-Path $taskRoot ($Target+'.cs')))
if($Target -ne 'Probe'){$sourceFiles+=Join-Path $taskRoot 'Bridge.cs'}
if(Test-Path -LiteralPath (Join-Path $taskRoot 'Growth.cs')){$sourceFiles+=Join-Path $taskRoot 'Growth.cs'}
$taskOutput=Join-Path $taskRoot ($Target+'.exe')
if(Test-Path -LiteralPath $taskOutput){Remove-Item -LiteralPath $taskOutput}
$compiler=New-Object System.CodeDom.Compiler.CompilerParameters -Property @{GenerateExecutable=$true;OutputAssembly=$taskOutput;CompilerOptions='/platform:x64 /optimize+'}
if($Target -eq 'Trainer'){$compiler.CompilerOptions+=' /target:winexe /win32manifest:"'+(Join-Path $taskRoot 'Trainer.manifest')+'"'}
if($Target -eq 'Trainer'){$compiler.CompilerOptions+=' /win32icon:"'+(Join-Path $taskRoot 'Trainer.ico')+'"'}
$compiler.ReferencedAssemblies.AddRange(@('System.dll','System.Core.dll','System.Windows.Forms.dll','System.Drawing.dll'))
Add-Type -Path $sourceFiles -CompilerParameters $compiler
Get-Item -LiteralPath $taskOutput | Select-Object Name,Length
