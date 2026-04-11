import AppKit
import SwiftUI
import Combine

final class MainWindowController: NSObject {
    static let shared = MainWindowController()

    private var window: NSWindow?
    @Published var selectedNav: NavItem = .home

    private override init() {}

    func showWindow() {
        if let existing = window {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        buildWindow()
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func navigate(to item: NavItem) {
        selectedNav = item
        showWindow()
    }

    private func buildWindow() {
        let splitVC = NSSplitViewController()
        splitVC.splitView.isVertical = true
        splitVC.splitView.dividerStyle = .thin

        let sidebarItem = NSSplitViewItem(sidebarWithViewController:
            NSHostingController(rootView: SidebarView(controller: self)))
        sidebarItem.minimumThickness = 220
        sidebarItem.maximumThickness = 220
        sidebarItem.canCollapse = false
        splitVC.addSplitViewItem(sidebarItem)

        let contentItem = NSSplitViewItem(viewController:
            NSHostingController(rootView: NavigationContentView(controller: self)))
        contentItem.minimumThickness = 480
        splitVC.addSplitViewItem(contentItem)

        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 980, height: 720),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        win.title = "Whispr"
        win.contentViewController = splitVC
        win.isReleasedWhenClosed = false
        win.minSize = NSSize(width: 820, height: 580)
        win.center()
        window = win
    }
}

// MARK: - Nav

enum NavItem: String, CaseIterable {
    case home       = "Home"
    case history    = "History"
    case dictionary = "Dictionary"
    case snippets   = "Snippets"

    var icon: String {
        switch self {
        case .home:       return "house"
        case .history:    return "clock"
        case .dictionary: return "book.closed"
        case .snippets:   return "text.bubble"
        }
    }
}

// MARK: - NavigationContentView

struct NavigationContentView: View {
    let controller: MainWindowController
    @State private var currentNav: NavItem = .home

