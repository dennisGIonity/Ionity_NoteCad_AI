// Ionity NoteCad - Mobile (iOS) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import Capacitor
import Foundation

/// Where a launch action waits until the web app asks for it (cold start from the Action Button or Siri).
enum LaunchAction {
    static let notification = Notification.Name("NoteCadLaunchAction")
    private static var pending: String?
    private static let lock = NSLock()

    static func post(_ action: String) {
        lock.lock(); pending = action; lock.unlock()
        NotificationCenter.default.post(name: notification, object: nil, userInfo: ["action": action])
    }

    static func take() -> String? {
        lock.lock(); defer { lock.unlock() }
        let a = pending
        pending = nil
        return a
    }
}

/// The iOS half of src/lib/native.ts. Recording and the outbox live in the web layer on iOS
/// (IndexedDB + tus-js-client); this plugin only hands over "record" from the Action Button, Control Center and Siri.
@objc(NoteCadPlugin)
public class NoteCadPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "NoteCadPlugin"
    public let jsName = "NoteCad"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "configure", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "overlayAllowed", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "openOverlaySettings", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "startBubble", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopBubble", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "bubbleRunning", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "listOutbox", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "uploadNow", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "forget", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "consumeLaunchAction", returnType: CAPPluginReturnPromise),
    ]
    private var observer: NSObjectProtocol?

    public override func load() {
        observer = NotificationCenter.default.addObserver(forName: LaunchAction.notification, object: nil, queue: .main) { [weak self] n in
            guard let self, let a = n.userInfo?["action"] as? String else { return }
            _ = LaunchAction.take()  // delivered live, so it must not fire again on the next consume
            self.notifyListeners("launchAction", data: ["action": a], retainUntilConsumed: true)
        }
    }

    deinit { if let observer { NotificationCenter.default.removeObserver(observer) } }

    @objc func configure(_ call: CAPPluginCall) {
        let d = UserDefaults.standard
        d.set(call.getString("url") ?? "", forKey: "notecad.url")
        d.set(call.getString("ws") ?? "", forKey: "notecad.ws")
        call.resolve()  // the token stays in the web layer; nothing native uploads on iOS
    }

    @objc func overlayAllowed(_ call: CAPPluginCall) { call.resolve(["allowed": false]) }
    @objc func openOverlaySettings(_ call: CAPPluginCall) { call.resolve() }
    @objc func startBubble(_ call: CAPPluginCall) { call.resolve(["started": false, "overlay": false]) }
    @objc func stopBubble(_ call: CAPPluginCall) { call.resolve() }
    @objc func bubbleRunning(_ call: CAPPluginCall) { call.resolve(["running": false]) }
    @objc func listOutbox(_ call: CAPPluginCall) { call.resolve(["items": []]) }
    @objc func uploadNow(_ call: CAPPluginCall) { call.resolve() }
    @objc func forget(_ call: CAPPluginCall) { call.resolve() }

    @objc func consumeLaunchAction(_ call: CAPPluginCall) {
        if let a = LaunchAction.take() { call.resolve(["action": a]) } else { call.resolve(["action": NSNull()]) }
    }
}
