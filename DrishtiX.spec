# PyInstaller onedir build for Windows 11 x64. Run from this directory:
#   pyinstaller --noconfirm --clean DrishtiX.spec
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = [
    "PIL._tkinter_finder",
    "cv2",
    "onnxruntime",
    "onnxruntime.capi.onnxruntime_pybind11_state",
]
for package in ("uniface", "onnxruntime", "cv2", "PIL", "numpy"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
hiddenimports += collect_submodules("uniface")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas + [("assets", "assets"), ("VERSION", "."), ("NOTICE", "."), ("LICENSE", ".")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "torchvision", "faiss", "pytest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="DrishtiX",
    debug=False, bootloader_ignore_signals=False, strip=False,
    upx=False, console=False, disable_windowed_traceback=False,
    icon="assets/drishtix_logo.ico",
    version="version_info.txt",
)
coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=False,
    name="DrishtiX",
)
