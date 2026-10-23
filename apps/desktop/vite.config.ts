// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// Tauri v2 expects a fixed dev port and does not want the screen cleared
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',  // served from the brain at /app/ and from the Tauri bundle
  clearScreen: false,
  server: { port: 5173, strictPort: true, host: '127.0.0.1' },
  preview: { port: 4173, strictPort: true, host: '127.0.0.1' },
  envPrefix: ['VITE_', 'TAURI_ENV_'],
  build: {
    target: 'es2022',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: { output: { manualChunks: { flow: ['@xyflow/react', '@dagrejs/dagre'] } } },
  },
})
