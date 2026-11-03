# Contributing to PeopleLens

Thanks for taking a look. Bug reports, reproduction logs, and focused pull
requests are all welcome.

## Before you start

- Use Python **3.11.x 64-bit** on Windows.
- Read `README.md` for the project layout and `BUILD_WINDOWS11.md` for the
  release build.
- Never include a real photo library, database, settings file, or log in a
  commit, issue, or pull request.

## Development setup

```bat
py -3.11 -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt
```

Run the isolated test suites:

```bat
python tests\smoke_test_database.py
python tests\test_matching.py
python tests\test_scanner.py
python tests\test_ui_smoke.py
```

The tests point the data layer at temporary folders and never touch
`%LOCALAPPDATA%\TantraYantra\PeopleLens`.

## Pull requests

- Keep changes small and focused; one problem per pull request.
- Match the existing structure and naming. The UI is Tk/ttk and the data layer
  is SQLite; avoid adding a new framework for a small fix.
- Add or update a test when behaviour changes.
- Run all four test suites before opening the pull request.
- Describe what you changed and why. Screenshots help for UI changes.

## Data and privacy rules

- Do not add telemetry, analytics, cloud sync, or uploads.
- Do not delete, move, or rewrite a user's original media.
- Do not replace an existing user database; migrations must be additive and
  backed up first.
- Do not bundle AI model weights in the repository or a release. Keep the
  download-and-verify flow.

## Licensing

By contributing, you agree that your contribution is licensed under the MIT
License of this repository. Do not paste code you cannot license.
