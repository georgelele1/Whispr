//
//  Item.swift
//  Voice-to-Text input for Mac
//
//  Created by yanbo wang on 2026-02-23.
//

import Foundation
import SwiftData

@Model
final class Item {
    var timestamp: Date
    
    init(timestamp: Date) {
        self.timestamp = timestamp
    }
}
