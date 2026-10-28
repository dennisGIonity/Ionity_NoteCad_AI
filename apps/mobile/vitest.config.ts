// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import { defineConfig } from 'vitest/config'

export default defineConfig({ test: { environment: 'jsdom', include: ['src/**/*.test.ts'], setupFiles: ['fake-indexeddb/auto'] } })
