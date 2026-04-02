import SwiftUI

// =========================================================
// Data model
// =========================================================

struct DictionaryEntry: Identifiable {
    let id      = UUID()
    var phrase  : String
    var aliases : [String]
    var approved: Bool
}

// =========================================================
// Dictionary window
// =========================================================

struct DictionaryView: View {

    @State private var terms        : [DictionaryEntry] = []
    @State private var searchText   : String = ""
    @State private var newPhrase    : String = ""
    @State private var newAliases   : String = ""
    @State private var statusMessage: String = ""
    @State private var isLoading    : Bool   = false
    @State private var editingID    : UUID?  = nil

    var backendClient: LocalBackendClient?

    var filtered: [DictionaryEntry] {
        if searchText.isEmpty { return terms }
        return terms.filter {
            $0.phrase.localizedCaseInsensitiveContains(searchText) ||
            $0.aliases.joined(separator: " ").localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {

            // ── Header ────────────────────────────────────────
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Personal Dictionary")
                        .font(.title2)
                        .bold()
                    Text("\(terms.count) terms — corrections applied during transcription.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Spacer()
                if isLoading { ProgressView().scaleEffect(0.8) }

                Button {
                    loadTerms()
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.plain)
                .help("Refresh")
            }
            .padding()

            // ── Search ────────────────────────────────────────
            HStack {
                Image(systemName: "magnifyingglass").foregroundColor(.secondary)
                TextField("Search terms or aliases...", text: $searchText)
                    .textFieldStyle(.plain)
                if !searchText.isEmpty {
                    Button { searchText = "" } label: {
                        Image(systemName: "xmark.circle.fill").foregroundColor(.secondary)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal)
            .padding(.vertical, 6)
            .background(Color(NSColor.controlBackgroundColor))

            Divider()

            // ── Term list ─────────────────────────────────────
            if filtered.isEmpty && !isLoading {
                VStack(spacing: 8) {
                    Image(systemName: "book.closed")
                        .font(.system(size: 36))
                        .foregroundColor(.secondary)
                    Text(searchText.isEmpty ? "No dictionary terms yet." : "No matches.")
                        .foregroundColor(.secondary)
                    if searchText.isEmpty {
                        Text("Click Update Dictionary from the menu or add terms below.")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 40)
            } else {
                List {
                    ForEach(filtered) { entry in
                        DictionaryRow(
                            entry:     entry,
                            isEditing: editingID == entry.id,
                            onEdit:    { editingID = entry.id },
                            onSave:    { phrase, aliases in saveEdit(entry, phrase: phrase, aliases: aliases) },
                            onCancel:  { editingID = nil },
                            onDelete:  { removeTerm(entry) }
                        )
                    }
                }
                .listStyle(.inset)
            }

            Divider()

            // ── Add new term ──────────────────────────────────
            VStack(alignment: .leading, spacing: 8) {
                Text("Add term")
                    .font(.headline)

                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Correct phrase")
                            .font(.caption).foregroundColor(.secondary)
                        TextField("e.g. COMP9900", text: $newPhrase)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 150)
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Aliases (comma separated)")
                            .font(.caption).foregroundColor(.secondary)
                        TextField("e.g. comp 9900, comp9900", text: $newAliases)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 260)
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text(" ").font(.caption)
                        Button("Add") { addTerm() }
                            .buttonStyle(.borderedProminent)
                            .disabled(newPhrase.isEmpty)
                    }
                }

                if !statusMessage.isEmpty {
                    Text(statusMessage)
                        .font(.caption)
                        .foregroundColor(statusMessage.hasPrefix("Failed") ? .red : .secondary)
                }
            }
            .padding()
        }
        .frame(width: 620, height: 520)
        .onAppear { loadTerms() }
    }

    // =========================================================
    // Helpers
    // =========================================================

