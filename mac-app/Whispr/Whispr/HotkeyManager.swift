import AppKit
import Carbon.HIToolbox

// MARK: - ShortcutKey model

struct ShortcutKey: Codable, Equatable {
    var keyCode  : Int32
    var modifiers: UInt   // raw NSEvent.ModifierFlags

    static let defaultStart = ShortcutKey(keyCode: 49, modifiers: NSEvent.ModifierFlags.option.rawValue) // ⌥ Space
    static let defaultStop  = ShortcutKey(keyCode: 1,  modifiers: NSEvent.ModifierFlags.option.rawValue) // ⌥ S

    var modifierFlags: NSEvent.ModifierFlags { NSEvent.ModifierFlags(rawValue: modifiers) }

    var displayString: String {
        var parts: [String] = []
        let flags = modifierFlags
        if flags.contains(.control) { parts.append("⌃") }
        if flags.contains(.option)  { parts.append("⌥") }
        if flags.contains(.shift)   { parts.append("⇧") }
        if flags.contains(.command) { parts.append("⌘") }
        parts.append(Self.keyCodeToString(keyCode))
        return parts.joined()
    }

    static func keyCodeToString(_ code: Int32) -> String {
        switch code {
        case 49: return "Space"
        case 36: return "↩"
        case 51: return "⌫"
        case 53: return "Esc"
        default:
            // Map common letter keycodes
            let map: [Int32: String] = [
                0:"A",1:"S",2:"D",3:"F",4:"H",5:"G",6:"Z",7:"X",8:"C",9:"V",
                11:"B",12:"Q",13:"W",14:"E",15:"R",16:"Y",17:"T",31:"O",
                32:"U",34:"I",35:"P",37:"L",38:"J",40:"K",45:"N",46:"M",
                47:",",44:"/",
            ]
            return map[code] ?? "(\(code))"
        }
    }
}

// MARK: - ShortcutManager (persistence)

final class ShortcutManager {
    static let shared = ShortcutManager()
    private init() {}

    private let startKey = "whispr_shortcut_start"
    private let stopKey  = "whispr_shortcut_stop"

    var startShortcut: ShortcutKey {
        get {
            guard let data = UserDefaults.standard.data(forKey: startKey),
                  let val  = try? JSONDecoder().decode(ShortcutKey.self, from: data)
            else { return .defaultStart }
            return val
        }
        set {
            if let data = try? JSONEncoder().encode(newValue) {
                UserDefaults.standard.set(data, forKey: startKey)
            }
        }
    }

    var stopShortcut: ShortcutKey {
        get {
            guard let data = UserDefaults.standard.data(forKey: stopKey),
                  let val  = try? JSONDecoder().decode(ShortcutKey.self, from: data)
            else { return .defaultStop }
            return val
        }
        set {
            if let data = try? JSONEncoder().encode(newValue) {
                UserDefaults.standard.set(data, forKey: stopKey)
            }
        }
    }

    func reset() {
        UserDefaults.standard.removeObject(forKey: startKey)
        UserDefaults.standard.removeObject(forKey: stopKey)
    }
}

// MARK: - HotkeyManager

final class HotkeyManager {

    private var hotkeyMonitor: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var hotkeyHandler: ((Bool) -> Void)?

    private let relevantModifiers: NSEvent.ModifierFlags = [.command, .shift, .control, .option]

    func setupGlobalHotkey(handler: @escaping (Bool) -> Void) {
        hotkeyHandler = handler

        let trusted = AXIsProcessTrustedWithOptions(
            [kAXTrustedCheckOptionPrompt.takeRetainedValue(): true] as CFDictionary
        )
        if !trusted {
            NSLog("HotkeyManager: Accessibility permission not granted — hotkeys will not work")
        }

        let callback: CGEventTapCallBack = { _, type, event, refcon in
            guard let refcon else { return Unmanaged.passUnretained(event) }
            let manager = Unmanaged<HotkeyManager>.fromOpaque(refcon).takeUnretainedValue()

            if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
                if let port = manager.hotkeyMonitor { CGEvent.tapEnable(tap: port, enable: true) }
                return Unmanaged.passUnretained(event)
            }
            guard type == .keyDown else { return Unmanaged.passUnretained(event) }

            let keyCode   = Int32(event.getIntegerValueField(.keyboardEventKeycode))
            let rawMods   = NSEvent.ModifierFlags(rawValue: UInt(event.flags.rawValue))
            let modifiers = rawMods.intersection(manager.relevantModifiers)

            let start = ShortcutManager.shared.startShortcut
            let stop  = ShortcutManager.shared.stopShortcut

            if keyCode == start.keyCode && modifiers == start.modifierFlags {
                DispatchQueue.main.async { manager.hotkeyHandler?(true) }
                return nil
            }
            if keyCode == stop.keyCode && modifiers == stop.modifierFlags {
                DispatchQueue.main.async { manager.hotkeyHandler?(false) }
                return nil
            }

            return Unmanaged.passUnretained(event)
        }

        let mask: CGEventMask =
            (1 << CGEventType.keyDown.rawValue) |
            (1 << CGEventType.tapDisabledByTimeout.rawValue) |
            (1 << CGEventType.tapDisabledByUserInput.rawValue)

        hotkeyMonitor = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .defaultTap,
            eventsOfInterest: mask,
            callback: callback,
            userInfo: Unmanaged.passUnretained(self).toOpaque()
        )

        guard let monitor = hotkeyMonitor else {
            NSLog("HotkeyManager: Failed to create event tap — check Accessibility permissions")
            return
        }

        runLoopSource = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, monitor, 0)
        if let source = runLoopSource {
            CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        }
    }

    // Re-register is not needed — the tap reads from ShortcutManager live on every keypress
}
