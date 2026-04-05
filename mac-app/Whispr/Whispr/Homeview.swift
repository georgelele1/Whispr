import SwiftUI
import Combine

// =========================================================
// HomeView
// Pulls backendClient from AppManager.shared directly —
// no init parameter needed, fixing the "argument passed to
// call that takes no arguments" compiler error.
// =========================================================

struct HomeView: View {

    // Access backend via AppManager — no stored property needed
    private var backendClient: LocalBackendClient { AppManager.shared.localBackendClient }

    @State private var dictionaryCount : Int  = 0
    @State private var snippetsCount   : Int  = 0
    @State private var yesterdayCount  : Int  = 0
    @State private var recentEntries   : [HomeHistoryEntry] = []
    @State private var isLoading       : Bool = false

    // Status bar state — always expanded so result shows immediately
    @State private var appStatus      : AppStatus = .idle
    @State private var lastOutputText : String    = ""
    @State private var statusExpanded : Bool      = true

    @State private var cancellables = Set<AnyCancellable>()

    var body: some View {
        VStack(spacing: 0) {

            // ── Hotkey banner ─────────────────────────────────
            HStack(spacing: 6) {
                Image(systemName: "mic")
                    .font(.system(size: 12))
                    .foregroundColor(.secondary)
                Text("Start with")
                    .font(.system(size: 13))
                    .foregroundColor(.secondary)
                KbdTag(key: "⌥ Space")
                Text("·  Stop with")
                    .font(.system(size: 13))
                    .foregroundColor(.secondary)
                KbdTag(key: "⌥ S")
                Spacer()
                if isLoading { ProgressView().scaleEffect(0.7) }
                Button { loadAll() } label: {
                    Image(systemName: "arrow.clockwise").font(.system(size: 12))
                }
                .buttonStyle(.plain)
                .foregroundColor(.secondary)
                .help("Refresh")
            }
            .padding(.horizontal, 28)
            .padding(.vertical, 13)
            .background(Color(NSColor.controlBackgroundColor))

            Divider()

            // ── Main scrollable content ───────────────────────
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {

                    // Stat cards
                    HStack(spacing: 14) {
                        StatCard(label: "Dictionary terms", value: "\(dictionaryCount)", unit: "terms",         icon: "book.closed")
                        StatCard(label: "Snippets",         value: "\(snippetsCount)",   unit: "snippets",       icon: "text.bubble")
                        StatCard(label: "Yesterday",        value: "\(yesterdayCount)",  unit: "transcriptions", icon: "clock")
                    }

                    // Recent transcriptions
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Recent transcriptions")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)
                            .tracking(0.6)

                        if recentEntries.isEmpty && !isLoading {
                            VStack(spacing: 8) {
                                Image(systemName: "waveform")
                                    .font(.system(size: 32))
                                    .foregroundColor(.secondary)
                                Text("No transcriptions yet.")
                                    .foregroundColor(.secondary)
                                    .font(.subheadline)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 40)
                        } else {
                            VStack(spacing: 7) {
                                ForEach(recentEntries) { entry in
                                    HomeHistoryRow(entry: entry)
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal, 28)
                .padding(.vertical, 22)
            }

            // ── Status bar pinned at bottom ───────────────────
            HomeStatusBar(
                status:      appStatus,
                resultText:  lastOutputText,
                isExpanded:  $statusExpanded
            )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear {
            loadAll()
            bindAppManager()
        }
    }

    // MARK: - Bindings

    private func bindAppManager() {
        AppManager.shared.$appStatus
            .receive(on: DispatchQueue.main)
            .sink { status in
                appStatus = status
            }
            .store(in: &cancellables)

        AppManager.shared.$lastOutputText
            .receive(on: DispatchQueue.main)
            .sink { text in
                lastOutputText = text
                if !text.isEmpty {
                    statusExpanded = true
                    loadAll()
                }
            }
            .store(in: &cancellables)
    }

    // MARK: - Data loading

    private func loadAll() {
        isLoading = true
        let group = DispatchGroup()

        group.enter()
        backendClient.listDictionaryTerms { items in
            DispatchQueue.main.async { dictionaryCount = items.count; group.leave() }
        }

        group.enter()
        backendClient.listSnippets { items in
            DispatchQueue.main.async { snippetsCount = items.count; group.leave() }
        }

        group.enter()
        backendClient.loadHistory { items in
            let loaded = items.compactMap { item -> HomeHistoryEntry? in
                guard let finalText = item["final_text"] as? String else { return nil }
                let appName = item["app_name"] as? String ?? "unknown"
                let tsMs    = item["ts"]       as? Double ?? 0
                let date    = Date(timeIntervalSince1970: tsMs / 1000)
                return HomeHistoryEntry(text: finalText, appName: appName, timestamp: date)
            }
            let yCount = countYesterday(from: loaded)
            DispatchQueue.main.async {
                recentEntries  = Array(loaded.prefix(6))
                yesterdayCount = yCount
                group.leave()
            }
        }

        group.notify(queue: .main) { isLoading = false }
    }

    private func countYesterday(from entries: [HomeHistoryEntry]) -> Int {
        let cal = Calendar.current
        guard let yesterday = cal.date(byAdding: .day, value: -1, to: Date()) else { return 0 }
        return entries.filter { cal.isDate($0.timestamp, inSameDayAs: yesterday) }.count
    }
}

// =========================================================
// HomeStatusBar — pinned bottom strip, always fully visible
// =========================================================

struct HomeStatusBar: View {
    let status     : AppStatus
    let resultText : String
    @Binding var isExpanded: Bool   // kept for API compat, not used for toggling

    private var isActive: Bool { status == .listening || status == .processing }

    private var statusColor: Color {
        switch status {
        case .listening:  return .red
        case .processing: return Color(red: 0.498, green: 0.467, blue: 0.867)
        case .error:      return .red
        default:          return resultText.isEmpty ? .secondary : Color(red: 0.498, green: 0.467, blue: 0.867)
        }
    }

    private var statusLabel: String {
        switch status {
        case .idle:       return resultText.isEmpty ? "Idle — press ⌥ Space to start" : "Last result"
        case .listening:  return "Recording…"
        case .processing: return "Processing…"
        case .error:      return "Error"
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            Divider()

            VStack(alignment: .leading, spacing: 8) {

                // ── Header row ────────────────────────────────
                HStack(spacing: 8) {

                    // Waveform bars during recording, dot otherwise
                    if status == .listening {
                        MiniWaveform()
                    } else if status == .processing {
                        ProgressView().scaleEffect(0.55).frame(width: 14, height: 14)
                    } else {
                        Circle()
                            .fill(statusColor)
                            .frame(width: 7, height: 7)
                    }

                    Text(statusLabel)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(statusColor)

                    Spacer()

                    if !resultText.isEmpty {
                        CopyButton(text: resultText)
                    }
                }

                // ── Result text — always shown when available ──
                if !resultText.isEmpty {
                    Text(resultText)
                        .font(.system(size: 13))
                        .foregroundColor(.primary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(NSColor.textBackgroundColor))
                        .cornerRadius(8)
                        .overlay(
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(Color.secondary.opacity(0.15), lineWidth: 0.5)
                        )
                } else if status == .listening {
                    // Placeholder while recording
                    HStack(spacing: 6) {
                        Text("Listening…")
                            .font(.system(size: 13))
                            .foregroundColor(.secondary)
                            .italic()
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color(NSColor.textBackgroundColor).opacity(0.5))
                    .cornerRadius(8)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color.red.opacity(0.2), lineWidth: 0.5)
                    )
                } else if status == .processing {
                    HStack(spacing: 6) {
                        Text("Transcribing your recording…")
                            .font(.system(size: 13))
                            .foregroundColor(.secondary)
                            .italic()
                    }
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color(NSColor.textBackgroundColor).opacity(0.5))
                    .cornerRadius(8)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(statusColor.opacity(0.25), lineWidth: 0.5)
                    )
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
            .background(Color(NSColor.controlBackgroundColor))
        }
    }
}

// =========================================================
// MiniWaveform — tiny animated bars for the status bar
// =========================================================

struct MiniWaveform: View {
    @State private var phases: [Double] = [0.3, 0.7, 0.4, 0.9, 0.5]
    private let barCount = 5
    private let barW: CGFloat = 2.5
    private let maxH: CGFloat = 14
    private let minH: CGFloat = 3

