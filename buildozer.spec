[app]
title = Nokia Storage
package.name = nokiastorage
package.domain = com.ict18.nokia
source.dir = .
source.include_exts = py,kv,json,png,jpg,jpeg,atlas,xml
source.include_patterns = assets/*
version = 1.0.0

requirements = python3,kivy==2.3.0,plyer,pyjnius,android

orientation = portrait
fullscreen = 0

# Android permissions
android.permissions = INTERNET,CAMERA,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES

android.api = 33
android.minapi = 21
android.ndk = 25b
android.sdk = 33
android.accept_sdk_license = True
android.archs = arm64-v8a
android.allow_backup = True
android.enable_androidx = True

# FileProvider for camera and sharing
android.meta_data = android.support.FILE_PROVIDER_PATHS=filepaths.xml
android.add_src = fileprovider_src/

presplash.filename = %(source.dir)s/assets/presplash.png
icon.filename = %(source.dir)s/assets/icon.png


[buildozer]
log_level = 2
warn_on_root = 1
