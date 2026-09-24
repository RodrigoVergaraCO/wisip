; Wisip — Instalador Inno Setup
;
; Construye el instalador con:
;     iscc EXE\installer.iss
;
; Asume que EXE\Wisip\Wisip.exe ya existe (corre EXE\build.bat antes).
; Resultado: EXE\installer\Wisip-Setup-1.0.0.exe

#define MyAppName "Wisip"
#define MyAppVersion "2.7.0"
#define MyAppPublisher "Wisip"
#define MyAppExeName "Wisip.exe"
; Desde la 2.7.0 hay UN solo instalador liviano (~70 MB): las DLLs CUDA se
; descargan desde la app si hay GPU NVIDIA. Para un build "todo incluido"
; (2,2 GB, WISIP_BUNDLE_CUDA=1 al compilar) se puede etiquetar con:
;   iscc /DVariant=GPU-full EXE\installer.iss
#ifdef Variant
  #define Suffix "-" + Variant
#else
  #define Suffix ""
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
OutputBaseFilename=Wisip-Setup-{#MyAppVersion}{#Suffix}
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

[InstallDelete]
; PyInstaller regenera _internal por completo en cada build: se limpia antes
; de copiar para no dejar restos de versiones anteriores. Sin esto, actualizar
; desde un instalador GPU (<= 2.6.0) dejaba 1,9 GB de DLLs CUDA huérfanas en
; Program Files (verificado 2026-09-23). La configuración vive en %APPDATA%.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; Empaca la carpeta producida por PyInstaller (EXE\Wisip por defecto).
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