    var body: some View {
        Group {
            switch currentNav {
            case .home:       HomeView()
            case .history:    HistoryView(backendClient: AppManager.shared.localBackendClient)
            case .dictionary: DictionaryView(backendClient: AppManager.shared.localBackendClient)
            case .snippets:   SnippetsView(backendClient: AppManager.shared.localBackendClient)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onReceive(controller.$selectedNav) { currentNav = $0 }
    }
}

// MARK: - SidebarView

struct SidebarView: View {
    let controller: MainWindowController

    @State private var selectedNav      : NavItem = .home
    @State private var selectedLanguage : String  = LanguageManager.shared.current
    @State private var syncStatus       : String  = ""
    @State private var calendarEmail    : String  = "Not connected"

    @State private var clearingHistory    : ClearState = .idle
    @State private var clearingDictionary : ClearState = .idle
    @State private var clearingSnippets   : ClearState = .idle
    @State private var resettingProfile   : ClearState = .idle

    @State private var pendingClear   : DataClearAction? = nil
    @State private var showClearAlert : Bool = false

    private var backendClient: LocalBackendClient { AppManager.shared.localBackendClient }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {

            // ── Brand ─────────────────────────────────────────
            HStack(spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 7)
                        .fill(Color(red: 0.498, green: 0.467, blue: 0.867))
                        .frame(width: 28, height: 28)
                    Image(systemName: "mic.fill")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(.white)
                }
                Text("Whispr").font(.system(size: 15, weight: .medium))
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)

            Divider()

            // ── Nav ───────────────────────────────────────────
            VStack(alignment: .leading, spacing: 1) {
                Text("Menu")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundColor(.secondary)
                    .padding(.horizontal, 18)
                    .padding(.top, 12)
                    .padding(.bottom, 4)

                ForEach(NavItem.allCases, id: \.self) { item in
                    NavRow(item: item, isSelected: selectedNav == item) {
                        selectedNav = item
                        controller.navigate(to: item)
                    }
                }
            }

            Divider().padding(.top, 8)

            // ── Settings ──────────────────────────────────────
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {

                    SettingsSection(title: "Hotkeys") {
                        HotkeyRow(label: "Start", keys: ["⌥", "Space"])
                        HotkeyRow(label: "Stop",  keys: ["⌥", "S"])
                    }

                    Divider().padding(.vertical, 10)

                    SettingsSection(title: "Output language") {
                        Picker("", selection: $selectedLanguage) {
                            ForEach(Config.supportedLanguages, id: \.self) { Text($0).tag($0) }
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                        .onChange(of: selectedLanguage) { newValue in
                            LanguageManager.shared.setLanguage(newValue)
                            MenuBarController.shared.refreshLanguageMenu()
                            syncStatus = "Saving…"
                            backendClient.syncLanguageToBackend { success in
                                DispatchQueue.main.async {
                                    syncStatus = success ? "Saved" : "Saved locally"
                                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { syncStatus = "" }
                                }
                            }
                        }
                        if !syncStatus.isEmpty {
                            Text(syncStatus).font(.caption2).foregroundColor(.secondary)
                        }
                    }

                    Divider().padding(.vertical, 10)

                    SettingsSection(title: "Google Calendar") {
                        HStack(spacing: 8) {
                            Circle()
                                .fill(calendarEmail == "Not connected" ? Color.gray : Color.green)
                                .frame(width: 7, height: 7)
                            Text(calendarEmail == "Not connected" ? "Not connected" : calendarEmail)
                                .font(.system(size: 12))
                                .foregroundColor(.secondary)
                                .lineLimit(1)
                                .truncationMode(.middle)
                        }
                        if calendarEmail == "Not connected" || calendarEmail == "Connecting…" {
                            Button("Connect") { connectCalendar() }
                                .buttonStyle(.borderedProminent)
                                .controlSize(.small)
                                .tint(Color(red: 0.498, green: 0.467, blue: 0.867))
                                .disabled(calendarEmail == "Connecting…")
                        } else {
                            HStack(spacing: 6) {
                                Button("Switch")     { connectCalendar() }.buttonStyle(.bordered).controlSize(.small)
                                Button("Disconnect") { disconnectCalendar() }
                                    .buttonStyle(.bordered).controlSize(.small).foregroundColor(.red)
                            }
                        }
                    }

                    Divider().padding(.vertical, 10)

                    SettingsSection(title: "Data Management") {
                        VStack(spacing: 5) {
                            ClearRow(label: "Transcription history", state: clearingHistory)   { armClear(.history) }
                            ClearRow(label: "Personal dictionary",   state: clearingDictionary) { armClear(.dictionary) }
                            ClearRow(label: "Voice snippets",        state: clearingSnippets)   { armClear(.snippets) }
                            ClearRow(label: "Profile & learned context", state: resettingProfile) { armClear(.profile) }

                            Button { armClear(.all) } label: {
                                HStack(spacing: 5) {
                                    Image(systemName: "trash").font(.system(size: 10))
                                    Text("Reset All Data").font(.system(size: 11, weight: .medium))
                                }
                                .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .foregroundColor(.red)
                            .padding(.top, 3)
                        }
                    }
                    .alert(
                        pendingClear?.alertTitle ?? "Confirm",
                        isPresented: $showClearAlert,
                        presenting: pendingClear
                    ) { action in
                        Button("Cancel", role: .cancel) { pendingClear = nil }
                        Button(action.confirmLabel, role: .destructive) {
                            executeClear(action)
                            pendingClear = nil
                        }
                    } message: { action in
                        Text(action.alertMessage)
                    }
                }
                .padding(.top, 10)
            }

            Spacer()
            Divider()

            VStack(alignment: .leading, spacing: 0) {
                SidebarBottomRow(icon: "questionmark.circle", label: "Help") {}
                SidebarBottomRow(icon: "power", label: "Quit Whispr", isDestructive: true) {
                    NSApp.terminate(nil)
                }
            }
            .padding(.vertical, 8)
        }
        .frame(width: 220)
        .background(Color(NSColor.controlBackgroundColor))
        .onAppear {
            loadCalendarEmail()
            backendClient.fetchLanguageFromBackend { lang in
                DispatchQueue.main.async {
                    LanguageManager.shared.syncFromBackend(lang)
                    selectedLanguage = LanguageManager.shared.current
                    MenuBarController.shared.refreshLanguageMenu()
                }
            }
        }
        .onReceive(controller.$selectedNav) { selectedNav = $0 }
        .onReceive(LanguageManager.shared.$current) { selectedLanguage = $0 }
    }

