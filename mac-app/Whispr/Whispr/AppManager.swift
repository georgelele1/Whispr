import Foundation
import AppKit
import Combine

final class AppManager: ObservableObject {
    static let shared = AppManager()
    private init() {}

    let hotkeyManager     = HotkeyManager()
    let audioRecorder     = AudioRecorder()
    let localBackendClient = LocalBackendClient()
    let activeAppDetector = ActiveAppDetector()
    let floatingIndicator = FloatingIndicator()

    @Published var appStatus        : AppStatus = .idle
    @Published var lastOutputText   : String    = ""
    @Published var currentActiveApp : String    = "Unknown"

    private var cancellables    = Set<AnyCancellable>()
    private var backendProcess  : Process?

    // =========================================================
    // Startup
    // =========================================================

    func initialize() {
        startBackendServer()

        hotkeyManager.setupGlobalHotkey { [weak self] shouldStart in
            guard let self else { return }
            if shouldStart { self.startRecordingFromMenu() }
            else           { self.stopRecordingAndProcess() }
        }

        audioRecorder.$isRecording
            .receive(on: DispatchQueue.main)
            .sink { [weak self] isRecording in
                guard let self else { return }
                if isRecording {
                    self.updateAppStatus(.listening)
                    self.floatingIndicator.showIndicator()
                } else {
                    self.floatingIndicator.hideIndicator()
                }
            }
            .store(in: &cancellables)
    }

    // =========================================================
    // Backend server lifecycle
    // =========================================================

    private func startBackendServer() {
        guard let binaryURL = backendBinaryURL() else {
            NSLog("[AppManager] backend binary not found in bundle")
            DispatchQueue.main.async { self.localBackendClient.isBackendAvailable = false }
            return
        }

        NSLog("[AppManager] launching backend: \(binaryURL.path)")

        let process = Process()
        process.executableURL = binaryURL
        // Pass the Resources dir so server.py can locate sibling files if needed
        process.currentDirectoryURL = binaryURL.deletingLastPathComponent()
        process.standardOutput = FileHandle.nullDevice
        process.standardError  = FileHandle.nullDevice

        do {
            try process.run()
        } catch {
            NSLog("[AppManager] failed to launch backend: \(error)")
            DispatchQueue.main.async { self.localBackendClient.isBackendAvailable = false }
            return
        }

        backendProcess = process
        NSLog("[AppManager] backend PID \(process.processIdentifier) started")

        // Poll /ping until the server is ready (max 15 s)
        waitForBackend(attempts: 30, interval: 0.5)
    }

    private func backendBinaryURL() -> URL? {
        // Bundled binary lives at:
        // Whispr.app/Contents/Resources/backend/backend
        guard let resourcesURL = Bundle.main.resourceURL else { return nil }
        let candidate = resourcesURL
            .appendingPathComponent("backend")
            .appendingPathComponent("backend")
        return FileManager.default.fileExists(atPath: candidate.path) ? candidate : nil
    }

    private func waitForBackend(attempts: Int, interval: TimeInterval) {
        guard attempts > 0 else {
            NSLog("[AppManager] backend did not become ready in time")
            DispatchQueue.main.async { self.localBackendClient.isBackendAvailable = false }
            return
        }
        localBackendClient.ping { [weak self] ready in
            guard let self else { return }
            if ready {
                NSLog("[AppManager] backend ready")
                DispatchQueue.main.async {
                    self.localBackendClient.isBackendAvailable = true
                    // Kick off dictionary update in background
                    DispatchQueue.global(qos: .background).async {
                        self.localBackendClient.runDictionaryUpdate { result in
                            switch result {
                            case .success(let update):
                                if update.totalTerms > 0 {
                                    NSLog("[AppManager] dictionary: \(update.added.count) added, \(update.totalTerms) total")
                                }
                            case .failure(let error):
                                NSLog("[AppManager] dictionary update skipped: \(error.localizedDescription)")
                            }
                        }
                    }
                }
            } else {
                DispatchQueue.global().asyncAfter(deadline: .now() + interval) { [weak self] in
                    self?.waitForBackend(attempts: attempts - 1, interval: interval)
                }
            }
        }
    }

    func stopBackendServer() {
        guard let process = backendProcess, process.isRunning else { return }
        process.terminate()
        NSLog("[AppManager] backend terminated")
        backendProcess = nil
    }

    // =========================================================
    // Dictionary update (called from menu)
    // =========================================================

