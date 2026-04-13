import AppKit
import Carbon.HIToolbox

final class HotkeyManager {

    private var hotkeyMonitor: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var hotkeyHandler: ((Bool) -> Void)?

    // Start: Option + Space
    private let startHotkey = KeyCombo(keyCode: 49, modifiers: [.option])
    // Stop:  Option + S
    private let stopHotkey  = KeyCombo(keyCode: 1,  modifiers: [.option])

    // Only compare these modifier bits, ignore device-dependent raw bits
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
            guard let refcon else {
                return Unmanaged.passUnretained(event)
            }

            let manager = Unmanaged<HotkeyManager>.fromOpaque(refcon).takeUnretainedValue()

            // Re-enable the tap if macOS disables it (happens on timeout)
            if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
                if let port = manager.hotkeyMonitor {
                    CGEvent.tapEnable(tap: port, enable: true)
                }
                return Unmanaged.passUnretained(event)
            }

            guard type == .keyDown else {
                return Unmanaged.passUnretained(event)
            }

            let keyCode    = Int32(event.getIntegerValueField(.keyboardEventKeycode))
            let rawMods    = NSEvent.ModifierFlags(rawValue: UInt(event.flags.rawValue))
            let modifiers  = rawMods.intersection(manager.relevantModifiers)

            if keyCode == manager.startHotkey.keyCode && modifiers == manager.startHotkey.modifiers {
                DispatchQueue.main.async { manager.hotkeyHandler?(true) }
                return nil
            }

            if keyCode == manager.stopHotkey.keyCode && modifiers == manager.stopHotkey.modifiers {
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

    struct KeyCombo {
        let keyCode  : Int32
        let modifiers: NSEvent.ModifierFlags
    }
}
