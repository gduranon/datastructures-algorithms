// Transcribe un audio en la Mac, sin red (macOS 26 o posterior).
// Uso: macos_stt archivo.wav en-US,es-US [glosario]   ->  {"text": ..., "language": ..., "confidence": ...}
// Con varios idiomas, los prueba todos y devuelve el de mayor confianza.
import AVFoundation
import Foundation
import Speech

struct Out: Codable, Sendable { var text = "", language = "", confidence = 0.0 }

func run(_ path: String, _ id: String, _ terms: [String]) async throws -> Out {
    let t = SpeechTranscriber(locale: Locale(identifier: id), transcriptionOptions: [], reportingOptions: [],
                              attributeOptions: [.transcriptionConfidence])
    if let req = try await AssetInventory.assetInstallationRequest(supporting: [t]) {
        try await req.downloadAndInstall()
    }
    let analyzer = SpeechAnalyzer(modules: [t])
    if !terms.isEmpty {
        let ctx = AnalysisContext()
        ctx.contextualStrings[.general] = terms
        try await analyzer.setContext(ctx)
    }
    let collect = Task { () -> Out in
        var out = Out(language: id), sum = 0.0, n = 0.0
        for try await r in t.results {
            out.text += String(r.text.characters)
            for piece in r.text.runs {
                guard let c = piece.transcriptionConfidence else { continue }
                let len = Double(r.text[piece.range].characters.count)
                sum += c * len
                n += len
            }
        }
        out.confidence = n > 0 ? sum / n : 0
        out.text = out.text.trimmingCharacters(in: .whitespacesAndNewlines)
        return out
    }
    let file = try AVAudioFile(forReading: URL(fileURLWithPath: path))
    if let end = try await analyzer.analyzeSequence(from: file) {
        try await analyzer.finalizeAndFinish(through: end)
    } else {
        await analyzer.cancelAndFinishNow()
    }
    return try await collect.value
}

@main struct Main {
    static func main() async {
        let a = CommandLine.arguments
        do {
            guard a.count >= 3 else { throw NSError(domain: "uso: macos_stt archivo idiomas [glosario]", code: 2) }
            guard SpeechTranscriber.isAvailable else { throw NSError(domain: "no disponible en esta Mac", code: 1) }
            let terms = a.count > 3 ? a[3].split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) } : []
            let best = try await withThrowingTaskGroup(of: Out.self) { g in
                for id in a[2].split(separator: ",") { g.addTask { try await run(a[1], String(id), terms) } }
                var best = Out()
                for try await o in g where !o.text.isEmpty && (best.text.isEmpty || o.confidence > best.confidence) { best = o }
                return best
            }
            print(String(decoding: try JSONEncoder().encode(best), as: UTF8.self))
        } catch {
            FileHandle.standardError.write(Data("\(error)\n".utf8))
            exit(1)
        }
    }
}
