# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Use GitHub's private vulnerability reporting:

<https://github.com/TantraYantra/drishtix/security/advisories/new>

Include:

- the DrishtiX version (Settings -> About);
- Windows version;
- steps to reproduce;
- any relevant lines from
  `%LOCALAPPDATA%\TantraYantra\DrishtiX\drishtix.log` with personal paths
  removed.

You can expect an acknowledgement within a few days. Please allow time for a
fix before disclosing the issue publicly.

## Scope

DrishtiX runs entirely on the local PC. The only network request it makes is
downloading the two AI model files at install time or on first use. It does not
upload photos, face data, or telemetry.

Reports about the upstream model files or third-party libraries should go to
their respective projects.
