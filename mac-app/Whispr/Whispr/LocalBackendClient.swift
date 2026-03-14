import Foundation
import Combine

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

    private let timeout: TimeInterval = 20

    private var pythonPath: String?
    private var backendScriptPath: String?

    init() {
        checkBackendAvailability()
    }

    private func checkBackendAvailability() {
        let fm = FileManager.default

        pythonPath = pythonCandidates.first(where: { fm.fileExists(atPath: $0) })

        if let projectRoot = findProjectRoot() {
            let candidate = projectRoot.appendingPathComponent("backend/app.py").path
            if fm.fileExists(atPath: candidate) {
                backendScriptPath = candidate
            }
        }

        NSLog("python path = \(pythonPath ?? "nil")")
        NSLog("backend path = \(backendScriptPath ?? "nil")")

        isBackendAvailable = (pythonPath != nil && backendScriptPath != nil)
    }

    private func findProjectRoot() -> URL? {
        let fm = FileManager.default

        // Start from current working directory
        var current = URL(fileURLWithPath: fm.currentDirectoryPath)

        for _ in 0..<6 {
            let backendPath = current.appendingPathComponent("backend/app.py").path
            if fm.fileExists(atPath: backendPath) {
                return current
            }
            current.deleteLastPathComponent()
        }

        // Fallback: known project root on your machine
        let fallback = URL(fileURLWithPath: "/Users/yanbowang/Comp9900_project_testversion")
        let fallbackBackend = fallback.appendingPathComponent("backend/app.py").path
        if fm.fileExists(atPath: fallbackBackend) {
            return fallback
        }

        return nil
    }

    func transcribeAudio(
        fileURL: URL,
        appName: String,
        mode: TranscriptionMode,
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
            process.executableURL = URL(fileURLWithPath: pythonPath)

            process.arguments = [
                backendScriptPath,
                "cli",
                fileURL.path,
                mode.rawValue,
                self.contextFromAppName(appName),
                ""
            ]

            let outputPipe = Pipe()
            let errorPipe = Pipe()
            process.standardOutput = outputPipe
            process.standardError = errorPipe
            print("audio path =", fileURL.path)
            print("file exists before run =", FileManager.default.fileExists(atPath: fileURL.path))
            do {
                try process.run()
            } catch {
                completion(.failure(error))
                return
            }

            let deadline = Date().addingTimeInterval(self.timeout)
            while process.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.1)
            }

            if process.isRunning {
                process.terminate()
                completion(.failure(
                    NSError(
                        domain: "LocalBackendClient",
                        code: -2,
                        userInfo: [NSLocalizedDescriptionKey: "Transcription timed out"]
                    )
                ))
                return
            }

            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()

            let outputString = String(data: outputData, encoding: .utf8) ?? ""
            let errorString = String(data: errorData, encoding: .utf8) ?? ""

            if !errorString.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                NSLog("Backend stderr: \(errorString)")
            }

            if process.terminationStatus != 0 {
                completion(.failure(
                    NSError(
                        domain: "LocalBackendClient",
                        code: Int(process.terminationStatus),
                        userInfo: [
                            NSLocalizedDescriptionKey:
                                errorString.isEmpty
                                ? "Backend exited with code \(process.terminationStatus)"
                                : errorString
                        ]
                    )
                ))
                return
            }

            let trimmed = outputString.trimmingCharacters(in: .whitespacesAndNewlines)

            if let data = trimmed.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let ok = json["ok"] as? Bool,
               ok,
               let finalText = json["final_text"] as? String {
                completion(.success(finalText))
                return
            }

            if !trimmed.isEmpty {
                completion(.success(trimmed))
            } else {
                completion(.failure(
                    NSError(
                        domain: "LocalBackendClient",
                        code: -4,
                        userInfo: [NSLocalizedDescriptionKey: "No output from backend"]
                    )
                ))
            }
        }
    }

    private func contextFromAppName(_ appName: String) -> String {
        switch appName {
        case "Mail", "Microsoft Outlook", "Spark":
            return "email"
        case "Messages", "Slack", "Discord", "Telegram", "WhatsApp":
            return "chat"
        case "Visual Studio Code", "Code", "Xcode", "Terminal", "iTerm2", "PyCharm":
            return "code"
        default:
            return "generic"
        }
    }
}
