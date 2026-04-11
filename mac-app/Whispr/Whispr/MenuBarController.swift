import AppKit
import SwiftUI
import Combine

final class MenuBarController: NSObject, NSMenuDelegate {
    static let shared = MenuBarController()

    private let statusItem: NSStatusItem
    private var cancellables = Set<AnyCancellable>()
    private var calendarMenuItem: NSMenuItem?
    private var languageMenuItems: [NSMenuItem] = []

    private var backendClient: LocalBackendClient {
        AppManager.shared.localBackendClient
    }

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

        // ── Status info (read-only) ───────────────────────────
        let statusMenuItem = NSMenuItem(title: "Status: Idle", action: nil, keyEquivalent: "")
        let currentAppItem = NSMenuItem(title: "Current App: Unknown", action: nil, keyEquivalent: "")
        let lastResultItem = NSMenuItem(title: "Last Result: No transcription yet", action: nil, keyEquivalent: "")
        statusMenuItem.isEnabled = false
        currentAppItem.isEnabled = false
        lastResultItem.isEnabled = false
        menu.addItem(statusMenuItem)
        menu.addItem(currentAppItem)
        menu.addItem(lastResultItem)
        menu.addItem(.separator())

        // ── Recording ─────────────────────────────────────────
        let startItem = NSMenuItem(title: "Start Recording", action: #selector(startRecording), keyEquivalent: "r")
        startItem.target = self
        menu.addItem(startItem)

        let stopItem = NSMenuItem(title: "Stop Recording", action: #selector(stopRecording), keyEquivalent: "s")
        stopItem.target = self
        menu.addItem(stopItem)
        menu.addItem(.separator())

        // ── Output language submenu ───────────────────────────
        let languageMenu = NSMenu()
        languageMenuItems.removeAll()
        for lang in Config.supportedLanguages {
            let item = NSMenuItem(title: lang, action: #selector(selectLanguage(_:)), keyEquivalent: "")
            item.target = self
            languageMenu.addItem(item)
            languageMenuItems.append(item)
        }
        let languageParent = NSMenuItem(title: "Output Language", action: nil, keyEquivalent: "")
        languageParent.submenu = languageMenu
        menu.addItem(languageParent)
        refreshLanguageMenu()

        // ── Dictionary ────────────────────────────────────────
        let updateDictItem = NSMenuItem(title: "Update Dictionary", action: #selector(updateDictionary), keyEquivalent: "d")
        updateDictItem.target = self
        menu.addItem(updateDictItem)

        // ── Google Calendar ───────────────────────────────────
        let calItem = NSMenuItem(title: "Connect Google Calendar", action: #selector(toggleCalendar), keyEquivalent: "")
        calItem.target = self
        menu.addItem(calItem)
        calendarMenuItem = calItem
        menu.addItem(.separator())

        // ── Open / Quit ───────────────────────────────────────
        let openItem = NSMenuItem(title: "Open Whispr", action: #selector(openMainWindow), keyEquivalent: "o")
        openItem.target = self
        menu.addItem(openItem)
        menu.addItem(.separator())

        let quitItem = NSMenuItem(title: "Quit Whispr", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        // ── Reactive bindings ─────────────────────────────────
        AppManager.shared.$appStatus
            .receive(on: DispatchQueue.main)
            .sink { status in
                switch status {
                case .idle:       statusMenuItem.title = "Status: Idle"
                case .listening:  statusMenuItem.title = "Status: Recording"
                case .processing: statusMenuItem.title = "Status: Processing"
                case .error:      statusMenuItem.title = "Status: Error"
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
                    : "Last Result: \(String(text.prefix(60)))\(text.count > 60 ? "…" : "")"
            }
            .store(in: &cancellables)

        LanguageManager.shared.$current
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.refreshLanguageMenu() }
            .store(in: &cancellables)

        statusItem.menu = menu
        menu.delegate = self
        refreshCalendarLabel()
    }

    // Capture the frontmost app before the menu steals focus,
    // so paste always targets the right window.
    func menuWillOpen(_ menu: NSMenu) {
        AppManager.shared.detectCurrentApp()
    }

    // MARK: - Language

    func refreshLanguageMenu() {
        let lang = LanguageManager.shared.current
        languageMenuItems.forEach { $0.state = ($0.title == lang) ? .on : .off }
    }

    @objc private func selectLanguage(_ sender: NSMenuItem) {
        guard Config.supportedLanguages.contains(sender.title) else { return }
        LanguageManager.shared.setLanguage(sender.title)
        refreshLanguageMenu()
        backendClient.syncLanguageToBackend { _ in }
    }

    // MARK: - Calendar

    @objc private func toggleCalendar() {
        let isConnected = calendarMenuItem?.title.hasPrefix("Disconnect") ?? false
        if isConnected {
            calendarMenuItem?.title = "Disconnecting…"
            backendClient.disconnectGoogleCalendar { [weak self] _ in
                DispatchQueue.main.async {
                    self?.calendarMenuItem?.title = "Connect Google Calendar"
                }
            }
        } else {
            calendarMenuItem?.title = "Connecting…"
            backendClient.connectGoogleCalendar { [weak self] email in
                DispatchQueue.main.async {
                    if let email {
                        self?.calendarMenuItem?.title = "Disconnect Google Calendar (\(email))"
                    } else {
                        self?.calendarMenuItem?.title = "Connect Google Calendar"
                    }
                }
            }
        }
    }

    private func refreshCalendarLabel() {
        backendClient.fetchCalendarEmail { [weak self] email in
            DispatchQueue.main.async {
                if let email {
                    self?.calendarMenuItem?.title = "Disconnect Google Calendar (\(email))"
                } else {
                    self?.calendarMenuItem?.title = "Connect Google Calendar"
                }
            }
        }
    }

    // MARK: - Actions

    @objc private func updateDictionary() { AppManager.shared.updateDictionary() }
    @objc private func startRecording()   { AppManager.shared.startRecording() }
    @objc private func stopRecording()    { AppManager.shared.stopRecordingAndProcess() }
    @objc private func openMainWindow()   { MainWindowController.shared.navigate(to: .home) }
    @objc private func quitApp()          { NSApp.terminate(nil) }
}
