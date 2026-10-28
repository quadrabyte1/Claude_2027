#!/bin/bash
# Builds ~/Applications/Boundary Editor.app from BoundaryEditor.applescript, declares the .egm
# document type, registers it with Launch Services and (if possible) makes it the default for .egm.
# Re-runnable.  The app lives on the BOOT volume (/Volumes/GIT is nosuid; launchd can't run scripts there).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Boundary Editor"
APP="$HOME/Applications/$APP_NAME.app"
BUNDLE_ID="com.thomas.boundaryeditor"
UTI="com.thomas.egm"
EXT="egm"
PLIST="$APP/Contents/Info.plist"
PB=/usr/libexec/PlistBuddy
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister

mkdir -p "$HOME/Applications"
rm -rf "$APP"
osacompile -o "$APP" "$HERE/BoundaryEditor.applescript"

$PB -c "Set :CFBundleIdentifier $BUNDLE_ID" "$PLIST" 2>/dev/null || $PB -c "Add :CFBundleIdentifier string $BUNDLE_ID" "$PLIST"
$PB -c "Delete :CFBundleDocumentTypes" "$PLIST" 2>/dev/null || true
$PB -c "Delete :UTExportedTypeDeclarations" "$PLIST" 2>/dev/null || true
$PB -c "Add :CFBundleDocumentTypes array" \
    -c "Add :CFBundleDocumentTypes:0 dict" \
    -c "Add :CFBundleDocumentTypes:0:CFBundleTypeName string 'Elite Golf Moments EGM'" \
    -c "Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Editor" \
    -c "Add :CFBundleDocumentTypes:0:LSHandlerRank string Owner" \
    -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes array" \
    -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes:0 string $UTI" \
    -c "Add :UTExportedTypeDeclarations array" \
    -c "Add :UTExportedTypeDeclarations:0 dict" \
    -c "Add :UTExportedTypeDeclarations:0:UTTypeIdentifier string $UTI" \
    -c "Add :UTExportedTypeDeclarations:0:UTTypeDescription string 'Elite Golf Moments EGM project'" \
    -c "Add :UTExportedTypeDeclarations:0:UTTypeConformsTo array" \
    -c "Add :UTExportedTypeDeclarations:0:UTTypeConformsTo:0 string public.data" \
    -c "Add :UTExportedTypeDeclarations:0:UTTypeTagSpecification dict" \
    -c "Add :UTExportedTypeDeclarations:0:UTTypeTagSpecification:public.filename-extension array" \
    -c "Add :UTExportedTypeDeclarations:0:UTTypeTagSpecification:public.filename-extension:0 string $EXT" \
    "$PLIST" || echo "(PlistBuddy exited non-zero after writing; verifying below)"
plutil -lint "$PLIST"
$PB -c "Print :UTExportedTypeDeclarations:0:UTTypeIdentifier" "$PLIST" | grep -qx "$UTI"

codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
"$LSREGISTER" -f -R -trusted "$APP"

# Default handler: duti if present, else LSSetDefaultRoleHandlerForContentType via swift.
if command -v duti >/dev/null 2>&1; then
  duti -s "$BUNDLE_ID" "$UTI" all && echo "default handler set via duti"
elif command -v swift >/dev/null 2>&1; then
  swift -e "import CoreServices; import Foundation; let r = LSSetDefaultRoleHandlerForContentType(\"$UTI\" as NSString as CFString, LSRolesMask.all, \"$BUNDLE_ID\" as NSString as CFString); print(\"LSSetDefault status:\", r)" \
    || echo "swift default-handler call failed"
else
  echo "No duti/swift: set manually via Get Info > Open With > Change All"
fi
echo "Installed $APP"
