import AppKit
import SwiftUI

// =========================================================
// FloatingResultWindow
// A polished floating HUD shown after each transcription.
// Features:
//  - Dark pill-style panel, bottom-centre of screen
//  - "Whispr" brand + app name badge in header
//  - Transcribed text in a readable text view
//  - Copy button with "Copied!" feedback
//  - × close button
//  - Thin auto-dismiss progress bar at the bottom
//  - NSPanel so it never steals focus
//  - Draggable anywhere on the panel
//  - Fade in / fade out
// =========================================================

final class FloatingResultWindow: NSObject {

    // MARK: - Private state

    private static var panel      : NSPanel?
    private static var textView   : NSTextView?
    private static var copyBtn    : NSButton?
    private static var progressBar: NSView?
    private static var progressAnim: Timer?
    private static var dismissTimer: Timer?
    private static let shared = FloatingResultWindow()

    private static let autoDismissDuration: TimeInterval = 14

    // MARK: - Public

    static func show(text: String, appName: String = "") {
        DispatchQueue.main.async {
            dismissTimer?.invalidate()
            progressAnim?.invalidate()
            createPanelIfNeeded()
            updateContent(text: text, appName: appName)
            positionPanel()
            fadeIn()
            startDismissTimer()
        }
    }

    static func hide() {
        DispatchQueue.main.async {
            dismissTimer?.invalidate()
            progressAnim?.invalidate()
            fadeOut()
        }
    }

    // MARK: - Panel construction

    private static func createPanelIfNeeded() {
        if panel != nil { return }

        let W: CGFloat = 700
        let H: CGFloat = 210

        let p = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: W, height: H),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        p.isOpaque = false
        p.backgroundColor = .clear
        p.level = .floating
        p.hasShadow = true
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        p.ignoresMouseEvents = false
        p.isMovableByWindowBackground = true

        // ── Outer container ───────────────────────────────────
        let container = NSView(frame: NSRect(x: 0, y: 0, width: W, height: H))
        container.wantsLayer = true
        container.layer?.cornerRadius = 16
        container.layer?.masksToBounds = true
        container.layer?.backgroundColor = NSColor(red: 0.09, green: 0.09, blue: 0.10, alpha: 0.96).cgColor
        container.layer?.borderWidth = 0.5
        container.layer?.borderColor = NSColor(white: 1.0, alpha: 0.12).cgColor

        // ── Header ────────────────────────────────────────────
        let headerBg = NSView()
        headerBg.wantsLayer = true
        headerBg.layer?.backgroundColor = NSColor(white: 1.0, alpha: 0.04).cgColor
        headerBg.translatesAutoresizingMaskIntoConstraints = false

        // Brand label
        let brandLabel = NSTextField(labelWithString: "Whispr")
        brandLabel.font = NSFont.systemFont(ofSize: 13, weight: .semibold)
        brandLabel.textColor = NSColor(white: 1.0, alpha: 0.55)
        brandLabel.backgroundColor = .clear
        brandLabel.translatesAutoresizingMaskIntoConstraints = false

        // App name badge (populated dynamically)
        let appBadge = NSTextField(labelWithString: "")
        appBadge.font = NSFont.systemFont(ofSize: 11, weight: .medium)
        appBadge.textColor = NSColor(white: 0.6, alpha: 1.0)
        appBadge.backgroundColor = .clear
        appBadge.wantsLayer = true
        appBadge.layer?.backgroundColor = NSColor(white: 1.0, alpha: 0.08).cgColor
        appBadge.layer?.cornerRadius = 4
        appBadge.translatesAutoresizingMaskIntoConstraints = false
        appBadge.tag = 101   // tag for lookup

        // Copy button
        let copy = makeHeaderButton(title: "Copy", tag: 201)
        copy.target = shared
        copy.action = #selector(copyPressed)
        FloatingResultWindow.copyBtn = copy

        // Close button
        let close = makeHeaderButton(title: "×", tag: 0)
        close.font = NSFont.systemFont(ofSize: 17, weight: .light)
        close.target = shared
        close.action = #selector(closePressed)

