#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="$(tr -d '\r\n' < packaging/version.txt)"
PYTHON="${PYTHON:-python3}"
RAW_ARCH="$(uname -m)"
if [ "$RAW_ARCH" = "x86_64" ]; then ARCH_LABEL="x64"; else ARCH_LABEL="arm64"; fi

mkdir -p build dist

# .icns 必须用 macOS 的 iconutil 生成
ICONSET="build/Nudge.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" packaging/assets/nudge.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
  sips -z "$((size * 2))" "$((size * 2))" packaging/assets/nudge.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o build/nudge.icns

echo "[build] PyInstaller $VERSION / macos-$ARCH_LABEL"
"$PYTHON" -m PyInstaller \
  --noconfirm --clean --windowed --name Nudge \
  --icon build/nudge.icns \
  --osx-bundle-identifier com.nudge.app \
  --add-data "backend/app/static:backend/app/static" \
  --add-data "packaging/assets/nudge.png:assets" \
  --paths backend \
  --collect-submodules uvicorn \
  --collect-submodules app \
  --collect-submodules webview \
  --collect-submodules pystray \
  --hidden-import webview.platforms.cocoa \
  --hidden-import app.main \
  --distpath dist --workpath build \
  packaging/nudge_entry.py

APP="dist/Nudge.app"
if [ ! -d "$APP" ]; then
  echo "缺少 $APP" >&2
  exit 1
fi

if [ -n "${MACOS_SIGNING_IDENTITY:-}" ]; then
  echo "[build] codesign $MACOS_SIGNING_IDENTITY"
  codesign --deep --force --options runtime --timestamp --sign "$MACOS_SIGNING_IDENTITY" "$APP"
else
  echo "[build] 未配置 Apple 签名证书，生成未签名应用"
fi

DMG="dist/Nudge-${VERSION}-macos-${ARCH_LABEL}.dmg"
PKG="dist/Nudge-${VERSION}-macos-${ARCH_LABEL}.pkg"
STAGE="build/dmg-stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Nudge" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

pkgbuild --component "$APP" --install-location /Applications \
  --identifier com.nudge.app --version "$VERSION" "$PKG"

if [ -n "${MACOS_SIGNING_IDENTITY:-}" ]; then
  productsign --sign "$MACOS_SIGNING_IDENTITY" "$PKG" "$PKG.signed"
  mv "$PKG.signed" "$PKG"
  if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
    for artifact in "$DMG" "$PKG"; do
      xcrun notarytool submit "$artifact" \
        --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" --wait
      xcrun stapler staple "$artifact"
    done
  fi
fi

echo "[build] 完成：$DMG"
echo "[build] 完成：$PKG"