import AppKit
import SwiftUI
import Combine

final class MenuBarController: NSObject {
    static let shared = MenuBarController()

    private let statusItem: NSStatusItem
    private var cancellables = Set<AnyCancellable>()
    private var settingsWindow: NSWindow?
    private var snippetsWindow   : NSWindow?
    private var dictionaryWindow : NSWindow?
    private var historyWindow    : NSWindow?

    private override init() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()

        if let button = statusItem.button {
            button.image = AppStatus.idle.menuBarIcon
            button.imagePosition = .imageOnly
            button.title = ""
        }

        statusItem.isVisible = true
        setupMenu()
    }

    func updateIcon(_ image: NSImage) {
        DispatchQueue.main.async {
            self.statusItem.button?.image = image
            self.statusItem.button?.image?.isTemplate = true
            self.statusItem.button?.imagePosition = .imageOnly
            self.statusItem.button?.title = ""
            self.statusItem.isVisible = true
        }
    }

    private func setupMenu() {
        let menu = NSMenu()

        let statusItemMenu = NSMenuItem(title: "Status: Idle", action: nil, keyEquivalent: "")
        let currentAppItem = NSMenuItem(title: "Current App: Unknown", action: nil, keyEquivalent: "")
        let lastResultItem = NSMenuItem(title: "Last Result: No transcription yet", action: nil, keyEquivalent: "")

        menu.addItem(statusItemMenu)
        menu.addItem(currentAppItem)
        menu.addItem(lastResultItem)

        menu.addItem(.separator())

        let startItem = NSMenuItem(title: "Start Recording", action: #selector(startRecording), keyEquivalent: "r")
        startItem.target = self
        menu.addItem(startItem)

        let stopItem = NSMenuItem(title: "Stop Recording", action: #selector(stopRecording), keyEquivalent: "s")
        stopItem.target = self
        menu.addItem(stopItem)

        menu.addItem(.separator())

        let updateDictItem = NSMenuItem(title: "Update Dictionary", action: #selector(updateDictionary), keyEquivalent: "d")
        updateDictItem.target = self
        menu.addItem(updateDictItem)

        let snippetsItem = NSMenuItem(title: "Manage Snippets", action: #selector(openSnippets), keyEquivalent: "")
        snippetsItem.target = self
        menu.addItem(snippetsItem)

        let dictionaryItem = NSMenuItem(title: "My Dictionary", action: #selector(openDictionary), keyEquivalent: "")
        dictionaryItem.target = self
        menu.addItem(dictionaryItem)

        let historyItem = NSMenuItem(title: "History", action: #selector(openHistory), keyEquivalent: "")
        historyItem.target = self
        menu.addItem(historyItem)

        let settingsItem = NSMenuItem(title: "Settings", action: #selector(openSettings), keyEquivalent: ",")
        settingsItem.target = self
        menu.addItem(settingsItem)

        menu.addItem(.separator())

        let quitItem = NSMenuItem(title: "Quit Whispr", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        AppManager.shared.$appStatus
            .receive(on: DispatchQueue.main)
            .sink { status in
                switch status {
                case .idle:       statusItemMenu.title = "Status: Idle"
                case .listening:  statusItemMenu.title = "Status: Recording"
                case .processing: statusItemMenu.title = "Status: Processing"
                case .error:      statusItemMenu.title = "Status: Error"
                }
            }
            .store(in: &cancellables)

        AppManager.shared.$currentActiveApp
            .receive(on: DispatchQueue.main)
            .sink { appName in
                currentAppItem.title = "Current App: \(appName)"
            }
            .store(in: &cancellables)

        AppManager.shared.$lastOutputText
            .receive(on: DispatchQueue.main)
            .sink { text in
                lastResultItem.title = text.isEmpty
                    ? "Last Result: No transcription yet"
                    : "Last Result: \(text)"
            }
            .store(in: &cancellables)

        statusItem.menu = menu
    }

    // =========================================================
    // Dictionary update
    // =========================================================

    @objc private func updateDictionary() {
        AppManager.shared.updateDictionary()
    }

    // =========================================================
    // Actions
    // =========================================================

    @objc private func startRecording() {
        AppManager.shared.startRecordingFromMenu()
    }

    @objc private func stopRecording() {
        AppManager.shared.stopRecordingAndProcess()
    }

    @objc private func openSettings() {
        // Reuse existing window if already open
        if let existing = settingsWindow, existing.isVisible {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        // Build the SwiftUI settings view and host it in an NSWindow
        let backendClient = AppManager.shared.localBackendClient
        let settingsView  = SettingsView(backendClient: backendClient)
        let hostingView   = NSHostingView(rootView: settingsView)

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 360),
            styleMask:   [.titled, .closable],
            backing:     .buffered,
            defer:       false
        )
        window.title           = "Whispr Settings"
        window.contentView     = hostingView
        window.isReleasedWhenClosed = false
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        settingsWindow = window
    }

    @objc private func openSnippets() {
        if let existing = snippetsWindow, existing.isVisible {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let backendClient = AppManager.shared.localBackendClient
        let snippetsView  = SnippetsView(backendClient: backendClient)
        let hostingView   = NSHostingView(rootView: snippetsView)

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 560, height: 480),
            styleMask:   [.titled, .closable, .resizable],
            backing:     .buffered,
            defer:       false
        )
        window.title                = "Voice Snippets"
        window.contentView          = hostingView
        window.isReleasedWhenClosed = false
        window.minSize              = NSSize(width: 480, height: 360)
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        snippetsWindow = window
    }

    @objc private func openDictionary() {
        if let existing = dictionaryWindow, existing.isVisible {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let view       = DictionaryView(backendClient: AppManager.shared.localBackendClient)
        let hosting    = NSHostingView(rootView: view)
        let window     = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 620, height: 520),
            styleMask:   [.titled, .closable, .resizable],
            backing:     .buffered, defer: false
        )
        window.title                = "My Dictionary"
        window.contentView          = hosting
        window.isReleasedWhenClosed = false
        window.minSize              = NSSize(width: 520, height: 380)
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        dictionaryWindow = window
    }

    @objc private func openHistory() {
        if let existing = historyWindow, existing.isVisible {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let view       = HistoryView(backendClient: AppManager.shared.localBackendClient)
        let hosting    = NSHostingView(rootView: view)
        let window     = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 680, height: 520),
            styleMask:   [.titled, .closable, .resizable],
            backing:     .buffered, defer: false
        )
        window.title                = "Transcription History"
        window.contentView          = hosting
        window.isReleasedWhenClosed = false
        window.minSize              = NSSize(width: 560, height: 400)
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        historyWindow = window
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }
}
