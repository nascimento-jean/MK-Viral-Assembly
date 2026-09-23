[CmdletBinding()]
param([string]$Configuration = 'Release')

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $root
$assets = Join-Path $root 'assets'
$output = Join-Path $root 'output'
$publish = Join-Path $root 'launcher\bin\publish'
$dotnet = 'C:\Program Files\dotnet\dotnet.exe'

New-Item -ItemType Directory -Path $assets -Force | Out-Null
New-Item -ItemType Directory -Path $output -Force | Out-Null
Get-ChildItem -LiteralPath $output -File -ErrorAction SilentlyContinue | Remove-Item -Force

$icon = Join-Path $assets 'mkva.ico'
if (-not (Test-Path -LiteralPath $icon)) { throw 'Ícone do aplicativo não encontrado em windows-launcher/assets/mkva.ico.' }

& $dotnet publish (Join-Path $root 'launcher\MkViralAssembly.Launcher.csproj') -c $Configuration -r win-x64 --self-contained true --ignore-failed-sources -o $publish
if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar o launcher.' }

$launcher = Join-Path $publish 'MK-Viral-Assembly.exe'
$appFiles = @('MK-Viral-Assembly.exe')
foreach ($appFile in $appFiles) {
    Copy-Item -LiteralPath (Join-Path $publish $appFile) -Destination (Join-Path $output $appFile) -Force
}
Copy-Item -LiteralPath $icon -Destination (Join-Path $output 'mkva.ico') -Force
Copy-Item -LiteralPath (Join-Path $root 'bootstrap-wsl.sh') -Destination (Join-Path $output 'bootstrap-wsl.sh') -Force
Copy-Item -LiteralPath (Join-Path $repo 'LICENSE') -Destination (Join-Path $output 'LICENSE-MK-Viral-Assembly.txt') -Force
$dotnetRoot = Split-Path -Parent $dotnet
Copy-Item -LiteralPath (Join-Path $dotnetRoot 'LICENSE.txt') -Destination (Join-Path $output 'LICENSE-dotnet.txt') -Force
Copy-Item -LiteralPath (Join-Path $dotnetRoot 'ThirdPartyNotices.txt') -Destination (Join-Path $output 'THIRD-PARTY-NOTICES-dotnet.txt') -Force

$stage = Join-Path $env:TEMP ('mkva-setup-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage -Force | Out-Null
foreach ($stageFile in @(
    'MK-Viral-Assembly.exe',
    'mkva.ico',
    'bootstrap-wsl.sh',
    'LICENSE-MK-Viral-Assembly.txt',
    'LICENSE-dotnet.txt',
    'THIRD-PARTY-NOTICES-dotnet.txt'
)) {
    Copy-Item -LiteralPath (Join-Path $output $stageFile) -Destination (Join-Path $stage $stageFile) -Force
}
$setupExe = Join-Path $stage 'MK-Viral-Assembly-Setup.exe'
$finalSetupExe = Join-Path $output 'MK-Viral-Assembly-Setup.exe'
$iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
if (-not (Test-Path -LiteralPath $iscc)) { throw 'Inno Setup 6 não encontrado.' }
& $iscc "/DSourceDir=$stage" "/DOutputDir=$stage" (Join-Path $root 'installer.iss')
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $setupExe)) { throw 'Falha ao criar o instalador.' }
Copy-Item -LiteralPath $setupExe -Destination $finalSetupExe -Force
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$stageFullPath = [IO.Path]::GetFullPath($stage)
if (-not $stageFullPath.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing to remove a staging path outside the temporary directory: $stageFullPath" }
Remove-Item -LiteralPath $stageFullPath -Recurse -Force

Get-FileHash -LiteralPath $finalSetupExe -Algorithm SHA256 | Format-List
Get-Item -LiteralPath $launcher, $finalSetupExe | Select-Object FullName, Length
