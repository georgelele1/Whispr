import Foundation

enum Config {

    // ── Add your path here, nothing else needs to change ──
    static let fallbackRoots = [
        "/Users/quinta/Desktop/snippet实现和测试报告/Comp9900_project_testversion-main",
        "/Users/georgelele/OneDrive/桌面/9900/Comp9900_project_testversion",
        "/Users/yanbowang/Comp9900_project_testversion",
        // add your path below this line
    ]

    // ── Add your Python path here if it's not in the default list ──
    static let pythonCandidates = [
        "/Users/yanbowang/opt/anaconda3/bin/python3.11",
        "/Users/yanbowang/opt/anaconda3/bin/python3",
        "/opt/homebrew/bin/python3.11",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3.11",
        "/usr/local/bin/python3",
        "/usr/bin/python3"
    ]
}
