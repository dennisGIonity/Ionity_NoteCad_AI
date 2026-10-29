// Ionity Business Mind Map (IBMM) - Mobile (iOS) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import AppIntents
import Foundation

/// "Record an IBMM note": assign it to the Action Button (Settings > Action Button > Shortcut > IBMM),
/// add it to Control Center, or say it to Siri. It opens IBMM straight into recording.
@available(iOS 16.0, *)
struct RecordNoteIntent: AppIntent {
    static var title: LocalizedStringResource = "Record an IBMM note"
    static var description = IntentDescription("Opens IBMM and starts recording a voice note for the farm map.")
    static var openAppWhenRun: Bool = true

    @MainActor
    func perform() async throws -> some IntentResult {
        LaunchAction.post("record")
        return .result()
    }
}

@available(iOS 16.0, *)
struct NoteCadShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: RecordNoteIntent(),
            phrases: [
                "Record a note in \(.applicationName)",
                "New \(.applicationName) note",
                "\(.applicationName) record",
            ],
            shortTitle: "Record note",
            systemImageName: "mic.fill"
        )
    }
}
