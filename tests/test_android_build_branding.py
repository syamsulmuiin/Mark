from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_android_app_title_is_companion():
    strings=(ROOT/"android-companion/app/src/main/res/values/strings.xml").read_text()
    manifest=(ROOT/"android-companion/app/src/main/AndroidManifest.xml").read_text()
    assert '<string name="app_name">Companion</string>' in strings
    assert 'android:label="@string/app_name"' in manifest

def test_android_launcher_icon_is_explicit():
    manifest=(ROOT/"android-companion/app/src/main/AndroidManifest.xml").read_text()
    assert 'android:icon="@mipmap/ic_launcher"' in manifest
    assert 'android:roundIcon="@mipmap/ic_launcher_round"' in manifest
    assert (ROOT/"android-companion/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml").is_file()
    assert (ROOT/"android-companion/app/src/main/res/drawable/ic_launcher_foreground.xml").is_file()

def test_android_build_stack_is_single_and_current():
    top=(ROOT/"android-companion/build.gradle.kts").read_text()
    app=(ROOT/"android-companion/app/build.gradle.kts").read_text()
    workflow=(ROOT/".github/workflows/build-android.yml").read_text()
    assert 'com.android.application") version "9.0.1"' in top
    assert 'org.jetbrains.kotlin.android' not in top
    assert 'org.jetbrains.kotlin.android' not in app
    assert workflow.count("gradle-version: '9.1.0'") == 2
    assert "gradle-version: '8.10.2'" not in workflow
    assert "        with:\n          gradle-version: '9.1.0'\n          cache-read-only: true" in workflow

def test_android_artifact_names_use_companion():
    workflow=(ROOT/".github/workflows/build-android.yml").read_text()
    assert "name: Companion-debug" in workflow
    assert "name: Companion-release-signed" in workflow
    assert "jarvis-companion-debug" not in workflow
