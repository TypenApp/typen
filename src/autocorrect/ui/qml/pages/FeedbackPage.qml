import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

Page {
    id: page
    property string kind: "suggestion"
    property bool sending: false
    property string resultUrl: ""
    property string resultMessage: ""
    property bool resultOk: false

    function send() {
        if (sending) return
        sending = true
        resultUrl = ""; resultMessage = ""
        var raw = bridge.sendFeedback(kind, alias.text.trim(), email.text.trim(), note.text, steps.text, includeDiag.checked)
        var res = JSON.parse(raw)
        sending = false
        resultOk = res.ok === true
        resultMessage = res.message || ""
        resultUrl = res.url || ""
        if (resultOk) { note.text = ""; steps.text = "" }
    }

    PageHeader {
        number: "10"
        title: "Feedback"
        lead: "Tell us what would make Typen better, or what broke. Both land straight with the people who build it."
    }

    Card {
        Choice {
            options: [{ value: "suggestion", label: "Suggestion" }, { value: "bug", label: "Report a bug" }]
            value: page.kind
            onPicked: function (v) { page.kind = v; page.resultMessage = ""; page.resultUrl = "" }
        }
        Body {
            text: page.kind === "bug"
                ? "Bug reports become GitHub issues. Include what you typed, what you expected and what happened instead."
                : "Suggestions become GitHub discussions so others can weigh in and vote."
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Eyebrow { label: "Alias" }
                Field { id: alias; Layout.fillWidth: true; placeholderText: "How should we credit you?" }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Eyebrow { label: "Email (optional)" }
                Field { id: email; Layout.fillWidth: true; placeholderText: "Only if you want a reply"; inputMethodHints: Qt.ImhEmailCharactersOnly }
            }
        }
        Eyebrow { label: page.kind === "bug" ? "What happened?" : "Your idea" }
        TextBox {
            id: note
            Layout.fillWidth: true
            minimumHeight: 120
            placeholderText: page.kind === "bug" ? "Typen capitalised the word after a comma in Slack…" : "It would be great if…"
        }
        Eyebrow { label: "Steps to reproduce (optional)"; visible: page.kind === "bug" }
        TextBox {
            id: steps
            visible: page.kind === "bug"
            Layout.fillWidth: true
            minimumHeight: 80
            placeholderText: "1. Open Slack\n2. Type 'hello, world'\n3. …"
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Toggle { id: includeDiag; checked: true }
            Body {
                text: "Attach diagnostics — version, Windows build, hook state and which features are on. Never what you type."
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Body {
                visible: page.resultMessage !== ""
                text: page.resultMessage
                color: page.resultOk ? Theme.ok : Theme.proof
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            Item { Layout.fillWidth: page.resultMessage === "" }
            GhostButton { visible: page.resultUrl !== ""; text: "Open on GitHub"; onClicked: bridge.openUrl(page.resultUrl) }
            PrimaryButton {
                text: page.sending ? "Sending…" : (page.kind === "bug" ? "Report bug" : "Send suggestion")
                enabled: !page.sending && alias.text.trim() !== "" && note.text.trim().length >= 10
                onClicked: page.send()
            }
        }
    }

    Card {
        padding: 14
        RowLayout {
            Layout.fillWidth: true
            Body { text: "Prefer GitHub directly?"; Layout.fillWidth: true }
            GhostButton { text: "Issues"; onClicked: bridge.openUrl(String(bridge.about.source_url || "https://github.com/TypenApp/typen") + "/issues") }
            GhostButton { text: "Discussions"; onClicked: bridge.openUrl(String(bridge.about.source_url || "https://github.com/TypenApp/typen") + "/discussions") }
        }
    }
}
