#!/usr/bin/env bash
# Сборка APK «Цифровой механик» (приложение-оболочка) без Gradle: только инструменты Android SDK и JDK.
#
# Запуск из Git Bash:  bash android/build.sh
# Нужны: Android SDK (build-tools и platforms) и JDK 11 или новее.
#   ANDROID_SDK_ROOT — папка SDK, по умолчанию %LOCALAPPDATA%/Android/Sdk
#   JAVA_HOME        — папка JDK
# Подпись: android/keystore/release.jks и android/keystore/keystore.properties (в Git не входят).
# При первом запуске ключ создаётся сам. Сохраните папку keystore: без того же ключа
# телефон не поставит новую версию поверх старой.
#
# Результат: android/out/digital-mechanic-<версия>.apk и копия для сайта
# в frontend/public/app/digital-mechanic.apk.
set -euo pipefail

VERSION_NAME="0.1"
VERSION_CODE="1"
MIN_SDK=24
# 34, а не 35: с 35 Android рисует окно под системными панелями, сайту это мешало бы
TARGET_SDK=34
PLATFORM=android-35
BUILD_TOOLS=35.0.0

# В Git Bash нужен путь вида E:/...: javac и d8 не понимают /e/...
HERE="$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))"
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$LOCALAPPDATA/Android/Sdk}}"
BT="$SDK/build-tools/$BUILD_TOOLS"
# d8 и apksigner запускаются через java напрямую: их .bat-обёртки из Git Bash не стартуют
JAR="$SDK/platforms/$PLATFORM/android.jar"
: "${JAVA_HOME:?Укажите JAVA_HOME: папку JDK 11 или новее}"
export PATH="$JAVA_HOME/bin:$PATH"

OUT="$HERE/out"
KS_DIR="$HERE/keystore"
KS="$KS_DIR/release.jks"
KS_PROPS="$KS_DIR/keystore.properties"
APK="$OUT/digital-mechanic-$VERSION_NAME.apk"

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex" "$KS_DIR"

echo "1/6 ресурсы"
"$BT/aapt2" compile --dir "$HERE/res" -o "$OUT/res.zip"
"$BT/aapt2" link -o "$OUT/unsigned.apk" -I "$JAR" \
  --manifest "$HERE/AndroidManifest.xml" --java "$OUT/gen" \
  --min-sdk-version "$MIN_SDK" --target-sdk-version "$TARGET_SDK" \
  --version-code "$VERSION_CODE" --version-name "$VERSION_NAME" \
  "$OUT/res.zip"

echo "2/6 код"
find "$HERE/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
javac -encoding UTF-8 -source 11 -target 11 -Xlint:-options -nowarn \
  -classpath "$JAR" -d "$OUT/classes" @"$OUT/sources.txt"

echo "3/6 dex"
find "$OUT/classes" -name '*.class' > "$OUT/classes.txt"
java -cp "$BT/lib/d8.jar" com.android.tools.r8.D8 --release --min-api "$MIN_SDK" --lib "$JAR" --output "$OUT/dex" @"$OUT/classes.txt"
(cd "$OUT/dex" && jar uf "$OUT/unsigned.apk" classes.dex)

echo "4/6 выравнивание"
"$BT/zipalign" -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

echo "5/6 подпись"
if [ ! -f "$KS" ]; then
  PASS="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
  printf 'storePassword=%s\nkeyAlias=digital-mechanic\n' "$PASS" > "$KS_PROPS"
  keytool -genkeypair -keystore "$KS" -storepass "$PASS" -keypass "$PASS" \
    -alias digital-mechanic -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Digital Mechanic, O=Digital Mechanic" >/dev/null 2>&1
  echo "    создан новый ключ подписи: $KS (сохраните папку keystore)"
fi
PASS="$(grep '^storePassword=' "$KS_PROPS" | cut -d= -f2-)"
ALIAS="$(grep '^keyAlias=' "$KS_PROPS" | cut -d= -f2-)"
java -jar "$BT/lib/apksigner.jar" sign --ks "$KS" --ks-key-alias "$ALIAS" \
  --ks-pass "pass:$PASS" --key-pass "pass:$PASS" --out "$APK" "$OUT/aligned.apk"

echo "6/6 проверка"
java -jar "$BT/lib/apksigner.jar" verify "$APK"
"$BT/aapt2" dump badging "$APK" | grep -E "^package:|^sdkVersion|^targetSdkVersion|^application-label:" || true

mkdir -p "$HERE/../frontend/public/app"
cp "$APK" "$HERE/../frontend/public/app/digital-mechanic.apk"
ls -l "$APK"
echo "готово: $APK"
