import Foundation
import Combine

struct DictionaryTerm {
    let phrase    : String
    let type      : String
    let aliases   : [String]
    let confidence: Double

    init?(dict: [String: Any]) {
        guard let phrase = dict["phrase"] as? String else { return nil }
        self.phrase     = phrase
        self.type       = dict["type"]       as? String ?? "custom"
        self.aliases    = dict["aliases"]    as? [String] ?? []
        self.confidence = dict["confidence"] as? Double ?? 1.0
    }
}

struct DictionaryUpdateResult {
    let added     : [DictionaryTerm]
    let updated   : [DictionaryTerm]
    let totalTerms: Int
}

// =========================================================
// LocalBackendClient
//
// All communication goes to the Flask server running on
// localhost:8765. The server is launched by AppManager at
// startup and killed on quit.
//
// Every method mirrors its old CLI counterpart exactly —
// callers (AppManager, views) are unchanged.
// =========================================================

final class LocalBackendClient: ObservableObject {
    @Published var isBackendAvailable = false

    static let port    = 8765
    static let baseURL = URL(string: "http://127.0.0.1:\(port)")!

    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest  = 300
        config.timeoutIntervalForResource = 300
        return URLSession(configuration: config)
    }()

    init() {
        // Availability is set by AppManager after the server is confirmed ready
    }

    // =========================================================
    // Internal helpers
    // =========================================================

    private func url(_ path: String) -> URL {
        Self.baseURL.appendingPathComponent(path)
    }

    /// JSON GET
    private func get(
        _ path: String,
        completion: @escaping (Result<[String: Any], Error>) -> Void
    ) {
        var req = URLRequest(url: url(path))
        req.httpMethod = "GET"
        perform(req, completion: completion)
    }

    /// JSON POST with optional body
    private func post(
        _ path: String,
        body: [String: Any]? = nil,
        completion: @escaping (Result<[String: Any], Error>) -> Void
    ) {
        var req = URLRequest(url: url(path))
        req.httpMethod = "POST"
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        perform(req, completion: completion)
    }

    /// JSON DELETE with optional body
    private func delete(
        _ path: String,
        body: [String: Any]? = nil,
        completion: @escaping (Result<[String: Any], Error>) -> Void
    ) {
        var req = URLRequest(url: url(path))
        req.httpMethod = "DELETE"
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        perform(req, completion: completion)
    }

    private func perform(
        _ request: URLRequest,
        completion: @escaping (Result<[String: Any], Error>) -> Void
    ) {
        session.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                if let error {
                    completion(.failure(error)); return
                }
                guard let data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                else {
                    completion(.failure(NSError(
                        domain: "LocalBackendClient", code: -1,
                        userInfo: [NSLocalizedDescriptionKey: "Invalid JSON response"]
                    )))
                    return
                }
                completion(.success(json))
            }
        }.resume()
    }

    // =========================================================
    // Health check — called by AppManager while waiting for boot
    // =========================================================

    func ping(completion: @escaping (Bool) -> Void) {
        get("/ping") { result in
            if case .success = result { completion(true) } else { completion(false) }
        }
    }

    // =========================================================
    // Transcription
    // =========================================================

    func transcribeAudio(
        fileURL        : URL,
        appName        : String,
        completion     : @escaping (Result<String, Error>) -> Void
    ) {
        let targetLanguage = LanguageManager.shared.current

        var req = URLRequest(url: url("/transcribe"))
        req.httpMethod = "POST"

        let boundary = UUID().uuidString
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        let nl   = "\r\n"

        // Audio file field
        if let audioData = try? Data(contentsOf: fileURL) {
            body.append("--\(boundary)\(nl)".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"audio\"; filename=\"\(fileURL.lastPathComponent)\"\(nl)".data(using: .utf8)!)
            body.append("Content-Type: audio/wav\(nl)\(nl)".data(using: .utf8)!)
            body.append(audioData)
            body.append(nl.data(using: .utf8)!)
        }

        // app_name field
        body.append("--\(boundary)\(nl)".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"app_name\"\(nl)\(nl)".data(using: .utf8)!)
        body.append((appName.isEmpty ? "unknown" : appName).data(using: .utf8)!)
        body.append(nl.data(using: .utf8)!)

        // target_language field
        body.append("--\(boundary)\(nl)".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"target_language\"\(nl)\(nl)".data(using: .utf8)!)
        body.append(targetLanguage.data(using: .utf8)!)
        body.append(nl.data(using: .utf8)!)

        body.append("--\(boundary)--\(nl)".data(using: .utf8)!)
        req.httpBody = body

        session.dataTask(with: req) { data, _, error in
            DispatchQueue.main.async {
                if let error { completion(.failure(error)); return }
                guard let data,
                      let json   = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let output = json["output"] as? String
                else {
                    completion(.failure(NSError(
                        domain: "LocalBackendClient", code: -1,
                        userInfo: [NSLocalizedDescriptionKey: "Invalid transcription response"]
                    )))
                    return
                }
                completion(.success(output))
            }
        }.resume()
    }

    // =========================================================
    // Dictionary update
    // =========================================================

    func runDictionaryUpdate(completion: @escaping (Result<DictionaryUpdateResult, Error>) -> Void) {
        post("/dictionary/update") { result in
            switch result {
            case .failure(let error):
                completion(.failure(error))
            case .success(let json):
                let added   = (json["added"]   as? [[String: Any]] ?? []).compactMap { DictionaryTerm(dict: $0) }
                let updated = (json["updated"] as? [[String: Any]] ?? []).compactMap { DictionaryTerm(dict: $0) }
                let total   = json["total_terms"] as? Int ?? 0
                completion(.success(DictionaryUpdateResult(added: added, updated: updated, totalTerms: total)))
            }
        }
    }

    // =========================================================
    // Language
    // =========================================================

    func syncLanguageToBackend(completion: ((Bool) -> Void)? = nil) {
        let language = LanguageManager.shared.current
        post("/language", body: ["language": language]) { result in
            completion?(result.map { _ in true }.isSuccess)
        }
    }

    func fetchLanguageFromBackend(completion: @escaping (String?) -> Void) {
        get("/language") { result in
            guard case .success(let json) = result,
                  let lang = json["language"] as? String
            else { completion(nil); return }
            completion(lang)
        }
    }

    // =========================================================
    // History
    // =========================================================

    func loadHistory(completion: @escaping ([[String: Any]]) -> Void) {
        get("/history") { result in
            guard case .success(let json) = result,
                  let items = json["items"] as? [[String: Any]]
            else { completion([]); return }
            completion(items)
        }
    }

    // =========================================================
    // Data management
    // =========================================================

    func clearHistory(completion: @escaping (Bool) -> Void) {
        delete("/history") { result in
            completion(result.isSuccess)
        }
    }

    func clearDictionary(completion: @escaping (Bool) -> Void) {
        delete("/dictionary") { result in
            completion(result.isSuccess)
        }
    }

    func clearSnippets(completion: @escaping (Bool) -> Void) {
        delete("/snippets/all") { result in
            completion(result.isSuccess)
        }
    }

    func resetProfile(completion: @escaping (Bool) -> Void) {
        post("/reset/profile") { result in
            completion(result.isSuccess)
        }
    }

    func resetAll(completion: @escaping (Bool) -> Void) {
        post("/reset/all") { result in
            completion(result.isSuccess)
        }
    }

    // =========================================================
    // Onboarding & profile
    // =========================================================

    func isFirstLaunch(completion: @escaping (Bool) -> Void) {
        get("/profile/first-launch") { result in
            guard case .success(let json) = result,
                  let first = json["first_launch"] as? Bool
            else { completion(false); return }
            completion(first)
        }
    }

    func saveOnboardingProfile(_ profile: [String: Any], completion: @escaping (Bool) -> Void) {
        post("/profile/onboarding", body: profile) { result in
            completion(result.isSuccess)
        }
    }

    // =========================================================
    // Dictionary CRUD
    // =========================================================

    func listDictionaryTerms(completion: @escaping ([[String: Any]]) -> Void) {
        get("/dictionary") { result in
            guard case .success(let json) = result,
                  let terms = json["terms"] as? [[String: Any]]
            else { completion([]); return }
            completion(terms)
        }
    }

    func addDictionaryTerm(phrase: String, aliases: [String], completion: @escaping (Bool) -> Void) {
        post("/dictionary/term", body: ["phrase": phrase, "aliases": aliases]) { result in
            completion(result.isSuccess)
        }
    }

    func removeDictionaryTerm(phrase: String, completion: @escaping (Bool) -> Void) {
        delete("/dictionary/term", body: ["phrase": phrase]) { result in
            completion(result.isSuccess)
        }
    }

    // =========================================================
    // Snippets
    // =========================================================

    func listSnippets(completion: @escaping ([[String: Any]]) -> Void) {
        get("/snippets") { result in
            guard case .success(let json) = result,
                  let snippets = json["snippets"] as? [[String: Any]]
            else { completion([]); return }
            completion(snippets)
        }
    }

    func addSnippet(trigger: String, expansion: String, completion: @escaping (Bool) -> Void) {
        post("/snippets", body: ["trigger": trigger, "expansion": expansion]) { result in
            completion(result.isSuccess)
        }
    }

    func removeSnippet(trigger: String, completion: @escaping (Bool) -> Void) {
        delete("/snippets", body: ["trigger": trigger]) { result in
            completion(result.isSuccess)
        }
    }

    // =========================================================
    // Google Calendar
    // =========================================================

    func fetchCalendarEmail(completion: @escaping (String?) -> Void) {
        get("/calendar/email") { result in
            guard case .success(let json) = result else { completion(nil); return }
            completion(json["email"] as? String)
        }
    }

    func connectGoogleCalendar(completion: @escaping (String?) -> Void) {
        post("/calendar/connect") { result in
            guard case .success(let json) = result else { completion(nil); return }
            completion(json["email"] as? String)
        }
    }

    func disconnectGoogleCalendar(completion: @escaping (Bool) -> Void) {
        post("/calendar/disconnect") { result in
            completion(result.isSuccess)
        }
    }

    // =========================================================
    // Text insertions
    // =========================================================

    func listTextInsertions(completion: @escaping ([[String: Any]]) -> Void) {
        get("/insertions") { result in
            guard case .success(let json) = result,
                  let items = json["insertions"] as? [[String: Any]]
            else { completion([]); return }
            completion(items)
        }
    }

    func saveTextInsertion(label: String, value: String, completion: @escaping (Bool) -> Void) {
        post("/insertions", body: ["label": label, "value": value]) { result in
            completion(result.isSuccess)
        }
    }

    func removeTextInsertion(label: String, completion: @escaping (Bool) -> Void) {
        delete("/insertions", body: ["label": label]) { result in
            completion(result.isSuccess)
        }
    }
}

// =========================================================
// Result convenience
// =========================================================

private extension Result {
    var isSuccess: Bool {
        if case .success = self { return true }
        return false
    }
}
