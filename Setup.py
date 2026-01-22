import os
import shutil
import urllib.request
import zipfile
import subprocess

# AYARLAR
SDK_URL = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
TOOLS_DIR = "tools"
TEMP_DIR = "temp_sdk"

def log(msg):
    print(f">> {msg}")

def setup():
    if not os.path.exists(TEMP_DIR): os.makedirs(TEMP_DIR)
    
    # 1. Command Line Tools İndir
    zip_path = os.path.join(TEMP_DIR, "tools.zip")
    if not os.path.exists(zip_path):
        log("Android SDK araçları indiriliyor (yaklaşık 150MB)...")
        urllib.request.urlretrieve(SDK_URL, zip_path)
    
    # 2. Zipleri aç
    log("Dosyalar çıkartılıyor...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(TEMP_DIR)

    # 3. sdkmanager kullanarak gerekli parçaları çek (sadece ~100MB daha)
    # Not: Bu adım Java'nın kurulu olmasını gerektirir.
    log("Gerekli build-tools ve platform dosyaları indiriliyor...")
    cmd_path = os.path.join(TEMP_DIR, "cmdline-tools", "bin", "sdkmanager.bat")
    # Lisansları kabul et ve indir
    proc = subprocess.Popen([cmd_path, "--sdk_root=" + TEMP_DIR, "build-tools;34.0.0", "platforms;android-34"], 
                            stdin=subprocess.PIPE, text=True)
    proc.communicate(input="y\ny\ny\ny\n") 

    # 4. Sadece ihtiyacımız olanları 'tools' klasörüne kopyala
    if not os.path.exists(TOOLS_DIR): os.makedirs(TOOLS_DIR)
    
    mapping = {
        f"{TEMP_DIR}/build-tools/34.0.0/aapt2.exe": "aapt2.exe",
        f"{TEMP_DIR}/build-tools/34.0.0/d8.bat": "d8.bat",
        f"{TEMP_DIR}/build-tools/34.0.0/lib/d8.jar": "lib/d8.jar", # d8.bat buna ihtiyaç duyar
        f"{TEMP_DIR}/build-tools/34.0.0/zipalign.exe": "zipalign.exe",
        f"{TEMP_DIR}/build-tools/34.0.0/apksigner.bat": "apksigner.bat",
        f"{TEMP_DIR}/build-tools/34.0.0/lib/apksigner.jar": "lib/apksigner.jar",
        f"{TEMP_DIR}/platforms/android-34/android.jar": "android.jar"
    }

    for src, dest in mapping.items():
        dest_path = os.path.join(TOOLS_DIR, dest)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        if os.path.exists(src):
            shutil.copy2(src, dest_path)
            log(f"Kopyalandı: {dest}")

    # 5. Keystore oluştur (Eğer yoksa)
    keystore_path = os.path.join(TOOLS_DIR, "debug.keystore")
    if not os.path.exists(keystore_path):
        log("Debug keystore oluşturuluyor...")
        ks_cmd = [
            "keytool", "-genkey", "-v", "-keystore", keystore_path,
            "-storepass", "android", "-alias", "androiddebugkey",
            "-keypass", "android", "-keyalg", "RSA", "-keysize", "2048",
            "-validity", "10000", "-dname", "CN=Android Debug,O=Android,C=US"
        ]
        try:
            subprocess.run(ks_cmd, check=True)
        except:
            log("Uyarı: keytool bulunamadı, keystore manuel oluşturulmalı.")

    # Temizlik
    # shutil.rmtree(TEMP_DIR) 
    log("\nKURULUM TAMAMLANDI!")
    log(f"Artık '{TOOLS_DIR}' klasörün hazır.")

if __name__ == "__main__":
    setup()