    // MARK: - Calendar

    private func loadCalendarEmail() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            backendClient.fetchCalendarEmail { email in
                DispatchQueue.main.async { calendarEmail = email ?? "Not connected" }
            }
        }
    }

    private func connectCalendar() {
        calendarEmail = "Connecting…"
        backendClient.connectGoogleCalendar { email in
            DispatchQueue.main.async { calendarEmail = email ?? "Not connected" }
        }
    }

    private func disconnectCalendar() {
        backendClient.disconnectGoogleCalendar { _ in
            DispatchQueue.main.async { calendarEmail = "Not connected" }
        }
    }

    // MARK: - Data management

    private func armClear(_ action: DataClearAction) {
        pendingClear = action
        showClearAlert = true
    }

    private func executeClear(_ action: DataClearAction) {
        switch action {
        case .history:
            clearingHistory = .running
            backendClient.clearHistory { ok in
                self.clearingHistory = ok ? .done : .failed
                self.scheduleReset { self.clearingHistory = .idle }
            }
        case .dictionary:
            clearingDictionary = .running
            backendClient.clearDictionary { ok in
                self.clearingDictionary = ok ? .done : .failed
                self.scheduleReset { self.clearingDictionary = .idle }
            }
        case .snippets:
            clearingSnippets = .running
            backendClient.clearSnippets { ok in
                self.clearingSnippets = ok ? .done : .failed
                self.scheduleReset { self.clearingSnippets = .idle }
            }
        case .profile:
            resettingProfile = .running
            backendClient.resetProfile { ok in
                self.resettingProfile = ok ? .done : .failed
                self.scheduleReset { self.resettingProfile = .idle }
            }
        case .all:
            clearingHistory = .running; clearingDictionary = .running
            clearingSnippets = .running; resettingProfile = .running
            backendClient.resetAll { ok in
                let s: ClearState = ok ? .done : .failed
                self.clearingHistory = s; self.clearingDictionary = s
                self.clearingSnippets = s; self.resettingProfile = s
                self.scheduleReset { self.clearingHistory = .idle }
                self.scheduleReset { self.clearingDictionary = .idle }
                self.scheduleReset { self.clearingSnippets = .idle }
                self.scheduleReset { self.resettingProfile = .idle }
            }
        }
    }

    private func scheduleReset(_ reset: @escaping () -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 3, execute: reset)
    }
}

// MARK: - ClearRow

private struct ClearRow: View {
    let label  : String
    let state  : ClearState
    let action : () -> Void

    var body: some View {
        HStack(spacing: 6) {
            Group {
                switch state {
                case .idle:
                    Text(label).font(.system(size: 12)).foregroundColor(.primary)
                case .running:
                    HStack(spacing: 4) {
                        ProgressView().scaleEffect(0.55)
                        Text(label).font(.system(size: 12)).foregroundColor(.secondary)
                    }
                case .done:
                    HStack(spacing: 4) {
                        Image(systemName: "checkmark.circle.fill").font(.system(size: 10)).foregroundColor(.green)
                        Text(label).font(.system(size: 12)).foregroundColor(.secondary)
                    }
                case .failed:
                    HStack(spacing: 4) {
                        Image(systemName: "xmark.circle.fill").font(.system(size: 10)).foregroundColor(.red)
                        Text(label).font(.system(size: 12)).foregroundColor(.red)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Button("Clear") { action() }
                .buttonStyle(.plain)
                .font(.system(size: 11))
                .foregroundColor(.red)
                .disabled(state == .running)
                .opacity(state == .running ? 0 : 1)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(Color(NSColor.textBackgroundColor))
        .cornerRadius(6)
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.15), lineWidth: 0.5))
    }
}

// MARK: - Supporting enums

enum ClearState: Equatable { case idle, running, done, failed }

private enum DataClearAction {
    case history, dictionary, snippets, profile, all

