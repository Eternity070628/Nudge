#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="$(tr -d '\r\n' < packaging/version.txt)"
PYTHON="${PYTHON:-python3}"
RAW_ARCH="$(uname -m)"
if [ "$RAW_ARCH" = "x86_64" ]; then
  ARCH_LABEL="x64"
  DEB_ARCH="amd64"
  RPM_ARCH="x86_64"
  NFPM_ARCH="x86_64"
else
  ARCH_LABEL="arm64"
  DEB_ARCH="arm64"
  RPM_ARCH="aarch64"
  NFPM_ARCH="arm64"
fi

mkdir -p build dist

echo "[build] PyInstaller $VERSION / linux-$ARCH_LABEL"
"$PYTHON" -m PyInstaller \
  --noconfirm --clean --onedir --name nudge \
  --add-data "backend/app/static:backend/app/static" \
  --paths backend \
  --collect-submodules uvicorn \
  --collect-submodules app \
  --hidden-import app.main \
  --distpath dist --workpath build \
  packaging/nudge_entry.py

APPDIR="build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
  "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -R dist/nudge "$APPDIR/usr/lib/nudge"
cp packaging/linux/nudge-wrapper.sh "$APPDIR/usr/bin/nudge"
cp packaging/assets/nudge.png "$APPDIR/nudge.png"
cp packaging/assets/nudge.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/nudge.png"
cp packaging/linux/nudge.desktop "$APPDIR/nudge.desktop"
cp packaging/linux/nudge.desktop "$APPDIR/usr/share/applications/nudge.desktop"
cp packaging/linux/AppRun "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun" "$APPDIR/usr/bin/nudge"
ln -sf nudge.png "$APPDIR/.DirIcon"

# nfpm：根据平台选择官方 release 资产
NFPM_URL="$(NFPM_ARCH="$NFPM_ARCH" python3 - <<'PY'
import json, os, urllib.request
arch = os.environ["NFPM_ARCH"]
headers = {"User-Agent": "nudge-build"}
token = os.environ.get("GITHUB_TOKEN", "")
if token:
    headers["Authorization"] = "Bearer " + token
req = urllib.request.Request(
    "https://api.github.com/repos/goreleaser/nfpm/releases/latest",
    headers=headers,
)
data = json.load(urllib.request.urlopen(req, timeout=30))
for asset in data.get("assets", []):
    name = asset["name"].lower()
    if name.startswith("nfpm_") and f"linux_{arch}" in name and name.endswith(".tar.gz"):
        print(asset["browser_download_url"])
        break
PY
)"
if [ -z "$NFPM_URL" ]; then
  echo "找不到 nfpm 下载地址" >&2
  exit 1
fi
curl -fsSL --retry 3 -o build/nfpm.tar.gz "$NFPM_URL"
tar -xzf build/nfpm.tar.gz -C build nfpm
chmod +x build/nfpm

cat > build/nfpm-deb.yaml <<EOF
name: nudge
arch: ${DEB_ARCH}
platform: linux
version: ${VERSION}
section: utils
priority: optional
maintainer: Nudge
vendor: Nudge
homepage: https://github.com/Eternity070628/Nudge
license: MIT
description: Nudge 校园截止管家
contents:
  - src: dist/nudge
    dst: /usr/lib/nudge
    type: tree
  - src: packaging/linux/nudge-wrapper.sh
    dst: /usr/bin/nudge
    file_info:
      mode: 0755
  - src: packaging/linux/nudge.desktop
    dst: /usr/share/applications/nudge.desktop
  - src: packaging/assets/nudge.png
    dst: /usr/share/icons/hicolor/256x256/apps/nudge.png
EOF

cat > build/nfpm-rpm.yaml <<EOF
name: nudge
arch: ${RPM_ARCH}
platform: linux
version: ${VERSION}
section: utils
priority: optional
maintainer: Nudge
vendor: Nudge
homepage: https://github.com/Eternity070628/Nudge
license: MIT
description: Nudge 校园截止管家
contents:
  - src: dist/nudge
    dst: /usr/lib/nudge
    type: tree
  - src: packaging/linux/nudge-wrapper.sh
    dst: /usr/bin/nudge
    file_info:
      mode: 0755
  - src: packaging/linux/nudge.desktop
    dst: /usr/share/applications/nudge.desktop
  - src: packaging/assets/nudge.png
    dst: /usr/share/icons/hicolor/256x256/apps/nudge.png
EOF

build/nfpm package --config build/nfpm-deb.yaml --packager deb --target dist
build/nfpm package --config build/nfpm-rpm.yaml --packager rpm --target dist

# AppImage
TOOL="build/appimagetool"
if [ ! -x "$TOOL" ]; then
  curl -fsSL --retry 3 -o "$TOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${RAW_ARCH}.AppImage"
  chmod +x "$TOOL"
fi
ARCH="$RAW_ARCH" APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --no-appstream "$APPDIR" \
  "dist/Nudge-${VERSION}-linux-${ARCH_LABEL}.AppImage"
chmod +x "dist/Nudge-${VERSION}-linux-${ARCH_LABEL}.AppImage"

echo "[build] 完成：dist 下的 deb/rpm/AppImage"