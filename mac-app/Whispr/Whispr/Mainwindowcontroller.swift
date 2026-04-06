import AppKit
import SwiftUI
import Combine

// =========================================================
// MainWindowController
// Single persistent NSWindow with sidebar + content pane.
// =========================================================

final class MainWindowController: NSObject {
    static let shared = MainWindowController()

    private var window: NSWindow?
    @Published var selectedNav: NavItem = .home

    private override init() {}

    // MARK: - Show / hide

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

    // MARK: - Window construction

    private func buildWindow() {
        let splitVC = NSSplitViewController()
        splitVC.splitView.isVertical = true
        splitVC.splitView.dividerStyle = .thin

        let sidebarHost = NSHostingController(rootView: SidebarView(controller: self))
        let sidebarItem = NSSplitViewItem(sidebarWithViewController: sidebarHost)
        sidebarItem.minimumThickness = 220
        sidebarItem.maximumThickness = 220
        sidebarItem.canCollapse = false
        splitVC.addSplitViewItem(sidebarItem)

        let contentHost = NSHostingController(rootView: NavigationContentView(controller: self))
        let contentItem = NSSplitViewItem(viewController: contentHost)
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
        self.window = win
    }
}

// =========================================================
// Nav items
// =========================================================

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

// =========================================================
// NavigationContentView
// =========================================================

struct NavigationContentView: View {
    let controller: MainWindowController
    @State private var currentNav: NavItem = .home

    var body: some View {
        Group {
            switch currentNav {
            case .home:
                HomeView()
            case .history:
                HistoryView(backendClient: AppManager.shared.localBackendClient)
            case .dictionary:
                DictionaryView(backendClient: AppManager.shared.localBackendClient)
            case .snippets:
                SnippetsView(backendClient: AppManager.shared.localBackendClient)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onReceive(controller.$selectedNav) { currentNav = $0 }
    }
}

// =========================================================
// SidebarView
// =========================================================

struct SidebarView: View {
    let controller: MainWindowController

    @State private var selectedNav      : NavItem = .home
    @State private var selectedLanguage : String  = Config.targetLanguage
    @State private var syncStatus       : String  = ""
    @State private var calendarEmail    : String  = "Not connected"

    // Data-management action states
    @State private var clearingHistory    : ClearState = .idle
    @State private var clearingDictionary : ClearState = .idle
    @State private var clearingSnippets   : ClearState = .idle
    @State private var resettingProfile   : ClearState = .idle

    // Confirmation alert
    @State private var pendingClear : DataClearAction? = nil
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

            // ── Inline settings ───────────────────────────────
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {

                    // MARK: Hotkeys
                    SettingsSection(title: "Hotkeys") {
                        HotkeyRow(label: "Start", keys: ["⌥", "Space"])
                        HotkeyRow(label: "Stop",  keys: ["⌥", "S"])
                    }

                    Divider().padding(.vertical, 10)

                    // MARK: Output language
                    SettingsSection(title: "Output language") {
                        Picker("", selection: $selectedLanguage) {
                            ForEach(Config.supportedLanguages, id: \.self) { Text($0).tag($0) }
                        }
                        .pickerStyle(.menu)
                        .labelsHidden()
                        .onChange(of: selectedLanguage) { newValue in
                            Config.targetLanguage = newValue
                            syncStatus = "Saving..."
                            backendClient.syncLanguageToBackend { success in
                                syncStatus = success ? "Saved" : "Saved locally"
                                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { syncStatus = "" }
                            }
                        }
                        if !syncStatus.isEmpty {
                            Text(syncStatus).font(.caption2).foregroundColor(.secondary)
                        }
                    }

                    Divider().padding(.vertical, 10)

                    // MARK: Google Calendar
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
                        if calendarEmail == "Not connected" || calendarEmail == "Connecting..." {
                            Button("Connect") { connectCalendar() }
                                .buttonStyle(.borderedProminent)
                                .controlSize(.small)
                                .tint(Color(red: 0.498, green: 0.467, blue: 0.867))
                                .disabled(calendarEmail == "Connecting...")
                        } else {
                            HStack(spacing: 6) {
                                Button("Switch")     { connectCalendar() }.buttonStyle(.bordered).controlSize(.small)
                                Button("Disconnect") { disconnectCalendar() }
                                    .buttonStyle(.bordered).controlSize(.small).foregroundColor(.red)
                            }
                        }
                    }

                    Divider().padding(.vertical, 10)

                    // MARK: Data Management ──────────────────────────────────
                    SettingsSection(title: "Data Management") {
                        VStack(spacing: 5) {
                            ClearRow(
                                label:  "Transcription history",
                                state:  clearingHistory
                            ) {
                                armClear(.history)
                            }
                            ClearRow(
                                label:  "Personal dictionary",
                                state:  clearingDictionary
                            ) {
                                armClear(.dictionary)
                            }
                            ClearRow(
                                label:  "Voice snippets",
                                state:  clearingSnippets
                            ) {
                                armClear(.snippets)
                            }
                            ClearRow(
                                label:  "Profile & learned context",
                                state:  resettingProfile
                            ) {
                                armClear(.profile)
                            }

                            // Reset all — full-width red button
                            Button {
                                armClear(.all)
                            } label: {
                                HStack(spacing: 5) {
                                    Image(systemName: "trash")
                                        .font(.system(size: 10))
                                    Text("Reset All Data")
                                        .font(.system(size: 11, weight: .medium))
                                }
                                .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .foregroundColor(.red)
                            .padding(.top, 3)
                        }
                    }
                    // ── Confirmation alert ─────────────────────────────────
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

                    Divider().padding(.vertical, 10)

                    // MARK: Backend info
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Backend: local Python CLI")
                        Text("Recording: .wav file")
                        HStack(spacing: 4) {
                            Circle()
                                .fill(backendClient.isBackendAvailable ? Color.green : Color.red)
                                .frame(width: 6, height: 6)
                            Text(backendClient.isBackendAvailable ? "Available" : "Unavailable")
                        }
                    }
                    .font(.system(size: 10))
                    .foregroundColor(.secondary)
                    .padding(.horizontal, 14)
                    .padding(.bottom, 16)
                }
                .padding(.top, 10)
            }

