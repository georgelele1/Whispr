import SwiftUI
import AppKit
import AVFoundation
import Combine

// =========================================================
// WhisprApp
// Entry point. Settings are now embedded in the sidebar so
// we no longer need a separate Settings scene.
// All other launch logic is unchanged from baseline.
// =========================================================

@main
struct WhisprApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        // Empty Settings scene keeps macOS happy (prevents
        // a default empty window on launch)
        Settings {
            EmptyView()
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var cancellables = Set<AnyCancellable>()

    func applicationDidFinishLaunching(_ notification: Notification) {
        _ = MenuBarController.shared
        NSApp.setActivationPolicy(.accessory)

        let appManager = AppManager.shared
        appManager.initialize()
        appManager.updateAppStatus(.idle)

        appManager.localBackendClient.$isBackendAvailable
            .receive(on: DispatchQueue.main)
            .sink { isAvailable in
                if !isAvailable {
                    appManager.updateAppStatus(.error)
                    NSLog("Python backend script is not accessible")
                }
            }
            .store(in: &cancellables)

        AVCaptureDevice.requestAccess(for: .audio) { granted in
            if !granted {
                DispatchQueue.main.async {
                    appManager.showPermissionAlert()
                }
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        AppManager.shared.audioRecorder.stopRecording()
    }
}
