plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }

val assistantPublicUrl = (System.getenv("ASSISTANT_PUBLIC_URL") ?: "https://auth.kasirdigital.web.id").trimEnd('/')
val releaseStorePath = System.getenv("ASSISTANT_KEYSTORE_PATH")
val releaseStorePassword = System.getenv("ASSISTANT_KEYSTORE_PASSWORD")
val releaseKeyAlias = System.getenv("ASSISTANT_KEY_ALIAS")
val releaseKeyPassword = System.getenv("ASSISTANT_KEY_PASSWORD")
val releaseSigningReady = listOf(
    releaseStorePath, releaseStorePassword, releaseKeyAlias, releaseKeyPassword
).all { !it.isNullOrBlank() }

android {
    namespace = "com.jarvis.companion"
    compileSdk = 35

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    defaultConfig {
        applicationId = "com.jarvis.companion"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        buildConfigField("String", "ASSISTANT_PUBLIC_URL", "\"${assistantPublicUrl}\"")
    }

    buildFeatures { buildConfig = true }

    signingConfigs {
        if (releaseSigningReady) {
            create("release") {
                storeFile = file(releaseStorePath!!)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            if (releaseSigningReady) signingConfig = signingConfigs.getByName("release")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.bouncycastle:bcprov-jdk18on:1.79")
}
