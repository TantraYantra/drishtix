# Changelog

All notable changes to DrishtiX are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
semantic versioning.

## [1.1.0] - 2026-11-04

### Changed

- Renamed the product from PeopleLens to **DrishtiX**. The old name is used by
  an unrelated commercial product and by a Microsoft Research project, so the
  change avoids confusion in search results and in the marketplace.
- On first launch the existing library is copied from
  `%LOCALAPPDATA%\TantraYantra\PeopleLens` into
  `%LOCALAPPDATA%\TantraYantra\DrishtiX`. The old folder is never modified or
  deleted, so the original library remains intact as a backup.
- The installer, executable, Start Menu entry, shortcuts, and download asset are
  now `DrishtiX` and `DrishtiX-Setup.exe`.
- `NOTICE` now names the copyright holders and states the MIT licence for both
  model weight sets, as the MIT licence requires.

### Fixed

- The installer no longer reuses the previous install directory, so upgrading
  from 1.0.0 does not install DrishtiX inside the old PeopleLens folder.

## [1.0.0] - 2026-11-03

First public release.

### Added

- Local-first photo and video library for Windows, with folder scanning and a
  SQLite index that never modifies original files.
- All Photos timeline with month grouping, sorting, category filters, paging,
  favorites, archive, and reversible trash.
- Albums with covers, rename, and add/remove.
- Videos library with first-frame thumbnails and in-app playback.
- Other Photos view for images without a detected face.
- On-device face detection and recognition through UniFace RetinaFace and
  AdaFace IR-18 on ONNX Runtime CPU.
- People profiles and per-person galleries.
- Unassigned Faces with real face crops and one-click naming.
- Instant cross-photo matching from stored face vectors, with no re-index.
- Match Review for confirming suggestions, including bulk confirmation.
- Optional automatic assignment, off by default, with margin-based safety.
- Metadata-aware Smart Search across names, filenames, dates, categories,
  favorites, and media types.
- Scan History, dashboard totals, database integrity check, and local logs.
- Dark, Light, and Ocean themes with a dark native Windows title bar.
- Single-file per-user Windows installer that downloads and verifies the AI
  models during setup, creates shortcuts, and launches the app.

### Security

- No telemetry, no cloud sync, and no photo uploads. The only network request
  is the model download.
- User data stays under `%LOCALAPPDATA%\TantraYantra\DrishtiX` and is not
  removed by uninstalling the app.

### Known limitations

- Windows 11 x64 is the tested target; Windows 10 22H2 may work but is not
  supported.
- Video playback depends on the bundled OpenCV codecs.
- Smart Search is metadata-based, not visual scene recognition.
- The build is not code-signed yet, so Windows SmartScreen may warn on first
  run.
