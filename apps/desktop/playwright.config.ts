// Ionity Business Mind Map (IBMM) - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// End-to-end tests against the running stack (start_notecad.ps1): the app the brain serves at /app/.
// The installed Microsoft Edge is used (signed, so it runs under Smart App Control); no browser download.
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.NC_APP_URL ?? 'http://127.0.0.1:8788/app/',
    channel: 'msedge',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',  // the usual look; the light-mode test switches explicitly
    trace: 'retain-on-failure',
    // the owner's privacy-notice setup (POPIA) is put off on the test browser, so it does not cover the map; the
    // live workspace's notice is left as the owner set it. roles.spec reads it as the joining employee.
    storageState: { cookies: [], origins: [{ origin: 'http://127.0.0.1:8788', localStorage: [
      { name: 'notecad.privacy.later', value: '99999999999999' }] }] },
  },
  outputDir: '../../data/desktop/playwright',
})