    var body: some View {
        HStack(alignment: .center, spacing: 2) {
            ForEach(0..<barCount, id: \.self) { i in
                RoundedRectangle(cornerRadius: 1)
                    .fill(Color.red.opacity(0.85))
                    .frame(width: barW, height: minH + CGFloat(phases[i]) * (maxH - minH))
                    .animation(
                        .easeInOut(duration: 0.4 + Double(i) * 0.07)
                        .repeatForever(autoreverses: true)
                        .delay(Double(i) * 0.1),
                        value: phases[i]
                    )
            }
        }
        .frame(height: maxH)
        .onAppear {
            for i in 0..<barCount {
                DispatchQueue.main.asyncAfter(deadline: .now() + Double(i) * 0.05) {
                    phases[i] = [0.9, 0.4, 1.0, 0.6, 0.8][i]
                }
            }
        }
    }
}

// =========================================================
// HomeHistoryRow — with copy button
// =========================================================

struct HomeHistoryRow: View {
    let entry: HomeHistoryEntry

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Text(entry.timeString)
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(.secondary)
                .frame(width: 65, alignment: .leading)
                .padding(.top, 1)

            Text(entry.text)
                .font(.system(size: 13))
                .lineLimit(2)
                .foregroundColor(.primary)
                .frame(maxWidth: .infinity, alignment: .leading)

