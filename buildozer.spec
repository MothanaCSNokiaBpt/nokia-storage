[app]
title = Nokia Storage
package.name = nokiastorage
package.domain = com.ict18.nokia
source.dir = .
source.include_exts = py,kv,json,png,jpg,jpeg,atlas,xml,gif
source.include_patterns = assets/*
version = 1.0.0

requirements = python3,kivy==2.3.0,plyer,pyjnius,android

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,CAMERA,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES

android.api = 33
android.minapi = 21
android.ndk = 25b
android.sdk = 33
android.accept_sdk_license = True
android.archs = arm64-v8a
android.allow_backup = True

# White presplash - eliminates black flash on startup
presplash.filename = %(source.dir)s/assets/presplash.png
presplash.color = #FFFFFF
icon.filename = %(source.dir)s/assets/icon.png

# White activity theme to prevent black screen before presplash loads
android.whitelist = android.app.NativeActivity
android.manifest.theme = @android:style/Theme.Light.NoTitleBar

[buildozer]
log_level = 2
warn_on_root = 1
