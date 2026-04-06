import Foundation
import Combine

struct DictionaryTerm {
    let phrase: String
    let type: String
    let aliases: [String]
    let confidence: Double

    init?(dict: [String: Any]) {
        guard let phrase = dict["phrase"] as? String else { return nil }
        self.phrase = phrase
        self.type = dict["type"] as? String ?? "custom"
        self.aliases = dict["aliases"] as? [String] ?? []
        self.confidence = dict["confidence"] as? Double ?? 1.0
    }
}

struct DictionaryUpdateResult {
    let added: [DictionaryTerm]
    let updated: [DictionaryTerm]
    let totalTerms: Int
}

final class LocalBackendClient: ObservableObject {
    @Published var isBackendAvailable = false

    private let timeout: TimeInterval = 300

    private var pythonPath: String?
    private var backendScriptPath: String?

    init() {
        checkBackendAvailability()

        // Auto-update dictionary on launch in background
        if isBackendAvailable {
            DispatchQueue.global(qos: .background).async {
                self.runDictionaryUpdate { result in
                    switch result {
                    case .success(let update):
                        if update.totalTerms > 0 {
                            print("Dictionary updated: \(update.added.count) added, \(update.updated.count) updated, \(update.totalTerms) total")
                        }
                    case .failure(let error):
                        print("Dictionary update skipped or failed: \(error.localizedDescription)")
                    }
                }
            }
        }
    }

    // =========================================================
    // Backend availability
    // =========================================================

    private func checkBackendAvailability() {
        let fm = FileManager.default

        pythonPath = Config.pythonCandidates.first(where: { fm.fileExists(atPath: $0) })

        if let root = findProjectRoot() {
            let candidate = root.appendingPathComponent("backend/app.py").path
            if fm.fileExists(atPath: candidate) {
                backendScriptPath = candidate
            }
        }

        print("python path =", pythonPath ?? "nil")
        print("backend path =", backendScriptPath ?? "nil")

        isBackendAvailable = (pythonPath != nil && backendScriptPath != nil)
    }

    private func findProjectRoot() -> URL? {
        let fm = FileManager.default
        var current = URL(fileURLWithPath: fm.currentDirectoryPath)

        // Walk up from current directory firstCan you explain the redox effect in the chemical industry and give me an example?
        for _ in 0..<8 {
            let backendCandidate = current.appendingPathComponent("backend/app.py").path
            if fm.fileExists(atPath: backendCandidate) {
                return current
            }
            current.deleteLastPathComponent()
        }

        // Fall back to each teammate's known path from Config
        return Config.fallbackRoots
            .map { URL(fileURLWithPath: $0) }
            .first { fm.fileExists(atPath: $0.appendingPathComponent("backend/app.py").path) }
    }

    // =========================================================
    // Run a generic Python CLI command and return raw output
    // =========================================================

