// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import { Link2, Loader2, QrCode } from 'lucide-react'
import { useState } from 'react'
import { parseJoinLink, parsePairLink } from '../lib/pairing'
import { usePhone } from '../lib/phone'

export function PairScreen() {
  const pair = usePhone((s) => s.pair)
  const offerJoin = usePhone((s) => s.offerJoin)
  const revokedNote = usePhone((s) => s.error)
  const [link, setLink] = useState('')
  const [url, setUrl] = useState('http://192.168.')
  const [token, setToken] = useState('')
  const [ws, setWs] = useState('showcase')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const go = async (p: { url: string; token: string; ws: string } | null) => {
    if (!p) {
      setErr('That is not a NoteCad pairing link')
      return
    }
    setBusy(true)
    setErr(await pair(p))
    setBusy(false)
  }

  const field = 'w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-[15px] text-slate-100 placeholder:text-slate-500 focus:border-sky-400/60 focus:outline-none'
  return (
    <main className="safe mx-auto flex min-h-full max-w-md flex-col gap-6 py-8">
      <header>
        <p className="text-xs uppercase tracking-[0.3em] text-sky-300/80">Ionity NoteCad</p>
        <h1 className="mt-2 text-2xl font-semibold text-slate-50">Connect this phone to the farm</h1>
        <p className="mt-2 text-sm text-slate-400">Notes are saved on the phone first and sent to the NoteCad brain on the desktop or the Edge AI Node when the phone is on the farm network.</p>
      </header>

      <section className="nc-glass rounded-2xl p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-100"><QrCode className="size-4 text-sky-300" />Scan the code on the desktop</div>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-slate-300">
          <li>On the desktop run <code className="rounded bg-white/10 px-1">start_notecad.ps1 -Lan</code></li>
          <li>In the NoteCad map, click <b>Pair a phone</b></li>
          <li>Point this phone's camera at the code and open the link</li>
        </ol>
      </section>

      <section className="flex flex-col gap-2">
        <label htmlFor="link" className="flex items-center gap-2 text-sm font-semibold text-slate-100"><Link2 className="size-4 text-sky-300" />Or paste the invite or pairing link</label>
        <input id="link" className={field} placeholder="notecad://join?u=… or notecad://pair?u=…" value={link} onChange={(e) => setLink(e.target.value)} autoCapitalize="off" autoCorrect="off" />
        <button type="button" disabled={busy || !link} onClick={() => {
          const j = parseJoinLink(link)  // an invite from the owner or a manager (ADR 0014)
          if (j) void offerJoin(j)
          else void go(parsePairLink(link))
        }}
          className="rounded-xl bg-sky-500 px-4 py-2.5 font-medium text-white disabled:opacity-40">Connect</button>
      </section>

      <details className="rounded-2xl border border-white/10 p-4">
        <summary className="cursor-pointer text-sm font-semibold text-slate-200">Type it in</summary>
        <div className="mt-3 flex flex-col gap-2">
          <label htmlFor="url" className="text-xs text-slate-400">Brain address</label>
          <input id="url" className={field} value={url} onChange={(e) => setUrl(e.target.value)} inputMode="url" autoCapitalize="off" />
          <label htmlFor="token" className="text-xs text-slate-400">Phone token</label>
          <input id="token" className={field} value={token} onChange={(e) => setToken(e.target.value)} autoCapitalize="off" autoCorrect="off" />
          <label htmlFor="ws" className="text-xs text-slate-400">Workspace</label>
          <input id="ws" className={field} value={ws} onChange={(e) => setWs(e.target.value)} autoCapitalize="off" />
          <button type="button" disabled={busy} onClick={() => go({ url: url.replace(/\/$/, ''), token, ws })}
            className="mt-1 rounded-xl bg-white/10 px-4 py-2.5 font-medium text-slate-100">Connect</button>
        </div>
      </details>

      {busy && <p className="flex items-center gap-2 text-sm text-slate-400"><Loader2 className="size-4 animate-spin" />Checking the brain…</p>}
      {!err && revokedNote && <p role="status" className="rounded-xl border border-amber-400/30 bg-amber-500/10 p-3 text-sm text-amber-100">{revokedNote}</p>}
      {err && <p role="alert" className="rounded-xl border border-rose-400/30 bg-rose-500/10 p-3 text-sm text-rose-200">{err}</p>}
    </main>
  )
}
