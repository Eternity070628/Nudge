Unicode true
!include "MUI2.nsh"

!ifndef VERSION
  !define VERSION "2.0.0beta"
!endif
!ifndef VERSIONNUM
  !define VERSIONNUM "2.0.0.0"
!endif
!ifndef ARCH
  !define ARCH "x64"
!endif
!ifndef DISTDIR
  !define DISTDIR "..\..\dist"
!endif
!ifndef ASSETDIR
  !define ASSETDIR "..\assets"
!endif

Name "Nudge"
OutFile "${DISTDIR}\Nudge-${VERSION}-windows-${ARCH}-setup.exe"
InstallDir "$LOCALAPPDATA\Programs\Nudge"
InstallDirRegKey HKCU "Software\Nudge" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64

VIProductVersion "${VERSIONNUM}"
VIAddVersionKey /LANG=2052 "ProductName" "Nudge"
VIAddVersionKey /LANG=2052 "FileDescription" "Nudge 校园截止管家安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "LegalCopyright" "Nudge"

!define MUI_ICON "${ASSETDIR}\nudge.ico"
!define MUI_UNICON "${ASSETDIR}\nudge.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\Nudge.exe"
!define MUI_FINISHPAGE_RUN_TEXT "启动 Nudge"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

Section "Nudge" SEC_MAIN
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "${DISTDIR}\Nudge\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateDirectory "$SMPROGRAMS\Nudge"
  CreateShortCut "$SMPROGRAMS\Nudge\Nudge.lnk" "$INSTDIR\Nudge.exe"
  CreateShortCut "$DESKTOP\Nudge.lnk" "$INSTDIR\Nudge.exe"

  WriteRegStr HKCU "Software\Nudge" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Nudge" "DisplayName" "Nudge"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Nudge" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Nudge" "Publisher" "Nudge"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Nudge" "DisplayIcon" "$INSTDIR\Nudge.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Nudge" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Nudge" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Nudge" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$SMPROGRAMS\Nudge\Nudge.lnk"
  RMDir "$SMPROGRAMS\Nudge"
  Delete "$DESKTOP\Nudge.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "Software\Nudge"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Nudge"
SectionEnd