// Ionity Business Mind Map (IBMM) - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The privacy notice on the phone (POPIA s18; the POPIA review's fix 5): shown after joining, until the member has read
// it, and again from the menu. The owner sets the contact and the periods on the PC.
import { Loader2, ShieldCheck, X } from 'lucide-react'
import { useState } from 'react'
import { usePhone } from '../lib/phone'

export function PrivacySheet({ onClose }: { onClose?: () => void }) {
  const n = usePhone((s) => s.privacy)
  const ack = usePhone((s) => s.ackPrivacy)
  const [busy, setBusy] = useState(false)
  if (!n) return null
  const abroad = [
    n.cloud.claude && 'the text of each note goes to Anthropic (USA) to be filed',
    n.cloud.deepgram && 'voice recordings go to Deepgram (USA) to be turned into text',
    n.cloud.sync === 'supabase' && "a copy is kept in the business's Supabase project",
  ].filter(Boolean) as string[]
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="privacy-title" className="fixed inset-0 z-40 flex items-end bg-black/70">
      <div className="nc-glass safe max-h-[88vh] w-full overflow-y-auto rounded-t-3xl p-5 text-sm leading-relaxed text-slate-300">
        <div className="mb-3 flex items-center gap-2">
          <ShieldCheck className="size-5 text-emerald-300" />
          <h2 id="privacy-title" className="flex-1 font-semibold text-slate-50">Privacy notice · {n.business}</h2>
          {onClose && n.my_ack_at && (
            <button type="button" aria-label="Close" onClick={onClose} className="grid size-9 place-items-center rounded-full bg-white/5"><X className="size-4" /></button>
          )}
        </div>
        <div className="space-y-2">
          <p><b className="text-slate-100">Who is responsible:</b> {n.business}{n.owners.length ? ` (${n.owners.join(', ')})` : ''}. Information Officer: {n.officer ?? 'the owner'}. Questions about your information: {n.contact ?? 'ask the owner'}.</p>
          <p><b className="text-slate-100">What is recorded:</b> your voice notes and their text, what is filed from them, who made each change and when, and this phone. No location, contacts or ID numbers.</p>
          <p><b className="text-slate-100">Why:</b> to run the business's work on its map.</p>
          <p><b className="text-slate-100">Who sees it:</b> each person sees only what their role allows.</p>
          <p><b className="text-slate-100">At work:</b> your voice notes, the tasks you are given and how far you got, and your changes are recorded as part of the work. You can see your own activity, and get a copy of everything about you from the menu.</p>
          <p><b className="text-slate-100">Where:</b> on the business's own computer{abroad.length ? `; also: ${abroad.join('; ')}` : ', and nothing leaves it'}.</p>
          <p><b className="text-slate-100">How long:</b> {n.retention_text}.</p>
          <p><b className="text-slate-100">Your rights:</b> ask what is held about you, have it corrected or deleted, or object, through the contact above; or complain to the Information Regulator (inforegulator.org.za).</p>
          <p>Please do not dictate health, religion, union or other sensitive details about anyone.</p>
          {!n.my_ack_at && <p className="text-amber-200">Your notes wait on this phone until you have read this.</p>}
        </div>
        {!n.my_ack_at && (
          <button type="button" disabled={busy} onClick={() => { setBusy(true); void ack().finally(() => setBusy(false)) }}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl bg-emerald-500 py-3 font-semibold text-slate-950 disabled:opacity-50">
            {busy && <Loader2 className="size-4 animate-spin" />}I have read this
          </button>
        )}
      </div>
    </div>
  )
}
