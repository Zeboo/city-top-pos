#ifndef AppVersion
  #define AppVersion "0"
#endif
#ifndef BuildSource
  #define BuildSource "..\dist-fast-start-build\TopCityPOSOffline"
#endif
#ifndef OutputDirectory
  #define OutputDirectory "..\dist"
#endif

[Setup]
AppId={{D836F36B-1516-46E8-B14E-55B2D949471E}
AppName=Top City POS Offline
AppVersion={#AppVersion}
AppPublisher=Top City POS
DefaultDirName={localappdata}\Programs\TopCityPOS
DefaultGroupName=Top City POS
DisableProgramGroupPage=yes
OutputDir={#OutputDirectory}
OutputBaseFilename=TopCityPOSOffline-Setup
SetupIconFile=..\app\resources\top_city_pos.ico
UninstallDisplayIcon={app}\TopCityPOSOffline.exe
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
DirExistsWarning=no

[Files]
Source: "{#BuildSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\Top City POS"; Filename: "{app}\TopCityPOSOffline.exe"; WorkingDir: "{app}"
Name: "{autoprograms}\Top City POS"; Filename: "{app}\TopCityPOSOffline.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\TopCityPOSOffline.exe"; Description: "Launch Top City POS"; Flags: nowait postinstall skipifsilent

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
