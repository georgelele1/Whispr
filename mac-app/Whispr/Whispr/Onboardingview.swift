import SwiftUI
import AppKit

struct OnboardingView: View {
    let onComplete: () -> Void

    @State private var selectedUsage     : Set<String> = []
    @State private var selectedInterests : Set<String> = []
    @State private var writingStyle      : String = "casual"
    @State private var language          : String = "English"
    @State private var isSaving          : Bool   = false

    private let accent = Color(red: 0.498, green: 0.467, blue: 0.867)
    private var client: LocalBackendClient { AppManager.shared.localBackendClient }

    private let usageOptions: [OnbOption] = [
        .init(label: "Dictation / typing", icon: "keyboard"),
        .init(label: "Draft an email",     icon: "envelope"),
        .init(label: "Code comments",      icon: "chevron.left.forwardslash.chevron.right"),
        .init(label: "Meeting notes",      icon: "note.text"),
        .init(label: "Chat messages",      icon: "bubble.left"),
        .init(label: "Documents",          icon: "doc.text"),
        .init(label: "Academic writing",   icon: "graduationcap"),
        .init(label: "Personal notes",     icon: "pencil"),
    ]

    private let interestOptions: [OnbOption] = [
        .init(label: "Software / Tech", icon: "laptopcomputer"),
        .init(label: "Medicine",        icon: "cross.case"),
        .init(label: "Law",             icon: "building.columns"),
        .init(label: "Finance",         icon: "chart.line.uptrend.xyaxis"),
        .init(label: "Education",       icon: "books.vertical"),
        .init(label: "Design / Art",    icon: "paintbrush"),
        .init(label: "Research",        icon: "flask"),
        .init(label: "Business",        icon: "briefcase"),
    ]

    var body: some View {
        ZStack {
            Color(NSColor.windowBackgroundColor).ignoresSafeArea()

            VStack(spacing: 28) {

                // Brand
                VStack(spacing: 8) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 14).fill(accent).frame(width: 52, height: 52)
                        Image(systemName: "mic.fill").font(.system(size: 22, weight: .semibold)).foregroundColor(.white)
                    }
                    Text("How would you like\nto use Whispr?")
                        .font(.system(size: 22, weight: .bold))
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("Whispr personalises transcription based on how you work.\nYou can change these any time in Settings.")
                        .font(.system(size: 13)).foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.top, 8)

