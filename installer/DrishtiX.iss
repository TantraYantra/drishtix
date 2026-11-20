; DrishtiX - single-file Windows installer.
;
; Design goals:
;   * one download, one double-click, no ZIP and no admin prompt;
;   * per-user install under %LOCALAPPDATA%\Programs\DrishtiX;
;   * Start Menu entry, optional Desktop shortcut, launch when finished;
;   * pre-fetch the two AI models so the first face scan works immediately;
;   * never touch %LOCALAPPDATA%\TantraYantra\DrishtiX on install or uninstall.

#define MyAppName "DrishtiX"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "TantraYantra"
#define MyAppURL "https://tantrayantra.github.io/tantrayantra-website/"
#define MyAppExeName "DrishtiX.exe"

; CI builds use ..\dist\DrishtiX. Local builds can override with
;   ISCC.exe /DPayloadDir="C:\path\to\built\DrishtiX" installer\DrishtiX.iss
#ifndef PayloadDir
  #define PayloadDir "..\dist\DrishtiX"
#endif

; Overridable so the interactive model-download page can be tested against a
; temporary folder. Production builds keep the real per-user location.
#ifndef ModelsRoot
  #define ModelsRoot "{localappdata}\TantraYantra\DrishtiX\models"
#endif

[Setup]
AppId={{49C5BBAD-2316-4C5C-8E52-A34001E03BD7}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
VersionInfoVersion=1.1.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableWelcomePage=no

PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputDir=..\release
OutputBaseFilename=DrishtiX-Setup
SetupIconFile=..\assets\drishtix_logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no
; The 1.0.0 build was called PeopleLens and lived in a different folder, so do
; not inherit that install path. The uninstall entry (same AppId) is reused.
UsePreviousAppDir=no
SetupLogging=yes

WizardStyle=modern
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  AdaFaceUrl  = 'https://github.com/yakhyo/adaface-onnx/releases/download/weights/adaface_ir_18.onnx';
  AdaFaceSha  = '6b6a35772fb636cdd4fa86520c1a259d0c41472a76f70f802b351837a00d9870';
  AdaFaceName = 'adaface_ir_18.onnx';

  RetinaUrl   = 'https://github.com/yakhyo/uniface/releases/download/weights/retinaface_mv2.onnx';
  RetinaSha   = '3ca44c045651cabeed1193a1fae8946ad1f3a55da8fa74b341feab5a8319f757';
  RetinaName  = 'retinaface_mnet_v2.onnx';

var
  DownloadPage: TDownloadWizardPage;

function ModelsDir: String;
begin
  Result := ExpandConstant('{#ModelsRoot}');
end;

function FileHasHash(const FileName, Hash: String): Boolean;
begin
  Result := False;
  if not FileExists(FileName) then
    Exit;
  try
    Result := CompareText(GetSHA256OfFile(FileName), Hash) = 0;
  except
    Result := False;
  end;
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure DownloadModelsSilently;
begin
  if not FileHasHash(ModelsDir + '\' + AdaFaceName, AdaFaceSha) then
  begin
    try
      DownloadTemporaryFile(AdaFaceUrl, AdaFaceName, AdaFaceSha, nil);
    except
      Log('AdaFace model could not be downloaded: ' + GetExceptionMessage);
    end;
  end;

  if not FileHasHash(ModelsDir + '\' + RetinaName, RetinaSha) then
  begin
    try
      DownloadTemporaryFile(RetinaUrl, RetinaName, RetinaSha, nil);
    except
      Log('RetinaFace model could not be downloaded: ' + GetExceptionMessage);
    end;
  end;
end;

procedure InitializeWizard;
begin
  // Silent installs have no wizard; the models are fetched in CurStepChanged.
  if WizardSilent then
    Exit;

  DownloadPage := CreateDownloadPage(
    'Local AI models',
    'DrishtiX needs two face-recognition models (about 104 MB).' + #13#10 +
    'They are downloaded once and stay on this PC. No photos are uploaded.' + #13#10 +
    'If the download is skipped here, DrishtiX will try again the first time ' +
    'you use face recognition.',
    @OnDownloadProgress);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  NeedAdaFace, NeedRetina: Boolean;
begin
  Result := True;
  if CurPageID <> wpReady then
    Exit;

  NeedAdaFace := not FileHasHash(ModelsDir + '\' + AdaFaceName, AdaFaceSha);
  NeedRetina  := not FileHasHash(ModelsDir + '\' + RetinaName, RetinaSha);

  if (not NeedAdaFace) and (not NeedRetina) then
    Exit;

  DownloadPage.Clear;
  if NeedAdaFace then
    DownloadPage.Add(AdaFaceUrl, AdaFaceName, AdaFaceSha);
  if NeedRetina then
    DownloadPage.Add(RetinaUrl, RetinaName, RetinaSha);

  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
    except
      if MsgBox(
        'The AI models could not be downloaded.' + #13#10#13#10 +
        'DrishtiX will still install, and it will try again the first time ' +
        'you use face recognition.' + #13#10#13#10 +
        'Continue with the installation?',
        mbError, MB_YESNO) = IDNO then
        Result := False;
    end;
  finally
    DownloadPage.Hide;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  TargetDir: String;
begin
  if (CurStep = ssInstall) and WizardSilent then
    DownloadModelsSilently;

  if CurStep <> ssPostInstall then
    Exit;

  TargetDir := ModelsDir;
  ForceDirectories(TargetDir);

  if FileExists(ExpandConstant('{tmp}\' + AdaFaceName)) then
    CopyFile(ExpandConstant('{tmp}\' + AdaFaceName), TargetDir + '\' + AdaFaceName, False);
  if FileExists(ExpandConstant('{tmp}\' + RetinaName)) then
    CopyFile(ExpandConstant('{tmp}\' + RetinaName), TargetDir + '\' + RetinaName, False);
end;
