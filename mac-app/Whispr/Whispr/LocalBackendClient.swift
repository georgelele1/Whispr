import Foundation
import Combine
import AppKit

// MARK: - Shared response types (kept for DictionaryView / AppManager)

struct DictionaryTerm {
    let phrase: String
    let type: String
    let aliases: [String]
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

// MARK: - LocalBackendClient

final class LocalBackendClient: ObservableObject {

    @Published var isBackendAvailable: Bool = false
    /// Provider IDs with a stored key — free providers always included.
    @Published var storedProviders: Set<String> = Set(Config.providers.filter { $0.free }.map { $0.id })

    /// Currently active model ID — kept in sync with backend storage.
    @Published var activeModel: String = Config.defaultModel

    private let timeout: TimeInterval = 300
    private var pythonPath       : String?
    private var backendScriptPath: String?

    init() {
        checkBackendAvailability()
        refreshStoredProviders()

        if isBackendAvailable {
            fetchModelFromBackend { [weak self] model in
                if let model { self?.activeModel = model }
            }
        }
    }

    // =========================================================
    // Backend availability
    // =========================================================

    private func checkBackendAvailability() {
        let fm = FileManager.default

        pythonPath = Bundle.main.resourceURL?
            .appendingPathComponent("runtime/venv/bin/python")
            .path

        backendScriptPath = Bundle.main.resourceURL?
            .appendingPathComponent("backend/app.py")
            .path

        if let p = pythonPath,        !fm.fileExists(atPath: p) { pythonPath        = nil }
        if let p = backendScriptPath, !fm.fileExists(atPath: p) { backendScriptPath = nil }

        isBackendAvailable = (pythonPath != nil && backendScriptPath != nil)
    }

    func refreshRuntimePaths() {
        checkBackendAvailability()
    }

    // =========================================================
    // Core Python runner
    // =========================================================

    private func runPythonCommand(
        script    : String,
        arguments : [String],
        completion: @escaping (Result<String, Error>) -> Void
    ) {
        guard let pythonPath else {
            completion(.failure(makeError("Python not found")))
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.currentDirectoryURL = URL(fileURLWithPath: script).deletingLastPathComponent()
            process.executableURL       = URL(fileURLWithPath: pythonPath)
            process.arguments           = [script] + arguments
            process.environment         = ProcessInfo.processInfo.environment

            let outPipe = Pipe()
            let errPipe = Pipe()
            process.standardOutput = outPipe
            process.standardError  = errPipe

            do    { try process.run() }
            catch { DispatchQueue.main.async { completion(.failure(error)) }; return }

            process.waitUntilExit()

            let out = String(data: outPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            let err = String(data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""

            // Strip connectonion noise lines ([env], [co], [agent]) that pollute stdout
            let cleanOut = out.components(separatedBy: .newlines)
                .filter { line in
                    let t = line.trimmingCharacters(in: .whitespaces)
                    return !t.hasPrefix("[env]") && !t.hasPrefix("[co]") &&
                           !t.hasPrefix("[agent]") && !t.hasPrefix("[whispr]")
                }
                .joined(separator: "\n")

            DispatchQueue.main.async {
                if process.terminationStatus == 0 {
                    completion(.success(cleanOut))
                } else {
                    completion(.failure(self.makeError(err.isEmpty ? "Command failed" : err)))
                }
            }
        }
    }

    private func makeError(_ msg: String) -> Error {
        NSError(domain: "LocalBackendClient", code: -1,
                userInfo: [NSLocalizedDescriptionKey: msg])
    }

    // =========================================================
    // Model management
    // =========================================================

    func fetchModelFromBackend(completion: @escaping (String?) -> Void) {
        guard let backendScriptPath else { completion(nil); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "get-model"]) { result in
            guard case .success(let output) = result,
                  let data = output.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let model = json["model"] as? String
            else { completion(nil); return }
            completion(model)
        }
    }

    func setModelOnBackend(_ modelID: String, completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath else { completion(false); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "set-model", modelID]) { [weak self] result in
            let ok = (try? result.get()) != nil
            if ok { self?.activeModel = modelID }
            completion(ok)
        }
    }

