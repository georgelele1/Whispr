import AppKit
import Carbon.HIToolbox
import Combine

final class HotkeyManager {
    
    private var hotkeyMonitor: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var hotkeyHandler: ((Bool) -> Void)?
    
    // Start: option + Space
    private let startHotkey = KeyCombo(keyCode: 49, modifiers: [.option])
    
    // Stop: option Set my calendar for tomorrow.+ S
    private let stopHotkey = KeyCombo(keyCode: 1, modifiers: [.option])

    // Only compare these modifier bits, ignore device-dependent raw bits
    private let relevantModifiers: NSEvent.ModifierFlags = [.command, .shift, .control, .option]

    func setupGlobalHotkey(handler: @escaping (Bool) -> Void) {
        hotkeyHandler = handler

        // Check Accessibility permission first — tap creation silently fails without it
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

            let keyCode = Int32(event.getIntegerValueField(.keyboardEventKeycode))

            // Mask to only relevant modifier bits to avoid raw flag noise
            let rawModifiers = NSEvent.ModifierFlags(rawValue: UInt(event.flags.rawValue))
            let modifiers = rawModifiers.intersection(manager.relevantModifiers)

            let startMatch =
                keyCode == manager.startHotkey.keyCode &&
                modifiers == manager.startHotkey.modifiers

            let stopMatch =
                keyCode == manager.stopHotkey.keyCode &&
                modifiers == manager.stopHotkey.modifiers

            if startMatch {
                DispatchQueue.main.async {
                    manager.hotkeyHandler?(true)
                }
                return nil
            }

            if stopMatch {
                DispatchQueue.main.async {
                    manager.hotkeyHandler?(false)
                }
                return nil
            }

            return Unmanaged.passUnretained(event)
        }

        // Listen to keyDown + tapDisabled events
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
            // Use main run loop explicitly, not CFRunLoopGetCurrent()
            CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
            NSLog("HotkeyManager: Event tap registered successfully")
        }
    }

    func showHotkeyConfiguration() {
        let alert = NSAlert()
        alert.messageText = "Hotkeys"
        alert.informativeText = """
Start Recording: Cmd + Shift + Space
Stop Recording: Cmd + Shift + S
"""
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    struct KeyCombo {
        let keyCode: Int32
        let modifiers: NSEvent.ModifierFlags
    }
}
