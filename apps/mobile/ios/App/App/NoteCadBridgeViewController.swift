// Ionity Business Mind Map (IBMM) - Mobile (iOS) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import Capacitor
import UIKit

/// Registers the app's own plugin with the Capacitor bridge.
class NoteCadBridgeViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(NoteCadPlugin())
    }
}
