[Setup]
AppId={{A366B5BD-6EA1-4CE1-A2C3-9AA1B56215B6}
AppName=谱间
AppVersion=0.3.0
AppPublisher=Bionysus-bot
DefaultDirName={localappdata}\Programs\PuJian
DefaultGroupName=谱间
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\output\desktop
OutputBaseFilename=PuJian-0.3.0-Windows-x64-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\PuJian.exe
CloseApplications=yes
[Files]
Source: "..\output\desktop\PuJian\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userprograms}\谱间"; Filename: "{app}\PuJian.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\谱间"; Filename: "{app}\PuJian.exe"; WorkingDir: "{app}"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"
[Run]
Filename: "{app}\PuJian.exe"; Description: "启动谱间"; Flags: nowait postinstall skipifsilent
