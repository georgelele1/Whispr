import AppKit

enum AppStatus: String, CaseIterable {
    case idle
    case listening
    case processing
    case error

    var menuBarIcon: NSImage {
        let imageName: String
        switch self {
        case .idle:       imageName = "mic.slash"
        case .listening:  imageName = "mic.fill"
        case .processing: imageName = "waveform.circle.fill"
        case .error:      imageName = "mic.badge.xmark"
        }
        let image = NSImage(systemSymbolName: imageName, accessibilityDescription: rawValue)
            ?? NSImage(systemSymbolName: "mic", accessibilityDescription: "default")!
        image.isTemplate = true
        return image
    }
}
