//
//  Voice_to_Text_input_for_MacApp.swift
//  Voice-to-Text input for Mac
//
//  Created by yanbo wang on 2026-02-23.
//

import SwiftUI
import SwiftData

@main
struct Voice_to_Text_input_for_MacApp: App {
    var sharedModelContainer: ModelContainer = {
        let schema = Schema([
            Item.self,
        ])
        let modelConfiguration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: false)

        do {
            return try ModelContainer(for: schema, configurations: [modelConfiguration])
        } catch {
            fatalError("Could not create ModelContainer: \(error)")
        }
    }()

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .modelContainer(sharedModelContainer)
    }
}
