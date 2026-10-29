// Ionity Business Mind Map (IBMM) - Desktop shell | Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd
// No console window on Windows release builds
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    notecad_desktop_lib::run()
}
