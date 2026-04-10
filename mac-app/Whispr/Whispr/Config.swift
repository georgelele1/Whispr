import Foundation

enum Config {

    // ── Supported output languages ────────────────────────
    static let supportedLanguages = [
        "English", "Chinese", "Spanish", "French",
        "Japanese", "Korean", "Arabic", "German", "Portuguese",
    ]

    // ── Target language preference (persisted in UserDefaults) ──
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
}
