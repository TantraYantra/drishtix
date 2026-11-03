# PeopleLens 1.0.0 - Windows 11 x64 build notes

## Release target

- Windows 11 x64
- CPU inference through ONNX Runtime
- PyInstaller one-folder distribution
- First-run model download; no model weights are bundled
- Python 3.11.x x64 (built and tested with Python 3.11.9)

## Prerequisites

1. Windows 11 x64.
2. 64-bit Python 3.11 installed from python.org, with the **py launcher**
   available:
   ```bat
   py -3.11 -c "import struct,sys; print(sys.version); print(struct.calcsize('P')*8)"
   ```
   The output must report Python 3.11 and `64`.
3. Internet access for the first dependency install and first AI model download.
4. Free disk space for `.build-venv`, `build`, `dist`, and `release`. The current
   one-folder application is about 342 MB before ZIP compression.

## Build

Run from this directory:

```bat
build_windows11.bat
```

The script performs a clean, repeatable build:

1. Verifies Python 3.11 x64 through `py -3.11`.
2. Creates `.build-venv` when missing and activates it.
3. Upgrades pip and installs `requirements.txt` plus `requirements-build.txt`.
4. Verifies imports for OpenCV, NumPy, Pillow, ONNX Runtime, and UniFace.
5. Runs the isolated test suite:
   ```bat
   python tests\smoke_test_database.py
   python tests\test_scanner.py
   python tests\test_ui_smoke.py
   ```
6. Removes the previous `build` and `dist\PeopleLens` directories.
7. Builds with `python -m PyInstaller --noconfirm --clean PeopleLens.spec`.
8. Creates `release\PeopleLens-1.0.0-windows11-x64.zip` from
   `dist\PeopleLens\*`.

### Outputs

```text
dist\PeopleLens\PeopleLens.exe
dist\PeopleLens\_internal\
release\PeopleLens-1.0.0-windows11-x64.zip
```

### Source archive

Create a clean source ZIP separately:

```bat
package_source.bat
```

Output:

```text
release\PeopleLens-1.0.0-source.zip
```

The source archive includes application source, UI, assets, tests, build files,
and documentation. It excludes:

- `.venv`, `.build-venv`
- `build`, `dist`, `release`
- `__pycache__`, `*.pyc`
- databases, WAL/SHM files, settings, logs, thumbnails, model caches
- developer-local data and temporary files

## What the spec bundles

`PeopleLens.spec`:

- builds a windowed (`console=False`) `PeopleLens.exe`;
- uses `assets/peoplelens_logo.ico` as the executable icon;
- applies `version_info.txt` (version 1.0.0.0, company TantraYantra);
- collects UniFace, ONNX Runtime, OpenCV, Pillow, and NumPy packages;
- bundles `assets\` and `VERSION` inside `_internal`;
- excludes PyTorch, TorchVision, FAISS, and pytest.

The application is one-folder rather than one-file because OpenCV and ONNX
Runtime include native binaries. A one-folder layout is easier to inspect and
diagnose and avoids one-file extraction behavior.

## Version bump checklist

Before publishing a new version:

1. Update `VERSION`.
2. Update `APP_VERSION` in `app_paths.py`.
3. Update `version_info.txt` (`filevers`, `prodvers`, `FileVersion`,
   `ProductVersion`).
4. Update the output filename in `build_windows11.bat`.
5. Update the version in this file and in `README.md`.
6. Run the full build and manual release checks.

## Model files

UniFace manages the RetinaFace and AdaFace downloads. PeopleLens sets
`UNIFACE_CACHE_DIR` to:

```text
%LOCALAPPDATA%\TantraYantra\PeopleLens\models
```

The first model initialization requires internet access. Later inference is
local. Model files are not included in the source or release archives.

## Automated verification completed for 1.0.0

The following checks passed with Python 3.11.9 on Windows 11 x64:

- Database smoke test: persistence, schema migration, cascades, albums, people,
  favorites, and search.
- Scanner test: 28-file scan, duplicate handling, AI-failure isolation,
  cancellation, and video indexing.
- UI smoke test: every page renders; All Photos shows 28 items; at least 20
  thumbnails load; no Tk callback errors.
- Packaged executable launched with an isolated `LOCALAPPDATA`.
- Splash appeared and the main window opened with the expected title.
- `peoplelens.db` was created under
  `%LOCALAPPDATA%\TantraYantra\PeopleLens`.
- Log contained a clean startup record and no traceback.
- Window closed normally and the process exited.
- Release ZIP contained only `PeopleLens.exe` and `_internal\*`; no development
  database, settings, logs, virtual environments, or build output.
- Executable metadata reported PeopleLens 1.0.0 and TantraYantra.

## Manual release checks

Perform these on a clean Windows 11 x64 account or machine before publishing:

- [ ] Launch the packaged app from a non-development account.
- [ ] Confirm the approved splash, logo, and assets load.
- [ ] Scan a folder containing photos and videos.
- [ ] Confirm photos appear in All Photos and survive a restart.
- [ ] Confirm video thumbnails and playback behavior.
- [ ] Trigger face recognition with internet access and confirm both models
      download.
- [ ] Restart with internet disconnected and confirm cached inference works.
- [ ] Create a person, confirm a match, and exercise Match Review.
- [ ] Create an album, add/remove media, and delete the album without losing
      source files.
- [ ] Exercise Favorites, Archive, Trash, and restore from Trash.
- [ ] Confirm Smart Search and Scan History behave correctly.
- [ ] Confirm data remains under
      `%LOCALAPPDATA%\TantraYantra\PeopleLens`.
- [ ] Confirm no console window appears and errors are understandable.
- [ ] Check Windows SmartScreen behavior; the executable is not code-signed.

Do not call the build production-ready until these checks pass on Windows 11
x64.

## Troubleshooting

### `py -3.11` is not found

Install 64-bit Python 3.11 from python.org and enable the Python Launcher.
Confirm with:

```bat
py -0p
```

### A dependency install fails

Delete `.build-venv`, confirm internet access, and rerun the build. The build
script recreates the environment automatically.

### PyInstaller reports `scipy.special._cdflib` not found

This warning can appear while collecting UniFace dependencies. The current
release was built and smoke-tested with the warning present. Verify the packaged
app launches and face recognition works before publishing.

### The app opens but no photos appear

Check `%LOCALAPPDATA%\TantraYantra\PeopleLens\peoplelens.log`. Use
**Settings → Check database** for an integrity report. Do not delete the
database while diagnosing; back up the whole user-data folder first.

### SmartScreen warns on first launch

The executable is not code-signed. Produce a signed installer before broad
public distribution.

## Release archive audit

The release ZIP should contain only:

```text
PeopleLens.exe
_internal\...
```

It must not contain:

```text
*.db, *.db-wal, *.db-shm
settings.json
*.log
.venv\, .build-venv\
build\, dist\, release\
tests\, __pycache__\
```

Use the following to inspect the archive:

```powershell
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead(
    (Resolve-Path 'release\PeopleLens-1.0.0-windows11-x64.zip')
)
$zip.Entries | Select-Object FullName, Length
$zip.Dispose()
```
