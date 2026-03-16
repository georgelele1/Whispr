import AppKit

final class FloatingResultWindow {

    private static var window: NSWindow?
    private static var scrollView: NSScrollView?
    private static var textView: NSTextView?

    static func show(text: String) {
        DispatchQueue.main.async {
            createWindowIfNeeded()
            updateText(text)
            positionWindowAtBottom()
            showWindow()
        }
    }

    static func hide() {
        DispatchQueue.main.async {
            window?.orderOut(nil)
        }
    }

    private static func createWindowIfNeeded() {
        if window != nil { return }

        let initialWidth: CGFloat = 700
        let initialHeight: CGFloat = 220

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: initialWidth, height: initialHeight),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )

        window.isOpaque = false
        window.backgroundColor = .clear
        window.level = .floating
        window.hasShadow = true
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        window.ignoresMouseEvents = false

        let containerView = NSView(frame: NSRect(x: 0, y: 0, width: initialWidth, height: initialHeight))
        containerView.wantsLayer = true
        containerView.layer?.cornerRadius = 16
        containerView.layer?.backgroundColor = NSColor.black.withAlphaComponent(0.88).cgColor
        containerView.layer?.borderWidth = 1
        containerView.layer?.borderColor = NSColor.white.withAlphaComponent(0.08).cgColor

        let titleLabel = NSTextField(labelWithString: "Whispr Result")
        titleLabel.font = NSFont.systemFont(ofSize: 14, weight: .semibold)
        titleLabel.textColor = .white
        titleLabel.backgroundColor = .clear
        titleLabel.translatesAutoresizingMaskIntoConstraints = false

        let textView = NSTextView(frame: .zero)
        textView.isEditable = false
        textView.isSelectable = true
        textView.drawsBackground = false
        textView.textColor = .white
        textView.font = NSFont.systemFont(ofSize: 16)
        textView.textContainerInset = NSSize(width: 6, height: 8)
        textView.isHorizontallyResizable = false
        textView.isVerticallyResizable = true
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = true
        textView.textContainer?.containerSize = NSSize(width: initialWidth - 48, height: .greatestFiniteMagnitude)

        let scrollView = NSScrollView(frame: .zero)
        scrollView.borderType = .noBorder
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.autohidesScrollers = true
        scrollView.drawsBackground = false
        scrollView.documentView = textView
        scrollView.translatesAutoresizingMaskIntoConstraints = false

        let closeButton = NSButton(title: "×", target: self, action: #selector(closePressed))
        closeButton.bezelStyle = .regularSquare
        closeButton.isBordered = false
        closeButton.font = NSFont.systemFont(ofSize: 18, weight: .medium)
        closeButton.contentTintColor = .white
        closeButton.translatesAutoresizingMaskIntoConstraints = false

        containerView.addSubview(titleLabel)
        containerView.addSubview(closeButton)
        containerView.addSubview(scrollView)

        NSLayoutConstraint.activate([
            titleLabel.leadingAnchor.constraint(equalTo: containerView.leadingAnchor, constant: 16),
            titleLabel.topAnchor.constraint(equalTo: containerView.topAnchor, constant: 12),

            closeButton.trailingAnchor.constraint(equalTo: containerView.trailingAnchor, constant: -12),
            closeButton.centerYAnchor.constraint(equalTo: titleLabel.centerYAnchor),
            closeButton.widthAnchor.constraint(equalToConstant: 24),
            closeButton.heightAnchor.constraint(equalToConstant: 24),

            scrollView.leadingAnchor.constraint(equalTo: containerView.leadingAnchor, constant: 14),
            scrollView.trailingAnchor.constraint(equalTo: containerView.trailingAnchor, constant: -14),
            scrollView.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 10),
            scrollView.bottomAnchor.constraint(equalTo: containerView.bottomAnchor, constant: -14)
        ])

        window.contentView = containerView

        self.window = window
        self.scrollView = scrollView
        self.textView = textView
    }

    private static func updateText(_ text: String) {
        guard let textView else { return }
        textView.string = text
        textView.scrollToBeginningOfDocument(nil)
    }

    private static func positionWindowAtBottom() {
        guard let window else { return }

        guard let screen = NSScreen.main else { return }
        let visibleFrame = screen.visibleFrame

        let width = min(760, visibleFrame.width - 80)
        let height: CGFloat = 240
        let x = visibleFrame.midX - width / 2
        let y = visibleFrame.minY + 30

        window.setFrame(NSRect(x: x, y: y, width: width, height: height), display: true)
    }

    private static func showWindow() {
        guard let window else { return }

        window.alphaValue = 0
        window.orderFrontRegardless()

        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.18
            window.animator().alphaValue = 1
        }
    }

    @objc private static func closePressed() {
        hide()
    }
}
