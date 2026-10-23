// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',
  server: { port: 5174, strictPort: true, host: '0.0.0.0' },  // open on the phone over the LAN while developing
  build: { target: 'es2020', sourcemap: false, chunkSizeWarningLimit: 700 },
})
