// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import { useEffect } from 'react'
import { Inspector } from './components/Inspector'
import { MindMap } from './components/MindMap'
import { RecorderHUD } from './components/RecorderHUD'
import { SyncIndicator } from './components/SyncIndicator'
import { useRecorder } from './lib/recorder'
import { useApp } from './lib/store'
import { fitWindow, inTauri, onHotkey } from './lib/tauri'
import { cls } from './lib/ui'

const typingIn = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))

export default function App() {
  const view = useApp((s) => s.view)
  const inspecting = useApp((s) => !!s.selected)
  const init = useApp((s) => s.init)

  useEffect(() => { void init() }, [init])
  useEffect(() => { document.documentElement.classList.toggle('tauri', inTauri) }, [])
  useEffect(() => { void fitWindow(view) }, [view])

  // hold Space to talk; Esc cancels; M toggles the map
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (typingIn(e.target) || e.defaultPrevented) return
      const rec = useRecorder.getState()
      if (e.code === 'Space' && !e.repeat) {
        e.preventDefault()
        if (rec.state === 'idle') void rec.start(useApp.getState().selected)
      } else if (e.code === 'Space') {
        e.preventDefault()
      } else if (e.key === 'Escape') {
        if (rec.state !== 'idle') rec.cancel()
        else useApp.getState().select(null)
      } else if ((e.key === 'm' || e.key === 'M') && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const app = useApp.getState()
        app.setView(app.view === 'map' ? 'hud' : 'map')
      }
    }
    const up = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !typingIn(e.target)) {
        e.preventDefault()
        void useRecorder.getState().stop()
      }
    }
    const lost = () => {  // focus moved away while Space was held: keyup will never come
      const rec = useRecorder.getState()
      if (rec.state === 'recording' || rec.state === 'arming') void rec.stop()
    }
    const hidden = () => { if (document.hidden) lost() }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', lost)
    document.addEventListener('visibilitychange', hidden)
    let off: () => void = () => {}
    void onHotkey((s) => {
      const rec = useRecorder.getState()
      if (s === 'pressed' && rec.state === 'idle') void rec.start(useApp.getState().selected)
      if (s === 'released') void rec.stop()
    }).then((f) => { off = f })
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', lost)
      document.removeEventListener('visibilitychange', hidden)
      off()
    }
  }, [])

  const isMap = view === 'map'
  return (
    <div className={cls('nc-app relative h-full w-full overflow-hidden', isMap ? 'nc-app-map' : 'nc-app-hud')}>
      <main
        aria-hidden={!isMap}
        className={cls('absolute inset-0 transition-all duration-500 ease-[cubic-bezier(.2,.8,.2,1)]',
          isMap ? 'scale-100 opacity-100' : 'pointer-events-none scale-[0.96] opacity-0')}
      >
        {isMap && <MindMap />}
        <Inspector />
      </main>
      {!isMap && !inTauri && (
        <div className="pointer-events-none absolute inset-x-0 top-[22%] text-center">
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Ionity NoteCad</p>
          <p className="mt-2 text-sm text-slate-400">Hold <kbd className="rounded border border-white/15 bg-white/5 px-1.5 py-0.5 text-[11px]">Space</kbd> to talk · <kbd className="rounded border border-white/15 bg-white/5 px-1.5 py-0.5 text-[11px]">M</kbd> for the map</p>
        </div>
      )}
      <div className={cls('pointer-events-none absolute inset-x-0 z-40 transition-all duration-500',
        isMap ? 'bottom-0' : inTauri ? 'bottom-3' : 'bottom-[18%]', isMap && inspecting && 'md:pr-[416px]')}>
        <RecorderHUD docked={isMap} />
      </div>
      <SyncIndicator />
    </div>
  )
}
