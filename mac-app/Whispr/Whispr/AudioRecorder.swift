import Foundation
import AVFoundation
import Combine

final class AudioRecorder: NSObject, ObservableObject, AVAudioRecorderDelegate {
    @Published var isRecording = false

    private var recorder: AVAudioRecorder?
    private var tempAudioURL: URL?
    private let maxRecordingDuration: TimeInterval = 600

    // Tracks whether the current stop was triggered manually (via stopRecording()).
    // If false when audioRecorderDidFinishRecording fires, it was a timeout auto-stop.
    private var manualStop = false

    func startRecording() throws {
        guard !isRecording else { return }

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("whispr_recording_\(UUID().uuidString).wav")
        tempAudioURL = url

        let settings: [String: Any] = [
            AVFormatIDKey:              kAudioFormatLinearPCM,
            AVSampleRateKey:            16000.0,
            AVNumberOfChannelsKey:      1,
            AVLinearPCMBitDepthKey:     16,
            AVLinearPCMIsBigEndianKey:  false,
            AVLinearPCMIsFloatKey:      false
        ]

        recorder = try AVAudioRecorder(url: url, settings: settings)
        recorder?.delegate = self
        recorder?.isMeteringEnabled = true

        guard recorder?.record(forDuration: maxRecordingDuration) == true else {
            throw NSError(
                domain: "AudioRecorder",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: "Could not start recording"]
            )
        }

        manualStop = false
        isRecording = true
    }

    func stopRecording() -> URL? {
        guard isRecording else { return nil }

        manualStop = true   // Mark as manual so the delegate doesn't trigger a second stop.
        recorder?.stop()
        isRecording = false
        return tempAudioURL
    }

    // MARK: - AVAudioRecorderDelegate

    func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        guard !manualStop else {
            // Manual stop already handled by stopRecording() — nothing to do.
            manualStop = false
            return
        }

        // Reached here only on a timeout auto-stop (maxRecordingDuration elapsed).
        isRecording = false
        if flag {
            // Kick off the transcription pipeline just as a manual stop would.
            DispatchQueue.main.async {
                AppManager.shared.stopRecordingAndProcess()
            }
        } else {
            AppManager.shared.showErrorAlert(message: "Recording failed to finish successfully")
            tempAudioURL = nil
            AppManager.shared.updateAppStatus(.error)
        }
    }

    func audioRecorderEncodeErrorDidOccur(_ recorder: AVAudioRecorder, error: Error?) {
        if let error {
            AppManager.shared.showErrorAlert(message: "Recording encode error: \(error.localizedDescription)")
        }
    }
}
