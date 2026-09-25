#define MyAppName "MK-Viral-Assembly"
#define MyAppVersion "1.2.1"
#define MyAppPublisher "MK-Viral-Assembly"
#define MyAppExeName "MK-Viral-Assembly.exe"

[Setup]
AppId={{8C7A0CC5-3D3A-49C3-BF83-4BB4C57D0964}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/nascimento-jean/MK-Viral-Assembly
AppSupportURL=https://github.com/nascimento-jean/MK-Viral-Assembly/issues
AppUpdatesURL=https://github.com/nascimento-jean/MK-Viral-Assembly/releases/latest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutputDir}
OutputBaseFilename=MK-Viral-Assembly-Setup
SetupIconFile={#SourceDir}\mkva.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile={#SourceDir}\LICENSE-MK-Viral-Assembly.txt
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "{#SourceDir}\MK-Viral-Assembly.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\mkva.ico"; DestDir: "{app}"; DestName: "mkva-v2.ico"; Flags: ignoreversion
Source: "{#SourceDir}\bootstrap-wsl.sh"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\LICENSE-MK-Viral-Assembly.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\LICENSE-dotnet.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\THIRD-PARTY-NOTICES-dotnet.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\mkva-v2.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\mkva-v2.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[InstallDelete]
Type: files; Name: "{app}\mkva.ico"
