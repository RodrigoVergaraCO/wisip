; Wisip — Instalador Inno Setup
;
; Construye el instalador con:
;     iscc EXE\installer.iss
;
; Asume que EXE\Wisip\Wisip.exe ya existe (corre EXE\build.bat antes).
; Resultado: EXE\installer\Wisip-Setup-1.0.0.exe

#define MyAppName "Wisip"
#define MyAppVersion "2.11.2"
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
; 2.11.0: instalación POR USUARIO ({localappdata}\Programs\Wisip), sin UAC.
; Es lo que permite que la auto-actualización sea silenciosa (como Chrome o
; VS Code). {autopf}, {autoprograms} y {autodesktop} pasan a las rutas de usuario.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UsePreviousPrivileges=no
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

[UninstallRun]
; Libera la licencia de este equipo antes de borrar los archivos, para que la
; clave se pueda activar en otro PC ("transferible al desinstalar").
Filename: "{app}\{#MyAppExeName}"; Parameters: "--deactivate-license"; Flags: runhidden waituntilterminated; RunOnceId: "WisipDeactivateLicense"

[Run]
; Wisip ya NO se compila con --uac-admin: corre en modo usuario.
; `runasoriginaluser` lanza la app como el usuario normal (no elevado), aunque
; el instalador esté corriendo elevado para escribir en Program Files. Sin esta
; flag, el proceso hijo heredaría la elevación del instalador y Wisip arrancaría
; como administrador esa primera vez (justo lo que queremos evitar).
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
// Cierra un Wisip en ejecución ANTES de que Setup revise archivos en uso.
// Wisip "oculta al tray" con la X, así que el Restart Manager de Windows no
// logra cerrarlo y la instalación silenciosa abortaba con archivos en uso
// (exit 5, log 2026-09-23). Dos capas: (1) el mismo evento Win32 que usa la
// instancia única de Wisip para pedir cierre limpio; (2) taskkill de respaldo.
function OpenEventW(dwDesiredAccess: DWORD; bInheritHandle: BOOL; lpName: String): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function SetEvent(hEvent: THandle): BOOL;
  external 'SetEvent@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';

procedure CloseRunningWisip();
var
  h: THandle;
  Ok: Boolean;
  ResultCode: Integer;
begin
  h := OpenEventW(2 { EVENT_MODIFY_STATE }, False, 'Local\Wisip_CerrarInstanciaPrevia');
  if h <> 0 then
  begin
    SetEvent(h);
    CloseHandle(h);
    Log('Wisip: evento de cierre limpio enviado');
    Sleep(2500);
  end
  else
    Log('Wisip: sin instancia (evento no existe)');
  ResultCode := -1;
  Ok := Exec(ExpandConstant('{cmd}'), '/C taskkill /IM Wisip.exe /F /T', '',
             SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Log('taskkill Wisip.exe -> exec=' + IntToStr(Integer(Ok)) + ' code=' + IntToStr(ResultCode));
  Sleep(1000);
end;

function InitializeSetup(): Boolean;
begin
  CloseRunningWisip();
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseRunningWisip();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  CloseRunningWisip();
  Result := True;
end;
