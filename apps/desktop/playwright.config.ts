// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
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
    trace: 'retain-on-failure',
  },
  outputDir: '../../data/desktop/playwright',
})
