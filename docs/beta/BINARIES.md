<!--
  Ionity Business Mind Map (IBMM) - Beta 1 | Binaries
  Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-->

# Binaries

The desktop app needs **no binary**: it is built from `source\IBMM` by `tools\setup_ibmm.ps1` and runs in your
browser. This folder is for the optional extras that GitHub Actions builds for commit `@COMMIT@`:

| File | What | Needed for |
|---|---|---|
| `IBMM-android-debug.apk` | Android phone app 0.5.0, debug build (Android 7.0+, `today.ionity.notecad`) | Phone tests (user guide 6.4, test script line 15) |
| `IBMM-windows-installer` (`.msi` / `-setup.exe`) | Tauri desktop window 0.3.0, **unsigned** | Not in Beta 1 scope (Smart App Control blocks it) |

When CI builds the package (job "Beta handover package", artifact `ibmm-beta-package`) the APK is already in this
folder. **If it is not here**, ask Dennis (dennis.g@ionity.digital) for it, or skip the phone tests.

For Ionity: the package is built by `tools/make_beta_package.sh <out-dir> [app-debug.apk]`; CI runs it on every push
to `main`, with the APK from the same run.
