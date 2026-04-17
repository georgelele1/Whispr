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

    // ── Model options (mirrors storage.py MODEL_OPTIONS) ──
    struct ModelOption: Identifiable {
        let id       : String   // model ID passed to backend
        let label    : String   // display name
        let provider : String   // "OpenAI" | "Google"
    }

    static let modelOptions: [ModelOption] = [
        // Google via connectonion — no API key needed
        ModelOption(id: "co/gemini-3-flash-preview", label: "Gemini 3 Flash",   provider: "Google"),
        ModelOption(id: "co/gemini-3-pro-preview",   label: "Gemini 3 Pro",     provider: "Google"),
        ModelOption(id: "co/gemini-2.5-flash",       label: "Gemini 2.5 Flash", provider: "Google"),
        // OpenAI — requires user API key
        ModelOption(id: "gpt-5.4", label: "GPT-5.4 (Fast)",     provider: "OpenAI"),
        ModelOption(id: "gpt-5",   label: "GPT-5 (Powerful)",   provider: "OpenAI"),
        ModelOption(id: "gpt-4o",  label: "GPT-4o (Efficient)", provider: "OpenAI"),
    ]

    static let defaultModel = "co/gemini-3-flash-preview"

    static let openAIModelIDs: Set<String> = Set(
        modelOptions.filter { $0.provider == "OpenAI" }.map { $0.id }
    )

    /// Returns true only for OpenAI models.
    /// All co/ (Google Gemini) models are authenticated via OPENONION_API_KEY
    /// in the bundled backend .env — no user key required.
    static func requiresAPIKey(_ modelID: String) -> Bool {
        openAIModelIDs.contains(modelID)
    }

    /// Models grouped by provider — Google first so the free tier is most visible.
    static var modelsByProvider: [(provider: String, models: [ModelOption])] {
        ["Google", "OpenAI"].compactMap { p in
            let ms = modelOptions.filter { $0.provider == p }
            return ms.isEmpty ? nil : (provider: p, models: ms)
        }
    }
}
