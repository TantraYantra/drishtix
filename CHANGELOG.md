# Changelog

All notable changes to PeopleLens are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
semantic versioning.

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
- User data stays under `%LOCALAPPDATA%\TantraYantra\PeopleLens` and is not
  removed by uninstalling the app.

### Known limitations

- Windows 11 x64 is the tested target; Windows 10 22H2 may work but is not
  supported.
- Video playback depends on the bundled OpenCV codecs.
- Smart Search is metadata-based, not visual scene recognition.
- The build is not code-signed yet, so Windows SmartScreen may warn on first
  run.
