import Foundation

final class RuntimeBootstrapper {
    static let shared = RuntimeBootstrapper()
    private init() {}

    private let fm = FileManager.default

    // MARK: - Paths

    var appSupportURL: URL {
        let base = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = base.appendingPathComponent("Whispr", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    var runtimeRootURL: URL {
        let dir = appSupportURL.appendingPathComponent("runtime", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    var backendRuntimeURL: URL {
        runtimeRootURL.appendingPathComponent("backend", isDirectory: true)
    }

    var setupStateURL: URL {
        runtimeRootURL.appendingPathComponent("setup_state.json")
    }

    // MARK: - Bundled resources

    var bundledBackendURL: URL? {
        Bundle.main.resourceURL?.appendingPathComponent("backend", isDirectory: true)
    }

    var bundledPythonURL: URL? {
        Bundle.main.resourceURL?
            .appendingPathComponent("runtime", isDirectory: true)
            .appendingPathComponent("venv", isDirectory: true)
            .appendingPathComponent("bin", isDirectory: true)
            .appendingPathComponent("python")
    }

    // MARK: - State

    func isRuntimeReady() -> Bool {
        guard let bundledPythonURL else { return false }
        return fm.fileExists(atPath: bundledPythonURL.path) &&
               fm.fileExists(atPath: backendRuntimeURL.appendingPathComponent("app.py").path)
    }

    func writeSetupState(ready: Bool, message: String) {
        let payload: [String: Any] = [
            "ready": ready,
            "message": message,
            "updated_at": ISO8601DateFormatter().string(from: Date())
        ]

        if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted]) {
            try? data.write(to: setupStateURL)
        }
    }

    // MARK: - File operations

    func copyBundledBackend() throws {
        guard let bundledBackendURL else {
            throw NSError(
                domain: "RuntimeBootstrapper",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Bundled backend not found in app resources"]
            )
        }

        if fm.fileExists(atPath: backendRuntimeURL.path) {
            try? fm.removeItem(at: backendRuntimeURL)
        }

        try fm.copyItem(at: bundledBackendURL, to: backendRuntimeURL)
    }

    // MARK: - Public setup

    func prepareRuntime(completion: @escaping (Bool, String) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                guard let bundledPythonURL = self.bundledPythonURL,
                      self.fm.fileExists(atPath: bundledPythonURL.path) else {
                    throw NSError(
                        domain: "RuntimeBootstrapper",
                        code: 2,
                        userInfo: [NSLocalizedDescriptionKey: "Bundled prebuilt runtime not found"]
                    )
                }

                try self.copyBundledBackend()
                self.writeSetupState(ready: true, message: "Runtime prepared successfully")

                DispatchQueue.main.async {
                    completion(true, "Runtime prepared successfully")
                }
            } catch {
                self.writeSetupState(ready: false, message: error.localizedDescription)
                DispatchQueue.main.async {
                    completion(false, error.localizedDescription)
                }
            }
        }
    }
}