        // ── Divider ───────────────────────────────────────────
        let divider = NSView()
        divider.wantsLayer = true
        divider.layer?.backgroundColor = NSColor(white: 1.0, alpha: 0.08).cgColor
        divider.translatesAutoresizingMaskIntoConstraints = false

        // ── Text view ─────────────────────────────────────────
        let tv = NSTextView()
        tv.isEditable = false
        tv.isSelectable = true
        tv.drawsBackground = false
        tv.textColor = NSColor(white: 0.95, alpha: 1.0)
        tv.font = NSFont.systemFont(ofSize: 15, weight: .regular)
        tv.textContainerInset = NSSize(width: 2, height: 4)
        tv.isHorizontallyResizable = false
        tv.isVerticallyResizable = true
        tv.autoresizingMask = [.width]
        tv.textContainer?.widthTracksTextView = true
        tv.textContainer?.containerSize = NSSize(width: W - 56, height: .greatestFiniteMagnitude)
        textView = tv

        let scroll = NSScrollView()
        scroll.borderType = .noBorder
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = false
        scroll.autohidesScrollers = true
        scroll.drawsBackground = false
        scroll.documentView = tv
        scroll.translatesAutoresizingMaskIntoConstraints = false

        // ── Progress bar (auto-dismiss countdown) ─────────────
        let progTrack = NSView()
        progTrack.wantsLayer = true
        progTrack.layer?.backgroundColor = NSColor(white: 1.0, alpha: 0.06).cgColor
        progTrack.translatesAutoresizingMaskIntoConstraints = false

        let progFill = NSView()
        progFill.wantsLayer = true
        progFill.layer?.backgroundColor = NSColor(red: 0.498, green: 0.467, blue: 0.867, alpha: 0.6).cgColor
        progFill.translatesAutoresizingMaskIntoConstraints = false
        progressBar = progFill

        progTrack.addSubview(progFill)

        // ── Assemble ──────────────────────────────────────────
        container.addSubview(headerBg)
        container.addSubview(brandLabel)
        container.addSubview(appBadge)
        container.addSubview(copy)
        container.addSubview(close)
        container.addSubview(divider)
        container.addSubview(scroll)
        container.addSubview(progTrack)

        NSLayoutConstraint.activate([
            // Header background
            headerBg.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            headerBg.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            headerBg.topAnchor.constraint(equalTo: container.topAnchor),
            headerBg.heightAnchor.constraint(equalToConstant: 40),

            // Brand
            brandLabel.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 16),
            brandLabel.centerYAnchor.constraint(equalTo: headerBg.centerYAnchor),

            // App badge
            appBadge.leadingAnchor.constraint(equalTo: brandLabel.trailingAnchor, constant: 8),
            appBadge.centerYAnchor.constraint(equalTo: headerBg.centerYAnchor),

            // Close button
            close.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -10),
            close.centerYAnchor.constraint(equalTo: headerBg.centerYAnchor),
            close.widthAnchor.constraint(equalToConstant: 28),
            close.heightAnchor.constraint(equalToConstant: 28),

            // Copy button
            copy.trailingAnchor.constraint(equalTo: close.leadingAnchor, constant: -4),
            copy.centerYAnchor.constraint(equalTo: headerBg.centerYAnchor),
            copy.widthAnchor.constraint(equalToConstant: 60),
            copy.heightAnchor.constraint(equalToConstant: 24),

            // Divider
            divider.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            divider.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            divider.topAnchor.constraint(equalTo: headerBg.bottomAnchor),
            divider.heightAnchor.constraint(equalToConstant: 0.5),

