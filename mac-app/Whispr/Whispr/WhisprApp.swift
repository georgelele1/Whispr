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

        // Sync language from backend on launch
        appManager.localBackendClient.fetchLanguageFromBackend { lang in
            DispatchQueue.main.async {
                LanguageManager.shared.syncFromBackend(lang)
                MenuBarController.shared.refreshLanguageMenu()
            }
        }

        // Show onboarding on first launch
        AppManager.shared.localBackendClient.isFirstLaunch { isFirst in
            if isFirst {
                self.showOnboarding()
            }
        }
    }

    private func showOnboarding() {
        let host = NSHostingController(rootView: OnboardingView {
            self.onboardingWindow?.close()
            self.onboardingWindow = nil
        })

        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 620, height: 700),
            styleMask: [.titled, .closable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        win.title = "Welcome to Whispr"
        win.contentViewController = host
        win.titlebarAppearsTransparent = true
        win.isMovableByWindowBackground = true
        win.isReleasedWhenClosed = false
        win.center()
        win.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        onboardingWindow = win
    }

    private var onboardingWindow: NSWindow?

    func applicationWillTerminate(_ notification: Notification) {
        AppManager.shared.audioRecorder.stopRecording()
    }
}
