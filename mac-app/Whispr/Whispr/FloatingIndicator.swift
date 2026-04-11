import SwiftUI
import AppKit
import Combine

// =========================================================
// FloatingStatusButton
//
// A small pill that sits permanently at the bottom-centre of
// the screen (above the dock). It is ALWAYS visible and shows
// the current Whispr status. Clicking it opens the main window.
//
// States:
//   .idle        → grey mic icon      "Whispr"
//   .recording   → red waveform bars  "Recording"
//   .processing  → blue bouncing dots "Processing…"
//   .error       → orange icon        "Error"
//
// Lifecycle — call once at app start:
//   FloatingStatusButton.shared.show()
//
// Update state from anywhere:
//   FloatingStatusButton.shared.update(.recording)
//   FloatingStatusButton.shared.update(.idle)
// =========================================================

final class FloatingStatusButton {

    static let shared = FloatingStatusButton()
    private init() {}

    private var panel: NSPanel?
    private let model = ButtonModel()

    // MARK: - Public

    /// Call once from AppDelegate to put the button on screen permanently.
    func show() {
        DispatchQueue.main.async { [self] in
            guard panel == nil else { return }
            buildPanel()
        }
    }

    /// Update the displayed state.
    func update(_ state: ButtonState) {
        DispatchQueue.main.async { [self] in
            model.state = state
        }
    }

    // MARK: - Build (called once, panel lives forever)

    private func buildPanel() {
        let W: CGFloat = 130
        let H: CGFloat = 36

        let p = NSPanel(
            contentRect: .init(x: 0, y: 0, width: W, height: H),
            styleMask:   [.borderless, .nonactivatingPanel],
            backing:     .buffered,
            defer:       false
        )
        p.isOpaque           = false
        p.backgroundColor    = .clear
        p.level              = .statusBar
        p.hasShadow          = true
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        p.ignoresMouseEvents = false
        p.alphaValue         = 0

        let hostView = NSHostingView(rootView: ButtonPillView(model: model))
        hostView.frame = .init(x: 0, y: 0, width: W, height: H)
        hostView.autoresizingMask = [.width, .height]
        p.contentView = hostView

        // Bottom-centre above the dock
        if let screen = NSScreen.main {
            let sf = screen.visibleFrame
            p.setFrameOrigin(.init(x: sf.midX - W / 2, y: sf.minY + 12))
        }

        p.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.25
            p.animator().alphaValue = 1
        }

        panel = p
    }
}

// =========================================================
// ButtonState
// =========================================================

enum ButtonState: Equatable {
    case idle
    case recording
    case processing
    case error
}

// =========================================================
// ButtonModel
// =========================================================

final class ButtonModel: ObservableObject {
    @Published var state: ButtonState = .idle
}

// =========================================================
// ButtonPillView — the always-visible SwiftUI pill
// =========================================================

struct ButtonPillView: View {
    @ObservedObject var model: ButtonModel
    @State private var isHovered = false

    // Pill background colour per state
    private var bgColor: Color {
        switch model.state {
        case .idle:       return Color(white: 0.13, opacity: 0.88)
        case .recording:  return Color(red: 0.55, green: 0.08, blue: 0.08, opacity: 0.92)
        case .processing: return Color(red: 0.10, green: 0.22, blue: 0.48, opacity: 0.92)
        case .error:      return Color(red: 0.50, green: 0.25, blue: 0.05, opacity: 0.92)
        }
    }

    var body: some View {
        ZStack {
            Capsule()
                .fill(bgColor)
                .overlay(
                    Capsule()
                        .strokeBorder(Color.white.opacity(isHovered ? 0.25 : 0.12), lineWidth: 0.5)
                )
                .shadow(color: .black.opacity(0.4), radius: 6, x: 0, y: 2)
                .scaleEffect(isHovered ? 1.04 : 1.0)

            HStack(spacing: 7) {
                // Left indicator
                switch model.state {
                case .idle:
                    Image(systemName: "mic.fill")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(Color.white.opacity(0.55))
                case .recording:
                    MiniWaveformView()
                case .processing:
                    MiniDotsView()
                case .error:
                    Image(systemName: "exclamationmark.circle.fill")
                        .font(.system(size: 11))
                        .foregroundColor(Color.orange.opacity(0.9))
                }

                // Label
                Text(label)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(Color.white.opacity(model.state == .idle ? 0.65 : 1.0))
                    .lineLimit(1)
            }
            .padding(.horizontal, 12)
        }
        .frame(width: 130, height: 36)
        .contentShape(Capsule())
        .onHover { hovered in
            withAnimation(.easeInOut(duration: 0.15)) { isHovered = hovered }
        }
        .onTapGesture {
            NSApp.activate(ignoringOtherApps: true)
            MainWindowController.shared.navigate(to: .home)
        }
        .animation(.easeInOut(duration: 0.25), value: model.state)
        .help("Click to open Whispr")
    }

    private var label: String {
        switch model.state {
        case .idle:       return "Whispr"
        case .recording:  return "Recording"
        case .processing: return "Processing…"
        case .error:      return "Error"
        }
    }
}

// =========================================================
// MiniWaveformView — compact red bars for recording state
// =========================================================

struct MiniWaveformView: View {
    private let count = 4
    private let barW: CGFloat = 2
    private let maxH: CGFloat = 12
    private let minH: CGFloat = 3

    @State private var phases: [Double] = [0, 0.4, 0.7, 0.3]

    var body: some View {
        HStack(alignment: .center, spacing: 2) {
            ForEach(0..<count, id: \.self) { i in
                RoundedRectangle(cornerRadius: 1)
                    .fill(Color(red: 1.0, green: 0.35, blue: 0.35))
                    .frame(width: barW, height: barHeight(i))
                    .animation(
                        .easeInOut(duration: 0.38 + Double(i) * 0.08)
                            .repeatForever(autoreverses: true)
                            .delay(Double(i) * 0.10),
                        value: phases[i]
                    )
            }
        }
        .frame(width: CGFloat(count) * (barW + 2) - 2, height: maxH)
        .onAppear {
            for i in 0..<count {
                DispatchQueue.main.asyncAfter(deadline: .now() + Double(i) * 0.05) {
                    phases[i] = 1.0
                }
            }
        }
    }

    private func barHeight(_ i: Int) -> CGFloat {
        minH + CGFloat(phases[i]) * (maxH - minH)
    }
}

// =========================================================
// MiniDotsView — compact blue dots for processing state
// =========================================================

struct MiniDotsView: View {
    private let dotD: CGFloat   = 4
    private let bounce: CGFloat = 5
    private let color           = Color(red: 0.45, green: 0.72, blue: 1.0)

    @State private var offsets: [CGFloat] = [0, 0, 0]

    var body: some View {
        HStack(alignment: .center, spacing: 3) {
            ForEach(0..<3, id: \.self) { i in
                Circle()
                    .fill(color)
                    .frame(width: dotD, height: dotD)
                    .offset(y: offsets[i])
                    .animation(
                        .easeInOut(duration: 0.36)
                            .repeatForever(autoreverses: true)
                            .delay(Double(i) * 0.12),
                        value: offsets[i]
                    )
            }
        }
        .frame(width: 20, height: 12)
        .onAppear {
            for i in 0..<3 {
                DispatchQueue.main.asyncAfter(deadline: .now() + Double(i) * 0.10) {
                    offsets[i] = -bounce
                }
            }
        }
    }
}
