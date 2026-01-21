import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass

# ============================================================
#    GENEL LOG SİSTEMİ
# ============================================================

def log_info(msg: str):
    print(f"[INFO] {msg}")

def log_step(step: str):
    print(f"\n=== {step} ===")

def log_error(msg: str):
    print(f"[ERROR] {msg}")

def abort(msg: str):
    log_error(msg)
    sys.exit(1)

# ============================================================
#    KOMUT ÇALIŞTIRICI
# ============================================================

def run(cmd: list, cwd=None, desc="Komut"):
    cmd_str = " ".join(cmd)
    log_info(f"Çalıştırılıyor: {cmd_str}")
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
    except FileNotFoundError:
        abort(f"Gerekli araç bulunamadı: {cmd[0]}")
    except subprocess.CalledProcessError as e:
        abort(f"{desc} başarısız oldu (exit={e.returncode})")

# ============================================================
#    KONFİG
# ============================================================

@dataclass
class BuildConfig:
    input_dir: str
    tools_dir: str
    android_jar: str

    @property
    def build_dir(self):
        return os.path.join(self.input_dir, "build")

    @property
    def output_dir(self):
        return os.path.dirname(os.path.abspath(self.input_dir))

    @property
    def final_apk_path(self):
        name = os.path.basename(self.input_dir) + "_signed.apk"
        return os.path.join(self.output_dir, name)

# ============================================================
#    DERLEYİCİ
# ============================================================

