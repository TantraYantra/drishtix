# Windows installer

`PeopleLens.iss` builds the single-file, per-user installer published on the
TantraYantra website.

## What it does

- Installs to `%LOCALAPPDATA%\Programs\PeopleLens` without an admin prompt.
- Adds a Start Menu entry and, by default, a Desktop shortcut.
- Offers to launch PeopleLens when setup finishes.
- Registers a normal uninstaller in **Settings -> Apps**.
- Downloads the two AI models (about 104 MB) during setup and verifies their
  SHA-256 checksums, so the first face scan works immediately.
- Leaves `%LOCALAPPDATA%\TantraYantra\PeopleLens` untouched on install, upgrade,
  and uninstall.

## Build

```powershell
# 1. Build the application first.
pyinstaller PeopleLens.spec --noconfirm

# 2. Compile the installer (Inno Setup 6.3 or newer).
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\PeopleLens.iss
```

The result is `release\PeopleLens-Setup.exe`.

To package a different build:

```powershell
ISCC.exe /DPayloadDir="C:\path\to\PeopleLens" installer\PeopleLens.iss
```

## Silent install

The installer supports winget and managed deployment:

```bat
PeopleLens-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Silent mode still downloads and verifies the models. If the download fails, the
app installs anyway and retries when face recognition is first used.

## Model URLs

The URLs and checksums are pinned in the `[Code]` section and match the UniFace
model registry:

| File | SHA-256 |
|---|---|
| `adaface_ir_18.onnx` | `6b6a35772fb636cdd4fa86520c1a259d0c41472a76f70f802b351837a00d9870` |
| `retinaface_mnet_v2.onnx` | `3ca44c045651cabeed1193a1fae8946ad1f3a55da8fa74b341feab5a8319f757` |

If an upstream release moves, update both the URL and the checksum together.

## Signing

The installer is not signed yet. When a certificate is available, sign
`PeopleLens.exe` before building and sign `PeopleLens-Setup.exe` after building,
then timestamp both. Do not change the payload after signing.
