// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import { App as CapApp } from '@capacitor/app'
import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { Home } from './components/Home'
import { PairScreen } from './components/PairScreen'
import './index.css'
import { isNative } from './lib/native'
import { parsePairLink } from './lib/pairing'
import { usePhone } from './lib/phone'

function App() {
  const paired = usePhone((s) => !!s.pairing)
  useEffect(() => {
    void usePhone.getState().init()
    // the desktop's pairing QR opens notecad://pair?... on the phone; in a browser, ?pair=<link> works too
    const fromWeb = new URLSearchParams(location.search).get('pair')
    if (fromWeb) { const p = parsePairLink(fromWeb); if (p) void usePhone.getState().pair(p) }
    if (!isNative) return
    const h = CapApp.addListener('appUrlOpen', ({ url }) => {
      const p = parsePairLink(url)
      if (p) void usePhone.getState().pair(p)
    })
    const r = CapApp.addListener('resume', () => { void usePhone.getState().refresh(); void usePhone.getState().drain() })
    return () => { void h.then((x) => x.remove()); void r.then((x) => x.remove()) }
  }, [])
  return paired ? <Home /> : <PairScreen />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
