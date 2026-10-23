// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Only active inside the Tauri v2 shell (src-tauri): transparent window sizing per view and the global hotkey.
// In a browser every function here is a no-op.
import type { View } from './store'

export const inTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

const SIZES: Record<View, [number, number]> = { hud: [760, 260], map: [1360, 860] }

export async function fitWindow(view: View) {
  if (!inTauri) return
  const { getCurrentWindow, LogicalSize } = await import('@tauri-apps/api/window')
  const w = getCurrentWindow()
  const [width, height] = SIZES[view]
  await w.setSize(new LogicalSize(width, height))
  await w.setAlwaysOnTop(view === 'hud')
  if (view === 'map') await w.center()
}

/** Ctrl+Shift+Space anywhere in Windows (registered in src-tauri/src/lib.rs) toggles recording. */
export async function onHotkey(cb: (state: 'pressed' | 'released') => void): Promise<() => void> {
  if (!inTauri) return () => undefined
  const { listen } = await import('@tauri-apps/api/event')
  return listen<string>('notecad://hotkey', (e) => cb(e.payload === 'released' ? 'released' : 'pressed'))
}
