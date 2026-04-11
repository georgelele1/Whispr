import SwiftUI
import AppKit
import AVFoundation
import Combine

@main
struct WhisprApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        Settings { EmptyView() }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var onboardingWindow: NSWindow?
    private var setupWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        _ = MenuBarController.shared
        NSApp.setActivationPolicy(.accessory)

        let appManager = AppManager.shared
        appManager.initialize()
        appManager.updateAppStatus(.idle)

        AVCaptureDevice.requestAccess(for: .audio) { granted in
            if !granted {
                DispatchQueue.main.async { appManager.showPermissionAlert() }
            }
        }

        prepareRuntimeAndContinue()
    }

    func applicationWillTerminate(_ notification: Notification) {
        _ = AppManager.shared.audioRecorder.stopRecording()
    }

    // MARK: - Runtime bootstrap

    private func prepareRuntimeAndContinue() {
        if RuntimeBootstrapper.shared.isRuntimeReady() {
            AppManager.shared.localBackendClient.refreshRuntimePaths()
            continueNormalLaunchFlow()
            return
        }

        showSetupWindow(message: "Preparing Whispr for first use…")

        RuntimeBootstrapper.shared.prepareRuntime { success, message in
            AppManager.shared.localBackendClient.refreshRuntimePaths()
            self.closeSetupWindow()

            if success {
                self.continueNormalLaunchFlow()
            } else {
                AppManager.shared.updateAppStatus(.error)
                AppManager.shared.showErrorAlert(message: "First-time setup failed: \(message)")
            }
        }
    }

    private func continueNormalLaunchFlow() {
        let client = AppManager.shared.localBackendClient

        client.fetchLanguageFromBackend { lang in
            DispatchQueue.main.async {
                LanguageManager.shared.syncFromBackend(lang)
                MenuBarController.shared.refreshLanguageMenu()
            }
        }

        client.isFirstLaunch { isFirst in
            if isFirst {
                DispatchQueue.main.async { self.showOnboarding() }
            }
        }
    }

    // MARK: - Setup window

    private func showSetupWindow(message: String) {
        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 180),
            styleMask: [.titled, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        win.title = "Setting up Whispr"
        win.contentViewController = NSHostingController(rootView: SetupLoadingView(message: message))
        win.titlebarAppearsTransparent = true
        win.isMovableByWindowBackground = true
        win.isReleasedWhenClosed = false
        win.center()
        win.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        setupWindow = win
    }

    private func closeSetupWindow() {
        setupWindow?.close()
        setupWindow = nil
    }

    // MARK: - Onboarding

    private func showOnboarding() {
        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 620, height: 700),
            styleMask: [.titled, .closable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        win.title = "Welcome to Whispr"
        win.contentViewController = NSHostingController(rootView: OnboardingView {
            self.onboardingWindow?.close()
            self.onboardingWindow = nil
        })
        win.titlebarAppearsTransparent = true
        win.isMovableByWindowBackground = true
        win.isReleasedWhenClosed = false
        win.center()
        win.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        onboardingWindow = win
    }
}

struct SetupLoadingView: View {
    let message: String

    var body: some View {
        VStack(spacing: 16) {
            ProgressView().scaleEffect(1.1)
            Text(message).font(.headline)
            Text("This only happens the first time.")
                .font(.caption).foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(24)
    }
}
