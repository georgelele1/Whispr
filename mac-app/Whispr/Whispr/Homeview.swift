import SwiftUI
import Combine

struct HomeView: View {

    private var backendClient: LocalBackendClient { AppManager.shared.localBackendClient }

    @State private var dictionaryCount : Int  = 0
    @State private var snippetsCount   : Int  = 0
    @State private var todayCount      : Int  = 0
    @State private var groupedEntries  : [(date: String, entries: [HomeHistoryEntry])] = []
    @State private var isLoading       : Bool = false
    @State private var cancellables    = Set<AnyCancellable>()

    var body: some View {
        VStack(spacing: 0) {

            // ── Hotkey banner ──────────────────────────────────
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

            ScrollView {
                VStack(alignment: .leading, spacing: 24) {

                    // ── Stat cards ─────────────────────────────
                    HStack(spacing: 14) {
                        StatCard(label: "Dictionary", value: "\(dictionaryCount)", unit: "terms",    icon: "book.closed")
                        StatCard(label: "Snippets",   value: "\(snippetsCount)",   unit: "snippets", icon: "text.bubble")
                        StatCard(label: "Today",      value: "\(todayCount)",      unit: "recorded", icon: "clock")
                    }

                    // ── Recent transcriptions ───────────────────
                    VStack(alignment: .leading, spacing: 0) {
                        Text("Recent transcriptions")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)
                            .tracking(0.6)
                            .padding(.bottom, 12)

                        if groupedEntries.isEmpty && !isLoading {
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
                            VStack(alignment: .leading, spacing: 0) {
                                ForEach(groupedEntries, id: \.date) { group in
                                    Text(group.date)
                                        .font(.system(size: 13, weight: .semibold))
                                        .foregroundColor(.primary)
                                        .padding(.top, 16)
                                        .padding(.bottom, 8)

                                    VStack(spacing: 0) {
                                        ForEach(group.entries) { entry in
                                            HomeHistoryRow(entry: entry)
                                            if entry.id != group.entries.last?.id {
                                                Divider().padding(.leading, 80)
                                            }
                                        }
                                    }
                                    .background(Color(NSColor.textBackgroundColor))
                                    .cornerRadius(10)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 10)
                                            .stroke(Color.secondary.opacity(0.12), lineWidth: 0.5)
                                    )
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal, 28)
                .padding(.vertical, 22)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear {
            loadAll()
            AppManager.shared.$lastOutputText
                .receive(on: DispatchQueue.main)
                .sink { text in if !text.isEmpty { loadAll() } }
                .store(in: &cancellables)
        }
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
                guard let finalText = item["final_text"] as? String,
                      !finalText.trimmingCharacters(in: .whitespaces).isEmpty
                else { return nil }
                let appName = item["app_name"] as? String ?? "unknown"
                let tsMs    = item["ts"]       as? Double ?? 0
                return HomeHistoryEntry(
                    text: finalText,
                    appName: appName,
                    timestamp: Date(timeIntervalSince1970: tsMs / 1000)
                )
            }
            let today  = Calendar.current.startOfDay(for: Date())
            let tCount = loaded.filter { Calendar.current.startOfDay(for: $0.timestamp) == today }.count
            DispatchQueue.main.async {
                todayCount     = tCount
                groupedEntries = Self.groupByDate(loaded)
                group.leave()
            }
        }

        group.notify(queue: .main) { isLoading = false }
    }

    static func groupByDate(_ entries: [HomeHistoryEntry]) -> [(date: String, entries: [HomeHistoryEntry])] {
        let cal = Calendar.current
        let fmt = DateFormatter()
        var result: [(date: String, entries: [HomeHistoryEntry])] = []
        var seen:   [String: Int] = [:]

        for entry in entries {
            let label: String
            if cal.isDateInToday(entry.timestamp) {
                label = "Today"
            } else if cal.isDateInYesterday(entry.timestamp) {
                label = "Yesterday"
            } else {
                fmt.dateFormat = "MMMM d, yyyy"
                label = fmt.string(from: entry.timestamp)
            }
            if let idx = seen[label] {
                result[idx].entries.append(entry)
            } else {
                seen[label] = result.count
                result.append((date: label, entries: [entry]))
            }
        }
        return result
    }
}

// MARK: - HomeHistoryRow

struct HomeHistoryRow: View {
    let entry: HomeHistoryEntry
    @State private var copied = false

    private var timeString: String {
        let fmt = DateFormatter()
        fmt.dateFormat = "hh:mm a"
        return fmt.string(from: entry.timestamp).uppercased()
    }

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            Text(timeString)
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundColor(.secondary)
                .frame(width: 78, alignment: .leading)
                .padding(.vertical, 14)
                .padding(.leading, 16)

            Rectangle()
                .fill(Color.secondary.opacity(0.1))
                .frame(width: 1)
                .padding(.vertical, 10)

            Text(entry.text)
                .font(.system(size: 13))
                .foregroundColor(.primary)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 14)
                .padding(.horizontal, 14)

            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(entry.text, forType: .string)
                withAnimation { copied = true }
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                    withAnimation { copied = false }
                }
            } label: {
                Image(systemName: copied ? "checkmark" : "doc.on.doc")
                    .font(.system(size: 12))
                    .foregroundColor(copied ? .green : .secondary)
                    .frame(width: 36, height: 36)
            }
            .buttonStyle(.plain)
            .padding(.trailing, 8)
            .padding(.top, 8)
        }
    }
}

// MARK: - Supporting types

struct HomeHistoryEntry: Identifiable {
    let id        = UUID()
    let text      : String
    let appName   : String
    let timestamp : Date
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
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.15), lineWidth: 0.5))
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
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color.secondary.opacity(0.3), lineWidth: 0.5))
    }
}
