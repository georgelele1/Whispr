import SwiftUI

struct APIKeysView: View {

    @ObservedObject private var client = AppManager.shared.localBackendClient

    @State private var selectedModel    : String  = AppManager.shared.localBackendClient.activeModel
    @State private var apiKeyInput      : String  = ""
    @State private var detectedProvider : Config.Provider? = nil
    @State private var isDetecting      : Bool    = false
    @State private var isSavingKey      : Bool    = false
    @State private var isLoadingModel   : Bool    = false
    @State private var statusMessage    : String  = ""
    @State private var isError          : Bool    = false
    @State private var isLoadingBalance : Bool    = false
    @State private var lastCost         : Double? = nil
    @State private var coBalance        : Double? = nil
    @State private var coUsed           : Double? = nil

    var backendClient: LocalBackendClient?
    private let accent = Color(red: 0.498, green: 0.467, blue: 0.867)

    private var activeClient: LocalBackendClient {
        backendClient ?? AppManager.shared.localBackendClient
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    balanceSection
                    modelPicker
                    keySection
                }
                .padding(24)
            }
        }
        .frame(width: 580, height: 520)
        .onAppear {
            loadCurrentState()
            loadBalance()
        }
    }

    // MARK: - Header

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Model & API Keys").font(.title2).bold()
                Text("Google Gemini is included free via connectonion. Add keys for other providers to unlock their models.")
                    .font(.caption).foregroundColor(.secondary)
            }
            Spacer()
            if isLoadingModel { ProgressView().scaleEffect(0.8) }
        }
        .padding()
    }

    // MARK: - Model picker (only shows unlocked providers)

    private var modelPicker: some View {
        VStack(alignment: .leading, spacing: 14) {
            sectionLabel("Choose a model", icon: "cpu")

            ForEach(Config.modelsByProvider, id: \.provider.id) { group in
                let unlocked = client.storedProviders.contains(group.provider.id)

                VStack(alignment: .leading, spacing: 8) {

                    // Provider header
                    HStack(spacing: 6) {
                        Image(systemName: group.provider.free ? "star.fill" : (unlocked ? "checkmark.shield.fill" : "lock"))
                            .font(.system(size: 10))
                            .foregroundColor(providerColor(group.provider))
                        Text(group.provider.displayName)
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(providerColor(group.provider))
                        if group.provider.free {
                            Text("included free")
                                .font(.caption2).foregroundColor(.secondary)
                                .padding(.horizontal, 6).padding(.vertical, 2)
                                .background(Color.secondary.opacity(0.1))
                                .cornerRadius(4)
                        } else if unlocked {
                            Text("key saved")
                                .font(.caption2).foregroundColor(.green)
                                .padding(.horizontal, 6).padding(.vertical, 2)
                                .background(Color.green.opacity(0.08))
                                .cornerRadius(4)
                        } else {
                            Text("add key to unlock")
                                .font(.caption2).foregroundColor(.secondary)
                                .padding(.horizontal, 6).padding(.vertical, 2)
                                .background(Color.secondary.opacity(0.08))
                                .cornerRadius(4)
                        }
                    }

                    // Model pills — greyed out if locked
                    HStack(spacing: 8) {
                        ForEach(group.models) { option in
                            ModelPill(
                                option:     option,
                                isSelected: selectedModel == option.id,
                                isLocked:   !unlocked,
                                accent:     accent
                            ) {
                                guard unlocked else { return }
                                selectModel(option.id)
                            }
                        }
                    }
                }
            }
        }
    }

    // MARK: - API key section

    private var keySection: some View {
        VStack(alignment: .leading, spacing: 14) {
            Divider()
            sectionLabel("API Keys", icon: "key")

            // Stored keys per paid provider
            ForEach(Config.providers.filter { !$0.free }, id: \.id) { provider in
                let hasKey = client.storedProviders.contains(provider.id)
                HStack(spacing: 10) {
                    Image(systemName: hasKey ? "checkmark.circle.fill" : "circle")
                        .foregroundColor(hasKey ? .green : .secondary)
                    Text(provider.displayName)
                        .font(.subheadline)
                    Spacer()
                    if hasKey {
                        Button("Replace") {
                            apiKeyInput      = ""
                            detectedProvider = provider
                        }
                        .buttonStyle(.bordered).controlSize(.small)
                        Button("Remove") { removeKey(provider: provider.id) }
                            .buttonStyle(.bordered).controlSize(.small)
                            .tint(.red)
                    }
                }
                .padding(10)
                .background(hasKey ? Color.green.opacity(0.05) : Color(NSColor.controlBackgroundColor))
                .cornerRadius(8)
                .overlay(RoundedRectangle(cornerRadius: 8)
                    .stroke(hasKey ? Color.green.opacity(0.2) : Color.secondary.opacity(0.12), lineWidth: 0.5))
            }

            // Key input — auto-detects provider on paste
            VStack(alignment: .leading, spacing: 8) {
                Text("Paste an API key — provider is detected automatically from the key prefix.")
                    .font(.caption).foregroundColor(.secondary)

                HStack(spacing: 10) {
                    ZStack(alignment: .leading) {
                        SecureField("sk-… or AIza… or sk-ant-…", text: $apiKeyInput)
                            .textFieldStyle(.roundedBorder)
                            .onChange(of: apiKeyInput) { newValue in
                                detectFromInput(newValue)
                            }
                    }

                    // Detected provider badge
                    if let detected = detectedProvider {
                        HStack(spacing: 4) {
                            Image(systemName: "checkmark.circle.fill")
                                .font(.system(size: 11))
                                .foregroundColor(.green)
                            Text(detected.displayName)
                                .font(.system(size: 11, weight: .medium))
                                .foregroundColor(.green)
                        }
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(Color.green.opacity(0.08))
                        .cornerRadius(6)
                    } else if !apiKeyInput.isEmpty {
                        HStack(spacing: 4) {
                            Image(systemName: "questionmark.circle")
                                .font(.system(size: 11))
                                .foregroundColor(.orange)
                            Text("Unknown")
                                .font(.system(size: 11))
                                .foregroundColor(.orange)
                        }
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(Color.orange.opacity(0.08))
                        .cornerRadius(6)
                    }

                    Button(action: saveKey) {
                        if isSavingKey {
                            ProgressView().scaleEffect(0.75).frame(width: 60, height: 22)
                        } else {
                            Text("Save")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(accent)
                    .disabled(apiKeyInput.trimmingCharacters(in: .whitespaces).isEmpty
                              || detectedProvider == nil
                              || isSavingKey)
                }
            }

            if !statusMessage.isEmpty {
                HStack(spacing: 4) {
                    Image(systemName: isError ? "xmark.circle.fill" : "checkmark.circle.fill")
                        .font(.system(size: 11))
                        .foregroundColor(isError ? .red : .green)
                    Text(statusMessage)
                        .font(.caption)
                        .foregroundColor(isError ? .red : .green)
                }
            }
        }
    }

    // MARK: - Balance section

    private var balanceSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionLabel("Usage & balance", icon: "coloncurrencysign.circle")

            HStack(spacing: 10) {
                balanceCard(
                    title: "Last call",
                    value: lastCost.map { $0 < 0.0001 ? "<$0.0001" : String(format: "$%.4f", $0) } ?? "—",
                    color: .primary
                )
                balanceCard(
                    title: "Connectonion",
                    value: coBalance.map { String(format: "$%.2f", $0) } ?? "—",
                    subtitle: coUsed.map { String(format: "$%.4f used", $0) },
                    color: (coBalance ?? 0) < 1 ? .orange : .green
                )
                if isLoadingBalance {
                    ProgressView().scaleEffect(0.7)
                } else {
                    Button { loadBalance() } label: {
                        Image(systemName: "arrow.clockwise").font(.system(size: 12)).foregroundColor(.secondary)
                    }
                    .buttonStyle(.plain).help("Refresh balances")
                }
            }
        }
    }

    private func balanceCard(title: String, value: String, subtitle: String? = nil, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption).foregroundColor(.secondary)
            Text(value).font(.system(size: 14, weight: .semibold)).foregroundColor(color)
            if let subtitle { Text(subtitle).font(.caption2).foregroundColor(.secondary) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.15), lineWidth: 0.5))
    }

    // MARK: - Helpers

    private func sectionLabel(_ text: String, icon: String) -> some View {
        Label(text, systemImage: icon)
            .font(.system(size: 11, weight: .semibold))
            .foregroundColor(.secondary)
            .textCase(.uppercase)
            .tracking(0.4)
    }

    private func providerColor(_ provider: Config.Provider) -> Color {
        switch provider.id {
        case "google":    return Color(red: 0.26, green: 0.52, blue: 0.96)
        case "openai":    return Color(red: 0.07, green: 0.73, blue: 0.49)
        case "anthropic": return Color(red: 0.80, green: 0.40, blue: 0.20)
        default:          return .secondary
        }
    }

    // MARK: - Actions

    private func detectFromInput(_ key: String) {
        let trimmed = key.trimmingCharacters(in: .whitespacesAndNewlines)
        detectedProvider = trimmed.isEmpty ? nil : Config.detectProvider(for: trimmed)
    }

    private func loadBalance() {
        isLoadingBalance = true
        activeClient.fetchBalance { result, _ in
            DispatchQueue.main.async {
                self.isLoadingBalance = false
                self.coBalance        = result?.connectonionBalance
                self.coUsed           = result?.connectonionUsed
            }
        }
    }

    private func loadCurrentState() {
        lastCost  = AppManager.shared.lastCost
        coBalance = AppManager.shared.lastConnectonionBalance

        isLoadingModel = true
        activeClient.fetchModelFromBackend { model in
            DispatchQueue.main.async {
                self.selectedModel  = model ?? AppManager.shared.localBackendClient.activeModel
                self.isLoadingModel = false
            }
        }
        activeClient.refreshStoredProviders()
    }

    private func selectModel(_ modelID: String) {
        guard modelID != selectedModel else { return }
        selectedModel = modelID
        activeClient.setModelOnBackend(modelID) { _ in }
        statusMessage = ""
    }

    private func saveKey() {
        let key = apiKeyInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { return }
        isSavingKey = true

        activeClient.detectAndSaveAPIKey(key) { result in
            DispatchQueue.main.async {
                self.isSavingKey = false
                switch result {
                case .success(let provider):
                    self.isError       = false
                    self.statusMessage = "\(provider.displayName) key saved — \(provider.models.count) models unlocked"
                    self.apiKeyInput   = ""
                    self.detectedProvider = nil
                    // Auto-select first model of newly unlocked provider if current is locked
                    if Config.requiresAPIKey(self.selectedModel),
                       !self.client.storedProviders.contains(
                            Config.provider(forModelID: self.selectedModel)?.id ?? "") {
                        if let first = provider.models.first {
                            self.selectModel(first.id)
                        }
                    }
                case .failure(let error):
                    self.isError       = true
                    self.statusMessage = error.localizedDescription
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 4) { self.statusMessage = "" }
            }
        }
    }

    private func removeKey(provider: String) {
        activeClient.removeAPIKey(provider: provider) { success in
            DispatchQueue.main.async {
                self.isError       = !success
                self.statusMessage = success ? "Key removed" : "Failed to remove key"
                // If active model belonged to removed provider, fall back to free default
                if success,
                   let currentProvider = Config.provider(forModelID: self.selectedModel),
                   currentProvider.id == provider {
                    self.selectModel(Config.defaultModel)
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.statusMessage = "" }
            }
        }
    }
}

// MARK: - ModelPill

private struct ModelPill: View {
    let option    : Config.ModelOption
    let isSelected: Bool
    let isLocked  : Bool
    let accent    : Color
    let action    : () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: isLocked ? "lock" : (isSelected ? "checkmark.circle.fill" : "circle"))
                    .font(.system(size: 12))
                    .foregroundColor(isLocked ? .secondary.opacity(0.4) : (isSelected ? accent : .secondary))
                Text(option.label)
                    .font(.system(size: 12))
                    .foregroundColor(isLocked ? .secondary.opacity(0.4) : (isSelected ? .primary : .secondary))
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(isLocked
                ? Color(NSColor.controlBackgroundColor).opacity(0.5)
                : (isSelected ? accent.opacity(0.08) : Color(NSColor.controlBackgroundColor)))
            .cornerRadius(8)
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(isLocked ? Color.secondary.opacity(0.1)
                            : (isSelected ? accent : Color.secondary.opacity(0.2)),
                            lineWidth: isSelected ? 1 : 0.5)
            )
        }
        .buttonStyle(.plain)
        .disabled(isLocked)
    }
}
