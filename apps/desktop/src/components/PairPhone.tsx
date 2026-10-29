// Ionity Business Mind Map (IBMM) - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// "Pair a phone": a QR code with notecad://pair?u=<brain on the LAN>&t=<phone token>&w=<workspace>.
// The brain only hands this out to this PC (GET /api/v1/pairing answers 403 to anyone else).
import { Copy, Loader2, Smartphone, X } from 'lucide-react'
import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useApp } from '../lib/store'
import type { Pairing } from '../lib/types'
import { cls } from '../lib/ui'

export function PairPhone({ onClose }: { onClose: () => void }) {
  const ws = useApp((s) => s.ws)
  const [p, setP] = useState<Pairing | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [pick, setPick] = useState(0)
  const [svg, setSvg] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    api.pairing(ws).then(setP, (e: Error) => setErr(e.message))
  }, [ws])

  const link = p?.links[pick] ?? null
  useEffect(() => {
    if (!link) { setSvg(null); return }
    QRCode.toString(link, { type: 'svg', margin: 1, errorCorrectionLevel: 'M', color: { dark: '#020617', light: '#ffffff' } })
      .then(setSvg, () => setSvg(null))
  }, [link])

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); onClose() } }
    window.addEventListener('keydown', k, true)  // capture: before the app's own Escape (deselect)
    return () => window.removeEventListener('keydown', k, true)
  }, [onClose])

  const copy = async () => {
    if (!link) return
    try { await navigator.clipboard.writeText(link); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* clipboard blocked */ }
  }

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: a click on the backdrop closes; Escape is handled above
    <div role="dialog" aria-modal="true" aria-labelledby="pair-title"
      className="pointer-events-auto fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-sm" onClick={onClose}>
      {/* biome-ignore lint/a11y/useKeyWithClickEvents lint/a11y/noStaticElementInteractions: keeps backdrop clicks off the panel */}
      <div className="nc-glass w-full max-w-sm rounded-3xl p-5 text-slate-300 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 id="pair-title" className="flex items-center gap-2 text-sm font-semibold text-slate-100"><Smartphone className="size-4 text-sky-300" />Pair a phone</h2>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded-lg p-1 hover:bg-white/10"><X className="size-4" /></button>
        </div>
        {err && <p role="alert" className="mt-3 rounded-xl border border-rose-400/30 bg-rose-500/10 p-3 text-xs text-rose-200">{err}</p>}
        {!p && !err && <p className="mt-6 flex items-center gap-2 text-xs"><Loader2 className="size-4 animate-spin" />Asking the brain…</p>}
        {p && !p.ready && (
          <div className="mt-3 space-y-2 text-xs">
            <p className="rounded-xl border border-amber-400/30 bg-amber-500/10 p-3 text-amber-100">
              {!p.lan ? 'The brain only listens on this PC, so a phone cannot reach it yet.' : !p.token_set ? 'The brain has no phone token yet.' : 'No network address found for this PC.'}
            </p>
            {p.hint && <p className="text-slate-400">{p.hint}</p>}
          </div>
        )}
        {p?.ready && (
          <>
            <p className="mt-2 text-xs text-slate-400">Install IBMM on the phone, open it and scan this code (or point the camera app at it). The phone saves notes offline and sends them when it is on this network.</p>
            <div className="mx-auto mt-4 aspect-square w-60 overflow-hidden rounded-2xl bg-white p-2">
              {svg && <img className="size-full" alt="Pairing QR code" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`} />}
            </div>
            {p.urls.length > 1 && (
              <fieldset className="m-0 mt-3 flex min-w-0 flex-wrap gap-1.5 border-0 p-0">
                <legend className="sr-only">Network address</legend>
                {p.urls.map((u, i) => (
                  <button key={u} type="button" aria-pressed={i === pick} onClick={() => setPick(i)}
                    className={cls('rounded-full border px-2 py-0.5 text-[11px]', i === pick ? 'border-sky-400/60 bg-sky-500/20 text-sky-100' : 'border-white/10 text-slate-400 hover:bg-white/5')}>
                    {u.replace('http://', '')}
                  </button>
                ))}
              </fieldset>
            )}
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[11px]">
              <dt className="text-slate-500">Brain</dt><dd className="truncate text-slate-200">{p.urls[pick]}</dd>
              <dt className="text-slate-500">Workspace</dt><dd className="truncate text-slate-200">{p.workspaces.find((w) => w.id === p.workspace)?.name ?? p.workspace}</dd>
            </dl>
            <button type="button" onClick={() => void copy()}
              className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-white/10 px-3 py-2 text-xs text-slate-100 hover:bg-white/15">
              <Copy className="size-3.5" />{copied ? 'Copied' : 'Copy the link instead'}
            </button>
            <p className="mt-2 text-[10px] text-slate-500">The code holds the phone token. Only show it to phones you trust.</p>
          </>
        )}
      </div>
    </div>
  )
}
