import Foundation

enum Config {

    // ── Supported output languages ────────────────────────
    static let supportedLanguages = [
        "English", "Chinese", "Spanish", "French",
        "Japanese", "Korean", "Arabic", "German", "Portuguese",
    ]

    static var targetLanguage: String {
        get {
            let saved = UserDefaults.standard.string(forKey: "targetLanguage") ?? "English"
            return supportedLanguages.contains(saved) ? saved : "English"
        }
        set {
            guard supportedLanguages.contains(newValue) else { return }
            UserDefaults.standard.set(newValue, forKey: "targetLanguage")
        }
    }

    // ── Model option ──────────────────────────────────────
    struct ModelOption: Identifiable {
        let id       : String   // model ID passed to backend
        let label    : String   // display name
        let provider : String   // matches Provider.id
    }

    // ── Provider registry ─────────────────────────────────
    /// A provider entry. `free` means no user API key is required.
    /// `keyPrefixes` are used to auto-detect which provider a pasted key belongs to.
    struct Provider: Identifiable {
        let id         : String          // e.g. "openai", "google", "anthropic"
        let displayName: String          // e.g. "OpenAI"
        let free       : Bool            // true = always available (connectonion covers it)
        let keyPrefixes: [String]        // key prefixes for auto-detection
        let models     : [ModelOption]
    }

    static let providers: [Provider] = [
        Provider(
            id:          "google",
            displayName: "Google",
            free:        true,
            keyPrefixes: ["AIza"],
            models: [
                ModelOption(id: "co/gemini-3-flash-preview", label: "Gemini 3 Flash",   provider: "Google"),
                ModelOption(id: "co/gemini-3-pro-preview",   label: "Gemini 3 Pro",     provider: "Google"),
                ModelOption(id: "co/gemini-2.5-flash",       label: "Gemini 2.5 Flash", provider: "Google"),
            ]
        ),
        Provider(
            id:          "openai",
            displayName: "OpenAI",
            free:        false,
            keyPrefixes: ["sk-"],
            models: [
                ModelOption(id: "gpt-5.4", label: "GPT-5.4 (Fast)",     provider: "OpenAI"),
                ModelOption(id: "gpt-5",   label: "GPT-5 (Powerful)",   provider: "OpenAI"),
                ModelOption(id: "gpt-4o",  label: "GPT-4o (Efficient)", provider: "OpenAI"),
            ]
        ),
        Provider(
            id:          "anthropic",
            displayName: "Anthropic",
            free:        false,
            keyPrefixes: ["sk-ant-"],
            models: [
                ModelOption(id: "claude-opus-4-6",    label: "Claude Opus 4.6",   provider: "Anthropic"),
                ModelOption(id: "claude-sonnet-4-6",  label: "Claude Sonnet 4.6", provider: "Anthropic"),
                ModelOption(id: "claude-haiku-4-5",   label: "Claude Haiku 4.5",  provider: "Anthropic"),
            ]
        ),
    ]

    // ── Flat model list (all providers) ──────────────────
    static var modelOptions: [ModelOption] {
        providers.flatMap { $0.models }
    }

    static let defaultModel = "co/gemini-3-flash-preview"

    // ── Provider lookup helpers ───────────────────────────

    /// Detect which provider a pasted API key belongs to based on its prefix.
    /// Returns nil if no prefix matches — user will be asked to pick manually.
    static func detectProvider(for key: String) -> Provider? {
        let trimmed = key.trimmingCharacters(in: .whitespacesAndNewlines)
        // Longest prefix wins so "sk-ant-" beats "sk-"
        return providers
            .filter { !$0.free }
            .flatMap { p in p.keyPrefixes.map { (prefix: $0, provider: p) } }
            .sorted { $0.prefix.count > $1.prefix.count }
            .first { trimmed.hasPrefix($0.prefix) }?
            .provider
    }

    static func provider(for id: String) -> Provider? {
        providers.first { $0.id == id }
    }

    static func provider(forModelID modelID: String) -> Provider? {
        providers.first { $0.models.contains { $0.id == modelID } }
    }

    /// Returns true if the model belongs to a provider that requires a user key.
    static func requiresAPIKey(_ modelID: String) -> Bool {
        guard let p = provider(forModelID: modelID) else { return false }
        return !p.free
    }

    /// Models grouped by provider — free providers first.
    static var modelsByProvider: [(provider: Provider, models: [ModelOption])] {
        providers.map { p in (provider: p, models: p.models) }
    }
}