            Spacer()
            Divider()

            VStack(alignment: .leading, spacing: 0) {
                SidebarBottomRow(icon: "questionmark.circle", label: "Help", isDestructive: false) {}
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
                if let lang, Config.supportedLanguages.contains(lang) {
                    DispatchQueue.main.async {
                        selectedLanguage = lang
                        Config.targetLanguage = lang
                    }
                }
            }
        }
        .onReceive(controller.$selectedNav) { selectedNav = $0 }
    }

    // =========================================================
    // Calendar helpers (unchanged)
    // =========================================================

    private func loadCalendarEmail() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            backendClient.fetchCalendarEmail { email in
                DispatchQueue.main.async { calendarEmail = email ?? "Not connected" }
            }
        }
    }
    private func connectCalendar() {
        calendarEmail = "Connecting..."
        backendClient.connectGoogleCalendar { email in
            DispatchQueue.main.async { calendarEmail = email ?? "Not connected" }
        }
    }
    private func disconnectCalendar() {
        backendClient.disconnectGoogleCalendar { _ in
            DispatchQueue.main.async { calendarEmail = "Not connected" }
        }
    }

    // =========================================================
    // Data-management helpers
    // =========================================================

    private func armClear(_ action: DataClearAction) {
        pendingClear  = action
        showClearAlert = true
    }

    private func executeClear(_ action: DataClearAction) {
        switch action {
        case .history:
            clearingHistory = .running
            backendClient.clearHistory { ok in
                clearingHistory = ok ? .done : .failed
                resetState(&clearingHistory)
            }
        case .dictionary:
            clearingDictionary = .running
            backendClient.clearDictionary { ok in
                clearingDictionary = ok ? .done : .failed
                resetState(&clearingDictionary)
            }
        case .snippets:
            clearingSnippets = .running
            backendClient.clearSnippets { ok in
                clearingSnippets = ok ? .done : .failed
                resetState(&clearingSnippets)
            }
        case .profile:
            resettingProfile = .running
            backendClient.resetProfile { ok in
                resettingProfile = ok ? .done : .failed
                resetState(&resettingProfile)
            }
        case .all:
            clearingHistory    = .running
            clearingDictionary = .running
            clearingSnippets   = .running
            resettingProfile   = .running
            backendClient.resetAll { ok in
                let state: ClearState = ok ? .done : .failed
                clearingHistory    = state
                clearingDictionary = state
                clearingSnippets   = state
                resettingProfile   = state
                resetState(&clearingHistory)
                resetState(&clearingDictionary)
                resetState(&clearingSnippets)
                resetState(&resettingProfile)
            }
        }
    }

    private func resetState(_ state: inout ClearState) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            if state == .done || state == .failed { state = .idle }
        }
    }
}

// =========================================================
// ClearRow — a single data-delete row inside the sidebar
// =========================================================

private struct ClearRow: View {
    let label  : String
    let state  : ClearState
    let action : () -> Void

    var body: some View {
        HStack(spacing: 6) {
            // State indicator / label
            Group {
                switch state {
                case .idle:
                    Text(label)
                        .font(.system(size: 12))
                        .foregroundColor(.primary)
                case .running:
                    HStack(spacing: 4) {
                        ProgressView().scaleEffect(0.55)
                        Text(label)
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                    }
                case .done:
                    HStack(spacing: 4) {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.system(size: 10))
                            .foregroundColor(.green)
                        Text(label)
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                    }
                case .failed:
                    HStack(spacing: 4) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.system(size: 10))
                            .foregroundColor(.red)
                        Text(label)
                            .font(.system(size: 12))
                            .foregroundColor(.red)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // Clear button — only shown when idle or after result
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
        .overlay(
            RoundedRectangle(cornerRadius: 6)
                .stroke(Color.secondary.opacity(0.15), lineWidth: 0.5)
        )
    }
}

// =========================================================
// Supporting enums
// =========================================================

enum ClearState: Equatable {
    case idle, running, done, failed
}

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
        case .history:
            return "All past transcriptions will be permanently deleted."
        case .dictionary:
            return "Every custom term and alias will be removed. This cannot be undone."
        case .snippets:
            return "All voice snippet shortcuts will be deleted. This cannot be undone."
        case .profile:
            return "Your name, organisation, role and AI-learned context will be cleared. Your language preference is kept."
        case .all:
            return "History, dictionary, snippets and profile will all be permanently deleted. Your language preference is kept. This cannot be undone."
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

// =========================================================
// Sidebar sub-components (unchanged)
// =========================================================

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
                        .overlay(RoundedRectangle(cornerRadius: 4)
                            .stroke(Color.secondary.opacity(0.3), lineWidth: 0.5))
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
