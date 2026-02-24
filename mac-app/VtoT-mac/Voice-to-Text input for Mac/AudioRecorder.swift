import Foundation
import AVFoundation
import Combine

final class AudioRecorder: NSObject, ObservableObject, AVAudioRecorderDelegate {
    private var recorder: AVAudioRecorder?
    @Published var isRecording = false
    private(set) var outputURL: URL?

    func startRecording() throws {

        // ✅ Use temp directory (always writable in sandbox)
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("whispr_recording.m4a")

        outputURL = url

        // Remove old file if exists
        if FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44100,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
        ]

        let recorder = try AVAudioRecorder(url: url, settings: settings)
        recorder.prepareToRecord()

        guard recorder.record() else {
            throw NSError(domain: "Whispr", code: -1,
                          userInfo: [NSLocalizedDescriptionKey: "Recording failed"])
        }

        self.recorder = recorder
        isRecording = true

        print("🎙️ Recording to:", url.path)
    }

    func stopRecording() {
        recorder?.stop()
        recorder = nil
        isRecording = false
    }
}