    func updateDictionary() {
        guard localBackendClient.isBackendAvailable else {
            showErrorAlert(message: "Backend is not available")
            return
        }
        updateAppStatus(.processing)
        localBackendClient.runDictionaryUpdate { [weak self] result in
            guard let self else { return }
            DispatchQueue.main.async {
                switch result {
                case .success(let update):
                    self.updateAppStatus(.idle)
                    let alert = NSAlert()
                    alert.messageText = "Dictionary Updated"

                    var lines: [String] = []
                    lines.append("Total terms: \(update.totalTerms)")
                    if !update.added.isEmpty {
                        lines.append("\nNewly added (\(update.added.count)):")
                        for term in update.added {
                            var line = "  • \(term.phrase) [\(term.type)]"
                            if !term.aliases.isEmpty {
                                line += " — aliases: \(term.aliases.joined(separator: ", "))"
                            }
                            lines.append(line)
                        }
                    }
                    if update.added.isEmpty {
                        lines.append("\nNo new terms were added this run.")
                    }
                    alert.informativeText = lines.joined(separator: "\n")
                    alert.addButton(withTitle: "OK")
                    alert.runModal()

                case .failure(let error):
                    self.updateAppStatus(.error)
                    self.showErrorAlert(message: "Dictionary update failed: \(error.localizedDescription)")
                }
            }
        }
    }

    // =========================================================
    // App detection / recording / processing
    // (unchanged from original)
    // =========================================================

    func detectCurrentApp() {
        let appName = activeAppDetector.getActiveAppName()
        DispatchQueue.main.async { self.currentActiveApp = appName }
    }

    func updateAppStatus(_ status: AppStatus) {
        DispatchQueue.main.async {
            self.appStatus = status
            MenuBarController.shared.updateIcon(status.menuBarIcon)
        }
    }

    func startRecordingFromMenu() {
        detectCurrentApp()
        startRecording()
    }

    private func startRecording() {
        guard localBackendClient.isBackendAvailable else {
            updateAppStatus(.error)
            showErrorAlert(message: "Backend is not available")
            return
        }
        do {
            try audioRecorder.startRecording()
        } catch {
            updateAppStatus(.error)
            showErrorAlert(message: "Failed to start recording: \(error.localizedDescription)")
        }
    }

    func stopRecordingAndProcess() {
        guard let audioFileURL = audioRecorder.stopRecording() else {
            updateAppStatus(.error)
            showErrorAlert(message: "No audio file recorded")
            return
        }

        updateAppStatus(.processing)

        localBackendClient.transcribeAudio(
            fileURL: audioFileURL,
            appName: currentActiveApp
        ) { [weak self] result in
            guard let self else { return }
            DispatchQueue.main.async {
                switch result {
                case .success(let text):
                    self.lastOutputText = text
                    self.updateAppStatus(.idle)
                    self.pasteTextToActiveApp(text: text)
                case .failure(let error):
                    self.updateAppStatus(.error)
                    self.showErrorAlert(message: "Transcription failed: \(error.localizedDescription)")
                }
                try? FileManager.default.removeItem(at: audioFileURL)
            }
        }
    }

    // =========================================================
    // Alerts
    // =========================================================

    func showPermissionAlert() {
        let alert = NSAlert()
        alert.messageText    = "Microphone Permission Required"
        alert.informativeText = "Whispr needs microphone access. Please enable it in System Settings > Privacy & Security > Microphone."
        alert.addButton(withTitle: "Open Settings")
        alert.addButton(withTitle: "Cancel")
        if alert.runModal() == .alertFirstButtonReturn,
           let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") {
            NSWorkspace.shared.open(url)
        }
    }

    func showErrorAlert(message: String) {
        let alert = NSAlert()
        alert.messageText    = "Error"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    // =========================================================
    // Paste to active app (unchanged)
    // =========================================================

    private func pasteTextToActiveApp(text: String) {
        let pasteboard    = NSPasteboard.general
        let previousItems = pasteboard.pasteboardItems

        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)

        let source  = CGEventSource(stateID: .hidSystemState)
        let keyDown = CGEvent(keyboardEventSource: source, virtualKey: 0x09, keyDown: true)
        keyDown?.flags = .maskCommand
        keyDown?.post(tap: .cghidEventTap)

        let keyUp = CGEvent(keyboardEventSource: source, virtualKey: 0x09, keyDown: false)
        keyUp?.flags = .maskCommand
        keyUp?.post(tap: .cghidEventTap)

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            pasteboard.clearContents()
            previousItems?.forEach { item in
                for type in item.types {
                    if let data = item.data(forType: type) {
                        pasteboard.setData(data, forType: type)
                    }
                }
            }
        }
    }
}
