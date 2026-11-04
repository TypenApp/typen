import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1060
    height: 720
    minimumWidth: 920
    minimumHeight: 620
    visible: true
    title: "Typen — Settings"
    color: "#0b0f19"

    // Design Tokens
    readonly property color bgPrimary: "#0b0f19"
    readonly property color bgSidebar: "#111827"
    readonly property color bgCard: "#1e293b"
    readonly property color bgInput: "#090d16"
    readonly property color borderSubtle: "#334155"
    readonly property color textPrimary: "#f8fafc"
    readonly property color textSecondary: "#94a3b8"
    readonly property color accentBlue: "#3b82f6"
    readonly property color accentGreen: "#10b981"
    readonly property color accentAmber: "#f59e0b"
    readonly property color accentRed: "#ef4444"

    property int currentScreenIndex: 0

    readonly property var navItems: [
        { title: "Overview", subtitle: "Status & typing insights", badge: "" },
        { title: "General", subtitle: "Startup, hotkeys & privacy", badge: "" },
        { title: "Dictionary", subtitle: "Custom & suggested words", badge: "" },
        { title: "Languages", subtitle: "Regions & 6 domain packs", badge: "" },
        { title: "Corrections", subtitle: "Sensitivity, rules & undo", badge: "" },
        { title: "Intelligence", subtitle: "Local AI & BYOK Cloud AI", badge: "" },
        { title: "Profiles", subtitle: "Per-application behaviour", badge: "" },
        { title: "Text Expansion", subtitle: "Snippets & macros", badge: "" },
        { title: "Updates", subtitle: "App, lexicon & AI models", badge: "" },
        { title: "About", subtitle: "Version, licence & support", badge: "" }
    ]

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // --- Left Sidebar Navigation Rail (240px) ---
        Rectangle {
            Layout.preferredWidth: 248
            Layout.fillHeight: true
            color: window.bgSidebar

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 8

                // Brand Header
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Rectangle {
                        width: 34
                        height: 34
                        radius: 9
                        color: window.accentBlue
                        Text {
                            anchors.centerIn: parent
                            text: "✓"
                            color: "#ffffff"
                            font.pixelSize: 18
                            font.bold: true
                        }
                    }
                    ColumnLayout {
                        spacing: 1
                        Text {
                            text: "Typen"
                            color: window.textPrimary
                            font.pixelSize: 16
                            font.bold: true
                        }
                        Text {
                            text: "v" + bridge.appVersion + " • free & open source"
                            color: window.textSecondary
                            font.pixelSize: 11
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: window.borderSubtle
                    Layout.topMargin: 6
                    Layout.bottomMargin: 6
                }

                // 10-Screen Navigation List
                ListView {
                    id: navList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: window.navItems
                    spacing: 4
                    clip: true

                    delegate: Rectangle {
                        width: navList.width
                        height: 46
                        radius: 8
                        color: index === window.currentScreenIndex ? "#1d4ed8" : "transparent"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 8

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                Text {
                                    text: modelData.title
                                    color: window.textPrimary
                                    font.pixelSize: 13
                                    font.bold: index === window.currentScreenIndex
                                }
                                Text {
                                    text: modelData.subtitle
                                    color: index === window.currentScreenIndex ? "#bfdbfe" : window.textSecondary
                                    font.pixelSize: 10
                                }
                            }

                            Rectangle {
                                visible: modelData.badge !== ""
                                width: 34
                                height: 18
                                radius: 9
                                color: "#312e81"
                                Text {
                                    anchors.centerIn: parent
                                    text: modelData.badge
                                    color: "#a5b4fc"
                                    font.pixelSize: 9
                                    font.bold: true
                                }
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: window.currentScreenIndex = index
                        }
                    }
                }

                // IPC Connection Health Footer
                Rectangle {
                    Layout.fillWidth: true
                    height: 52
                    radius: 8
                    color: window.bgCard
                    border.color: window.borderSubtle
                    border.width: 1

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 8
                        Rectangle {
                            width: 10
                            height: 10
                            radius: 5
                            color: bridge.isPaused ? window.accentAmber : window.accentGreen
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                text: bridge.isPaused ? "Assistance Paused" : "System Hook Active"
                                color: window.textPrimary
                                font.pixelSize: 11
                                font.bold: true
                            }
                            Text {
                                text: bridge.ipcTransportLabel
                                color: window.textSecondary
                                font.pixelSize: 10
                            }
                        }
                    }
                }
            }
        }

        // --- Main Content Stack (10 Screens) ---
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: window.currentScreenIndex

            // =================================================================
            // SCREEN 1: OVERVIEW
            // =================================================================
            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width - 48
                    anchors.margins: 24
                    spacing: 16

                    Text {
                        text: "1. Overview & Live Typing Insights"
                        color: window.textPrimary
                        font.pixelSize: 22
                        font.bold: true
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 90
                        radius: 12
                        color: window.bgCard
                        border.color: window.borderSubtle
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 20
                            ColumnLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: bridge.statusMessage
                                    color: window.textPrimary
                                    font.pixelSize: 15
                                    font.bold: true
                                }
                                Text {
                                    text: "Active Region: " + bridge.activeRegion + "  •  Lexicon (mmap): " + bridge.lexiconWordCount + " words  •  Custom Words: " + bridge.customWordCount
                                    color: window.textSecondary
                                    font.pixelSize: 12
                                }
                            }
                            Button {
                                text: bridge.isPaused ? "Resume Typing Assistance" : "Pause Assistance"
                                onClicked: bridge.togglePause()
                            }
                        }
                    }

                    // Custom LGPL-Safe QML Bar Chart for Local Insights (Zero QtCharts GPL module)
                    Rectangle {
                        Layout.fillWidth: true
                        height: 240
                        radius: 12
                        color: window.bgCard
                        border.color: window.borderSubtle
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 20
                            spacing: 10
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: "Privacy-Preserving Local Typing Insights (Aggregate Counters Only)"
                                    color: window.textPrimary
                                    font.pixelSize: 14
                                    font.bold: true
                                    Layout.fillWidth: true
                                }
                                Button {
                                    text: "Reset Counters"
                                    onClicked: bridge.resetInsights()
                                }
                            }
                            Text {
                                text: bridge.insightsSummaryText
                                color: window.textSecondary
                                font.pixelSize: 13
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }

            // =================================================================
            // SCREEN 2: GENERAL
            // =================================================================
            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width - 48
                    anchors.margins: 24
                    spacing: 16
                    Text {
                        text: "2. General Preferences & Privacy Controls"
                        color: window.textPrimary
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        height: 220
                        radius: 12
                        color: window.bgCard
                        border.color: window.borderSubtle
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 20
                            spacing: 12
                            CheckBox {
                                text: "Launch the Typen background service automatically at OS login"
                                checked: bridge.launchAtLogin
                                onToggled: bridge.setLaunchAtLogin(checked)
                            }
                            Text {
                                text: "Sentence Rewrite Hotkey: " + bridge.rewriteHotkey + "  |  Pause Hotkey: " + bridge.pauseHotkey
                                color: window.textSecondary
                                font.pixelSize: 13
                            }
                            Button {
                                text: "One-Click Privacy Wipe (Clear All Custom Words & Preferences)"
                                onClicked: bridge.privacyWipe()
                            }
                        }
                    }
                }
            }

            // =================================================================
            // SCREEN 3: DICTIONARY
            // =================================================================
            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width - 48
                    anchors.margins: 24
                    spacing: 16
                    Text {
                        text: "3. My Custom Dictionary & Reverted Suggestions"
                        color: window.textPrimary
                        font.pixelSize: 22
                        font.bold: true
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        TextField {
                            id: newWordField
                            Layout.fillWidth: true
                            placeholderText: "Enter a word, name, or technical term to never correct..."
                            onAccepted: {
                                bridge.addCustomWord(newWordField.text)
                                newWordField.text = ""
                            }
                        }
                        Button {
                            text: "Add Word"
                            onClicked: {
                                bridge.addCustomWord(newWordField.text)
                                newWordField.text = ""
                            }
                        }
                    }
                    Text {
                        text: "Active Custom Words (" + bridge.customWordCount + "): " + bridge.customWordsPreview
                        color: window.textPrimary
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    Text {
                        text: "Suggested Words from Double-Backspace Reverts: " + bridge.suggestedWordsPreview
                        color: window.accentAmber
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }

            // =================================================================
            // SCREEN 4: LANGUAGES
            // =================================================================
            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width - 48
                    anchors.margins: 24
                    spacing: 16
                    Text {
                        text: "4. Regional English & Domain Vocabulary Packs"
                        color: window.textPrimary
                        font.pixelSize: 22
                        font.bold: true
                    }
                    RowLayout {
                        spacing: 8
                        Repeater {
                            model: ["EN_GB", "EN_US", "EN_CA", "EN_AU", "UNIVERSAL"]
                            Button {
                                text: modelData
                                highlighted: bridge.activeRegion === modelData
                                onClicked: bridge.setRegion(modelData)
                            }
                        }
                    }
                    Text {
                        text: "Enabled Domain Vocabulary Packs: " + bridge.enabledDomainPacksText
                        color: window.textSecondary
                        font.pixelSize: 13
                    }
                }
            }

            // =================================================================
            // SCREEN 5: CORRECTIONS
            // =================================================================
            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width - 48
                    anchors.margins: 24
                    spacing: 16
                    Text {
                        text: "5. Correction Behaviour, Punctuation & Undo"
                        color: window.textPrimary
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Text {
                        text: bridge.correctionsSummaryText
                        color: window.textSecondary
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }

            // =================================================================
            // SCREEN 6: INTELLIGENCE
            // =================================================================
            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width - 48
                    anchors.margins: 24
                    spacing: 16
                    Text {
                        text: "6. Intelligence: Local AI & BYOK Cloud AI"
                        color: window.textPrimary
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Text {
                        text: bridge.aiSummaryText
                        color: window.textSecondary
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }

            // =================================================================
            // SCREEN 7: PROFILES
            // =================================================================
            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width - 48
                    anchors.margins: 24
                    spacing: 16
                    Text {
                        text: "7. Application-Specific Typing Profiles"
                        color: window.textPrimary
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Text {
                        text: bridge.profilesSummaryText
                        color: window.textSecondary
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }

            // =================================================================
            // SCREEN 8: TEXT EXPANSION
            // =================================================================
            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width - 48
                    anchors.margins: 24
                    spacing: 16
                    Text {
                        text: "8. Text Expansion Snippets"
                        color: window.textPrimary
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Text {
                        text: bridge.snippetsSummaryText
                        color: window.textSecondary
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }

            // =================================================================
            // SCREEN 9: UPDATES
            // =================================================================
            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width - 48
                    anchors.margins: 24
                    spacing: 16
                    Text {
                        text: "9. Independent Updates: App, Language Library & AI Models"
                        color: window.textPrimary
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Text {
                        text: bridge.updatesSummaryText
                        color: window.textSecondary
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    Button {
                        text: "Rollback Language Library to Last Known Good"
                        onClicked: bridge.rollbackResources()
                    }
                }
            }

            // =================================================================
            // SCREEN 10: ABOUT
            // =================================================================
            ScrollView {
                clip: true
                ColumnLayout {
                    width: parent.width - 48
                    anchors.margins: 24
                    spacing: 16
                    Text {
                        text: "10. About Typen"
                        color: window.textPrimary
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Text {
                        text: bridge.aboutSummaryText
                        color: window.textSecondary
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    Button {
                        text: "Support Typen with a donation"
                        onClicked: bridge.openDonatePage()
                    }
                }
            }
        }
    }
}
