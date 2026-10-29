// Ionity Business Mind Map (IBMM) - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import { App as CapApp } from '@capacitor/app'
import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { Home } from './components/Home'
import { JoinOffer } from './components/JoinOffer'
import { PairOffer } from './components/PairOffer'
import { PairScreen } from './components/PairScreen'
import './index.css'
import { isNative } from './lib/native'
import { parseJoinLink, parsePairLink } from './lib/pairing'
import { usePhone } from './lib/phone'

function App() {
  const paired = usePhone((s) => !!s.pairing)
  useEffect(() => {
    void usePhone.getState().init()
    // the desktop's pairing QR opens notecad://pair?... on the phone; in a browser, ?pair=<link> works too
    const q = new URLSearchParams(location.search)
    const fromWeb = q.get('pair')
    if (fromWeb) { const p = parsePairLink(fromWeb); if (p) usePhone.getState().offerPair(p) }  // the owner confirms
    const joinWeb = q.get('join')  // ADR 0014: a seat offered with a one-time code; the person confirms
    if (joinWeb) { const j = parseJoinLink(joinWeb); if (j) void usePhone.getState().offerJoin(j) }
    if (!isNative) return
    const h = CapApp.addListener('appUrlOpen', ({ url }) => {
      const j = parseJoinLink(url)
      if (j) { void usePhone.getState().offerJoin(j); return }
      const p = parsePairLink(url)
      if (p) usePhone.getState().offerPair(p)
    })
    const r = CapApp.addListener('resume', () => { void usePhone.getState().refresh(); void usePhone.getState().drain() })
    return () => { void h.then((x) => x.remove()); void r.then((x) => x.remove()) }
  }, [])
  return <>{paired ? <Home /> : <PairScreen />}<PairOffer /><JoinOffer /></>
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
