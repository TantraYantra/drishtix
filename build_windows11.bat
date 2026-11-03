@echo off
setlocal
cd /d "%~dp0"

echo [PeopleLens] Checking 64-bit Python 3.11...
py -3.11 -c "import struct,sys; print(sys.version); assert sys.version_info[:2] == (3,11), 'Use Python 3.11 x64 for this release build'; assert struct.calcsize('P')*8 == 64, 'Use 64-bit Python'" || goto :error

echo [PeopleLens] Creating clean build environment...
if not exist .build-venv py -3.11 -m venv .build-venv || goto :error
call .build-venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.txt || goto :error
python -m pip install -r requirements-build.txt || goto :error

echo [PeopleLens] Verifying imports...
python -c "import cv2,numpy,PIL,onnxruntime,uniface; print('OpenCV',cv2.__version__); print('NumPy',numpy.__version__); print('ONNX Runtime',onnxruntime.__version__); print('UniFace',getattr(uniface,'__version__','installed'))" || goto :error

echo [PeopleLens] Running isolated smoke tests...
python tests\smoke_test_database.py || goto :error
python tests\test_matching.py || goto :error
python tests\test_scanner.py || goto :error
python tests\test_ui_smoke.py || goto :error

echo [PeopleLens] Building onedir application...
if exist build rmdir /s /q build
if exist dist\PeopleLens rmdir /s /q dist\PeopleLens
python -m PyInstaller --noconfirm --clean PeopleLens.spec || goto :error

echo [PeopleLens] Packaging release ZIP...
if not exist release mkdir release
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\PeopleLens\*' -DestinationPath 'release\PeopleLens-1.0.0-windows11-x64.zip' -Force" || goto :error

echo [PeopleLens] Packaging clean source ZIP...
call package_source.bat || goto :error

echo.
echo Build complete: dist\PeopleLens\PeopleLens.exe
echo Release archive: release\PeopleLens-1.0.0-windows11-x64.zip
echo Source archive: release\PeopleLens-1.0.0-source.zip
echo Note: run the packaged app and test model download/inference before creating an installer.
goto :eof

:error
echo.
echo BUILD FAILED. Review the error above.
exit /b 1
