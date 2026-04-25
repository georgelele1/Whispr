import AppKit
import SwiftUI
import Combine

final class MenuBarController: NSObject, NSMenuDelegate {
    static let shared = MenuBarController()

    private let statusItem: NSStatusItem
    private var cancellables = Set<AnyCancellable>()

    private var lastResultItem   : NSMenuItem?
    private var activeModelItem  : NSMenuItem?
    private var startItem        : NSMenuItem?
    private var stopItem         : NSMenuItem?
    private var languageMenuItems: [NSMenuItem] = []

    private var backendClient: LocalBackendClient { AppManager.shared.localBackendClient }

    private override init() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()
        if let button = statusItem.button {
            button.image = AppStatus.idle.menuBarIcon
            button.image?.isTemplate = true
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

    // =========================================================
    // MARK: - Menu setup
    // =========================================================

    private func setupMenu() {
        let menu = NSMenu()
        menu.delegate = self

        // ── 1. STATUS INFO ────────────────────────────────────────
        let resultItem = makeInfoItem(label: "Last result", value: "No transcription yet", icon: "text.bubble")
        resultItem.action = #selector(copyLastResult)
        resultItem.target = self
        resultItem.isEnabled = false
        menu.addItem(resultItem)
        self.lastResultItem = resultItem

        let modelItem = makeInfoItem(label: "Model", value: "…", icon: "cpu")
        modelItem.action = #selector(openAPIKeys)
        modelItem.target = self
        menu.addItem(modelItem)
        self.activeModelItem = modelItem

        menu.addItem(makeSectionSeparator(label: "RECORDING"))

        // ── 2. START / STOP ───────────────────────────────────────
        let start = NSMenuItem(title: "Start Recording", action: #selector(startRecording), keyEquivalent: "")
        start.target = self
        start.image  = icon("record.circle.fill", color: .systemGreen, size: 14)
        menu.addItem(start)
        self.startItem = start

        let stop = NSMenuItem(title: "Stop & Transcribe", action: #selector(stopRecording), keyEquivalent: "")
        stop.target    = self
        stop.image     = icon("stop.circle.fill", color: .systemRed, size: 14)
        stop.isEnabled = false
        menu.addItem(stop)
        self.stopItem = stop

        menu.addItem(makeSectionSeparator(label: "SETTINGS"))

        // ── 3. FLAT SETTINGS ITEMS ────────────────────────────────

        // Output Language submenu
        let langMenu = NSMenu()
        languageMenuItems.removeAll()
        for lang in Config.supportedLanguages {
            let item = NSMenuItem(title: lang, action: #selector(selectLanguage(_:)), keyEquivalent: "")
            item.target = self
            langMenu.addItem(item)
            languageMenuItems.append(item)
        }
        let langParent = NSMenuItem(title: "Output Language", action: nil, keyEquivalent: "")
        langParent.image   = icon("globe", color: .secondaryLabelColor, size: 13)
        langParent.submenu = langMenu
        menu.addItem(langParent)
        refreshLanguageMenu()

        let dictItem = NSMenuItem(title: "Update Dictionary", action: #selector(updateDictionary), keyEquivalent: "d")
        dictItem.target = self
        dictItem.image  = icon("text.book.closed", color: .secondaryLabelColor, size: 13)
        menu.addItem(dictItem)

        menu.addItem(.separator())

        // ── 4. SETTINGS (highlighted, above quit) ─────────────────
        let settingsItem = makeHighlightedItem(
            title:  "Settings",
            icon:   "gearshape.fill",
            color:  NSColor(red: 0.498, green: 0.467, blue: 0.867, alpha: 1),
            action: #selector(openSettings),
            key:    ","
        )
        menu.addItem(settingsItem)

        // ── 5. QUIT ───────────────────────────────────────────────
        let quitItem = NSMenuItem(title: "Quit Whispr", action: #selector(quitApp), keyEquivalent: "q")
        quitItem.target = self
        quitItem.attributedTitle = NSAttributedString(
            string: "Quit Whispr",
            attributes: [.foregroundColor: NSColor.systemRed]
        )
        quitItem.image = icon("power", color: .systemRed, size: 13)
        menu.addItem(quitItem)

        statusItem.menu = menu

        // ── Reactive bindings ─────────────────────────────────────

        AppManager.shared.$appStatus
            .receive(on: DispatchQueue.main)
            .sink { [weak self] status in self?.applyStatus(status) }
            .store(in: &cancellables)

        AppManager.shared.$lastOutputText
            .receive(on: DispatchQueue.main)
            .sink { [weak self] text in
                guard let self else { return }
                let preview = text.isEmpty
                    ? "No transcription yet"
                    : String(text.prefix(55)) + (text.count > 55 ? "…" : "")
                self.lastResultItem?.attributedTitle = self.makeInfoAttributed(label: "Last result", value: preview)
                self.lastResultItem?.isEnabled = !text.isEmpty
            }
            .store(in: &cancellables)

        Publishers.CombineLatest3(
            AppManager.shared.$lastCost,
            AppManager.shared.$lastConnectonionBalance,
            backendClient.$activeModel
        )
        .receive(on: DispatchQueue.main)
        .sink { [weak self] cost, coBalance, model in
            guard let self else { return }
            var parts = [model]
            if let cost      { parts.append(cost < 0.0001 ? "<$0.0001" : String(format: "$%.4f", cost)) }
            if let coBalance { parts.append(String(format: "$%.2f left", coBalance)) }
            self.activeModelItem?.attributedTitle = self.makeInfoAttributed(label: "Model", value: parts.joined(separator: " · "))
        }
        .store(in: &cancellables)

        LanguageManager.shared.$current
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.refreshLanguageMenu() }
            .store(in: &cancellables)
    }

    // =========================================================
    // MARK: - Helpers
    // =========================================================

    /// A visually prominent item with a filled-color icon and bold title — used for primary actions.
    private func makeHighlightedItem(
        title  : String,
        icon   : String,
        color  : NSColor,
        action : Selector?,
        key    : String
    ) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self

        // Bold title in the accent colour
        item.attributedTitle = NSAttributedString(string: title, attributes: [
            .font           : NSFont.systemFont(ofSize: 13, weight: .semibold),
            .foregroundColor: color,
        ])
        item.image = self.icon(icon, color: color, size: 14)
        return item
    }

    private func applyStatus(_ status: AppStatus) {
        startItem?.isEnabled = (status == .idle || status == .error)
        stopItem?.isEnabled  = (status == .listening)
        startItem?.image = icon("record.circle.fill",
            color: startItem?.isEnabled == true ? .systemGreen : .tertiaryLabelColor, size: 14)
    }

    func menuWillOpen(_ menu: NSMenu) {
        AppManager.shared.detectCurrentApp()
        startItem?.title = "Start Recording    \(ShortcutManager.shared.startShortcut.displayString)"
        stopItem?.title  = "Stop & Transcribe  \(ShortcutManager.shared.stopShortcut.displayString)"
    }

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

    // ── Actions ──────────────────────────────────────────────
    @objc private func updateDictionary() { AppManager.shared.updateDictionary() }
    @objc private func startRecording()   { AppManager.shared.startRecording() }
    @objc private func stopRecording()    { AppManager.shared.stopRecordingAndProcess() }
    @objc private func openSettings()     { MainWindowController.shared.navigate(to: .home) }
    @objc private func openAPIKeys()      { MainWindowController.shared.navigate(to: .apiKeys) }
    @objc private func quitApp()          { NSApp.terminate(nil) }

    @objc private func copyLastResult() {
        let text = AppManager.shared.lastOutputText
        guard !text.isEmpty else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    // ── Item builders ─────────────────────────────────────────

    private func makeInfoItem(label: String, value: String, icon iconName: String) -> NSMenuItem {
        let item = NSMenuItem()
        item.isEnabled = false
        item.image = icon(iconName, color: .tertiaryLabelColor, size: 13)
        item.attributedTitle = makeInfoAttributed(label: label, value: value)
        return item
    }

    private func makeInfoAttributed(label: String, value: String, valueColor: NSColor = .labelColor) -> NSAttributedString {
        let str = NSMutableAttributedString(
            string: label + "  ",
            attributes: [.foregroundColor: NSColor.tertiaryLabelColor, .font: NSFont.systemFont(ofSize: 11)]
        )
        str.append(NSAttributedString(
            string: value,
            attributes: [.foregroundColor: valueColor, .font: NSFont.systemFont(ofSize: 12)]
        ))
        return str
    }

    private func makeSectionSeparator(label: String) -> NSMenuItem {
        let item = NSMenuItem()
        item.isEnabled = false
        item.attributedTitle = NSAttributedString(string: label, attributes: [
            .foregroundColor: NSColor.quaternaryLabelColor,
            .font: NSFont.systemFont(ofSize: 9, weight: .semibold),
            .kern: 1.2
        ])
        return item
    }

    private func icon(_ name: String, color: NSColor, size: CGFloat) -> NSImage {
        let cfg = NSImage.SymbolConfiguration(pointSize: size, weight: .medium)
        let img = NSImage(systemSymbolName: name, accessibilityDescription: nil)?
            .withSymbolConfiguration(cfg) ?? NSImage()
        return img.tinted(color)
    }
}

private extension NSImage {
    func tinted(_ color: NSColor) -> NSImage {
        guard let copy = self.copy() as? NSImage else { return self }
        copy.lockFocus()
        color.set()
        NSRect(origin: .zero, size: copy.size).fill(using: .sourceAtop)
        copy.unlockFocus()
        copy.isTemplate = false
        return copy
    }
}
