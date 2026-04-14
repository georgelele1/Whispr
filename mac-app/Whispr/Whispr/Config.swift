import Foundation

enum Config {

<<<<<<< Updated upstream
=======
    // ── Add your path here, nothing else needs to change ──
    static let fallbackRoots = [
        "/Users/quinta/Desktop/snippet实现和测试报告/Comp9900_project_testversion-main",
        "/Users/georgelele/OneDrive/桌面/9900/Comp9900_project_testversion",
        "/Users/yanbowang/Comp9900_project_testversion",
        "/Users/austinmac/Desktop/9900/new/Comp9900_project_testversion",
        "/Users/fiona/Desktop/9900/Comp9900_project_testversion"
        // add your path below this line
    ]

    // ── Add your Python path here if it's not in the default list ──
    static let pythonCandidates = [
        "/Users/yanbowang/opt/anaconda3/bin/python3.11",
        "/Users/yanbowang/opt/anaconda3/bin/python3",
        "/opt/homebrew/bin/python3.11",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3.11",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3",
        "/Users/fiona/anaconda3/bin/python"
    ]

>>>>>>> Stashed changes
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
