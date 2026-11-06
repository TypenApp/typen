import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

Page {
    id: page
    readonly property var ov: bridge.overview
    readonly property var ins: ov.insights || {}
    readonly property var session: ov.session || {}
    readonly property var last: session.last_correction || null
    readonly property var hook: ov.hook_status || {}
    readonly property bool paused: bridge.isPaused
    readonly property bool healthy: bridge.ipcConnected && !paused && ["active", "dry_run"].indexOf(String(hook.state)) >= 0

    // Live counters while this page is visible.
    Timer {
        interval: 1000
        running: page.visible
        repeat: true
        onTriggered: bridge.refreshOverview()
    }

    PageHeader {
        number: "01"
        title: "Overview"
        lead: "Typen corrects as you type, everywhere. Here is what it is doing right now."
    }

    // --- Status -----------------------------------------------------------
    Card {
        RowLayout {
            Layout.fillWidth: true
            spacing: 18
            Rectangle {
                width: 12; height: 12; radius: 6
                color: page.healthy ? Theme.ok : (page.paused ? Theme.inkFaint : Theme.proof)
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: 8
                SequentialAnimation on opacity {
                    running: page.healthy
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.35; duration: 1200; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 1.0; duration: 1200; easing.type: Easing.InOutSine }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Text {
                    text: bridge.statusMessage
                    color: Theme.ink
                    font.family: Theme.display
                    font.pixelSize: Theme.fsTitle
                    font.weight: Font.Bold
                    font.letterSpacing: -0.5
                }
                Body { text: bridge.statusDetail }
                Body {
                    visible: hook.backend !== undefined && String(hook.backend) !== ""
                    text: "Hook: " + hook.backend + " · " + hook.state + (hook.detail ? " · " + hook.detail : "")
                    font.family: Theme.mono
                    font.pixelSize: 11
                }
            }
            PrimaryButton {
                text: page.paused ? "Resume" : "Pause"
                onClicked: bridge.togglePause()
                Layout.alignment: Qt.AlignTop
            }
        }
    }

    // --- Try it -------------------------------------------------------------
    Card {
        SectionTitle {
            title: "Try it"
            description: "Type a sentence with a few mistakes. The system hook fixes it live when Typen is active; the preview below shows what the engine would do with the same text."
        }
        Field {
            id: tryField
            Layout.fillWidth: true
            placeholderText: "teh quick brown fox jumps over teh lazy dog. i recieved your mesage"
            onTextChanged: previewTimer.restart()
        }
        Timer {
            id: previewTimer
            interval: 250
            onTriggered: preview.text = tryField.text.trim() === "" ? "" : bridge.tryText(tryField.text + " ")
        }
        Rectangle {
            Layout.fillWidth: true
            visible: preview.text !== ""
            implicitHeight: preview.implicitHeight + 20
            radius: Theme.radiusSm
            color: Theme.paper1
            border.color: Theme.line
            Text {
                id: preview
                anchors.fill: parent
                anchors.margins: 10
                color: Theme.ink
                font.family: Theme.sans
                font.pixelSize: Theme.fsLead
                wrapMode: Text.WordWrap
            }
        }
    }

    // --- Counters ---------------------------------------------------------
    Card {
        RowLayout {
            Layout.fillWidth: true
            SectionTitle {
                title: "Typing insights"
                description: "Counts only, kept on this computer. Typen never stores what you type."
                Layout.fillWidth: true
            }
            GhostButton { text: "Reset"; onClicked: bridge.call("reset_insights", "{}") }
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 4
            columnSpacing: 28
            rowSpacing: 16
            Stat { label: "This session"; value: String(session.corrections || 0); highlight: true }
            Stat { label: "Spelling"; value: String(ins.spelling_corrections || 0) }
            Stat { label: "Context"; value: String(ins.contextual_corrections || 0) }
            Stat { label: "Punctuation & caps"; value: String(ins.punctuation_and_caps_fixes || 0) }
            Stat { label: "Words seen"; value: String(ins.words_evaluated || 0) }
            Stat { label: "Snippets"; value: String(ins.snippets_expanded || 0) }
            Stat { label: "Undone"; value: String(ins.corrections_undone || 0) }
            Stat { label: "Keystrokes saved"; value: String(ins.keystrokes_saved || 0) }
        }
        Divider {}
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Eyebrow { label: "Last fix" }
            Text {
                visible: page.last !== null
                text: page.last ? (page.last.original + "  →  " + page.last.replacement) : ""
                color: Theme.ink
                font.family: Theme.sans
                font.pixelSize: Theme.fsBody
            }
            Pill {
                visible: page.last !== null
                label: page.last ? String(page.last.reason).replace(/_/g, " ").toLowerCase() : ""
            }
            Body {
                visible: page.last === null
                text: "Nothing corrected yet this session."
                font.pixelSize: Theme.fsSmall
            }
            Item { Layout.fillWidth: true }
            Body {
                text: "Hold Esc for " + Number(ov.hold_esc_seconds || 10).toFixed(0) + " s to pause or resume"
                font.pixelSize: Theme.fsSmall
                horizontalAlignment: Text.AlignRight
            }
        }
    }

    // --- Quick toggles ---------------------------------------------------
    Card {
        SectionTitle { title: "Quick switches"; description: "The four behaviours people change most. Everything else is under Corrections." }
        ToggleRow { key: "enable_spelling"; label: "Spelling corrections" }
        ToggleRow { key: "enable_auto_capitalise"; label: "Capitalisation" }
        ToggleRow { key: "enable_punctuation_assist"; label: "Punctuation assistance" }
        ToggleRow { key: "enable_auto_space_after_sentence"; label: "Space after . ! ?" }
    }

    // --- Environment -------------------------------------------------------
    Card {
        padding: 14
        RowLayout {
            Layout.fillWidth: true
            spacing: 28
            Repeater {
                model: [
                    { k: "Language", v: String(ov.active_region || "").replace("_", "-") },
                    { k: "Lexicon", v: Number(ov.lexicon_word_count || 0).toLocaleString(Qt.locale(), "f", 0) + " words" },
                    { k: "Custom words", v: String(ov.custom_word_count || 0) },
                    { k: "Language data", v: "v" + String(ov.resource_version || "") }
                ]
                RowLayout {
                    spacing: 8
                    Eyebrow { label: modelData.k }
                    Text { text: modelData.v; color: Theme.ink; font.family: Theme.mono; font.pixelSize: Theme.fsSmall }
                }
            }
            Item { Layout.fillWidth: true }
            Pill { label: bridge.ipcConnected ? "connected" : "offline"; tone: bridge.ipcConnected ? "ok" : "proof" }
        }
    }
}
