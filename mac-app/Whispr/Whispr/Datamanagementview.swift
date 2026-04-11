import SwiftUI
import AppKit

struct DataManagementView: View {

    private var client: LocalBackendClient { AppManager.shared.localBackendClient }

    @State private var historyState    : DMState = .idle
    @State private var dictionaryState : DMState = .idle
    @State private var snippetsState   : DMState = .idle
    @State private var profileState    : DMState = .idle
    @State private var resetAllState   : DMState = .idle

    @State private var pending     : DMAction? = nil
    @State private var showConfirm : Bool      = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {

            VStack(alignment: .leading, spacing: 3) {
                Text("Data & Privacy").font(.title2).bold()
                Text("Permanently delete stored data. These actions cannot be undone.")
                    .font(.caption).foregroundColor(.secondary)
            }
            .padding(.horizontal, 28).padding(.top, 24).padding(.bottom, 20)

            Divider()

            ScrollView {
                VStack(spacing: 12) {
                    DMRow(icon: "clock",             title: "Transcription History",    detail: "All past recordings and transcribed text.",                      state: historyState,    label: "Clear") { arm(.history) }
                    DMRow(icon: "book.closed",       title: "Personal Dictionary",      detail: "Every custom term and alias you have added.",                    state: dictionaryState, label: "Clear") { arm(.dictionary) }
                    DMRow(icon: "text.bubble",       title: "Voice Snippets",           detail: "All trigger-word expansion shortcuts.",                          state: snippetsState,   label: "Clear") { arm(.snippets) }
                    DMRow(icon: "person.crop.circle",title: "Profile & Learned Context",detail: "Name, organisation, role and AI-learned context. Language is kept.", state: profileState, label: "Reset") { arm(.profile) }

                    VStack(alignment: .leading, spacing: 10) {
                        HStack(spacing: 8) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundColor(.red).font(.system(size: 14))
                            Text("Reset Everything")
                                .font(.system(size: 14, weight: .semibold)).foregroundColor(.red)
                        }
                        Text("Clears history, dictionary, snippets and profile in one go. Language preference is kept.")
                            .font(.caption).foregroundColor(.secondary)
                        HStack {
                            DMStateBadge(state: resetAllState)
                            Spacer()
                            Button { arm(.all) } label: {
                                Label("Reset All Data", systemImage: "trash.fill")
                                    .font(.system(size: 12, weight: .medium))
                            }
                            .buttonStyle(.borderedProminent).controlSize(.small).tint(.red)
                            .disabled(resetAllState == .running)
                        }
                    }
                    .padding()
                    .background(Color.red.opacity(0.05))
                    .cornerRadius(10)
                    .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.red.opacity(0.18), lineWidth: 0.5))
                }
                .padding(.horizontal, 28).padding(.vertical, 20)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .alert(pending?.alertTitle ?? "Confirm", isPresented: $showConfirm, presenting: pending) { action in
            Button("Cancel", role: .cancel) { pending = nil }
            Button(action.confirmLabel, role: .destructive) { execute(action); pending = nil }
        } message: { action in
            Text(action.alertMessage)
        }
    }

    private func arm(_ action: DMAction) {
        pending     = action
        showConfirm = true
    }

    private func execute(_ action: DMAction) {
        switch action {
        case .history:
            historyState = .running
            client.clearHistory { ok in
                self.historyState = ok ? .done : .failed
                self.scheduleReset { self.historyState = .idle }
            }
        case .dictionary:
            dictionaryState = .running
            client.clearDictionary { ok in
                self.dictionaryState = ok ? .done : .failed
                self.scheduleReset { self.dictionaryState = .idle }
            }
        case .snippets:
            snippetsState = .running
            client.clearSnippets { ok in
                self.snippetsState = ok ? .done : .failed
                self.scheduleReset { self.snippetsState = .idle }
            }
        case .profile:
            profileState = .running
            client.resetProfile { ok in
                self.profileState = ok ? .done : .failed
                self.scheduleReset { self.profileState = .idle }
            }
        case .all:
            historyState = .running; dictionaryState = .running
            snippetsState = .running; profileState = .running; resetAllState = .running
            client.resetAll { ok in
                let s: DMState = ok ? .done : .failed
                self.historyState = s; self.dictionaryState = s
                self.snippetsState = s; self.profileState = s; self.resetAllState = s
                self.scheduleReset { self.historyState = .idle }
                self.scheduleReset { self.dictionaryState = .idle }
                self.scheduleReset { self.snippetsState = .idle }
                self.scheduleReset { self.profileState = .idle }
                self.scheduleReset { self.resetAllState = .idle }
            }
        }
    }

    private func scheduleReset(_ reset: @escaping () -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 3, execute: reset)
    }
}

private struct DMRow: View {
    let icon   : String
    let title  : String
    let detail : String
    let state  : DMState
    let label  : String
    let action : () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 18)).foregroundColor(.secondary)
                .frame(width: 24).padding(.top, 2)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.system(size: 13, weight: .medium))
                Text(detail).font(.caption).foregroundColor(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 5) {
                DMStateBadge(state: state)
                Button(label) { action() }
                    .buttonStyle(.bordered).controlSize(.small)
                    .foregroundColor(.red).disabled(state == .running)
            }
        }
        .padding()
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.15), lineWidth: 0.5))
    }
}

private struct DMStateBadge: View {
    let state: DMState
    var body: some View {
        switch state {
        case .idle:    EmptyView()
        case .running:
            HStack(spacing: 4) {
                ProgressView().scaleEffect(0.6)
                Text("Working…").font(.caption2).foregroundColor(.secondary)
            }
        case .done:
            Label("Done", systemImage: "checkmark.circle.fill").font(.caption2).foregroundColor(.green)
        case .failed:
            Label("Failed", systemImage: "xmark.circle.fill").font(.caption2).foregroundColor(.red)
        }
    }
}

enum DMState: Equatable { case idle, running, done, failed }

private enum DMAction {
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
        case .dictionary: return "Every custom term and alias will be removed. Whispr will no longer correct those phrases."
        case .snippets:   return "All voice snippet shortcuts will be deleted."
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
