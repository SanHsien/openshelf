; OpenShelf — Inno Setup 安裝腳本
;
; 先以 PyInstaller 產出 dist\OpenShelf.exe（python build_exe.py），再編譯本檔：
;   iscc installer\openshelf.iss /DMyAppVersion=0.4.0
;
; 產物：dist\OpenShelf-<版本>-setup.exe，含開始功能表捷徑、可選桌面捷徑、解除安裝。
; 若 dist\ms-playwright 存在（可攜 Chromium），會一併安裝。

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "OpenShelf"
#define MyAppPublisher "SanHsien"
#define MyAppURL "https://github.com/SanHsien/openshelf"
#define MyAppExeName "OpenShelf.exe"

[Setup]
; 固定 AppId（升級時沿用同一個，勿更動）
AppId={{B8C6E4A2-1D3F-4E5A-9C7B-2A4D6E8F0A12}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist
OutputBaseFilename=OpenShelf-{#MyAppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; 不需系統管理員：可安裝到使用者目錄
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
; 若你的 Inno Setup 有安裝繁中語言檔，可取消下行註解：
; Name: "cht"; MessagesFile: "compiler:Languages\ChineseTraditional.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; 可攜 Chromium（存在才打包；登入優先用本機 Chrome/Edge，沒有才用內建）
Source: "..\dist\ms-playwright\*"; DestDir: "{app}\ms-playwright"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