            CopyButton(text: entry.text)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Color(NSColor.textBackgroundColor))
        .cornerRadius(8)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.secondary.opacity(0.15), lineWidth: 0.5)
        )
    }
}

// =========================================================
// CopyButton
// =========================================================

struct CopyButton: View {
    let text: String
    @State private var copied = false

    var body: some View {
        Button {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
            withAnimation { copied = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                withAnimation { copied = false }
            }
        } label: {
            Label(
                copied ? "Copied!" : "Copy",
                systemImage: copied ? "checkmark" : "doc.on.doc"
            )
            .font(.system(size: 11))
            .foregroundColor(copied ? .green : .secondary)
        }
        .buttonStyle(.plain)
        .animation(.easeInOut(duration: 0.15), value: copied)
    }
}

// =========================================================
// Supporting types
// =========================================================

struct HomeHistoryEntry: Identifiable {
    let id        = UUID()
    let text      : String
    let appName   : String
    let timestamp : Date

    var timeString: String {
        let fmt = DateFormatter()
        fmt.timeStyle = .short
        return fmt.string(from: timestamp)
    }
}

struct StatCard: View {
    let label: String
    let value: String
    let unit : String
    let icon : String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 5) {
                Image(systemName: icon).font(.system(size: 11)).foregroundColor(.secondary)
                Text(label).font(.system(size: 11)).foregroundColor(.secondary)
                    .textCase(.uppercase).tracking(0.4)
            }
            HStack(alignment: .lastTextBaseline, spacing: 4) {
                Text(value).font(.system(size: 28, weight: .medium))
                Text(unit).font(.system(size: 13)).foregroundColor(.secondary)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.secondary.opacity(0.15), lineWidth: 0.5)
        )
    }
}

struct KbdTag: View {
    let key: String
    var body: some View {
        Text(key)
            .font(.system(size: 11, design: .monospaced))
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(Color(NSColor.textBackgroundColor))
            .cornerRadius(4)
            .overlay(
                RoundedRectangle(cornerRadius: 4)
                    .stroke(Color.secondary.opacity(0.3), lineWidth: 0.5)
            )
    }
}
