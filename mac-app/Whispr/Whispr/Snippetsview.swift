import SwiftUI

struct SnippetEntry: Identifiable {
    let id        = UUID()
    var trigger   : String
    var expansion : String
    var enabled   : Bool
}

struct SnippetsView: View {

    @State private var snippets      : [SnippetEntry] = []
    @State private var newTrigger    : String = ""
    @State private var newExpansion  : String = ""
    @State private var statusMessage : String = ""
    @State private var isLoading     : Bool   = false
    @State private var editingID     : UUID?  = nil

    var backendClient: LocalBackendClient?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {

            // Header
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Voice Snippets").font(.title2).bold()
                    Text("Say the trigger word during dictation to insert the expansion.")
                        .font(.caption).foregroundColor(.secondary)
                }
                Spacer()
                if isLoading { ProgressView().scaleEffect(0.8) }
            }
            .padding()

            Divider()

            if snippets.isEmpty && !isLoading {
                VStack(spacing: 8) {
                    Image(systemName: "text.bubble").font(.system(size: 36)).foregroundColor(.secondary)
                    Text("No snippets yet.").foregroundColor(.secondary)
                    Text("Add your first snippet below.").font(.caption).foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity).padding(.vertical, 40)
            } else {
                List {
                    ForEach(snippets) { snippet in
                        SnippetRow(
                            snippet:   snippet,
                            isEditing: editingID == snippet.id,
                            onEdit:    { editingID = snippet.id },
                            onSave:    { t, e in saveEdit(snippet, trigger: t, expansion: e) },
                            onCancel:  { editingID = nil },
                            onDelete:  { removeSnippet(snippet) }
                        )
                    }
                }
                .listStyle(.inset)
            }

            Divider()

            // Add snippet
            VStack(alignment: .leading, spacing: 8) {
                Text("Add snippet").font(.headline)
                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Trigger word").font(.caption).foregroundColor(.secondary)
                        TextField("e.g. zoom link", text: $newTrigger)
                            .textFieldStyle(.roundedBorder).frame(width: 160)
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Expansion").font(.caption).foregroundColor(.secondary)
                        TextField("Text or URL", text: $newExpansion)
                            .textFieldStyle(.roundedBorder).frame(width: 260)
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text(" ").font(.caption)
                        Button("Add") { addSnippet() }
                            .buttonStyle(.borderedProminent)
                            .disabled(newTrigger.isEmpty || newExpansion.isEmpty)
                    }
                }
                if !statusMessage.isEmpty {
                    Text(statusMessage).font(.caption)
                        .foregroundColor(statusMessage.hasPrefix("Failed") ? .red : .secondary)
                }
            }
            .padding()
        }
        .frame(width: 560, height: 480)
        .onAppear { loadSnippets() }
    }

    private func loadSnippets() {
        isLoading = true
        backendClient?.listSnippets { items in
            let loaded = items.compactMap { s -> SnippetEntry? in
                guard let trigger   = s["trigger"]   as? String,
                      let expansion = s["expansion"] as? String
                else { return nil }
                return SnippetEntry(trigger: trigger, expansion: expansion, enabled: s["enabled"] as? Bool ?? true)
            }
            DispatchQueue.main.async {
                self.snippets  = loaded
                self.isLoading = false
            }
        }
    }

    private func addSnippet() {
        let trigger   = newTrigger.trimmingCharacters(in: .whitespacesAndNewlines)
        let expansion = newExpansion.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trigger.isEmpty, !expansion.isEmpty else { return }

        backendClient?.addSnippet(trigger: trigger, expansion: expansion) { success in
            DispatchQueue.main.async {
                if success {
                    self.snippets.append(SnippetEntry(trigger: trigger, expansion: expansion, enabled: true))
                    self.newTrigger    = ""
                    self.newExpansion  = ""
                    self.statusMessage = "Saved"
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.statusMessage = "" }
                } else {
                    self.statusMessage = "Failed to save"
                }
            }
        }
    }

    private func saveEdit(_ snippet: SnippetEntry, trigger: String, expansion: String) {
        backendClient?.removeSnippet(trigger: snippet.trigger) { _ in
            self.backendClient?.addSnippet(trigger: trigger, expansion: expansion) { success in
                DispatchQueue.main.async {
                    if success, let idx = self.snippets.firstIndex(where: { $0.id == snippet.id }) {
                        self.snippets[idx] = SnippetEntry(trigger: trigger, expansion: expansion, enabled: true)
                    }
                    self.editingID = nil
                }
            }
        }
    }

    private func removeSnippet(_ snippet: SnippetEntry) {
        backendClient?.removeSnippet(trigger: snippet.trigger) { success in
            DispatchQueue.main.async {
                if success { self.snippets.removeAll { $0.id == snippet.id } }
            }
        }
    }
}

struct SnippetRow: View {
    let snippet   : SnippetEntry
    let isEditing : Bool
    let onEdit    : () -> Void
    let onSave    : (String, String) -> Void
    let onCancel  : () -> Void
    let onDelete  : () -> Void

    @State private var editTrigger   : String = ""
    @State private var editExpansion : String = ""

    var body: some View {
        if isEditing {
            HStack(spacing: 8) {
                TextField("Trigger", text: $editTrigger)
                    .textFieldStyle(.roundedBorder).frame(width: 140)
                TextField("Expansion", text: $editExpansion).textFieldStyle(.roundedBorder)
                Button("Save") {
                    onSave(
                        editTrigger.trimmingCharacters(in: .whitespacesAndNewlines),
                        editExpansion.trimmingCharacters(in: .whitespacesAndNewlines)
                    )
                }
                .buttonStyle(.borderedProminent).controlSize(.small)
                .disabled(editTrigger.isEmpty || editExpansion.isEmpty)
                Button("Cancel", action: onCancel).buttonStyle(.bordered).controlSize(.small)
            }
            .padding(.vertical, 4)
            .onAppear {
                editTrigger   = snippet.trigger
                editExpansion = snippet.expansion
            }
        } else {
            HStack(spacing: 10) {
                Text(snippet.trigger)
                    .font(.subheadline).fontWeight(.medium)
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(Color.accentColor.opacity(0.12))
                    .cornerRadius(5)
                Text(snippet.expansion)
                    .font(.subheadline).foregroundColor(.secondary)
                    .lineLimit(1).truncationMode(.middle)
                Spacer()
                Button { onEdit() } label: {
                    Image(systemName: "pencil").foregroundColor(.secondary)
                }.buttonStyle(.plain)
                Button { onDelete() } label: {
                    Image(systemName: "trash").foregroundColor(.red)
                }.buttonStyle(.plain)
            }
            .padding(.vertical, 4)
        }
    }
}