    var alertTitle: String {
        switch self {
        case .history:    return "Clear Transcription History?"
        case .dictionary: return "Clear Personal Dictionary?"
        case .snippets:   return "Clear Voice Snippets?"
        case .profile:    return "Reset Profile?"
        case .all:        return "Reset All Data?"
        }
    }

    var alertMessage: String {
        switch self {
        case .history:    return "All past transcriptions will be permanently deleted."
        case .dictionary: return "Every custom term and alias will be removed. This cannot be undone."
        case .snippets:   return "All voice snippet shortcuts will be deleted. This cannot be undone."
        case .profile:    return "Your name, organisation, role and AI-learned context will be cleared. Your language preference is kept."
        case .all:        return "History, dictionary, snippets and profile will all be permanently deleted. Your language preference is kept."
        }
    }

    var confirmLabel: String {
        switch self {
        case .history:    return "Clear History"
        case .dictionary: return "Clear Dictionary"
        case .snippets:   return "Clear Snippets"
        case .profile:    return "Reset Profile"
        case .all:        return "Reset Everything"
        }
    }
}

// MARK: - Sidebar sub-components

struct NavRow: View {
    let item: NavItem; let isSelected: Bool; let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Image(systemName: item.icon).font(.system(size: 13)).frame(width: 16)
                Text(item.rawValue).font(.system(size: 13, weight: isSelected ? .medium : .regular))
                Spacer()
            }
            .foregroundColor(isSelected ? .primary : .secondary)
            .padding(.horizontal, 10).padding(.vertical, 7)
            .background(RoundedRectangle(cornerRadius: 6)
                .fill(isSelected ? Color(NSColor.selectedContentBackgroundColor).opacity(0.15) : Color.clear))
            .overlay(Rectangle().fill(Color(red: 0.498, green: 0.467, blue: 0.867))
                .frame(width: 2).opacity(isSelected ? 1 : 0), alignment: .leading)
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 8)
    }
}

struct SettingsSection<Content: View>: View {
    let title: String; @ViewBuilder let content: () -> Content
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 10, weight: .medium)).foregroundColor(.secondary)
                .textCase(.uppercase).tracking(0.5).padding(.horizontal, 14)
            VStack(alignment: .leading, spacing: 4) { content() }.padding(.horizontal, 12)
        }
    }
}

struct HotkeyRow: View {
    let label: String; let keys: [String]
    var body: some View {
        HStack {
            Text(label).font(.system(size: 12))
            Spacer()
            HStack(spacing: 3) {
                ForEach(keys, id: \.self) { key in
                    Text(key).font(.system(size: 10, design: .monospaced))
                        .padding(.horizontal, 5).padding(.vertical, 2)
                        .background(Color(NSColor.controlBackgroundColor))
                        .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color.secondary.opacity(0.3), lineWidth: 0.5))
                        .cornerRadius(4)
                }
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .background(Color(NSColor.textBackgroundColor))
        .cornerRadius(6)
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.15), lineWidth: 0.5))
    }
}

struct SidebarBottomRow: View {
    let icon: String; let label: String; var isDestructive: Bool = false; let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Image(systemName: icon).font(.system(size: 12)).frame(width: 16)
                Text(label).font(.system(size: 12))
                Spacer()
            }
            .foregroundColor(isDestructive ? .red : .secondary)
            .padding(.horizontal, 18).padding(.vertical, 6)
        }
        .buttonStyle(.plain)
    }
}