                ScrollView(showsIndicators: false) {
                    VStack(alignment: .leading, spacing: 22) {

                        VStack(alignment: .leading, spacing: 10) {
                            Label("I mainly use Whispr for", systemImage: "waveform")
                                .font(.system(size: 12, weight: .semibold)).foregroundColor(.secondary)
                                .textCase(.uppercase).tracking(0.4)
                            let cols = [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]
                            LazyVGrid(columns: cols, spacing: 10) {
                                ForEach(usageOptions) { opt in
                                    OnbPill(option: opt, selected: selectedUsage.contains(opt.label), accent: accent) {
                                        toggle(opt.label, in: &selectedUsage)
                                    }
                                }
                            }
                        }

                        Divider()

                        VStack(alignment: .leading, spacing: 10) {
                            Label("My area of work", systemImage: "person.text.rectangle")
                                .font(.system(size: 12, weight: .semibold)).foregroundColor(.secondary)
                                .textCase(.uppercase).tracking(0.4)
                            let cols2 = [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]
                            LazyVGrid(columns: cols2, spacing: 10) {
                                ForEach(interestOptions) { opt in
                                    OnbPill(option: opt, selected: selectedInterests.contains(opt.label), accent: accent) {
                                        toggle(opt.label, in: &selectedInterests)
                                    }
                                }
                            }
                        }

                        Divider()

                        HStack(alignment: .top, spacing: 24) {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("Writing style")
                                    .font(.system(size: 12, weight: .semibold)).foregroundColor(.secondary)
                                    .textCase(.uppercase).tracking(0.4)
                                HStack(spacing: 6) {
                                    ForEach(["Casual", "Formal", "Technical"], id: \.self) { s in
                                        let on = writingStyle == s.lowercased()
                                        Button { writingStyle = s.lowercased() } label: {
                                            Text(s)
                                                .font(.system(size: 12, weight: on ? .semibold : .regular))
                                                .padding(.horizontal, 12).padding(.vertical, 6)
                                                .background(on ? accent.opacity(0.12) : Color.clear)
                                                .foregroundColor(on ? accent : .secondary)
                                                .cornerRadius(20)
                                                .overlay(RoundedRectangle(cornerRadius: 20)
                                                    .stroke(on ? accent : Color.secondary.opacity(0.3),
                                                            lineWidth: on ? 1 : 0.5))
                                        }
                                        .buttonStyle(.plain)
                                    }
                                }
                            }

                            Spacer()

                            VStack(alignment: .leading, spacing: 8) {
                                Text("Output language")
                                    .font(.system(size: 12, weight: .semibold)).foregroundColor(.secondary)
                                    .textCase(.uppercase).tracking(0.4)
                                Picker("", selection: $language) {
                                    ForEach(Config.supportedLanguages, id: \.self) { Text($0).tag($0) }
                                }
                                .pickerStyle(.menu).labelsHidden().frame(width: 140)
                            }
                        }
                    }
                    .padding(24)
                    .background(
                        RoundedRectangle(cornerRadius: 16)
                            .fill(Color(NSColor.controlBackgroundColor))
                            .shadow(color: .black.opacity(0.06), radius: 12, x: 0, y: 4)
                    )
                }
                .frame(maxWidth: 520)

                VStack(spacing: 10) {
                    Button { save() } label: {
                        Group {
                            if isSaving { ProgressView().scaleEffect(0.8) }
                            else { Text("Get started").font(.system(size: 14, weight: .semibold)) }
                        }
                        .frame(width: 220, height: 42)
                        .background(accent).foregroundColor(.white).cornerRadius(11)
                    }
                    .buttonStyle(.plain).disabled(isSaving)

                    Button("Skip") { save(skip: true) }
                        .buttonStyle(.plain).font(.system(size: 12)).foregroundColor(.secondary)
                }
                .padding(.bottom, 8)
            }
            .padding(.horizontal, 40)
        }
        .frame(width: 620, height: 700)
    }

    private func toggle(_ label: String, in set: inout Set<String>) {
        if set.contains(label) { set.remove(label) } else { set.insert(label) }
    }

    private func save(skip: Bool = false) {
        isSaving = true
        let profile: [String: Any] = skip ? [:] : [
            "usage_type":    Array(selectedUsage),
            "career_area":   selectedInterests.first ?? "",
            "primary_apps":  [] as [String],
            "writing_style": writingStyle,
            "language":      language,
        ]
        client.saveOnboardingProfile(profile) { _ in
            isSaving = false
            onComplete()
        }
    }
}

struct OnbOption: Identifiable {
    let id    = UUID()
    let label : String
    let icon  : String
}

struct OnbPill: View {
    let option   : OnbOption
    let selected : Bool
    let accent   : Color
    let action   : () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: option.icon).font(.system(size: 13)).frame(width: 18)
                Text(option.label)
                    .font(.system(size: 13, weight: selected ? .medium : .regular)).lineLimit(1)
                Spacer()
                if selected { Image(systemName: "checkmark").font(.system(size: 11, weight: .semibold)) }
            }
            .padding(.horizontal, 13).padding(.vertical, 10)
            .background(selected ? accent.opacity(0.10) : Color(NSColor.textBackgroundColor))
            .foregroundColor(selected ? accent : .primary)
            .cornerRadius(10)
            .overlay(RoundedRectangle(cornerRadius: 10)
                .stroke(selected ? accent : Color.secondary.opacity(0.2), lineWidth: selected ? 1 : 0.5))
        }
        .buttonStyle(.plain)
    }
}
