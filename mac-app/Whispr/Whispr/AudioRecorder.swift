import Foundation
import AVFoundation
import Combine

final class AudioRecorder: NSObject, ObservableObject, AVAudioRecorderDelegate {
    @Published var isRecording = false

    private var recorder: AVAudioRecorder?
    private var tempAudioURL: URL?
    private let maxRecordingDuration: TimeInterval = 60

    func startRecording() throws {
        guard !isRecording else { return }

        let tempDir = FileManager.default.temporaryDirectory
        let fileName = "whispr_recording_\(UUID().uuidString).wav"
        let url = tempDir.appendingPathComponent(fileName)
        tempAudioURL = url

        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 16000.0,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsFloatKey: false
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

        isRecording = true
        NSLog("Started recording: \(url.path)")
    }

    func stopRecording() -> URL? {
        guard isRecording else { return nil }

        recorder?.stop()
        isRecording = false
        NSLog("Stopped recording")

        return tempAudioURL
    }

    func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        if !flag {
            AppManager.shared.showErrorAlert(message: "Recording failed to finish successfully")
            tempAudioURL = nil
        }
        isRecording = false
        AppManager.shared.floatingIndicator.hideIndicator()
    }

    func audioRecorderEncodeErrorDidOccur(_ recorder: AVAudioRecorder, error: Error?) {
        if let error {
            AppManager.shared.showErrorAlert(message: "Recording encode error: \(error.localizedDescription)")
        }
    }
}