    // =========================================================
    // API key management (OpenAI — stored as .env on backend)
    // =========================================================

    /// Returns whether a key is currently stored (does NOT return the key itself).
    func checkAPIKeyExists(provider: String = "openai", completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath else { completion(false); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "get-api-key", provider]) { result in
            guard case .success(let output) = result,
                  let data = output.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { completion(false); return }
            completion(json["has_key"] as? Bool ?? false)
        }
    }

    func saveAPIKey(_ key: String, provider: String = "openai", completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath else { completion(false); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "set-api-key", key, provider]) { result in
            switch result {
            case .failure(let error):
                NSLog("[saveAPIKey] Python error: %@", error.localizedDescription)
                completion(false)
            case .success(let output):
                NSLog("[saveAPIKey] output: %@", output)
                if let data = output.data(using: .utf8),
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    completion(json["ok"] as? Bool ?? false)
                } else {
                    completion(!output.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }

    func removeAPIKey(provider: String = "openai", completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath else { completion(false); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "remove-api-key", provider]) { result in
            if (try? result.get()) != nil {
                DispatchQueue.main.async { self.storedProviders.remove(provider) }
                completion(true)
            } else {
                completion(false)
            }
        }
    }

    // ── Provider-aware key management ─────────────────────

    /// Detect provider from key prefix, save it (replacing any existing key for
    /// that provider), and refresh storedProviders. Returns the detected provider
    /// display name so the UI can confirm, or nil if detection failed.
    func detectAndSaveAPIKey(
        _ key: String,
        completion: @escaping (Result<Config.Provider, Error>) -> Void
    ) {
        let trimmed = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            completion(.failure(makeError("Key is empty")))
            return
        }
        guard let provider = Config.detectProvider(for: trimmed) else {
            completion(.failure(makeError("Could not detect provider from key prefix")))
            return
        }
        saveAPIKey(trimmed, provider: provider.id) { success in
            if success {
                DispatchQueue.main.async { self.storedProviders.insert(provider.id) }
                completion(.success(provider))
            } else {
                completion(.failure(self.makeError("Failed to save key for \(provider.displayName)")))
            }
        }
    }

    /// Refresh storedProviders by checking which providers have a key stored.
    func refreshStoredProviders() {
        let paid = Config.providers.filter { !$0.free }
        let group = DispatchGroup()
        var found = Set(Config.providers.filter { $0.free }.map { $0.id })

        for provider in paid {
            group.enter()
            checkAPIKeyExists(provider: provider.id) { exists in
                if exists { found.insert(provider.id) }
                group.leave()
            }
        }
        group.notify(queue: .main) { self.storedProviders = found }
    }

    // =========================================================
    // Transcription
    // =========================================================

