// Ionity Business Mind Map (IBMM) - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Unit tests: the app's stores and the shared, framework-free logic in packages/core (fold).
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

const core = fileURLToPath(new URL('../../packages/core/src', import.meta.url))

export default defineConfig({
  resolve: { alias: { '@notecad/core': core } },
  server: { fs: { allow: ['.', core] } },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx', '../../packages/core/src/**/*.test.ts'],
    // packages/core has no node_modules of its own: its tests use this app's vitest
    alias: { vitest: fileURLToPath(new URL('./node_modules/vitest/dist/index.js', import.meta.url)) },
  },
})
