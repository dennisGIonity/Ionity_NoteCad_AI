// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The native side of the phone app (android/.../NoteCadPlugin.java, ios/App/App/NoteCadPlugin.swift).
// Android: the floating capture bubble, which records and uploads on its own (WorkManager + tus) with the app closed.
// iOS: the Action Button / Control Center / Siri "Record a NoteCad note" opens the app straight into recording.
// In a browser every call resolves to a harmless default.
import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core'

export interface NativeItem {
  id: string
  state: 'saved' | 'uploading' | 'uploaded' | 'failed'
  progress: number
  size: number
  createdAt: number
  recordedAt: string
  source: string
  error?: string
}

interface NoteCadPlugin {
  configure(o: { url: string; token: string; ws: string; pin: string }): Promise<void>
  trust(o: { url: string; pin: string }): Promise<void>
  token(): Promise<{ token: string }>
  overlayAllowed(): Promise<{ allowed: boolean }>
  openOverlaySettings(): Promise<void>
  startBubble(): Promise<{ started: boolean; overlay: boolean }>
  stopBubble(): Promise<void>
  bubbleRunning(): Promise<{ running: boolean }>
  listOutbox(): Promise<{ items: NativeItem[] }>
  uploadNow(): Promise<void>
  forget(o: { id: string }): Promise<void>
  consumeLaunchAction(): Promise<{ action: string | null }>
  wipe(): Promise<void>
  addListener(event: 'outboxChanged' | 'launchAction', cb: (data: { action?: string }) => void): Promise<PluginListenerHandle>
}

const plugin = registerPlugin<NoteCadPlugin>('NoteCad')
export const platform = Capacitor.getPlatform()  // 'android' | 'ios' | 'web'
export const isNative = Capacitor.isNativePlatform()
const hasPlugin = isNative && Capacitor.isPluginAvailable('NoteCad')

export const Native = {
  available: hasPlugin,
  configure: (o: { url: string; token: string; ws: string; pin: string }) => (hasPlugin ? plugin.configure(o) : Promise.resolve()),
  /** This phone's token from the Keystore-encrypted vault (Android); '' elsewhere. */
  token: async () => (hasPlugin && platform === 'android' ? (await plugin.token()).token : ''),
  /** On Android the token lives in the native vault, not in the web layer's storage. */
  vaulted: hasPlugin && platform === 'android',
  /** Trust this brain's own certificate (its SHA-256 from the QR) before the first request to it: HTTPS on the farm
   * network with no certificate authority (POPIA review, fix 4). A no-op in a browser. */
  trust: (url: string, pin: string | undefined) =>
    (hasPlugin && pin && url.startsWith('https') ? plugin.trust({ url, pin }) : Promise.resolve()),
  overlayAllowed: async () => (hasPlugin && platform === 'android' ? (await plugin.overlayAllowed()).allowed : false),
  openOverlaySettings: () => (hasPlugin ? plugin.openOverlaySettings() : Promise.resolve()),
  startBubble: () => (hasPlugin ? plugin.startBubble() : Promise.resolve({ started: false, overlay: false })),
  stopBubble: () => (hasPlugin ? plugin.stopBubble() : Promise.resolve()),
  bubbleRunning: async () => (hasPlugin && platform === 'android' ? (await plugin.bubbleRunning()).running : false),
  listOutbox: async (): Promise<NativeItem[]> => (hasPlugin && platform === 'android' ? (await plugin.listOutbox()).items : []),
  uploadNow: () => (hasPlugin && platform === 'android' ? plugin.uploadNow() : Promise.resolve()),
  forget: (id: string) => (hasPlugin ? plugin.forget({ id }) : Promise.resolve()),
  consumeLaunchAction: async () => (hasPlugin ? (await plugin.consumeLaunchAction()).action : null),
  /** A revoked phone (ADR 0014): the native outbox, cache and token go. */
  wipe: () => (hasPlugin ? plugin.wipe() : Promise.resolve()),
  on: (event: 'outboxChanged' | 'launchAction', cb: (d: { action?: string }) => void) =>
    hasPlugin ? plugin.addListener(event, cb) : Promise.resolve({ remove: async () => undefined } as PluginListenerHandle),
}
