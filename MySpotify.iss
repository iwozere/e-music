; Inno Setup script for MySpotify - Standalone Edition (docs/features-v7.md, Phase 5)
;
; Packages the PyInstaller output (dist\MySpotify\) into a single per-user installer
; that needs no admin rights. Build it with build-installer.ps1, or directly:
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" MySpotify.iss
;
; The app's data (library, db, cache) lives in %LOCALAPPDATA%\iwozere\MySpotify and is
; intentionally NOT removed on uninstall, so a reinstall keeps your collected library.

#define MyAppName "MySpotify"
#define MyAppVersion "2.9.28"
#define MyAppPublisher "iwozere"
#define MyAppURL "https://github.com/iwozere/e-music"
#define MyAppExeName "MySpotify.exe"

[Setup]
; A stable AppId so upgrades replace the prior install instead of stacking.
AppId={{8F3A1B2C-9D4E-4F5A-AB6C-1234567890AB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install: no UAC/admin prompt.
PrivilegesRequired=lowest
OutputDir=dist\installer
OutputBaseFilename=MySpotify-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire one-folder PyInstaller build (exe + _internal with Python, deps, ffmpeg, web UI).
Source: "dist\MySpotify\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
