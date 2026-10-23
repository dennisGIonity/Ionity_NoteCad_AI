// Ionity NoteCad - Desktop shell | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
//
// A transparent, frameless, always-on-top window that shows the recorder pill; the web app resizes it into the
// mind map (src/lib/tauri.ts). Ctrl+Shift+Space anywhere in Windows is hold-to-talk: the shell sends
// "notecad://hotkey" with "pressed" / "released" and the app records while it is held.
use tauri::{Emitter, Manager};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let talk = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::Space);
    tauri::Builder::default()
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, shortcut, event| {
                    if shortcut == &talk {
                        let state = match event.state() {
                            ShortcutState::Pressed => "pressed",
                            ShortcutState::Released => "released",
                        };
                        if let Some(w) = app.get_webview_window("main") {
                            if state == "pressed" {
                                let _ = w.show();
                            }
                        }
                        let _ = app.emit("notecad://hotkey", state);
                    }
                })
                .build(),
        )
        .setup(move |app| {
            app.global_shortcut().register(talk)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running NoteCad");
}
