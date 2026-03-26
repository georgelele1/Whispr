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

    private let pythonCandidates = [
        "/Users/yanbowang/opt/anaconda3/bin/python3.11",
        "/Users/yanbowang/opt/anaconda3/bin/python3",
        "/opt/homebrew/bin/python3.11",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3.11",
        "/usr/local/bin/python3",
        "/usr/bin/python3"
    ]

    private let timeout: TimeInterval = 300

    private var pythonPath: String?
    private var backendScriptPath: String?

    init() {
        checkBackendAvailability()
    }

    private func checkBackendAvailability() {
        let fm = FileManager.default

        pythonPath = pythonCandidates.first(where: { fm.fileExists(atPath: $0) })

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

        for _ in 0..<8 {
            let backendCandidate = current.appendingPathComponent("backend/app.py").path
            if fm.fileExists(atPath: backendCandidate) {
                return current
            }
            current.deleteLastPathComponent()
        }

        let fallback = URL(fileURLWithPath: "/Users/quinta/Desktop/snippet实现和测试报告/Comp9900_project_testversion-main")
        let fallbackBackend = fallback.appendingPathComponent("backend/app.py").path
        if fm.fileExists(atPath: fallbackBackend) {
            return fallback
        }

        return nil
    }

    func runDictionaryUpdate(completion: @escaping (Result<DictionaryUpdateResult, Error>) -> Void) {
        guard let pythonPath, let backendScriptPath else {
            completion(.failure(NSError(
                domain: "LocalBackendClient", code: -1,
                userInfo: [NSLocalizedDescriptionKey: "Python or backend script not found"]
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

        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.currentDirectoryURL = URL(fileURLWithPath: backendScriptPath).deletingLastPathComponent()
            process.executableURL = URL(fileURLWithPath: pythonPath)
            process.arguments = [dictionaryScriptPath, "cli", "update"]

            let outputPipe = Pipe()
            let errorPipe = Pipe()
            process.standardOutput = outputPipe
            process.standardError = errorPipe

            do {
                print("Running dictionary update...")
                try process.run()
            } catch {
                DispatchQueue.main.async { completion(.failure(error)) }
                return
            }

            process.waitUntilExit()

            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
            let outputString = String(data: outputData, encoding: .utf8) ?? ""
            let errorString = String(data: errorData, encoding: .utf8) ?? ""

            print("Dictionary STDOUT:", outputString)
            print("Dictionary STDERR:", errorString)

            DispatchQueue.main.async {
                guard process.terminationStatus == 0 else {
                    completion(.failure(NSError(
                        domain: "LocalBackendClient", code: Int(process.terminationStatus),
                        userInfo: [NSLocalizedDescriptionKey: errorString.isEmpty ? "Dictionary update failed" : errorString]
                    )))
                    return
                }

                let trimmed = outputString.trimmingCharacters(in: .whitespacesAndNewlines)
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

                let added = (json["added"] as? [[String: Any]] ?? []).compactMap { DictionaryTerm(dict: $0) }
                let updated = (json["updated"] as? [[String: Any]] ?? []).compactMap { DictionaryTerm(dict: $0) }
                let total = json["total_terms"] as? Int ?? 0
                completion(.success(DictionaryUpdateResult(added: added, updated: updated, totalTerms: total)))
            }
        }
    }

    func transcribeAudio(
        fileURL: URL,
        appName: String,
        completion: @escaping (Result<String, Error>) -> Void
    ) {
        guard let pythonPath, let backendScriptPath else {
            completion(.failure(
                NSError(
                    domain: "LocalBackendClient",
                    code: -1,
                    userInfo: [NSLocalizedDescriptionKey: "Python or backend script not found"]
                )
            ))
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.currentDirectoryURL = URL(fileURLWithPath: backendScriptPath).deletingLastPathComponent()
            process.executableURL = URL(fileURLWithPath: pythonPath)
            process.arguments = [
                backendScriptPath,
                "cli",
                fileURL.path,
                appName
            ]

            let outputPipe = Pipe()
            let errorPipe = Pipe()
            process.standardOutput = outputPipe
            process.standardError = errorPipe

            do {
                print("file exists before run =", FileManager.default.fileExists(atPath: fileURL.path))
                print("Launching backend...")
                print("python =", pythonPath)
                print("script =", backendScriptPath)
                print("audio =", fileURL.path)
                print("app name =", appName)
                print("args =", process.arguments ?? [])
                print("cwd =", process.currentDirectoryURL?.path ?? "nil")
                try process.run()
            } catch {
                DispatchQueue.main.async {
                    completion(.failure(error))
                }
                return
            }

            let group = DispatchGroup()
            group.enter()

            DispatchQueue.global(qos: .userInitiated).async {
                process.waitUntilExit()
                group.leave()
            }

            let waitResult = group.wait(timeout: .now() + self.timeout)
            if waitResult == .timedOut {
                process.terminate()
                DispatchQueue.main.async {
                    completion(.failure(
                        NSError(
                            domain: "LocalBackendClient",
                            code: -2,
                            userInfo: [NSLocalizedDescriptionKey: "Transcription timed out"]
                        )
                    ))
                }
                return
            }

            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()

            let outputString = String(data: outputData, encoding: .utf8) ?? ""
            let errorString = String(data: errorData, encoding: .utf8) ?? ""

            print("STDOUT:", outputString)
            print("STDERR:", errorString)
            print("Exit code:", process.terminationStatus)

            DispatchQueue.main.async {
                let trimmed = outputString.trimmingCharacters(in: .whitespacesAndNewlines)

                guard !trimmed.isEmpty else {
                    completion(.failure(
                        NSError(
                            domain: "LocalBackendClient",
                            code: -4,
                            userInfo: [NSLocalizedDescriptionKey: "No output from backend"]
                        )
                    ))
                    return
                }

                let lines = trimmed
                    .components(separatedBy: .newlines)
                    .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                    .filter { !$0.isEmpty }

                guard let jsonLine = lines.last(where: { $0.hasPrefix("{") && $0.hasSuffix("}") }) else {
                    completion(.failure(
                        NSError(
                            domain: "LocalBackendClient",
                            code: -6,
                            userInfo: [NSLocalizedDescriptionKey: "No JSON line found in backend output: \(trimmed)"]
                        )
                    ))
                    return
                }

                guard let data = jsonLine.data(using: .utf8) else {
                    completion(.failure(
                        NSError(
                            domain: "LocalBackendClient",
                            code: -7,
                            userInfo: [NSLocalizedDescriptionKey: "Failed to encode backend JSON line"]
                        )
                    ))
                    return
                }

                do {
                    let response = try JSONDecoder().decode(BackendResponse.self, from: data)

                    if process.terminationStatus == 0 {
                        completion(.success(response.output))
                    } else {
                        completion(.failure(
                            NSError(
                                domain: "LocalBackendClient",
                                code: Int(process.terminationStatus),
                                userInfo: [
                                    NSLocalizedDescriptionKey: errorString.isEmpty
                                        ? "Backend exited with code \(process.terminationStatus)"
                                        : errorString
                                ]
                            )
                        ))
                    }
                } catch {
                    completion(.failure(
                        NSError(
                            domain: "LocalBackendClient",
                            code: -8,
                            userInfo: [NSLocalizedDescriptionKey: "Invalid JSON line from backend: \(jsonLine)"]
                        )
                    ))
                }
            }
        }
    }
}
