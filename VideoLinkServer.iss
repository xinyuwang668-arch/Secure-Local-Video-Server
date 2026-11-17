[Setup]
; 不写 AppId：Inno 会用 AppName 推导（"Secure Local Video Server_is1"），
; 与 2.0.0 老安装包保持同一身份，安装时能识别并直接升级覆盖，不会并存两份。
AppName=Secure Local Video Server
AppVersion=2.1.1
AppVerName=Secure Local Video Server 2.1.1
AppPublisher=Xinyu Wang

DefaultDirName={autopf}\SecureLocalVideoServer
DefaultGroupName=Secure Local Video Server
DisableProgramGroupPage=yes

OutputDir=installer_output
OutputBaseFilename=SecureLocalVideoServer_Setup_V2.1.1

Compression=lzma2
SolidCompression=yes

SetupIconFile=SecureLocalVideoServer.ico
WizardStyle=modern

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; 已装过旧版本时先关掉旧程序，避免文件占用
CloseApplications=yes
RestartApplications=no


[InstallDelete]

; 旧版本的 PyInstaller 目录整体清掉，避免残留旧版 _internal 文件
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\SecureLocalVideoServer.exe"


[Files]

; ===== 主程序 =====
Source: "dist\SecureLocalVideoServer\SecureLocalVideoServer.exe"; \
    DestDir: "{app}"; \
    Flags: ignoreversion


; ===== PyInstaller 内部文件（含 cloudflared.exe）=====
Source: "dist\SecureLocalVideoServer\_internal\*"; \
    DestDir: "{app}\_internal"; \
    Flags: ignoreversion recursesubdirs createallsubdirs


; ===== 程序图标 =====
Source: "SecureLocalVideoServer.ico"; \
    DestDir: "{app}"; \
    Flags: ignoreversion


[Icons]

; 开始菜单
Name: "{group}\Secure Local Video Server"; \
    Filename: "{app}\SecureLocalVideoServer.exe"; \
    IconFilename: "{app}\SecureLocalVideoServer.ico"

Name: "{group}\卸载 Secure Local Video Server"; \
    Filename: "{uninstallexe}"


; 桌面快捷方式
Name: "{commondesktop}\Secure Local Video Server"; \
    Filename: "{app}\SecureLocalVideoServer.exe"; \
    IconFilename: "{app}\SecureLocalVideoServer.ico"


[Run]

; 安装结束后启动程序
Filename: "{app}\SecureLocalVideoServer.exe"; \
    Description: "启动 Secure Local Video Server"; \
    Flags: nowait postinstall skipifsilent


[UninstallDelete]

Type: filesandordirs; Name: "{app}\_internal"
