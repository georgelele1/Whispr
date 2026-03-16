import AppKit

final class FloatingResultWindow {

    private static var window: NSWindow?

    static func show(text: String) {

        DispatchQueue.main.async {

            if window == nil {
                let contentRect = NSRect(x: 0, y: 0, width: 420, height: 120)

                let w = NSWindow(
                    contentRect: contentRect,
                    styleMask: [.borderless],
                    backing: .buffered,
                    defer: false
                )

                w.isOpaque = false
                w.backgroundColor = NSColor.black.withAlphaComponent(0.85)
                w.level = .floating
                w.hasShadow = true
                w.ignoresMouseEvents = false
                w.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]

                window = w
            }

            guard let window = window else { return }

            let textView = NSTextField(labelWithString: text)
            textView.textColor = .white
            textView.font = NSFont.systemFont(ofSize: 16)
            textView.alignment = .left
            textView.lineBreakMode = .byWordWrapping
            textView.maximumNumberOfLines = 4
            textView.translatesAutoresizingMaskIntoConstraints = false

            let contentView = NSView()
            contentView.wantsLayer = true
            contentView.layer?.cornerRadius = 12
            contentView.layer?.backgroundColor = NSColor.black.withAlphaComponent(0.85).cgColor

            contentView.addSubview(textView)

            NSLayoutConstraint.activate([
                textView.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 16),
                textView.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -16),
                textView.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 12),
                textView.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -12)
            ])

            window.contentView = contentView

            if let screen = NSScreen.main {
                let screenFrame = screen.visibleFrame
                let x = screenFrame.midX - 210
                let y = screenFrame.midY - 60
                window.setFrame(NSRect(x: x, y: y, width: 420, height: 120), display: true)
            }

            window.orderFrontRegardless()

            DispatchQueue.main.asyncAfter(deadline: .now() + 5) {
                window.orderOut(nil)
            }
        }
    }
}