    private func runPythonCommand(
        script: String,
        arguments: [String],
        completion: @escaping (Result<String, Error>) -> Void
    ) {
        guard let pythonPath else {
            completion(.failure(NSError(
                domain: "LocalBackendClient", code: -1,
                userInfo: [NSLocalizedDescriptionKey: "Python not found"]
            )))
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.currentDirectoryURL = URL(fileURLWithPath: script).deletingLastPathComponent()
            process.executableURL = URL(fileURLWithPath: pythonPath)
            process.arguments = [script] + arguments

            let outputPipe = Pipe()
            let errorPipe  = Pipe()
            process.standardOutput = outputPipe
            process.standardError  = errorPipe

            do {
                try process.run()
            } catch {
                DispatchQueue.main.async { completion(.failure(error)) }
                return
            }

            process.waitUntilExit()

            let output = String(data: outputPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            let stderr = String(data: errorPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""

            DispatchQueue.main.async {
                if process.terminationStatus == 0 {
                    completion(.success(output))
                } else {
                    completion(.failure(NSError(
                        domain: "LocalBackendClient",
                        code: Int(process.terminationStatus),
                        userInfo: [NSLocalizedDescriptionKey: stderr.isEmpty ? "Command failed" : stderr]
                    )))
                }
            }
        }
    }

    // =========================================================
    // Dictionary update
    // =========================================================

    func runDictionaryUpdate(completion: @escaping (Result<DictionaryUpdateResult, Error>) -> Void) {
        guard let backendScriptPath else {
            completion(.failure(NSError(
                domain: "LocalBackendClient", code: -1,
                userInfo: [NSLocalizedDescriptionKey: "Backend script not found"]
            )))
            return
        }

        let dictionaryScriptPath = URL(fileURLWithPath: backendScriptPath)
            .deletingLastPathComponent()
            .appendingPathComponent("dictionary_agent.py")
            .path

        guard FileManager.default.fileExists(atPath: dictionaryScriptPath) else {
            completion(.failure(NSError(
                domain: "LocalBackendClient", code: -1,
                userInfo: [NSLocalizedDescriptionKey: "dictionary_agent.py not found"]
            )))
            return
        }

        runPythonCommand(script: dictionaryScriptPath, arguments: ["cli", "update"]) { result in
            switch result {
            case .failure(let error):
                completion(.failure(error))
            case .success(let output):
                let trimmed = output.trimmingCharacters(in: .whitespacesAndNewlines)
                guard let jsonLine = trimmed
                    .components(separatedBy: .newlines)
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
                completion(.success(DictionaryUpdateResult(added: added, updated: updated, totalTerms: total)))
            }
        }
    }

    // =========================================================
    // Transcription
    // =========================================================

    func transcribeAudio(
        fileURL: URL,
        appName: String,
        completion: @escaping (Result<String, Error>) -> Void
    ) {
        guard let pythonPath, let backendScriptPath else {
            completion(.failure(NSError(
                domain: "LocalBackendClient", code: -1,
                userInfo: [NSLocalizedDescriptionKey: "Python or backend script not found"]
            )))
            return
        }

        let targetLanguage = Config.targetLanguage

        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.currentDirectoryURL = URL(fileURLWithPath: backendScriptPath).deletingLastPathComponent()
            process.executableURL = URL(fileURLWithPath: pythonPath)
            process.arguments = [
                backendScriptPath,
                "cli",
                "transcribe",
                fileURL.path,
                appName.isEmpty ? "unknown" : appName,
                targetLanguage                          // ← language passed to Python
            ]

            let outputPipe = Pipe()
            let errorPipe  = Pipe()
            process.standardOutput = outputPipe
            process.standardError  = errorPipe

            do {
                print("file exists before run =", FileManager.default.fileExists(atPath: fileURL.path))
                print("Launching backend...")
                print("python =", pythonPath)
                print("script =", backendScriptPath)
                print("audio =", fileURL.path)
                print("app name =", appName)
                print("target language =", targetLanguage)
                print("args =", process.arguments ?? [])
                print("cwd =", process.currentDirectoryURL?.path ?? "nil")
                try process.run()
            } catch {
                DispatchQueue.main.async { completion(.failure(error)) }
                return
            }

            // Read pipes concurrently while process runs to avoid blocking
            var outputData = Data()
            var errorData  = Data()
            let readGroup  = DispatchGroup()

            readGroup.enter()
            DispatchQueue.global(qos: .userInitiated).async {
                outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
                readGroup.leave()
            }

            readGroup.enter()
            DispatchQueue.global(qos: .userInitiated).async {
                errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
                readGroup.leave()
            }

            process.waitUntilExit()
            _ = readGroup.wait(timeout: .now() + self.timeout)

            if process.terminationStatus != 0 && outputData.isEmpty {
                process.terminate()
                DispatchQueue.main.async {
                    completion(.failure(NSError(
                        domain: "LocalBackendClient", code: -2,
                        userInfo: [NSLocalizedDescriptionKey: "Transcription timed out"]
                    )))
                }
                return
            }

            let outputString = String(data: outputData, encoding: .utf8) ?? ""
            let errorString  = String(data: errorData,  encoding: .utf8) ?? ""

            print("STDOUT:", outputString)
            print("STDERR:", errorString)
            print("Exit code:", process.terminationStatus)

            DispatchQueue.main.async {
                let trimmed = outputString.trimmingCharacters(in: .whitespacesAndNewlines)

                guard !trimmed.isEmpty else {
                    completion(.failure(NSError(
                        domain: "LocalBackendClient", code: -4,
                        userInfo: [NSLocalizedDescriptionKey: "No output from backend"]
                    )))
                    return
                }

                let lines = trimmed
                    .components(separatedBy: .newlines)
                    .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                    .filter { !$0.isEmpty }

                guard let jsonLine = lines.last(where: { $0.hasPrefix("{") && $0.hasSuffix("}") }) else {
                    completion(.failure(NSError(
                        domain: "LocalBackendClient", code: -6,
                        userInfo: [NSLocalizedDescriptionKey: "No JSON in backend output: \(trimmed)"]
                    )))
                    return
                }

                guard let data = jsonLine.data(using: .utf8) else {
                    completion(.failure(NSError(
                        domain: "LocalBackendClient", code: -7,
                        userInfo: [NSLocalizedDescriptionKey: "Failed to encode JSON line"]
                    )))
                    return
                }

                do {
                    let response = try JSONDecoder().decode(BackendResponse.self, from: data)
                    if process.terminationStatus == 0 {
                        completion(.success(response.output))
                    } else {
                        completion(.failure(NSError(
                            domain: "LocalBackendClient",
                            code: Int(process.terminationStatus),
                            userInfo: [NSLocalizedDescriptionKey: errorString.isEmpty
                                ? "Backend exited with code \(process.terminationStatus)"
                                : errorString]
                        )))
                    }
                } catch {
                    completion(.failure(NSError(
                        domain: "LocalBackendClient", code: -8,
                        userInfo: [NSLocalizedDescriptionKey: "Invalid JSON: \(jsonLine)"]
                    )))
                }
            }
        }
    }

    // =========================================================
    // Language management
    // =========================================================

    /// Push the current Config.targetLanguage to the Python backend profile.
    /// Call this after the user changes language in Settings.
    func syncLanguageToBackend(completion: ((Bool) -> Void)? = nil) {
        guard let backendScriptPath else {
            completion?(false)
            return
        }

        runPythonCommand(
            script: backendScriptPath,
            arguments: ["cli", "set-language", Config.targetLanguage]
        ) { result in
            switch result {
            case .success:
                print("Language synced to backend:", Config.targetLanguage)
                completion?(true)
            case .failure(let error):
                print("Language sync failed:", error.localizedDescription)
                completion?(false)
            }
        }
    }

    /// Fetch the language currently stored in the Python backend profile.
    func fetchLanguageFromBackend(completion: @escaping (String?) -> Void) {
        guard let backendScriptPath else {
            completion(nil)
            return
        }

        runPythonCommand(
            script: backendScriptPath,
            arguments: ["cli", "get-language"]
        ) { result in
            guard case .success(let output) = result,
                  let data = output.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let lang = json["language"] as? String
            else {
                completion(nil)
                return
            }
            completion(lang)
        }
    }

    // =========================================================
    // Google Calendar account management
    // =========================================================

    /// Read the currently saved Google email from the Python tokens directory.
    func fetchCalendarEmail(completion: @escaping (String?) -> Void) {
        guard let backendScriptPath else {
            print("[calendar] backendScriptPath is nil")
            completion(nil)
            return
        }

        let calendarScript = URL(fileURLWithPath: backendScriptPath)
            .deletingLastPathComponent()
            .appendingPathComponent("gcalendar.py")
            .path

        runPythonCommand(script: calendarScript, arguments: ["get-email"]) { result in
            switch result {
            case .success(let output):
                print("[calendar] get-email output: \(output)")
                // Parse JSON — find the line containing valid JSON
                let email = output
                    .components(separatedBy: .newlines)
                    .compactMap { line -> String? in
                        guard let data = line.data(using: .utf8),
                              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                              let email = json["email"] as? String
                        else { return nil }
                        return email
                    }
                    .first
                print("[calendar] parsed email: \(email ?? "nil")")
                completion(email)
            case .failure(let error):
                print("[calendar] get-email error: \(error.localizedDescription)")
                completion(nil)
            }
        }
    }

    /// Trigger the Python OAuth flow to connect or switch Google account.
    /// Opens a browser window for the user to approve access.
    func connectGoogleCalendar(completion: @escaping (String?) -> Void) {
        guard let backendScriptPath else { completion(nil); return }
        let calendarScript = URL(fileURLWithPath: backendScriptPath)
            .deletingLastPathComponent().appendingPathComponent("gcalendar.py").path

        runPythonCommand(script: calendarScript, arguments: ["connect"]) { [weak self] result in
            guard let self else { return }
            // OAuth process finished — now read the saved email from disk
            // (more reliable than parsing the connect output which may contain stderr noise)
            self.fetchCalendarEmail { email in
                completion(email)
            }
        }
    }

    func disconnectGoogleCalendar(completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath else { completion(false); return }
        let calendarScript = URL(fileURLWithPath: backendScriptPath)
            .deletingLastPathComponent().appendingPathComponent("gcalendar.py").path
        runPythonCommand(script: calendarScript, arguments: ["disconnect"]) { result in
            if case .success = result { completion(true) } else { completion(false) }
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
            let lines = output.components(separatedBy: .newlines)
            for line in lines {
                guard let data = line.data(using: .utf8),
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let snippets = json["snippets"] as? [[String: Any]]
                else { continue }
                completion(snippets)
                return
            }
            completion([])
        }
    }

    func addSnippet(trigger: String, expansion: String, completion: @escaping (Bool) -> Void) {
        guard let script = snippetsScriptPath else { completion(false); return }
        runPythonCommand(script: script, arguments: ["cli", "add", trigger, expansion]) { result in
            if case .success = result { completion(true) } else { completion(false) }
        }
    }

    func removeSnippet(trigger: String, completion: @escaping (Bool) -> Void) {
        guard let script = snippetsScriptPath else { completion(false); return }
        runPythonCommand(script: script, arguments: ["cli", "remove", trigger]) { result in
            if case .success = result { completion(true) } else { completion(false) }
        }
    }

    // =========================================================
    // Dictionary
    // =========================================================

    private var dictionaryAgentPath: String? {
        guard let backendScriptPath else { return nil }
        return URL(fileURLWithPath: backendScriptPath)
            .deletingLastPathComponent()
            .appendingPathComponent("dictionary_agent.py").path
    }

    func listDictionaryTerms(completion: @escaping ([[String: Any]]) -> Void) {
        guard let script = dictionaryAgentPath else { completion([]); return }
        runPythonCommand(script: script, arguments: ["cli", "list"]) { result in
            guard case .success(let output) = result else { completion([]); return }

            // Helper to extract terms from any known JSON structure
            func extractTerms(_ json: [String: Any]) -> [[String: Any]]? {
                // {"terms": [...]}
                if let terms = json["terms"] as? [[String: Any]] { return terms }
                // {"output": {"terms": [...]}}
                if let out   = json["output"] as? [String: Any],
                   let terms = out["terms"]   as? [[String: Any]] { return terms }
                // {"output": {"dictionary": {"terms": [...]}}}
                if let out   = json["output"]      as? [String: Any],
                   let dict  = out["dictionary"]   as? [String: Any],
                   let terms = dict["terms"]       as? [[String: Any]] { return terms }
                // {"dictionary": {"terms": [...]}}
                if let dict  = json["dictionary"]  as? [String: Any],
                   let terms = dict["terms"]       as? [[String: Any]] { return terms }
                return nil
            }

            // Try single-line JSON first (each line is a complete JSON object)
            for line in output.components(separatedBy: .newlines) {
                let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
                guard trimmed.hasPrefix("{"),
                      let data = trimmed.data(using: .utf8),
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let terms = extractTerms(json)
                else { continue }
                completion(terms)
                return
            }

            // Try full output as multi-line JSON (pretty-printed)
            let fullOutput = output.trimmingCharacters(in: .whitespacesAndNewlines)
            if let data  = fullOutput.data(using: .utf8),
               let json  = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let terms = extractTerms(json) {
                completion(terms)
                return
            }

            completion([])
        }
    }

    func addDictionaryTerm(phrase: String, aliases: [String], completion: @escaping (Bool) -> Void) {
        guard let script = dictionaryAgentPath else { completion(false); return }
        let aliasStr = aliases.joined(separator: ",")
        runPythonCommand(script: script, arguments: ["cli", "add", phrase, aliasStr]) { result in
            if case .success = result { completion(true) } else { completion(false) }
        }
    }

    func removeDictionaryTerm(phrase: String, completion: @escaping (Bool) -> Void) {
        guard let script = dictionaryAgentPath else { completion(false); return }
        runPythonCommand(script: script, arguments: ["cli", "remove", phrase]) { result in
            if case .success = result { completion(true) } else { completion(false) }
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
                guard let data = line.data(using: .utf8),
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let items = json["items"] as? [[String: Any]]
                else { continue }
                completion(items)
                return
            }
            completion([])
        }
    }

    // =========================================================
    // Data management — clear / reset
    // =========================================================

    func clearHistory(completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath else { completion(false); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "clear-history"]) { result in
            if case .success = result { completion(true) } else { completion(false) }
        }
    }

    func clearDictionary(completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath else { completion(false); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "clear-dictionary"]) { result in
            if case .success = result { completion(true) } else { completion(false) }
        }
    }

    func clearSnippets(completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath else { completion(false); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "clear-snippets"]) { result in
            if case .success = result { completion(true) } else { completion(false) }
        }
    }

    func resetProfile(completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath else { completion(false); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "reset-profile"]) { result in
            if case .success = result { completion(true) } else { completion(false) }
        }
    }

    func resetAll(completion: @escaping (Bool) -> Void) {
        guard let backendScriptPath else { completion(false); return }
        runPythonCommand(script: backendScriptPath, arguments: ["cli", "reset-all"]) { result in
            if case .success = result { completion(true) } else { completion(false) }
        }
    }
}