    func transcribeAudio(
        fileURL : URL,
        appName : String,
        completion: @escaping (Result<(text: String, cost: Double?), Error>) -> Void
    ) {
        guard let pythonPath, let backendScriptPath else {
            completion(.failure(makeError("Python or backend script not found")))
            return
        }

        let targetLanguage = LanguageManager.shared.current

        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.currentDirectoryURL = URL(fileURLWithPath: backendScriptPath).deletingLastPathComponent()
            process.executableURL       = URL(fileURLWithPath: pythonPath)
            process.arguments = [
                backendScriptPath,
                "cli", "transcribe",
                fileURL.path,
                appName.isEmpty ? "unknown" : appName,
                targetLanguage,
            ]
            process.environment = ProcessInfo.processInfo.environment

            let outPipe = Pipe()
            let errPipe = Pipe()
            process.standardOutput = outPipe
            process.standardError  = errPipe

            do    { try process.run() }
            catch { DispatchQueue.main.async { completion(.failure(error)) }; return }

            var outputData = Data()
            var errorData  = Data()
            let readGroup  = DispatchGroup()

            readGroup.enter()
            DispatchQueue.global().async {
                outputData = outPipe.fileHandleForReading.readDataToEndOfFile()
                readGroup.leave()
            }
            readGroup.enter()
            DispatchQueue.global().async {
                errorData = errPipe.fileHandleForReading.readDataToEndOfFile()
                readGroup.leave()
            }

            process.waitUntilExit()
            _ = readGroup.wait(timeout: .now() + self.timeout)

            let outputString = String(data: outputData, encoding: .utf8) ?? ""
            let errorString  = String(data: errorData,  encoding: .utf8) ?? ""

            DispatchQueue.main.async {
                let trimmed = outputString.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !trimmed.isEmpty else {
                    let detail = errorString.trimmingCharacters(in: .whitespacesAndNewlines)
                    completion(.failure(self.makeError(
                        detail.isEmpty ? "No output from backend" : "No output from backend:\n\(detail)"
                    )))
                    return
                }

                let lines = trimmed.components(separatedBy: .newlines)
                    .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                    .filter { !$0.isEmpty }
                    .filter { !$0.hasPrefix("[env]") && !$0.hasPrefix("[co]") && !$0.hasPrefix("[agent]") && !$0.hasPrefix("[whispr]") }

                guard let jsonLine = lines.last(where: { $0.hasPrefix("{") && $0.hasSuffix("}") }),
                      let data = jsonLine.data(using: .utf8)
                else {
                    completion(.failure(self.makeError("No JSON in output: \(trimmed)")))
                    return
                }

                do {
                    let response = try JSONDecoder().decode(BackendResponse.self, from: data)
                    if process.terminationStatus == 0 {
                        let cost = self.parseTotalCost(from: errorString)
                        completion(.success((text: response.output, cost: cost)))
                    } else {
                        completion(.failure(self.makeError(
                            errorString.isEmpty ? "Backend error \(process.terminationStatus)" : errorString
                        )))
                    }
                } catch {
                    completion(.failure(self.makeError("Invalid JSON: \(jsonLine)")))
                }
            }
        }
    }

    // =========================================================
    // Cost parsing
    // =========================================================

    /// Parse total USD cost from connectonion stderr output.
    /// Lines look like: [co] ● gemini-3-flash-preview · 282 tok · $0.0003 · 0% ctx
    /// We sum all $ amounts found across all agent runs in one transcription.
    private func parseTotalCost(from stderr: String) -> Double? {
        let pattern = #"\[co\] ●[^\n]*\$([0-9]+\.[0-9]+)"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range   = NSRange(stderr.startIndex..., in: stderr)
        let matches = regex.matches(in: stderr, range: range)
        guard !matches.isEmpty else { return nil }

        let total = matches.compactMap { match -> Double? in
            guard let r = Range(match.range(at: 1), in: stderr) else { return nil }
            return Double(stderr[r])
        }.reduce(0, +)

        return total > 0 ? total : nil
    }

    struct BalanceResult {
        let connectonionBalance : Double?
        let connectonionUsed    : Double?
        let openAIBalance       : Double?
        let openAIPlan          : String?
    }

    func fetchBalance(completion: @escaping (BalanceResult?, String?) -> Void) {
        guard let backendScriptPath else { completion(nil, "Backend not available"); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "get-balance"]) { result in
            guard case .success(let output) = result,
                  let data = output.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  json["ok"] as? Bool == true
            else { completion(nil, "Request failed"); return }

            var coBalance  : Double? = nil
            var coUsed     : Double? = nil
            var oaiBalance : Double? = nil
            var oaiPlan    : String? = nil

            if let co = json["connectonion"] as? [String: Any] {
                coBalance = co["balance_usd"]    as? Double
                coUsed    = co["total_cost_usd"] as? Double
            }
            if let oai = json["openai"] as? [String: Any] {
                oaiBalance = oai["balance_usd"] as? Double
                oaiPlan    = oai["plan"] as? String ?? (oaiBalance == nil ? "Pay as you go" : nil)
            }

            completion(BalanceResult(
                connectonionBalance: coBalance,
                connectonionUsed:    coUsed,
                openAIBalance:       oaiBalance,
                openAIPlan:          oaiPlan
            ), nil)
        }
    }

    func syncLanguageToBackend(completion: ((Bool) -> Void)? = nil) {
        guard let backendScriptPath else { completion?(false); return }
        runPythonCommand(
            script: backendScriptPath,
            arguments: ["cli", "set-language", LanguageManager.shared.current]
        ) { result in completion?((try? result.get()) != nil) }
    }

    func fetchLanguageFromBackend(completion: @escaping (String?) -> Void) {
        guard let backendScriptPath else { completion(nil); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "get-language"]) { result in
            guard case .success(let output) = result,
                  let data = output.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let lang = json["language"] as? String
            else { completion(nil); return }
            completion(lang)
        }
    }

    // =========================================================
    // Snippets
    // =========================================================

    private var snippetsScriptPath: String? {
        guard let backendScriptPath else { return nil }
        return URL(fileURLWithPath: backendScriptPath)
            .deletingLastPathComponent()
            .appendingPathComponent("snippets.py").path
    }

    func listSnippets(completion: @escaping ([[String: Any]]) -> Void) {
        guard let script = snippetsScriptPath else { completion([]); return }
        runPythonCommand(script: script, arguments: ["cli", "list"]) { result in
            guard case .success(let output) = result else { completion([]); return }
            for line in output.components(separatedBy: .newlines) {
                guard let data     = line.data(using: .utf8),
                      let json     = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let snippets = json["snippets"] as? [[String: Any]]
                else { continue }
                completion(snippets); return
            }
            completion([])
        }
    }

    func addSnippet(trigger: String, expansion: String, completion: @escaping (Bool) -> Void) {
        guard let script = snippetsScriptPath else { completion(false); return }
        runPythonCommand(script: script, arguments: ["cli", "add", trigger, expansion]) { result in
            completion((try? result.get()) != nil)
        }
    }

    func removeSnippet(trigger: String, completion: @escaping (Bool) -> Void) {
        guard let script = snippetsScriptPath else { completion(false); return }
        runPythonCommand(script: script, arguments: ["cli", "remove", trigger]) { result in
            completion((try? result.get()) != nil)
        }
    }

    // =========================================================
    // Dictionary
    // =========================================================

    private var dictionaryAgentPath: String? {
        guard let backendScriptPath else { return nil }
        return URL(fileURLWithPath: backendScriptPath)
            .deletingLastPathComponent()
            .appendingPathComponent("agents/dictionary_agent.py").path
    }

    func runDictionaryUpdate(completion: @escaping (Result<DictionaryUpdateResult, Error>) -> Void) {
        guard let script = dictionaryAgentPath else {
            completion(.failure(makeError("dictionary_agent.py not found"))); return
        }
        runPythonCommand(script: script, arguments: ["cli", "update", "--force"]) { result in
            switch result {
            case .failure(let e): completion(.failure(e))
            case .success(let output):
                let trimmed = output.trimmingCharacters(in: .whitespacesAndNewlines)
                guard let jsonLine = trimmed.components(separatedBy: .newlines)
                    .map({ $0.trimmingCharacters(in: .whitespacesAndNewlines) })
                    .last(where: { $0.hasPrefix("{") && $0.hasSuffix("}") }),
                      let data = jsonLine.data(using: .utf8),
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                else {
                    completion(.success(DictionaryUpdateResult(added: [], updated: [], totalTerms: 0)))
                    return
                }
                let added   = (json["added"]   as? [[String: Any]] ?? []).compactMap { DictionaryTerm(dict: $0) }
                let updated = (json["updated"] as? [[String: Any]] ?? []).compactMap { DictionaryTerm(dict: $0) }
                let total   = json["total_terms"] as? Int ?? 0
                // skipped=true means no new history — still a success, just nothing to add
                completion(.success(DictionaryUpdateResult(added: added, updated: updated, totalTerms: total)))
            }
        }
    }

    func listDictionaryTerms(completion: @escaping ([[String: Any]]) -> Void) {
        guard let script = dictionaryAgentPath else { completion([]); return }
        runPythonCommand(script: script, arguments: ["cli", "list"]) { result in
            guard case .success(let output) = result else { completion([]); return }

            func extractTerms(_ json: [String: Any]) -> [[String: Any]]? {
                if let t = json["terms"] as? [[String: Any]] { return t }
                if let o = json["output"] as? [String: Any], let t = o["terms"] as? [[String: Any]] { return t }
                if let d = json["dictionary"] as? [String: Any], let t = d["terms"] as? [[String: Any]] { return t }
                return nil
            }

            for line in output.components(separatedBy: .newlines) {
                let t = line.trimmingCharacters(in: .whitespacesAndNewlines)
                guard t.hasPrefix("{"),
                      let data  = t.data(using: .utf8),
                      let json  = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let terms = extractTerms(json)
                else { continue }
                completion(terms); return
            }
            completion([])
        }
    }

    func addDictionaryTerm(phrase: String, aliases: [String], completion: @escaping (Bool) -> Void) {
        guard let script = dictionaryAgentPath else { completion(false); return }
        runPythonCommand(script: script, arguments: ["cli", "add", phrase, aliases.joined(separator: ",")]) { result in
            completion((try? result.get()) != nil)
        }
    }

    func removeDictionaryTerm(phrase: String, completion: @escaping (Bool) -> Void) {
        guard let script = dictionaryAgentPath else { completion(false); return }
        runPythonCommand(script: script, arguments: ["cli", "remove", phrase]) { result in
            completion((try? result.get()) != nil)
        }
    }

    // =========================================================
    // History
    // =========================================================

    func loadHistory(completion: @escaping ([[String: Any]]) -> Void) {
        guard let backendScriptPath else { completion([]); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "get-history"]) { result in
            guard case .success(let output) = result else { completion([]); return }
            for line in output.components(separatedBy: .newlines) {
                guard let data  = line.data(using: .utf8),
                      let json  = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let items = json["items"] as? [[String: Any]]
                else { continue }
                completion(items); return
            }
            completion([])
        }
    }

    // =========================================================
    // Data management
    // =========================================================

    func clearHistory(completion: @escaping (Bool) -> Void) {
        guard let s = backendScriptPath else { completion(false); return }
        runPythonCommand(script: s, arguments: ["cli", "clear-history"]) { r in completion((try? r.get()) != nil) }
    }

    func clearDictionary(completion: @escaping (Bool) -> Void) {
        guard let s = backendScriptPath else { completion(false); return }
        runPythonCommand(script: s, arguments: ["cli", "clear-dictionary"]) { r in completion((try? r.get()) != nil) }
    }

    func clearSnippets(completion: @escaping (Bool) -> Void) {
        guard let s = backendScriptPath else { completion(false); return }
        runPythonCommand(script: s, arguments: ["cli", "clear-snippets"]) { r in completion((try? r.get()) != nil) }
    }

    func resetProfile(completion: @escaping (Bool) -> Void) {
        guard let s = backendScriptPath else { completion(false); return }
        runPythonCommand(script: s, arguments: ["cli", "reset-profile"]) { r in completion((try? r.get()) != nil) }
    }

    func resetAll(completion: @escaping (Bool) -> Void) {
        guard let s = backendScriptPath else { completion(false); return }
        runPythonCommand(script: s, arguments: ["cli", "reset-all"]) { r in completion((try? r.get()) != nil) }
    }

    // =========================================================
    // Onboarding & profile
    // =========================================================

    func isFirstLaunch(completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath else { completion(false); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "is-first-launch"]) { result in
            guard case .success(let output) = result,
                  let data  = output.data(using: .utf8),
                  let json  = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let first = json["first_launch"] as? Bool
            else { completion(false); return }
            completion(first)
        }
    }

    func saveOnboardingProfile(_ profile: [String: Any], completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath,
              let jsonData = try? JSONSerialization.data(withJSONObject: profile),
              let jsonStr  = String(data: jsonData, encoding: .utf8)
        else { completion(false); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "save-profile", jsonStr]) { result in
            completion((try? result.get()) != nil)
        }
    }
}
