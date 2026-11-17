[Setup]
AppId={{8F3C1D62-5B4A-4F0E-9B7E-2D6A1C4E8B93}
AppName=Secure Local Video Server
AppVersion=2.1.0
AppVerName=Secure Local Video Server 2.1.0
AppPublisher=Xinyu Wang

DefaultDirName={autopf}\SecureLocalVideoServer
DefaultGroupName=Secure Local Video Server
DisableProgramGroupPage=yes

OutputDir=installer_output
OutputBaseFilename=SecureLocalVideoServer_Setup_V2.1.0

Compression=lzma2
SolidCompression=yes

SetupIconFile=SecureLocalVideoServer.ico
WizardStyle=modern

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; 升级安装时先关掉正在运行的程序，避免文件占用
CloseApplications=yes
RestartApplications=no


[Files]

; ===== 主程序 =====
Source: "D:\VideoServer\dist\SecureLocalVideoServer\SecureLocalVideoServer.exe"; \
    DestDir: "{app}"; \
    Flags: ignoreversion


; ===== PyInstaller 内部文件（含 cloudflared.exe）=====
Source: "D:\VideoServer\dist\SecureLocalVideoServer\_internal\*"; \
    DestDir: "{app}\_internal"; \
    Flags: ignoreversion recursesubdirs createallsubdirs


; ===== 程序图标 =====
Source: "D:\VideoServer\SecureLocalVideoServer.ico"; \
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

; PyInstaller onedir 的 _internal 目录由卸载器清理不干净时兜底
Type: filesandordirs; Name: "{app}\_internal"
