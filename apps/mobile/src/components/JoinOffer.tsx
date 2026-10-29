// Ionity Business Mind Map (IBMM) - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// A seat offered to this phone (notecad://join, ADR 0014). The brain says what the invite is (the farm, the role, the
// branches) and nothing happens until the person taps Join: the one-time code is used up then, not before.
import { Loader2, UserPlus } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { usePhone } from '../lib/phone'

const ROLE = { owner: 'an owner', manager: 'a manager', employee: 'an employee' } as Record<string, string>

export function JoinOffer() {
  const join = usePhone((s) => s.join)
  const preview = usePhone((s) => s.joinPreview)
  const error = usePhone((s) => s.error)
  const current = usePhone((s) => s.pairing)
  const offerJoin = usePhone((s) => s.offerJoin)
  const acceptJoin = usePhone((s) => s.acceptJoin)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const cancel = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!join) return
    setErr(null)
    cancel.current?.focus()  // the safe choice has the focus
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') void offerJoin(null) }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [join, offerJoin])

  if (!join) return null
  const go = async () => {
    setBusy(true)
    setErr(await acceptJoin())
    setBusy(false)
  }
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="join-title" className="fixed inset-0 z-50 grid place-items-end bg-black/60 p-3 sm:place-items-center">
      <div className="nc-glass w-full max-w-md rounded-2xl p-4">
        <h2 id="join-title" className="flex items-center gap-2 text-base font-semibold text-slate-50">
          <UserPlus className="size-5 text-sky-300" />
          {preview ? `Join ${preview.workspace} as ${ROLE[preview.role] ?? preview.role}?` : 'Checking the invite…'}
        </h2>
        {preview && (
          <dl className="mt-3 space-y-1 text-sm">
            <div className="flex gap-2"><dt className="w-24 text-slate-400">You</dt><dd className="text-slate-100">{preview.name}</dd></div>
            <div className="flex gap-2"><dt className="w-24 text-slate-400">Branches</dt><dd className="text-slate-100">{preview.scope.length ? preview.scope.join(', ') : 'the whole farm'}</dd></div>
            <div className="flex gap-2"><dt className="w-24 text-slate-400">Brain</dt><dd className="break-all text-slate-300">{join.url}</dd></div>
            {current && <div className="flex gap-2"><dt className="w-24 text-slate-400">Now</dt><dd className="text-amber-200">This phone leaves {current.name ?? current.ws}</dd></div>}
          </dl>
        )}
        {!preview && !error && <p className="mt-3 flex items-center gap-2 text-sm text-slate-400"><Loader2 className="size-4 animate-spin" />Asking the brain what this invite is</p>}
        <p className="mt-3 text-xs text-slate-400">The code works once. Only join a business whose owner or manager gave you this code.</p>
        {(err || (!preview && error)) && <p role="alert" className="mt-2 text-sm text-rose-300">{err ?? error}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <button ref={cancel} type="button" onClick={() => void offerJoin(null)} className="rounded-xl px-4 py-2 text-sm text-slate-200 hover:bg-white/10">Cancel</button>
          <button type="button" disabled={busy || !preview} onClick={() => void go()} className="flex items-center gap-2 rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-400 disabled:opacity-60">
            {busy && <Loader2 className="size-4 animate-spin" />}Join
          </button>
        </div>
      </div>
    </div>
  )
}
