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
  configure(o: { url: string; token: string; ws: string }): Promise<void>
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
  configure: (o: { url: string; token: string; ws: string }) => (hasPlugin ? plugin.configure(o) : Promise.resolve()),
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
