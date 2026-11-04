; Inno Setup Installer Script for Tact (Windows 10 & Windows 11)
; Build: ISCC.exe /DMyAppVersion=1.2.0 /DMyChannel=beta.1 packaging\windows_installer.iss
#ifndef MyAppVersion
  #define MyAppVersion "1.2.0"
#endif
#ifndef MyChannel
  #define MyChannel "beta.1"
#endif
#define MyAppName "Tact"
#define MyAppPublisher "Omnii"
#define MyAppExeName "AutoCorrectDesktop.exe"
#define MyFullVersion MyAppVersion + "-" + MyChannel

[Setup]
AppId={{8D4F62C1-4B9E-497A-9F3E-71B8C2094E1A}
; The Windows build is the stable one (macOS and Linux are still in beta), so the
; product name carries no channel tag. Upgrades key on AppId, not AppName.
AppName={#MyAppName}
AppVersion={#MyFullVersion}
AppVerName={#MyAppName} {#MyFullVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}.1
VersionInfoProductTextVersion={#MyFullVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=Tact-{#MyFullVersion}-win64-setup
SetupIconFile=autocorrect.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
; Optional Authenticode signing of Setup.exe and the uninstaller from inside Inno.
; build_windows_beta.ps1 signs Setup.exe itself after compilation, so this is only
; used when compiling manually with a configured Inno "SignTool" (Tools -> Configure Sign Tools)
; and passing /DSignTool=<name>.
#ifdef SignTool
SignTool={#SignTool} sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com /d $q{#MyAppName}$q $f
SignedUninstaller=yes
#endif

[Tasks]
Name: "startup"; Description: "Start {#MyAppName} automatically when Windows starts"; GroupDescription: "Startup Options:"
Name: "desktopicon"; Description: "Create a desktop shortcut to Settings"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\AutoCorrectDesktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "Start the background autocorrect service"
Name: "{group}\{#MyAppName} Settings"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--settings"; Comment: "Dictionary, Languages, Corrections, Profiles, Text Expansion, Licence"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName} Settings"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--settings"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AutoCorrectDesktop"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} in the background (tray icon)"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillAutoCorrect"
