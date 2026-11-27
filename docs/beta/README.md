<!--
  Ionity Business Mind Map (IBMM) - Beta 1 handover package | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
  Classification: CONFIDENTIAL - BETA TESTERS ONLY
-->

# Ionity Business Mind Map (IBMM) - Beta 1 handover

**Building Tomorrow, Today.**

Thank you for testing IBMM. This package has everything you need to install the beta on a Windows PC, understand
what it is, use it, and report what you find.

| | |
|---|---|
| Product | Ionity Business Mind Map (IBMM), development name **NoteCad** |
| Release | Beta 1 (desktop app 0.3.0, phone app 0.5.0) |
| Source build | Git `main` at commit `@COMMIT@` (@COMMIT_DATE@) |
| Package date | @DATE@ |
| Beta coordinator | Dennis Grobler - dennis.g@ionity.digital |
| Company | Ionity Global (Pty) Ltd (2026/276325/07) - info@ionity.today - +27 646 999 877 |

## Read these in order

| # | File | What it is for | Time |
|---|---|---|---|
| 1 | [`02_ABOUT_IBMM_POC_AND_SCOPE.md`](02_ABOUT_IBMM_POC_AND_SCOPE.md) | What IBMM is, what this proof of concept proves, what is in and out of scope for Beta 1 | 10 min |
| 2 | [`01_DEPLOYMENT_AND_INSTALLATION.md`](01_DEPLOYMENT_AND_INSTALLATION.md) | Requirements, installing on Windows, starting and stopping, phones, troubleshooting | 45-90 min (mostly downloads) |
| 3 | [`03_USER_GUIDE.md`](03_USER_GUIDE.md) | How to use the app, the beta test script, and how to report bugs | 20 min, then testing |

## What is in the package

```
IBMM_Beta1_Handover_@DATE_ISO@/
├── README.md                              this page
├── 01_DEPLOYMENT_AND_INSTALLATION.md
├── 02_ABOUT_IBMM_POC_AND_SCOPE.md
├── 03_USER_GUIDE.md
├── MANIFEST.txt                           every file in the package
├── SHA256SUMS.txt                         checksums, to confirm nothing was damaged in transfer
├── tools/
│   ├── setup_ibmm.ps1                     one-time installer (Python envs, models, app build)
│   └── collect_logs.ps1                   zips the logs for a bug report (no recordings, no database)
├── binaries/
│   ├── README.md                          where the Android APK and Windows installer come from
│   └── IBMM-android-debug.apk             the phone app (when the package was built by CI)
└── source/IBMM/                           the full application source at commit @COMMIT@
    ├── services/                          brain (:8788), companion (:8787), start scripts
    ├── apps/desktop/                      the desktop app (served by the brain at /app/)
    ├── apps/mobile/                       the phone app (Android / iOS)
    ├── packages/                          shared schema and logic
    ├── supabase/                          cloud database migrations (not used in Beta 1)
    └── docs/                              architecture decisions, performance, POPIA compliance
```

## The short version

```powershell
# 1. copy source\IBMM to D:\IBMM (any folder you like, no spaces is safest)
# 2. install Python 3.13+, Node.js 24 LTS and Ollama (links in 01_DEPLOYMENT_AND_INSTALLATION.md)
# 3. one-time set-up
powershell -ExecutionPolicy Bypass -File tools\setup_ibmm.ps1 -Root D:\IBMM
# 4. start, with the demo farm loaded
cd D:\IBMM
powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Showcase
# 5. the app opens at http://127.0.0.1:8788/  - hold Space and talk
```

## Ground rules for testers

- **This is a beta.** Expect rough edges. Do not put real customer, employee or financial information into it.
  Use the demo farm or made-up data.
- **Everything stays on your PC.** Beta 1 runs offline. No note, recording or transcript leaves the machine unless
  you add a Claude or Deepgram key *and* the owner turns the cloud transfer on (both are off by default; please
  leave them off unless Dennis asks you to test them).
- **Do not share this package.** It is confidential pre-release software of Ionity Global (Pty) Ltd.
- **Report everything**, even small things. How to do it is in section 7 of the user guide.

---
Policy 986 AED | License AED 900 | (c) 2018-2026 Antwerp Designs | Ionity Global (Pty) Ltd - All rights reserved.
