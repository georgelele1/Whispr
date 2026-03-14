import Foundation
import AppKit
import Combine

final class AppManager: ObservableObject {
    static let shared = AppManager()
    private init() {}

    let hotkeyManager = HotkeyManager()
    let audioRecorder = AudioRecorder()
    let localBackendClient = LocalBackendClient()
    let activeAppDetector = ActiveAppDetector()
    let floatingIndicator = FloatingIndicator()

    @Published var appStatus: AppStatus = .idle
    @Published var lastOutputText: String = ""
    @Published var currentActiveApp: String = "Unknown"
    @Published var currentTranscriptionMode: TranscriptionMode = .generic

    private var cancellables = Set<AnyCancellable>()

    func initialize() {
        hotkeyManager.setupGlobalHotkey { [weak self] shouldStart in
            guard let self else { return }
            if shouldStart {
                self.startRecordingFromMenu()
            } else {
                self.stopRecordingAndProcess()
            }
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

    func detectCurrentAppAndMode() {
        let (appName, mode) = activeAppDetector.getActiveAppAndMode()
        DispatchQueue.main.async {
            self.currentActiveApp = appName
            self.currentTranscriptionMode = mode
        }
    }

    func updateAppStatus(_ status: AppStatus) {
        DispatchQueue.main.async {
            self.appStatus = status
            MenuBarController.shared.updateIcon(status.menuBarIcon)
        }
    }

    func startRecordingFromMenu() {
        detectCurrentAppAndMode()
        startRecording()
    }

    private func startRecording() {
        guard localBackendClient.isBackendAvailable else {
            showErrorAlert(message: "Python backend is not accessible")
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
            appName: currentActiveApp,
            mode: currentTranscriptionMode
        ) { [weak self] result in
            guard let self else { return }

            DispatchQueue.main.async {
                //defer {
                //    try? FileManager.default.removeItem(at: audioFileURL)
               // }

                switch result {
                case .success(let text):
                    self.lastOutputText = text
                    self.updateAppStatus(.idle)
                    self.pasteTextToActiveApp(text: text)

                case .failure(let error):
                    self.updateAppStatus(.error)
                    self.showErrorAlert(message: "Transcription failed: \(error.localizedDescription)")
                }
            }
        }
    }

    func showPermissionAlert() {
        let alert = NSAlert()
        alert.messageText = "Microphone Permission Required"
        alert.informativeText = "Whispr needs microphone access to record audio. Please enable it in System Settings > Privacy & Security > Microphone."
        alert.addButton(withTitle: "Open Settings")
        alert.addButton(withTitle: "Cancel")

        if alert.runModal() == .alertFirstButtonReturn,
           let settingsURL = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") {
            NSWorkspace.shared.open(settingsURL)
        }
    }

    func showErrorAlert(message: String) {
        let alert = NSAlert()
        alert.messageText = "Error"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private func pasteTextToActiveApp(text: String) {
        let pasteboard = NSPasteboard.general
        let previousItems = pasteboard.pasteboardItems

        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)

        let source = CGEventSource(stateID: .hidSystemState)
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
