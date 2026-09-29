; Compile with ISCC /DVersion=... /DBundleDir=... /DOutputDir=...
#ifndef Version
  #error Version is required
#endif
#ifndef WithImportTools
  #define WithImportTools "0"
#endif
#ifndef BundleDir
  #error BundleDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif

[Setup]
AppId={{4596BB09-E79D-4547-A52F-845E33880628}
AppName=Transit2Fog
AppVersion={#Version}
AppPublisher=Transit2Fog contributors
AppPublisherURL=https://github.com/Uddoo/transit2fog
DefaultDirName={localappdata}\Programs\Transit2Fog
DefaultGroupName=Transit2Fog
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=Transit2Fog-{#Version}-windows-x64-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Transit2Fog.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "install.ps1,uninstall.ps1"

[InstallDelete]
; Remove only obsolete program-owned files when upgrading the former full ZIP.
Type: files; Name: "{app}\_internal\rail-routing\openrailrouting.jar"
Type: files; Name: "{app}\install.ps1"
Type: files; Name: "{app}\uninstall.ps1"
#if WithImportTools == "0"
Type: filesandordirs; Name: "{app}\_internal\pandas"
Type: filesandordirs; Name: "{app}\_internal\pandas.libs"
Type: filesandordirs; Name: "{app}\_internal\pyogrio"
Type: filesandordirs; Name: "{app}\_internal\pyogrio.libs"
#endif

[Icons]
Name: "{group}\Transit2Fog"; Filename: "{app}\Transit2Fog.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Transit2Fog"; Filename: "{app}\Transit2Fog.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Transit2Fog.exe"; Description: "Launch Transit2Fog"; Flags: nowait postinstall skipifsilent

; App data and downloaded components are outside {app}; never remove them.
