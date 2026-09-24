; Wisip — Instalador Inno Setup
;
; Construye el instalador con:
;     iscc EXE\installer.iss
;
; Asume que EXE\Wisip\Wisip.exe ya existe (corre EXE\build.bat antes).
; Resultado: EXE\installer\Wisip-Setup-1.0.0.exe

#define MyAppName "Wisip"
#define MyAppVersion "2.6.0"
#define MyAppPublisher "Wisip"
#define MyAppExeName "Wisip.exe"
; Variante del build: "GPU" (con DLLs CUDA para NVIDIA) o "CPU" (universal,
; ~700 MB más liviano). Se pasa por línea de comandos:
;   iscc /DVariant=CPU /DSourceDir=dist-cpu\Wisip EXE\installer.iss
;   iscc /DVariant=GPU EXE\installer.iss
#ifndef Variant
  #define Variant "GPU"
#endif
#ifndef SourceDir
  #define SourceDir "Wisip"
#endif

[Setup]
; Identificador único (no cambiar entre versiones — es la "clave" del uninstaller).
AppId={{8C2F1E6B-7A4D-4D2E-9F0E-9B7C1D8A6F12}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://wisip.ai
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=Wisip-Setup-{#MyAppVersion}-{#Variant}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
LicenseFile=installer-assets\LICENSE.txt
InfoBeforeFile=installer-assets\INFO_BEFORE.txt
InfoAfterFile=installer-assets\INFO_AFTER.txt
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
MinVersion=10.0
ShowLanguageDialog=auto

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Empaca la carpeta producida por PyInstaller (Wisip\ para GPU, dist-cpu\Wisip
; para CPU — ver el define SourceDir arriba).
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Wisip ya NO se compila con --uac-admin: corre en modo usuario.
; `runasoriginaluser` lanza la app como el usuario normal (no elevado), aunque
; el instalador esté corriendo elevado para escribir en Program Files. Sin esta
; flag, el proceso hijo heredaría la elevación del instalador y Wisip arrancaría
; como administrador esa primera vez (justo lo que queremos evitar).
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runasoriginaluser
