// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'today.ionity.notecad',
  appName: 'NoteCad',
  webDir: 'dist',
  // the brain is on the farm's LAN over plain HTTP: serve the app as http://localhost so the WebView may call it
  server: { androidScheme: 'http', cleartext: true },
  android: { allowMixedContent: true },
  ios: { contentInset: 'never' },
}

export default config
