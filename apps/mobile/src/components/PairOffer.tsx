// Ionity Business Mind Map (IBMM) - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// A pairing link (QR, notecad://pair, ?pair=) only proposes a brain. The owner sees where notes would go and
// confirms, so a link from a web page or another app cannot quietly send the farm's voice notes elsewhere.
import { Loader2, ShieldCheck } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { usePhone } from '../lib/phone'

export function PairOffer() {
  const offer = usePhone((s) => s.offer)
  const current = usePhone((s) => s.pairing)
  const pair = usePhone((s) => s.pair)
  const offerPair = usePhone((s) => s.offerPair)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const cancel = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!offer) return
    setErr(null)
    cancel.current?.focus()  // the safe choice has the focus
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') offerPair(null) }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [offer, offerPair])

  if (!offer) return null
  const switching = !!current && (current.url !== offer.url || current.ws !== offer.ws)
  const go = async () => {
    setBusy(true)
    setErr(await pair(offer))
    setBusy(false)
  }
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="offer-title" className="fixed inset-0 z-50 grid place-items-end bg-black/60 p-3 sm:place-items-center">
      <div className="nc-glass w-full max-w-md rounded-2xl p-4">
        <h2 id="offer-title" className="flex items-center gap-2 text-base font-semibold text-slate-50">
          <ShieldCheck className="size-5 text-sky-300" />{switching ? 'Switch this phone to another brain?' : 'Connect this phone?'}
        </h2>
        <dl className="mt-3 space-y-1 text-sm">
          <div className="flex gap-2"><dt className="w-24 text-slate-400">Brain</dt><dd className="break-all text-slate-100">{offer.url}</dd></div>
          <div className="flex gap-2"><dt className="w-24 text-slate-400">Farm</dt><dd className="text-slate-100">{offer.ws}</dd></div>
          {switching && <div className="flex gap-2"><dt className="w-24 text-slate-400">Now</dt><dd className="break-all text-slate-300">{current!.url} ({current!.name ?? current!.ws})</dd></div>}
        </dl>
        <p className="mt-3 text-xs text-slate-400">Only connect to a brain you started yourself (the code on your desktop's "Pair a phone").</p>
        {err && <p className="mt-2 text-sm text-rose-300">{err}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button ref={cancel} type="button" onClick={() => offerPair(null)} className="rounded-xl px-4 py-2 text-sm text-slate-200 hover:bg-white/10">Cancel</button>
          <button type="button" disabled={busy} onClick={() => void go()} className="flex items-center gap-2 rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-400 disabled:opacity-60">
            {busy && <Loader2 className="size-4 animate-spin" />}Connect
          </button>
        </div>
      </div>
    </div>
  )
}
