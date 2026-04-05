import SwiftUI
import AppKit
import Combine

// =========================================================
// FloatingIndicator
// A small floating HUD pinned to the bottom-centre of the
// screen (above the dock), shown while recording.
// Displays an animated sound-wave (5 bars) + "Recording"
// label. Dismissed automatically when recording stops.
// Uses NSPanel so it never steals focus.
// =========================================================

final class FloatingIndicator {

    private var panel: NSPanel?
    private static let shared = FloatingIndicator()

    // MARK: - Public

    func showIndicator() {
        DispatchQueue.main.async {
            guard self.panel == nil else { return }
            self.buildPanel()
        }
    }

    func hideIndicator() {
        DispatchQueue.main.async {
            guard let p = self.panel else { return }
            NSAnimationContext.runAnimationGroup({ ctx in
                ctx.duration = 0.18
                p.animator().alphaValue = 0
            }, completionHandler: {
                p.orderOut(nil)
                self.panel = nil
            })
        }
    }

    // MARK: - Build

    private func buildPanel() {
        let W: CGFloat = 160
        let H: CGFloat = 44

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
        p.ignoresMouseEvents = true
        p.alphaValue = 0

        let hostView = NSHostingView(rootView: WaveformIndicatorView())
        hostView.frame = NSRect(x: 0, y: 0, width: W, height: H)
        p.contentView = hostView

        // Position: bottom-centre just above the dock
        if let screen = NSScreen.main {
            let sf = screen.visibleFrame
            let x  = sf.midX - W / 2
            let y  = sf.minY + 16
            p.setFrameOrigin(NSPoint(x: x, y: y))
        }

        p.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.18
            p.animator().alphaValue = 1
        }

        self.panel = p
    }
}

// =========================================================
// WaveformIndicatorView — SwiftUI view inside the panel
// =========================================================

struct WaveformIndicatorView: View {

    // Each bar gets a slightly different phase so they ripple
    @State private var phases: [Double] = [0, 0.2, 0.4, 0.2, 0]
    @State private var animating = false

    private let barCount = 5
    private let barWidth: CGFloat = 3
    private let maxBarH: CGFloat  = 18
    private let minBarH: CGFloat  = 4
    private let barColor          = Color.white

    var body: some View {
        ZStack {
            // Pill background
            Capsule()
                .fill(Color(white: 0.08, opacity: 0.92))
                .overlay(Capsule().stroke(Color.white.opacity(0.12), lineWidth: 0.5))

            HStack(spacing: 10) {
                // Animated waveform bars
                HStack(alignment: .center, spacing: 3) {
                    ForEach(0..<barCount, id: \.self) { i in
                        RoundedRectangle(cornerRadius: 1.5)
                            .fill(Color.red.opacity(0.9))
                            .frame(width: barWidth, height: barHeight(for: i))
                            .animation(
                                .easeInOut(duration: 0.45 + Double(i) * 0.06)
                                .repeatForever(autoreverses: true)
                                .delay(Double(i) * 0.08),
                                value: phases[i]
                            )
                    }
                }
                .frame(width: CGFloat(barCount) * (barWidth + 3) - 3, height: maxBarH)

                Text("Recording")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(.white)
            }
            .padding(.horizontal, 14)
        }
        .frame(width: 160, height: 44)
        .onAppear { startAnimation() }
    }

    private func barHeight(for index: Int) -> CGFloat {
        let t = phases[index]
        // t oscillates 0→1 driven by animation; map to minBarH…maxBarH
        return minBarH + CGFloat(t) * (maxBarH - minBarH)
    }

    private func startAnimation() {
        // Stagger the target phase for each bar so they ripple
        for i in 0..<barCount {
            DispatchQueue.main.asyncAfter(deadline: .now() + Double(i) * 0.05) {
                phases[i] = 1.0
            }
        }
    }
}
