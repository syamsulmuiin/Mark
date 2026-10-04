# Cloud build + signed Release APK

The release keystore is intentionally **not stored in this repository**. Keep one permanent keystore and put only its Base64 representation/passwords in GitHub Actions Secrets. Losing this keystore means future APKs cannot update an app installed with the old signing identity.

## 1. Create the keystore once

Run this on any machine with a JDK (this is lightweight; Android Studio is not required):

```bash
keytool -genkeypair -v -keystore jarvis-release.jks -alias jarvis -keyalg RSA -keysize 4096 -validity 10000
```

Keep `jarvis-release.jks` somewhere backed up and private.

## 2. Convert it to Base64

Windows PowerShell:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("jarvis-release.jks")) | Set-Content -NoNewline keystore-base64.txt
```

Linux/macOS:

```bash
base64 -w 0 jarvis-release.jks > keystore-base64.txt
```

(macOS may use `base64 < jarvis-release.jks | tr -d '\n'`.)

## 3. Add GitHub Actions secrets

Repository -> Settings -> Secrets and variables -> Actions -> New repository secret:

- `ANDROID_KEYSTORE_BASE64` = contents of `keystore-base64.txt`
- `ANDROID_KEYSTORE_PASSWORD` = keystore password
- `ANDROID_KEY_ALIAS` = `jarvis` (or the alias you chose)
- `ANDROID_KEY_PASSWORD` = key password

Do not commit the `.jks`, the Base64 text, or any password.

## 4. Optional protection

Repository -> Settings -> Environments -> create `android-release`. The release job uses this environment, so GitHub can require approval before a signed build if desired.

## 5. Build in the cloud

GitHub -> Actions -> **Build Android Companion** -> **Run workflow**.

The workflow creates two artifacts:

- `jarvis-companion-debug`
- `jarvis-companion-release-signed`

The release job restores the keystore only inside the temporary GitHub runner, builds `assembleRelease`, verifies the APK with `apksigner`, then uploads the signed APK. The temporary runner is discarded afterward.
