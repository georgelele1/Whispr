import AppKit

final class ActiveAppDetector {
    func getActiveAppName() -> String {
        guard let activeApp = NSWorkspace.shared.frontmostApplication,
              let appName = activeApp.localizedName else {
            return "Unknown"
        }
        NSLog("Detected active app: \(appName)")
        return appName
    }
}
