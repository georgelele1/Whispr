import SwiftUI

struct SettingsView: View {
    @State private var selectedLanguage   = Config.targetLanguage
    @State private var syncStatus: String = ""
    @State private var calendarEmail: String = "Not connected"

    var backendClient: LocalBackendClient?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {

            Text("Whispr Settings")
                .font(.title2)
                .bold()

            Divider()

            // ── Hotkeys ───────────────────────────────────────
            Group {
                Label("Start recording:  Command + Shift + Space", systemImage: "mic")
                Label("Stop recording:   Command + Shift + S",     systemImage: "stop.circle")
            }
            .font(.subheadline)
            .foregroundColor(.secondary)

            Divider()

            // ── Output language ───────────────────────────────
            VStack(alignment: .leading, spacing: 8) {
                Text("Output language")
                    .font(.headline)

                Text("Transcribed text will be translated to this language.")
                    .font(.caption)
                    .foregroundColor(.secondary)

                HStack(spacing: 12) {
                    Picker("", selection: $selectedLanguage) {
                        ForEach(Config.supportedLanguages, id: \.self) { lang in
                            Text(lang).tag(lang)
                        }
                    }
                    .pickerStyle(.menu)
                    .frame(width: 160)
                    .onChange(of: selectedLanguage) { newValue in
                        Config.targetLanguage = newValue
                        syncStatus = "Saving..."
                        backendClient?.syncLanguageToBackend { success in
                            syncStatus = success ? "Saved" : "Saved locally"
                            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                                syncStatus = ""
                            }
                        }
                    }

                    if !syncStatus.isEmpty {
                        Text(syncStatus)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }

            Divider()

            // ── Google Calendar ───────────────────────────────
            VStack(alignment: .leading, spacing: 8) {
                Text("Google Calendar")
                    .font(.headline)

                HStack(spacing: 10) {
                    Image(systemName: calendarEmail == "Not connected" ? "calendar.badge.exclamationmark" : "calendar.badge.checkmark")
                        .foregroundColor(calendarEmail == "Not connected" ? .orange : .green)

                    Text(calendarEmail)
                        .font(.subheadline)
                        .foregroundColor(calendarEmail == "Not connected" ? .secondary : .primary)
                }

                if calendarEmail == "Not connected" || calendarEmail == "Connecting..." {
                    Button("Connect Google Calendar") {
                        connectCalendar()
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                    .disabled(calendarEmail == "Connecting...")
                } else {
                    HStack(spacing: 8) {
                        Button("Switch account") {
                            connectCalendar()
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)

                        Button("Disconnect") {
                            disconnectCalendar()
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .foregroundColor(.red)
                    }
                }
            }

            Divider()

            // ── Backend info ──────────────────────────────────
            Group {
                Text("Backend: local Python CLI")
                Text("Recording: temporary .m4a file")
            }
            .font(.caption)
            .foregroundColor(.secondary)

        }
        .padding()
        .frame(width: 420, height: 360)
        .onAppear {
            // Small delay to ensure backend process is ready
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                loadCurrentCalendarEmail()
            }

            backendClient?.fetchLanguageFromBackend { lang in
                if let lang = lang, Config.supportedLanguages.contains(lang) {
                    DispatchQueue.main.async {
                        selectedLanguage      = lang
                        Config.targetLanguage = lang
                    }
                }
            }
        }
    }

    // =========================================================
    // Helpers
    // =========================================================

    /// Read the saved Google email from the Python tokens directory.
    private func loadCurrentCalendarEmail() {
        backendClient?.fetchCalendarEmail { email in
            DispatchQueue.main.async {
                calendarEmail = email ?? "Not connected"
            }
        }
    }

    private func connectCalendar() {
        DispatchQueue.main.async { calendarEmail = "Connecting..." }
        backendClient?.connectGoogleCalendar { email in
            DispatchQueue.main.async {
                calendarEmail = email ?? "Not connected"
            }
        }
    }

    private func disconnectCalendar() {
        backendClient?.disconnectGoogleCalendar { _ in
            DispatchQueue.main.async {
                calendarEmail = "Not connected"
            }
        }
    }
}