            // Scroll view
            scroll.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 16),
            scroll.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -16),
            scroll.topAnchor.constraint(equalTo: divider.bottomAnchor, constant: 10),
            scroll.bottomAnchor.constraint(equalTo: progTrack.topAnchor, constant: -6),

            // Progress track
            progTrack.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            progTrack.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            progTrack.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            progTrack.heightAnchor.constraint(equalToConstant: 3),

            // Progress fill (starts full width, shrinks to 0)
            progFill.leadingAnchor.constraint(equalTo: progTrack.leadingAnchor),
            progFill.topAnchor.constraint(equalTo: progTrack.topAnchor),
            progFill.bottomAnchor.constraint(equalTo: progTrack.bottomAnchor),
            progFill.widthAnchor.constraint(equalTo: progTrack.widthAnchor, multiplier: 1.0),
        ])

        p.contentView = container
        panel = p
    }

    // MARK: - Helpers

    private static func makeHeaderButton(title: String, tag: Int) -> NSButton {
        let btn = NSButton(title: title, target: nil, action: nil)
        btn.bezelStyle = .regularSquare
        btn.isBordered = false
        btn.wantsLayer = true
        btn.layer?.cornerRadius = 5
        btn.layer?.backgroundColor = NSColor(white: 1.0, alpha: 0.08).cgColor
        btn.font = NSFont.systemFont(ofSize: 12, weight: .medium)
        btn.contentTintColor = NSColor(white: 0.85, alpha: 1.0)
        btn.translatesAutoresizingMaskIntoConstraints = false
        btn.tag = tag
        return btn
    }

    private static func updateContent(text: String, appName: String) {
        textView?.string = text
        textView?.scrollToBeginningOfDocument(nil)
        copyBtn?.title = "Copy"
        copyBtn?.layer?.backgroundColor = NSColor(white: 1.0, alpha: 0.08).cgColor

        // Update app badge
        if let badge = panel?.contentView?.viewWithTag(101) as? NSTextField {
            if appName.isEmpty {
                badge.stringValue = ""
                badge.layer?.backgroundColor = .none
            } else {
                badge.stringValue = "  \(appName)  "
                badge.layer?.backgroundColor = NSColor(white: 1.0, alpha: 0.08).cgColor
            }
        }
    }

    private static func positionPanel() {
        guard let p = panel, let screen = NSScreen.main else { return }
        let vf = screen.visibleFrame
        let W  = min(700, vf.width - 80)
        let H: CGFloat = 210
        p.setFrame(NSRect(x: vf.midX - W / 2, y: vf.minY + 40, width: W, height: H), display: true)
    }

    private static func fadeIn() {
        guard let p = panel else { return }
        p.alphaValue = 0
        p.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.18
            p.animator().alphaValue = 1
        }
    }

    private static func fadeOut() {
        guard let p = panel else { return }
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.2
            p.animator().alphaValue = 0
        }, completionHandler: { p.orderOut(nil) })
    }

    private static func startDismissTimer() {
        // Animate progress bar shrinking over autoDismissDuration
        guard let fill = progressBar,
              let track = fill.superview else { return }

        // Reset fill to full width
        fill.frame = NSRect(x: 0, y: 0, width: track.bounds.width, height: 3)

        let totalSteps = 60
        let stepInterval = autoDismissDuration / Double(totalSteps)
        var step = 0

        progressAnim = Timer.scheduledTimer(withTimeInterval: stepInterval, repeats: true) { timer in
            step += 1
            let progress = 1.0 - Double(step) / Double(totalSteps)
            DispatchQueue.main.async {
                fill.frame = NSRect(x: 0, y: 0, width: track.bounds.width * CGFloat(progress), height: 3)
            }
            if step >= totalSteps { timer.invalidate() }
        }

        dismissTimer = Timer.scheduledTimer(withTimeInterval: autoDismissDuration, repeats: false) { _ in
            FloatingResultWindow.hide()
        }
    }

    // MARK: - Actions

    @objc private func copyPressed() {
        guard let text = FloatingResultWindow.textView?.string, !text.isEmpty else { return }
        let pb = NSPasteboard.general
        pb.declareTypes([.string], owner: nil)
        pb.setString(text, forType: .string)

        FloatingResultWindow.copyBtn?.title = "Copied!"
        FloatingResultWindow.copyBtn?.layer?.backgroundColor = NSColor(white: 1.0, alpha: 0.16).cgColor
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
            FloatingResultWindow.copyBtn?.title = "Copy"
            FloatingResultWindow.copyBtn?.layer?.backgroundColor = NSColor(white: 1.0, alpha: 0.08).cgColor
        }
    }

    @objc private func closePressed() {
        FloatingResultWindow.hide()
    }
}
