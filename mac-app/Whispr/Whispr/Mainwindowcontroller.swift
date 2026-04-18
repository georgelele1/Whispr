import AppKit
import SwiftUI
import Combine
import EventKit

final class MainWindowController: NSObject, ObservableObject {
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
    case shortcuts  = "Shortcuts"
    case apiKeys    = "API Keys"

    var icon: String {
        switch self {
        case .home:       return "house"
        case .history:    return "clock"
        case .dictionary: return "book.closed"
        case .snippets:   return "text.bubble"
        case .shortcuts:  return "keyboard"
        case .apiKeys:    return "key"
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
            case .shortcuts:  ShortcutsView()
            case .apiKeys:    APIKeysView(backendClient: AppManager.shared.localBackendClient)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onReceive(controller.$selectedNav) { currentNav = $0 }
        .withWhisprTour()
    }
}

// MARK: - SidebarView

struct SidebarView: View {
    let controller: MainWindowController

    @State private var selectedNav      : NavItem = .home
    @State private var selectedLanguage : String  = LanguageManager.shared.current
    @State private var syncStatus       : String  = ""
    @State private var activeModel      : String  = AppManager.shared.localBackendClient.activeModel

    // Mac Calendar permission state — read from EventKit directly
    @State private var calendarStatus: EKAuthorizationStatus = EKEventStore.authorizationStatus(for: .event)

    @State private var clearingHistory    : ClearState = .idle
    @State private var clearingDictionary : ClearState = .idle
    @State private var clearingSnippets   : ClearState = .idle
    @State private var resettingProfile   : ClearState = .idle

    @State private var pendingClear   : DataClearAction? = nil
    @State private var showClearAlert : Bool = false

    private var backendClient: LocalBackendClient { AppManager.shared.localBackendClient }

    // Convenience — is calendar access fully granted?
    private var calendarGranted: Bool {
        calendarStatus == .authorized || calendarStatus == .fullAccess
    }

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

            // ── Active model indicator ─────────────────────────
            Button {
                selectedNav = .apiKeys
                controller.navigate(to: .apiKeys)
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "cpu")
                        .font(.system(size: 11))
                        .foregroundColor(Color(red: 0.498, green: 0.467, blue: 0.867))
                    Text(activeModel)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(.primary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 9))
                        .foregroundColor(.secondary)
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 7)
                .background(Color(NSColor.textBackgroundColor))
                .cornerRadius(6)
                .overlay(RoundedRectangle(cornerRadius: 6)
                    .stroke(Color(red: 0.498, green: 0.467, blue: 0.867).opacity(0.3), lineWidth: 0.5))
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)

            Divider()

            // ── Settings ──────────────────────────────────────
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 0) {

                    SettingsSection(title: "Hotkeys") {
                        Button {
                            selectedNav = .shortcuts
                            controller.navigate(to: .shortcuts)
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 3) {
                                    HStack(spacing: 4) {
                                        Text("Start").font(.system(size: 12)).foregroundColor(.primary)
                                        Spacer()
                                        Text(ShortcutManager.shared.startShortcut.displayString)
                                            .font(.system(size: 11, design: .monospaced))
                                            .foregroundColor(.secondary)
                                    }
                                    HStack(spacing: 4) {
                                        Text("Stop").font(.system(size: 12)).foregroundColor(.primary)
                                        Spacer()
                                        Text(ShortcutManager.shared.stopShortcut.displayString)
                                            .font(.system(size: 11, design: .monospaced))
                                            .foregroundColor(.secondary)
                                    }
                                }
                                Image(systemName: "chevron.right")
                                    .font(.system(size: 9))
                                    .foregroundColor(.secondary)
                                    .padding(.leading, 4)
                            }
                            .padding(.horizontal, 10).padding(.vertical, 8)
                            .background(Color(NSColor.textBackgroundColor))
                            .cornerRadius(6)
                            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.15), lineWidth: 0.5))
                        }
                        .buttonStyle(.plain)
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

                    // ── Mac Calendar permission ────────────────
                    SettingsSection(title: "Calendar") {
                        HStack(spacing: 8) {
                            Circle()
                                .fill(calendarGranted ? Color.green : Color.orange)
                                .frame(width: 7, height: 7)
                            Text(calendarGranted ? "Access granted" : calendarStatusLabel)
                                .font(.system(size: 12))
                                .foregroundColor(.secondary)
                                .lineLimit(1)
                        }

                        if !calendarGranted {
                            Button(calendarButtonLabel) { handleCalendarButton() }
                                .buttonStyle(.borderedProminent)
                                .controlSize(.small)
                                .tint(Color(red: 0.498, green: 0.467, blue: 0.867))
                        }

                        Text("Whispr reads Mac Calendar — no Google sign-in needed.")
                            .font(.system(size: 10))
                            .foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    Divider().padding(.vertical, 10)

                    SettingsSection(title: "Data Management") {
                        VStack(spacing: 5) {
                            ClearRow(label: "Transcription history",     state: clearingHistory)    { armClear(.history) }
                            ClearRow(label: "Personal dictionary",       state: clearingDictionary) { armClear(.dictionary) }
                            ClearRow(label: "Voice snippets",            state: clearingSnippets)   { armClear(.snippets) }
                            ClearRow(label: "Profile & learned context", state: resettingProfile)   { armClear(.profile) }

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

            // ── Quit ─────────────────────────────────────────
            Button {
                NSApp.terminate(nil)
            } label: {
                HStack(spacing: 9) {
                    Image(systemName: "power").font(.system(size: 12)).frame(width: 16)
                    Text("Quit Whispr").font(.system(size: 12))
                    Spacer()
                }
                .foregroundColor(.red)
                .padding(.horizontal, 18)
                .padding(.vertical, 6)
            }
            .buttonStyle(.plain)
            .padding(.vertical, 8)
        }
        .frame(width: 220)
        .background(Color(NSColor.controlBackgroundColor))
        .onAppear {
            refreshCalendarStatus()
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
        .onReceive(AppManager.shared.localBackendClient.$activeModel) { activeModel = $0 }
        // Re-check permission whenever the published value changes (e.g. from menu bar)
        .onReceive(AppManager.shared.localBackendClient.$calendarPermission) { status in
            calendarStatus = status
        }
    }

    // MARK: - Calendar permission helpers

    private var calendarStatusLabel: String {
        switch calendarStatus {
        case .authorized, .fullAccess:  return "Access granted"
        case .denied:                   return "Access denied"
        case .restricted:               return "Restricted by system"
        case .notDetermined:            return "Not yet granted"
        case .writeOnly:                return "Write-only access"
        @unknown default:               return "Unknown"
        }
    }

    private var calendarButtonLabel: String {
        switch calendarStatus {
        case .denied, .restricted:  return "Open Settings…"
        default:                    return "Grant Access"
        }
    }

    private func refreshCalendarStatus() {
        calendarStatus = EKEventStore.authorizationStatus(for: .event)
    }

    private func handleCalendarButton() {
        switch calendarStatus {
        case .denied, .restricted:
            backendClient.openCalendarSettings()
        default:
            backendClient.requestCalendarPermission { granted in
                calendarStatus = EKEventStore.authorizationStatus(for: .event)
                MenuBarController.shared.refreshCalendarItem()
            }
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