class ApkBuilder:

    def __init__(self, config: BuildConfig):
        self.cfg = config
        self.aapt2 = os.path.join(config.tools_dir, "aapt2.exe")
        self.d8 = os.path.join(config.tools_dir, "d8.bat")
        self.zipalign_path = os.path.join(config.tools_dir, "zipalign.exe")
        self.apksigner = os.path.join(config.tools_dir, "apksigner.bat")
        self.keystore = os.path.join(config.tools_dir, "debug.keystore")
        self.library_jars = self._load_libraries()
        self._validate()

    def _load_libraries(self):
        lib_file = os.path.join(self.cfg.input_dir, "library.lib")
        libs = []
        if os.path.isfile(lib_file):
            log_step("library.lib Okunuyor")
            with open(lib_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        if not os.path.isfile(line):
                            abort(f"library.lib içindeki JAR bulunamadı: {line}")
                        libs.append(os.path.abspath(line))
                        log_info(f"Eklenen kütüphane: {line}")
        return libs

    def _validate(self):
        req = {
            self.aapt2: "aapt2.exe",
            self.d8: "d8.bat",
            self.zipalign_path: "zipalign.exe",
            self.apksigner: "apksigner.bat",
            self.keystore: "debug.keystore",
            self.cfg.android_jar: "android.jar"
        }
        for path, name in req.items():
            if not os.path.isfile(path):
                abort(f"Araç eksik: {name} [{path}]")

    def clean(self):
        log_step("1) Temizleme")
        shutil.rmtree(self.cfg.build_dir, ignore_errors=True)
        os.makedirs(self.cfg.build_dir)

    def compile_resources(self):
        log_step("2) Kaynak Derleme (aapt2 compile)")
        res_dir = os.path.join(self.cfg.input_dir, "res")
        out_zip = os.path.join(self.cfg.build_dir, "res.zip")
        if not os.path.isdir(res_dir):
            abort(f"res klasörü yok: {res_dir}")
        run([self.aapt2, "compile", "--dir", res_dir, "-o", out_zip])

    def link_resources(self):
        log_step("3) Manifest + Kaynak Birleştirme (aapt2 link)")
        manifest = os.path.join(self.cfg.input_dir, "AndroidManifest.xml")
        res_zip = os.path.join(self.cfg.build_dir, "res.zip")
        java_out = os.path.join(self.cfg.build_dir, "java_out")
        base_apk = os.path.join(self.cfg.build_dir, "base.apk")
        os.makedirs(java_out, exist_ok=True)
        run([
            self.aapt2, "link",
            "-o", base_apk,
            "-I", self.cfg.android_jar,
            "--manifest", manifest,
            "-R", res_zip,
            "--java", java_out,
            "--auto-add-overlay"
        ])

    def compile_java(self):
        log_step("4) Java Derleme (javac)")
        src_dir = os.path.join(self.cfg.input_dir, "java")
        class_dir = os.path.join(self.cfg.build_dir, "classes")
        r_dir = os.path.join(self.cfg.build_dir, "java_out")
        java_files = []
        for root, _, files in os.walk(src_dir):
            for f in files:
                if f.endswith(".java"):
                    java_files.append(os.path.join(root, f))
        if not java_files:
            abort("Java dosyası bulunamadı.")
        os.makedirs(class_dir, exist_ok=True)
        cp_elements = [self.cfg.android_jar, r_dir] + self.library_jars
        combined_cp = os.pathsep.join(cp_elements)
        
        try:
            cmd_str = f'javac -encoding UTF-8 -source 8 -target 8 -classpath "{combined_cp}" -d "{class_dir}" ' + ' '.join([f'"{f}"' for f in java_files])
            subprocess.run(cmd_str, check=True, shell=True)
        except subprocess.CalledProcessError as e:
            abort(f"javac hatası! Kod: {e.returncode}")

    def jar_classes(self):
        log_step("5) classes.jar oluşturma")
        class_dir = os.path.join(self.cfg.build_dir, "classes")
        jar_path = os.path.join(self.cfg.build_dir, "classes.jar")
        run(["jar", "cf", jar_path, "-C", class_dir, "."])
        return jar_path

    def dex(self, jar_path):
        log_step("6) DEX Oluşturma")
        out = self.cfg.build_dir
        run([self.d8, jar_path, *self.library_jars, "--output", out, "--min-api", "21"])

    def merge_dex(self):
        log_step("7) DEX dosyalarını APK’ya ekleme")
        base = os.path.join(self.cfg.build_dir, "base.apk")
        dex_files = [f for f in os.listdir(self.cfg.build_dir) if f.endswith(".dex")]
        with zipfile.ZipFile(base, 'a') as z:
            for dex in dex_files:
                z.write(os.path.join(self.cfg.build_dir, dex), dex)
                log_info(f"DEX eklendi: {dex}")

    def add_assets(self):
        log_step("8) Assets ekleme")
        base = os.path.join(self.cfg.build_dir, "base.apk")
        assets_dir = os.path.join(self.cfg.input_dir, "assets")
        if not os.path.isdir(assets_dir):
            log_info("Assets yok, atlanıyor.")
            return
        with zipfile.ZipFile(base, 'a') as z:
            for root, _, files in os.walk(assets_dir):
                for f in files:
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, assets_dir)
                    # Android içinde yol her zaman '/' olmalıdır
                    apk_path = "assets/" + rel_path.replace(os.sep, '/')
                    z.write(full_path, apk_path)
                    log_info(f"Asset eklendi: {apk_path}")

    def zipalign(self):
        log_step("9) Zipalign")
        base = os.path.join(self.cfg.build_dir, "base.apk")
        aligned = os.path.join(self.cfg.build_dir, "aligned.apk")
        run([self.zipalign_path, "-f", "4", base, aligned])

    def sign(self):
        log_step("10) İmzalama")
        aligned = os.path.join(self.cfg.build_dir, "aligned.apk")
        run([
            self.apksigner, "sign", "--ks", self.keystore,
            "--ks-pass", "pass:android", "--key-pass", "pass:android",
            "--out", self.cfg.final_apk_path, aligned
        ])

    def build(self):
        self.clean()
        self.compile_resources()
        self.link_resources()
        self.compile_java()
        jar = self.jar_classes()
        self.dex(jar)
        self.merge_dex()
        self.add_assets() # Zipalign'dan ÖNCE eklenmeli!
        self.zipalign()
        self.sign()
        log_info(f"BİTTİ: {self.cfg.final_apk_path}")

def main():
    if len(sys.argv) < 2: abort("Kullanım: python ApkBuilder.py <AppFolder>")
    app_dir = sys.argv[1]
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    config = BuildConfig(
        input_dir=app_dir,
        tools_dir=os.path.join(script_dir, "tools"),
        android_jar=r"D:\androidStudyo\SDK\platforms\android-36\android.jar"
    )
    ApkBuilder(config).build()

if __name__ == "__main__":
    main()