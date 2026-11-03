# PeopleLens 1.0.0

**Your Photos. Your People. Your Memories.**

[**Download for Windows**](https://github.com/TantraYantra/peoplelens/releases/latest/download/PeopleLens-Setup.exe) · [Website](https://tantrayantra.github.io/tantrayantra-website/) · [Releases](https://github.com/TantraYantra/peoplelens/releases) · [MIT licensed](LICENSE)

PeopleLens is a local-first Windows desktop photo library with on-device face
detection and recognition. It indexes photos and videos already on your PC,
builds a searchable library, and helps you group faces into named people.
Original media stays in its existing folders and is never uploaded.

A product by **TantraYantra**.

---

## Install

1. Download **`PeopleLens-Setup.exe`** using the link above.
2. Run it. No administrator password is required.
3. When setup finishes, PeopleLens opens from the Start Menu or the Desktop
   shortcut.

One file installs everything. Setup also downloads the two AI models (about
104 MB) and verifies their checksums, so the first face scan works immediately.
Photos are indexed from folders you already have; nothing is uploaded.

> Windows SmartScreen may warn because the 1.0.0 installer is not code-signed
> yet. Choose **More info → Run anyway** to continue. Every release also ships
> `SHA256SUMS.txt` for verification.

Requirements: Windows 11 x64 (Windows 10 22H2 may work but is not supported),
about 450 MB of disk space, and an internet connection for the one-time model
download.

---

## Highlights

### Library
- Scan one or more folders for JPG, JPEG, PNG, BMP, TIF, TIFF, WEBP, MP4, MOV,
  M4V, AVI, MKV, WMV, and WEBM files.
- **All Photos** timeline with month grouping, paging, sorting, category filters,
  and background thumbnail loading.
- Disk-backed thumbnail cache, so revisiting the library is fast.
- **Videos** library with first-frame thumbnails, duration metadata, and in-app
  playback when the installed OpenCV decoder supports the codec.
- **Favorites**, **Archive**, and **Trash**. Trash is a reversible in-app action;
  it does not delete the original file from disk.
- **Albums** with create, rename, delete, add/remove items, and cover selection.
  Deleting an album never deletes source media.
- **Other Photos** for images where no face was detected.

### People and recognition
- UniFace **RetinaFace** detection and **AdaFace IR-18** recognition on CPU
  through ONNX Runtime.
- Named people, per-person galleries, unassigned faces, and Match Review.
- Instant cross-photo matching: naming one face compares the face vectors that
  were already stored during the scan, so the rest of the library is checked in
  milliseconds without re-reading a single photo.
- Match Review can confirm one suggestion at a time or all remaining
  suggestions in a single step.
- Optional automatic assignment, disabled by default. Only strong, clearly
  separated matches are auto-assigned.
- Adjustable review and auto-assignment thresholds in Settings.
- AI reindex command for libraries created by older builds, or for photos that
  were indexed before the AI models were available.

### Organisation and diagnostics
- Metadata-aware **Smart Search** across filenames, people, dates, categories,
  favorites, and media types.
- **Scan History** with completed, cancelled, and failed scans.
- Dashboard totals for media, people, faces, favorites, and library size.
- Settings for theme, recognition thresholds, and data tools.
- Database integrity check, data-folder shortcut, and log-file shortcut.
- Rotating local log file and visible error dialogs for troubleshooting.

---

## Platform and requirements

- **Windows 11 x64** is the supported release target. Windows 10 22H2 may work
  but is not supported for 1.0.0.
- **Python 3.11.x 64-bit** is required for source runs and release builds.
  The release was built and tested with **Python 3.11.9**.
- The installer downloads the RetinaFace and AdaFace model weights (about
  104 MB combined) and verifies their SHA-256 checksums. After the models are
  cached, inference runs offline. If the download is skipped or fails, the app
  retries on first face-recognition use.
- CPU inference is used. No NVIDIA GPU or CUDA installation is required.
- No console window is shown in the packaged application.

---

## Run from source

From this folder:

```bat
py -3.11 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

Alternatively, run `run_windows.bat`, which creates `.venv` with `py -3.11` when
needed, installs the runtime requirements, and starts the app.

The first AI initialization downloads the models into:

```text
%LOCALAPPDATA%\TantraYantra\PeopleLens\models
```

---

## Tests

The repository includes four isolated test scripts. They use temporary
databases and a temporary `LOCALAPPDATA`; they do not modify a real user
library.

```bat
python tests\smoke_test_database.py
python tests\test_scanner.py
python tests\test_matching.py
python tests\test_ui_smoke.py
```

- `smoke_test_database.py` covers persistence, schema migration, cascades,
  albums, people, favorites, and search.
- `test_scanner.py` covers a real 28-file scan, duplicate handling, AI-failure
  isolation, cancellation, and video indexing.
- `test_matching.py` covers instant vector matching, threshold behaviour, and
  bulk Match Review logic.
- `test_ui_smoke.py` builds the full Tk interface, visits every page, and checks
  that the All Photos grid renders and thumbnails load. It requires a desktop
  session.

`build_windows11.bat` runs the database, scanner, and UI tests before packaging.
GitHub Actions runs the database, scanner, and matching tests.

---

## Build the Windows 11 release

### Prerequisites
- Windows 11 x64.
- 64-bit **Python 3.11** installed with the `py` launcher available.
- Internet access for the first dependency/model download.
- Enough disk space for the build environment and the roughly 342 MB
  one-folder application.

### One command

```bat
build_windows11.bat
```

The script:

1. Verifies 64-bit Python 3.11 through `py -3.11`.
2. Creates an isolated `.build-venv`.
3. Installs pinned runtime requirements and PyInstaller.
4. Verifies OpenCV, NumPy, Pillow, ONNX Runtime, and UniFace imports.
5. Runs the three isolated test scripts.
6. Cleans `build` and `dist\PeopleLens`.
7. Builds the PyInstaller one-folder application.
8. Creates `release\PeopleLens-1.0.0-windows11-x64.zip`.

### Outputs

```text
dist\PeopleLens\PeopleLens.exe
release\PeopleLens-1.0.0-windows11-x64.zip
release\PeopleLens-Setup.exe              (after compiling the installer)
release\PeopleLens-1.0.0-source.zip       (after package_source.bat)
```

Compile the single-file installer after the app build:

```bat
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\PeopleLens.iss
```

The installer is per-user and does not need administrator rights. See
`installer\README.md` for model URLs, signing, and silent-install details.

Create the clean source archive separately:

```bat
package_source.bat
```

The source archive excludes virtual environments, build output, release output,
caches, logs, and all user databases/settings.

See `BUILD_WINDOWS11.md` for packaging details, manual release checks, and
troubleshooting.

---

## Application data and privacy

PeopleLens separates bundled application files from mutable user data.

- Installed assets live beside the executable inside `_internal\assets`.
- User data lives under:

```text
%LOCALAPPDATA%\TantraYantra\PeopleLens
```

Contents include:

```text
peoplelens.db        library database
settings.json        appearance and recognition settings
thumbnails\          cached photo thumbnails
video_thumbnails\    cached video first frames
models\              downloaded ONNX face models
backups\             pre-migration database backups
peoplelens.log       rotating diagnostic log
```

- Original photos and videos are not copied into the application folder.
- The app stores paths, metadata, face boxes, and local embeddings.
- Nothing is uploaded to TantraYantra as part of normal library, recognition, or
  search workflows.
- A database migration creates a backup before changing the schema.
- Legacy project-local `data\peoplelens.db`, `data\settings.json`, and video
  thumbnails are copied into the new location only when the destination file
  does not already exist. Existing user data is never overwritten.
- Release archives exclude databases, settings, logs, thumbnails, model caches,
  and developer paths.

To move or back up a library, close PeopleLens and copy the entire
`%LOCALAPPDATA%\TantraYantra\PeopleLens` folder.

---

## Upgrading an existing library

1. Close PeopleLens.
2. Back up `%LOCALAPPDATA%\TantraYantra\PeopleLens`.
3. Replace the application folder with the new build. Do not replace or delete
   your user-data folder.
4. Start PeopleLens. Schema changes are applied automatically with a safety
   backup.
5. If the library predates the current AdaFace embedding format, open
   **Settings → Rebuild AI face index** and review the results.

Confirmed person links are preserved where old and new face boxes overlap
sufficiently. Uncertain mappings remain unassigned for review.

---

## Recognition behavior and limitations

- Face recognition produces similarity scores, not identity verification.
  Review matches visually before relying on them.
- Accuracy varies with image quality, lighting, pose, age, occlusion, and the
  diversity of the training data. Demographic performance can differ.
- Automatic assignment is off by default. Keep the automatic threshold high
  until results are trusted.
- Naming a face never re-reads your photos. It compares the 512-dimensional
  vectors stored during the scan, so the result appears immediately. A rebuild
  is only needed when photos were indexed before the recognition models were
  available, because no vectors exist for those photos yet.
- When one face has suggestions for two people, the strongest score wins and
  the others are marked rejected. Faces you assigned by hand are never moved
  by bulk confirmation.
- **Other Photos** means no face was detected. It does not prove that no person
  is present.
- Smart Search is metadata-aware. It does not perform visual semantic scene
  recognition, so it cannot find "beach" or "sunset" unless that information is
  present in a filename, person name, date, category, or media type.
- Video playback depends on the codecs available in the bundled OpenCV build.
  Indexing and first-frame thumbnails may still work when playback does not.
- Trash is a reversible in-app state and does not remove files from disk.
- PeopleLens 1.0.0 does not edit images, create memory movies, detect duplicates,
  or provide cloud sync.
- The executable is not code-signed. Windows SmartScreen may show a warning on
  first launch until a signed installer is produced.

---

## AI models and licensing

- Detection: **RetinaFace** (face boxes and five-point alignment landmarks).
- Recognition: **AdaFace IR-18**, producing 512-dimensional embeddings.
- Runtime: **ONNX Runtime CPU** through **UniFace 4.2.1**.

UniFace source code is MIT-licensed. Its model-credit page lists AdaFace code
and weights as MIT and RetinaFace weights as following their upstream source.
Model training datasets can carry separate terms, and the UniFace maintainers
recommend independent diligence for commercial deployment. This notice is not
legal clearance for every jurisdiction or business use.

Model weights are downloaded on first use and are not bundled in the source
archive or release ZIP. Review upstream model terms before commercial
distribution.

---

## Project structure

```text
main.py                 startup, DPI awareness, splash, error handling
app_paths.py            user-data paths, settings, legacy migration
core/
  scanner.py            media scan, hashing, thumbnails, AI isolation
  recognition.py        UniFace detector/recognizer integration
  thumbnails.py         thumbnail cache and face crops
  logging_setup.py      rotating file logging
database/
  db.py                 SQLite schema, migrations, queries, integrity checks
ui/
  app.py                application shell and all pages
  theme.py              Dark, Light, and Ocean palettes and ttk styles
  widgets.py            paged photo grid, async images, cards, search box
assets/                 official PeopleLens logos, icons, and approved splash
tests/                  isolated database, scanner, and UI smoke tests
PeopleLens.spec         PyInstaller one-folder build definition
build_windows11.bat     clean build + tests + release ZIP
package_source.bat      clean source ZIP
version_info.txt        Windows executable version metadata
VERSION                 application version (1.0.0)
```

---

## Troubleshooting

**The app does not start.** Open
`%LOCALAPPDATA%\TantraYantra\PeopleLens\peoplelens.log` for the traceback. A
startup error dialog also points to this file.

**Model download fails.** Check internet access, then retry face recognition.
The cache is under `%LOCALAPPDATA%\TantraYantra\PeopleLens\models`. Delete the
cache only if you want to force a fresh download.

**A video will not play.** The codec may not be supported by the bundled OpenCV
build. The file can still be indexed and shown with a first-frame thumbnail.

**The database check reports a problem.** Close the app, copy the entire user
data folder for safekeeping, and open the log. Do not delete the database while
diagnosing; it contains library metadata and person links.

**Build reports a missing `scipy.special._cdflib` hidden import.** PyInstaller
can emit this warning while collecting UniFace dependencies. The packaged
application has been smoke-tested with this warning present. Confirm the app
launches and face recognition works before publishing.

---

## License

The source code is released under the [MIT License](LICENSE). The TantraYantra
and PeopleLens names, logos, and icons are brand assets and are not covered by
the MIT License; see [TRADEMARK.md](TRADEMARK.md).

Third-party components and AI model terms are listed in [NOTICE](NOTICE). The
model weights are not distributed in this repository or in the installer; they
are downloaded from their upstream projects and verified by SHA-256.

---

## Attribution

PeopleLens is a product by **TantraYantra**.

Built with Python, Tk/ttk, Pillow, OpenCV, SQLite, ONNX Runtime, and UniFace.
