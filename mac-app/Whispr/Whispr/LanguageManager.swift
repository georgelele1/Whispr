import Foundation
import Combine

final class LanguageManager: ObservableObject {
    static let shared = LanguageManager()

    @Published private(set) var current: String

    private init() {
        self.current = Config.targetLanguage
    }

    func setLanguage(_ language: String) {
        guard Config.supportedLanguages.contains(language) else { return }
        Config.targetLanguage = language
        current = language
    }

    func syncFromBackend(_ language: String?) {
        guard let language, Config.supportedLanguages.contains(language) else { return }
        setLanguage(language)
    }
}
