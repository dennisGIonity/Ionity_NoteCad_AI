<!--
  Ionity Business Mind Map (IBMM) - Mobile | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-->

# IBMM on the phone

Capacitor 8 + React 19 + Vite + Tailwind 4. Notes are saved on the phone first (outbox) and sent to the brain with
tus when the phone can reach it. Decisions: `docs\adr\0012-multi-worker-sync-and-phone-capture.md`.

## Connect a phone

1. On the desktop: `powershell -ExecutionPolicy Bypass -File services\start_notecad.ps1 -Lan`
   Once, let phones through Windows Firewall: `powershell -ExecutionPolicy Bypass -File services\allow_phones_firewall.ps1`
   (asks for admin; Private networks and the local subnet only; `-Check` to look, `-Remove` to undo).
2. In the IBMM map, click the status chip at the bottom right, then **Pair a phone**.
3. Scan the QR code with the phone. It opens IBMM with the brain address, phone token and workspace.

## Android

```bash
npm ci --include=dev
npm run build && npx cap sync android
cd android && ./gradlew assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
```

Needs JDK 21 and the Android SDK (`ANDROID_HOME`, platform 36). Install the APK, pair, then switch on
**Capture bubble**: allow the microphone, notifications and "Display over other apps". Tap the bubble to record,
tap again to save, drag it anywhere, long-press to close. Recordings go to the native outbox and upload in the
background (WorkManager) even with the app closed. The launcher icon's long-press menu has **Record note**.

Native code: `android/app/src/main/java/today/ionity/notecad/`
(`NoteCadPlugin`, `BubbleService`, `OutboxStore`, `TusUploader`, `UploadWorker`).

## iOS (needs a Mac with Xcode 16+)

```bash
npm run build && npx cap sync ios && npx cap open ios
```

Set the signing team, build to the phone, pair. Then Settings > Action Button > Shortcut > IBMM >
**Record an IBMM note** (iPhone 15 Pro and later), or add it to Control Center, or say "Record a note in IBMM".
Native code: `ios/App/App/` (`RecordNoteIntent.swift`, `NoteCadPlugin.swift`, `NoteCadBridgeViewController.swift`).

## In a browser (testing)

`npm run dev` and open `http://<pc>:5174/?pair=<pairing link>`. Recording needs https or localhost in most browsers.
