import SwiftUI

struct HistoryEntry: Identifiable {
    let id        = UUID()
    let rawText   : String
    let finalText : String
    let appName   : String
    let language  : String
    let timestamp : Date
}

struct HistoryView: View {

    @State private var entries      : [HistoryEntry] = []
    @State private var searchText   : String = ""
    @State private var isLoading    : Bool   = false
    @State private var confirmClear : Bool   = false
    @State private var selectedID   : UUID?  = nil

    var backendClient: LocalBackendClient?

    var filtered: [HistoryEntry] {
        guard !searchText.isEmpty else { return entries }
        return entries.filter {
            $0.finalText.localizedCaseInsensitiveContains(searchText) ||
            $0.rawText.localizedCaseInsensitiveContains(searchText) ||
            $0.appName.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {

            // Header
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Transcription History").font(.title2).bold()
                    Text("\(entries.count) recordings — newest first.")
                        .font(.caption).foregroundColor(.secondary)
                }
                Spacer()
                if isLoading { ProgressView().scaleEffect(0.8) }
                Button { loadHistory() } label: { Image(systemName: "arrow.clockwise") }
                    .buttonStyle(.plain).help("Refresh")
                Button { confirmClear = true } label: {
                    Image(systemName: "trash").foregroundColor(.red)
                }
                .buttonStyle(.plain)
                .help("Clear all history")
                .alert("Clear History", isPresented: $confirmClear) {
                    Button("Clear All", role: .destructive) {
                        backendClient?.clearHistory { success in
                            DispatchQueue.main.async {
                                if success { entries = []; selectedID = nil }
                            }
                        }
                    }
                    Button("Cancel", role: .cancel) {}
                } message: {
                    Text("This will permanently delete all transcription history.")
                }
            }
            .padding()

            // Search
            HStack {
                Image(systemName: "magnifyingglass").foregroundColor(.secondary)
                TextField("Search output text or app name…", text: $searchText).textFieldStyle(.plain)
                if !searchText.isEmpty {
                    Button { searchText = "" } label: {
                        Image(systemName: "xmark.circle.fill").foregroundColor(.secondary)
                    }.buttonStyle(.plain)
                }
            }
            .padding(.horizontal).padding(.vertical, 6)
            .background(Color(NSColor.controlBackgroundColor))

            Divider()

            if filtered.isEmpty && !isLoading {
                VStack(spacing: 8) {
                    Image(systemName: "waveform").font(.system(size: 36)).foregroundColor(.secondary)
                    Text(searchText.isEmpty ? "No recordings yet." : "No matches.").foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity).padding(.vertical, 40)
            } else {
                HStack(spacing: 0) {
                    List(selection: $selectedID) {
                        ForEach(filtered) { entry in
                            HistoryRow(entry: entry).tag(entry.id)
                        }
                    }
                    .listStyle(.inset)
                    .frame(width: 260)

                    Divider()

                    if let selected = filtered.first(where: { $0.id == selectedID }) {
                        HistoryDetail(entry: selected)
                    } else {
                        VStack {
                            Image(systemName: "arrow.left").font(.system(size: 24)).foregroundColor(.secondary)
                            Text("Select a recording").foregroundColor(.secondary)
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    }
                }
            }
        }
        .frame(width: 680, height: 520)
        .onAppear { loadHistory() }
    }

    private func loadHistory() {
        isLoading = true
        backendClient?.loadHistory { items in
            let loaded = items.compactMap { item -> HistoryEntry? in
                guard let finalText = item["final_text"] as? String else { return nil }
                return HistoryEntry(
                    rawText:   item["raw_text"]        as? String ?? "",
                    finalText: finalText,
                    appName:   item["app_name"]        as? String ?? "unknown",
                    language:  item["target_language"] as? String ?? "English",
                    timestamp: Date(timeIntervalSince1970: (item["ts"] as? Double ?? 0) / 1000)
                )
            }
            DispatchQueue.main.async {
                self.entries   = loaded
                self.isLoading = false
                if self.selectedID == nil { self.selectedID = loaded.first?.id }
            }
        }
    }
}

struct HistoryRow: View {
    let entry: HistoryEntry

    private var timeString: String {
        let fmt = DateFormatter()
        fmt.dateStyle = .short
        fmt.timeStyle = .short
        return fmt.string(from: entry.timestamp)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(entry.finalText).font(.subheadline).lineLimit(2)
            HStack(spacing: 6) {
                Text(timeString).font(.caption2).foregroundColor(.secondary)
                Text("·").foregroundColor(.secondary)
                Text(entry.appName).font(.caption2).foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 4)
    }
}

struct HistoryDetail: View {
    let entry: HistoryEntry

    private var timeString: String {
        let fmt = DateFormatter()
        fmt.dateStyle = .long
        fmt.timeStyle = .medium
        return fmt.string(from: entry.timestamp)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 16) {
                    Label(entry.appName, systemImage: "macwindow")
                    Label(entry.language, systemImage: "globe")
                    Label(timeString, systemImage: "clock")
                }
                .font(.caption).foregroundColor(.secondary)

                Divider()

                VStack(alignment: .leading, spacing: 6) {
                    Text("Output").font(.headline)
                    Text(entry.finalText)
                        .font(.body).textSelection(.enabled)
                        .padding(10)
                        .background(Color(NSColor.controlBackgroundColor))
                        .cornerRadius(8)
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(entry.finalText, forType: .string)
                    } label: {
                        Label("Copy", systemImage: "doc.on.doc")
                    }
                    .buttonStyle(.bordered).controlSize(.small)
                }

                if !entry.rawText.isEmpty && entry.rawText != entry.finalText {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Raw transcription").font(.headline)
                        Text(entry.rawText)
                            .font(.body).foregroundColor(.secondary).textSelection(.enabled)
                            .padding(10)
                            .background(Color(NSColor.controlBackgroundColor))
                            .cornerRadius(8)
                    }
                }
            }
            .padding()
        }
    }
}
