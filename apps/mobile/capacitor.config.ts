// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'today.ionity.notecad',
  appName: 'NoteCad',
  webDir: 'dist',
  // served as http://localhost (kept: the outbox and the device copy live in that origin's storage). The farm brain is
  // HTTPS with a pinned certificate; res/xml/network_security_config.xml allows plain HTTP to this phone only
  server: { androidScheme: 'http', cleartext: false },
  android: { allowMixedContent: false },
  ios: { contentInset: 'never' },
}

export default config
