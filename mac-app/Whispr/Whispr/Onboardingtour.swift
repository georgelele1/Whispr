import SwiftUI
import AppKit

// MARK: - Tour step model

private struct TourStep {
    let icon       : String
    let iconColor  : Color
    let title      : String
    let body       : String
    let hint       : String?   // optional keyboard/action hint
}

private let tourSteps: [TourStep] = [
    TourStep(
        icon:      "mic.fill",
        iconColor: Color(red: 0.498, green: 0.467, blue: 0.867),
        title:     "Welcome to Whispr",
        body:      "Whispr turns your voice into polished text — formatted for whatever app you're using, in any language.",
        hint:      nil
    ),
    TourStep(
        icon:      "keyboard",
        iconColor: Color(red: 0.498, green: 0.467, blue: 0.867),
        title:     "Start & stop with a shortcut",
        body:      "Press ⌥ Space to start recording from anywhere on your Mac. Press ⌥ S to stop and transcribe. The result is pasted automatically.",
        hint:      "⌥ Space  ·  ⌥ S"
    ),
    TourStep(
        icon:      "waveform.circle.fill",
        iconColor: .green,
        title:     "Smart transcription",
        body:      "Whispr detects context — dictation gets cleaned up and formatted for whatever app you're in, in any language.",
        hint:      nil
    ),
    TourStep(
        icon:      "text.bubble",
        iconColor: Color(red: 0.498, green: 0.467, blue: 0.867),
        title:     "Voice snippets",
        body:      "Say a trigger word like \"zoom link\" and it expands to your full URL. Set up your own shortcuts in the Snippets tab.",
        hint:      "Snippets → Add snippet"
    ),
    TourStep(
        icon:      "book.closed",
        iconColor: .orange,
        title:     "Personal dictionary",
        body:      "Add names, course codes, or technical terms so Whispr always spells them right. The AI also learns from your history automatically.",
        hint:      "Dictionary → Add term"
    ),
    TourStep(
        icon:      "cpu",
        iconColor: Color(red: 0.26, green: 0.52, blue: 0.96),
        title:     "Choose your model",
        body:      "Gemini models are included — no API key needed. Add your OpenAI key in API Keys to use GPT models instead.",
        hint:      "API Keys → Model picker"
    ),
]

// MARK: - OnboardingTour

struct OnboardingTour: View {

    @Binding var isPresented: Bool
    @State private var step = 0

    private let accent    = Color(red: 0.498, green: 0.467, blue: 0.867)
    private var current   : TourStep { tourSteps[step] }
    private var isLast    : Bool     { step == tourSteps.count - 1 }
    private var isFirst   : Bool     { step == 0 }

    var body: some View {
        ZStack {
            // Dim overlay
            Color.black.opacity(0.45)
                .ignoresSafeArea()
                .onTapGesture { /* block taps behind */ }

            // Card
            VStack(spacing: 0) {
                // Icon
                ZStack {
                    Circle()
                        .fill(current.iconColor.opacity(0.12))
                        .frame(width: 64, height: 64)
                    Image(systemName: current.icon)
                        .font(.system(size: 28, weight: .semibold))
                        .foregroundColor(current.iconColor)
                }
                .padding(.top, 32)
                .padding(.bottom, 16)

                // Step dots
                HStack(spacing: 5) {
                    ForEach(0..<tourSteps.count, id: \.self) { i in
                        Circle()
                            .fill(i == step ? accent : Color.secondary.opacity(0.3))
                            .frame(width: i == step ? 7 : 5, height: i == step ? 7 : 5)
                            .animation(.spring(response: 0.3), value: step)
                    }
                }
                .padding(.bottom, 20)

                // Title
                Text(current.title)
                    .font(.system(size: 20, weight: .bold))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)

                // Body
                Text(current.body)
                    .font(.system(size: 13))
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(3)
                    .padding(.horizontal, 32)
                    .padding(.top, 10)
                    .fixedSize(horizontal: false, vertical: true)

                // Hint badge
                if let hint = current.hint {
                    HStack(spacing: 4) {
                        Image(systemName: "hand.point.right")
                            .font(.system(size: 10))
                            .foregroundColor(accent)
                        Text(hint)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(accent)
                    }
                    .padding(.horizontal, 12).padding(.vertical, 5)
                    .background(accent.opacity(0.08))
                    .cornerRadius(20)
                    .padding(.top, 14)
                }

                Spacer(minLength: 24)

                Divider()

                // Navigation buttons
                HStack(spacing: 12) {
                    if !isFirst {
                        Button("← Back") { withAnimation(.spring(response: 0.35)) { step -= 1 } }
                            .buttonStyle(.bordered)
                            .controlSize(.regular)
                    } else {
                        Button("Skip") { dismiss() }
                            .buttonStyle(.plain)
                            .foregroundColor(.secondary)
                    }

                    Spacer()

                    Button(isLast ? "Get started  →" : "Next  →") {
                        withAnimation(.spring(response: 0.35)) {
                            if isLast { dismiss() }
                            else      { step += 1 }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(accent)
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 16)
            }
            .frame(width: 420)
            .background(
                RoundedRectangle(cornerRadius: 20)
                    .fill(Color(NSColor.windowBackgroundColor))
                    .shadow(color: .black.opacity(0.3), radius: 30, x: 0, y: 10)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 20)
                    .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
            )
            .transition(.scale(scale: 0.92).combined(with: .opacity))
        }
    }

    private func dismiss() {
        UserDefaults.standard.set(true, forKey: "whispr_tour_completed")
        withAnimation(.easeOut(duration: 0.2)) { isPresented = false }
    }
}

// MARK: - Tour trigger helper

extension View {
    /// Attach to the root view — shows the tour on first launch after onboarding.
    func withWhisprTour() -> some View {
        modifier(TourModifier())
    }
}

private struct TourModifier: ViewModifier {
    @State private var showTour = false

    func body(content: Content) -> some View {
        ZStack {
            content
            if showTour {
                OnboardingTour(isPresented: $showTour)
                    .zIndex(999)
            }
        }
        .onAppear {
            let done = UserDefaults.standard.bool(forKey: "whispr_tour_completed")
            if !done {
                // Small delay so the window is fully visible before the overlay appears
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    withAnimation(.spring(response: 0.4)) { showTour = true }
                }
            }
        }
    }
}
