// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

// Tauri v2 expects a fixed dev port and does not want the screen cleared
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // shared, framework-free logic (fold) lives in packages/core
  resolve: { alias: { '@notecad/core': fileURLToPath(new URL('../../packages/core/src', import.meta.url)) } },
  base: './',  // served from the brain at /app/ and from the Tauri bundle
  clearScreen: false,
  server: { port: 5173, strictPort: true, host: '127.0.0.1' },
  preview: { port: 4173, strictPort: true, host: '127.0.0.1' },
  envPrefix: ['VITE_', 'TAURI_ENV_'],
  build: {
    target: 'es2022',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    // Vite 8 (Rolldown): manualChunks is a function; module ids use forward slashes on Windows too
    rollupOptions: { output: { manualChunks: (id: string) => (/\/node_modules\/(@xyflow|@dagrejs)\//.test(id) ? 'flow' : undefined) } },
  },
})
