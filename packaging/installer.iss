#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif

#define AppName "简幕"
#define AppExeName "JianSubtitle.exe"
#ifndef StagingDir
  #error StagingDir must be provided by build_windows.ps1
#endif
#ifndef ReleaseDir
  #error ReleaseDir must be provided by build_windows.ps1
#endif

[Setup]
AppId={{D1E03AD8-C341-48C7-9A96-58FF4D0E7D7B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Jian Subtitle
DefaultDirName={localappdata}\Programs\JianSubtitle
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#ReleaseDir}
OutputBaseFilename=JianSubtitle-{#AppVersion}-win-x64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=..\src\subtitle_app\resources\app.ico
SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "创建桌面图标"; GroupDescription: "附加图标："; Flags: unchecked

[Files]
Source: "{#StagingDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef WebView2Installer
Source: "{#WebView2Installer}"; DestDir: "{tmp}"; DestName: "MicrosoftEdgeWebView2Setup.exe"; Flags: deleteafterinstall
#endif

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
#ifdef WebView2Installer
Filename: "{tmp}\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "正在安装 Microsoft WebView2…"; Flags: waituntilterminated; Check: NeedsWebView2
#endif
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent; Check: HasWebView2
; In-app updates run Setup with /SILENT /RELAUNCH=1 (src/subtitle_app/updater.py): reopen 简幕 afterwards, never elevated.
Filename: "{app}\{#AppExeName}"; Flags: nowait runasoriginaluser; Check: RelaunchAfterUpdate

[Code]
function HasWebView2: Boolean;
var UserVersion, MachineVersion: String;
begin
  RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', UserVersion);
  RegQueryStringValue(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', MachineVersion);
  Result := ((UserVersion <> '') and (UserVersion <> '0.0.0.0')) or ((MachineVersion <> '') and (MachineVersion <> '0.0.0.0'));
end;

function NeedsWebView2: Boolean;
begin
  Result := not HasWebView2;
end;

function RelaunchAfterUpdate: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1') and HasWebView2;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssDone) and NeedsWebView2 then
    MsgBox('简幕已安装，但 WebView2 未能安装成功。请安装 Microsoft 官方 WebView2 Runtime 后再启动。', mbError, MB_OK);
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  #ifndef WebView2Installer
  if NeedsWebView2 then begin
    MsgBox('此电脑缺少 Microsoft Edge WebView2 Runtime。请从 Microsoft 官方网站安装，或使用包含 WebView2 的简幕安装包。', mbError, MB_OK);
    Result := False;
  end;
  #endif
end;
