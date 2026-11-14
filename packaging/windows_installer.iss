; Inno Setup Installer Script for Typen (Windows 10 & Windows 11)
; Build: ISCC.exe /DMyAppVersion=1.3.0 /DMyChannel=stable packaging\windows_installer.iss
; MyChannel "stable" (the Windows build) yields plain 1.3.0; anything else is a
; pre-release suffix (beta.1 -> 1.3.0-beta.1).
#ifndef MyAppVersion
  #define MyAppVersion "2.0.0"
#endif
#ifndef MyChannel
  #define MyChannel "stable"
#endif
#define MyAppName "Typen"
#define MyAppPublisher "Omnii"
#define MyAppExeName "typen.exe"
#if MyChannel == "stable"
  #define MyFullVersion MyAppVersion
#else
  #define MyFullVersion MyAppVersion + "-" + MyChannel
#endif

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
UsePreviousAppDir=yes
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=Typen-{#MyFullVersion}-win64-setup
SetupIconFile=autocorrect.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; Stop the tray daemon ourselves in PrepareToInstall so Restart Manager does not
; prompt "files in use / force close" on upgrades. Post-install [Run] relaunches.
CloseApplications=no
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
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\Typen\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; One entry, "Typen": starts the background service when it is not running, and
; opens the Typen window when it already is (see launcher._run_daemon).
[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "System-wide autocorrect. Opens Typen when it is already running."
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AutoCorrectDesktop"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
; Interactive installs: optional post-install launch (skipped when /SILENT).
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} in the background (tray icon)"; Flags: nowait postinstall skipifsilent; Check: NotUpdatedByApp
; In-app Update & restart passes /UPDATEDBYAPP=1 with /VERYSILENT — always relaunch.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait postinstall skipifdoesntexist; Check: IsUpdatedByApp

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillAutoCorrect"

[Code]
var
  GUpdatedByApp: Boolean;

function IsUpdatedByApp: Boolean;
begin
  Result := GUpdatedByApp;
end;

function NotUpdatedByApp: Boolean;
begin
  Result := not GUpdatedByApp;
end;

function InitializeSetup(): Boolean;
begin
  { /UPDATEDBYAPP=1 from the desktop app's silent updater. }
  GUpdatedByApp := ExpandConstant('{param:UPDATEDBYAPP|0}') = '1';
  Result := True;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
var
  Uninstall: String;
begin
  { Older Inno builds reject DisableWelcomePage=auto. Skip the welcome page on upgrade. }
  Result := (PageID = wpWelcome) and RegQueryStringValue(
    HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{8D4F62C1-4B9E-497A-9F3E-71B8C2094E1A}_is1',
    'UninstallString',
    Uninstall
  );
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExePath: String;
  LegacyExePath: String;
  ResultCode: Integer;
begin
  Result := '';
  ExePath := ExpandConstant('{app}\{#MyAppExeName}');
  LegacyExePath := ExpandConstant('{app}\AutoCorrectDesktop.exe');
  if FileExists(ExePath) then
    Exec(ExePath, '--stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
  else if FileExists(LegacyExePath) then
    Exec(LegacyExePath, '--stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  Sleep(1000);
  Exec(
    ExpandConstant('{sys}\taskkill.exe'),
    '/F /IM {#MyAppExeName}',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
  Exec(
    ExpandConstant('{sys}\taskkill.exe'),
    '/F /IM AutoCorrectDesktop.exe',
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
  Sleep(500);
end;