    private func loadTerms() {
        isLoading = true
        backendClient?.listDictionaryTerms { items in
            let loaded = items.compactMap { d -> DictionaryEntry? in
                guard let phrase = d["phrase"] as? String else { return nil }
                let aliases  = d["aliases"] as? [String] ?? []
                let approved = d["approved"] as? Bool ?? true
                return DictionaryEntry(phrase: phrase, aliases: aliases, approved: approved)
            }
            DispatchQueue.main.async {
                self.terms     = loaded.sorted { $0.phrase < $1.phrase }
                self.isLoading = false
            }
        }
    }

    private func addTerm() {
        let phrase  = newPhrase.trimmingCharacters(in: .whitespacesAndNewlines)
        let aliases = newAliases
            .components(separatedBy: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }

        backendClient?.addDictionaryTerm(phrase: phrase, aliases: aliases) { success in
            DispatchQueue.main.async {
                if success {
                    self.terms.append(DictionaryEntry(phrase: phrase, aliases: aliases, approved: true))
                    self.terms.sort { $0.phrase < $1.phrase }
                    self.newPhrase    = ""
                    self.newAliases   = ""
                    self.statusMessage = "Saved"
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.statusMessage = "" }
                } else {
                    self.statusMessage = "Failed to save"
                }
            }
        }
    }

    private func saveEdit(_ entry: DictionaryEntry, phrase: String, aliases: [String]) {
        backendClient?.removeDictionaryTerm(phrase: entry.phrase) { _ in
            self.backendClient?.addDictionaryTerm(phrase: phrase, aliases: aliases) { success in
                DispatchQueue.main.async {
                    if success, let idx = self.terms.firstIndex(where: { $0.id == entry.id }) {
                        self.terms[idx] = DictionaryEntry(phrase: phrase, aliases: aliases, approved: true)
                        self.terms.sort { $0.phrase < $1.phrase }
                    }
                    self.editingID = nil
                }
            }
        }
    }

    private func removeTerm(_ entry: DictionaryEntry) {
        backendClient?.removeDictionaryTerm(phrase: entry.phrase) { success in
            DispatchQueue.main.async {
                if success { self.terms.removeAll { $0.id == entry.id } }
            }
        }
    }
}

// =========================================================
// Dictionary row
// =========================================================

struct DictionaryRow: View {
    let entry    : DictionaryEntry
    let isEditing: Bool
    let onEdit   : () -> Void
    let onSave   : (String, [String]) -> Void
    let onCancel : () -> Void
    let onDelete : () -> Void

    @State private var editPhrase  : String = ""
    @State private var editAliases : String = ""

    var body: some View {
        if isEditing {
            HStack(spacing: 8) {
                TextField("Phrase", text: $editPhrase)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 140)
                TextField("Aliases (comma separated)", text: $editAliases)
                    .textFieldStyle(.roundedBorder)
                Button("Save") {
                    let aliases = editAliases
                        .components(separatedBy: ",")
                        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                        .filter { !$0.isEmpty }
                    onSave(editPhrase.trimmingCharacters(in: .whitespacesAndNewlines), aliases)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(editPhrase.isEmpty)
                Button("Cancel", action: onCancel)
                    .buttonStyle(.bordered)
                    .controlSize(.small)
            }
            .padding(.vertical, 4)
            .onAppear {
                editPhrase  = entry.phrase
                editAliases = entry.aliases.joined(separator: ", ")
            }
        } else {
            HStack(spacing: 10) {
                Text(entry.phrase)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .frame(width: 140, alignment: .leading)

                if entry.aliases.isEmpty {
                    Text("no aliases")
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .italic()
                } else {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 4) {
                            ForEach(entry.aliases, id: \.self) { alias in
                                Text(alias)
                                    .font(.caption)
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 2)
                                    .background(Color.secondary.opacity(0.15))
                                    .cornerRadius(4)
                            }
                        }
                    }
                }

                Spacer()

                Button { onEdit() } label: {
                    Image(systemName: "pencil").foregroundColor(.secondary)
                }
                .buttonStyle(.plain)

                Button { onDelete() } label: {
                    Image(systemName: "trash").foregroundColor(.red)
                }
                .buttonStyle(.plain)
            }
            .padding(.vertical, 3)
        }
    }
}
