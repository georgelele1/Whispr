import Foundation
import AVFoundation
import Combine

final class AudioRecorder: NSObject, ObservableObject, AVAudioRecorderDelegate {
    @Published var isRecording = false

    private var recorder: AVAudioRecorder?
    private var tempAudioURL: URL?
    private let maxRecordingDuration: TimeInterval = 300

    func startRecording() {
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

        guard
            let rec = try? AVAudioRecorder(url: url, settings: settings),
            rec.record(forDuration: maxRecordingDuration)
        else {
            AppManager.shared.showErrorAlert(message: "Could not start recording")
            return
        }

        rec.delegate = self
        rec.isMeteringEnabled = true
        recorder = rec
        isRecording = true
    }

    func stopRecording() -> URL? {
        guard isRecording else { return nil }
        recorder?.stop()
        isRecording = false
        return tempAudioURL
    }

    func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        isRecording = false
        if !flag {
            tempAudioURL = nil
            FloatingStatusButton.shared.update(.error)
            AppManager.shared.showErrorAlert(message: "Recording failed to finish successfully")
        }
    }

    func audioRecorderEncodeErrorDidOccur(_ recorder: AVAudioRecorder, error: Error?) {
        if let error {
            AppManager.shared.showErrorAlert(message: "Recording encode error: \(error.localizedDescription)")
        }
    }
}
