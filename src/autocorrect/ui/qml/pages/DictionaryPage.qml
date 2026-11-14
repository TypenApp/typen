import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import Typen

Page {
    id: page
    readonly property var dict: bridge.dictionary
    readonly property var words: dict.words || []
    readonly property var suggested: dict.suggested || []
    readonly property var s: bridge.settings
    property string filter: ""

    function visibleWords() {
        var f = filter.trim().toLowerCase()
        if (f === "") return words
        return words.filter(function (w) { return String(w).toLowerCase().indexOf(f) >= 0 })
    }
    function addWord() {
        var w = newWord.text.trim()
        if (w === "") return
        bridge.call("add_custom_word", JSON.stringify({ word: w }))
        newWord.text = ""
    }

    PageHeader {
        number: "05"
        title: "Dictionary"
        lead: "Names, jargon and words of your own. Anything here is never flagged or changed."
    }

    Card {
        SectionTitle { title: "Suggested words"; description: "Words you put back after Typen changed them, or that you type again and again. Add them so it stops." }
        EmptyNote { visible: page.suggested.length === 0; text: "No suggestions right now. Undo a correction with Backspace and the word will appear here." }
        Repeater {
            model: page.suggested
            ListRow {
                primary: modelData.word
                secondary: modelData.source === "repeated"
                    ? "typed " + modelData.seen_count + " times"
                    : "put back " + modelData.revert_count + (modelData.revert_count === 1 ? " time" : " times") + (modelData.corrected_to ? " (was changed to " + modelData.corrected_to + ")" : "")
                SecondaryButton { text: "Add"; onClicked: bridge.call("accept_suggested_word", JSON.stringify({ word: modelData.word })) }
                GhostButton { text: "Dismiss"; onClicked: bridge.call("dismiss_suggested_word", JSON.stringify({ word: modelData.word })) }
            }
        }
    }

    Card {
        RowLayout {
            Layout.fillWidth: true
            SectionTitle { title: "Your words"; description: page.words.length + (page.words.length === 1 ? " word" : " words"); Layout.fillWidth: true }
            GhostButton { text: "Export CSV"; onClicked: exportDialog.open() }
            GhostButton { text: "Import"; onClicked: importDialog.open() }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Field {
                id: newWord
                Layout.fillWidth: true
                placeholderText: "Add a word…"
                onAccepted: page.addWord()
            }
            PrimaryButton { text: "Add"; enabled: newWord.text.trim() !== ""; onClicked: page.addWord() }
        }
        Field {
            visible: page.words.length > 12
            Layout.fillWidth: true
            placeholderText: "Filter…"
            onTextChanged: page.filter = text
        }
        EmptyNote { visible: page.words.length === 0; text: "Your dictionary is empty." }
        Flow {
            Layout.fillWidth: true
            spacing: 6
            visible: page.words.length > 0
            Repeater {
                model: page.visibleWords()
                Rectangle {
                    height: 28
                    width: chipRow.implicitWidth + 16
                    radius: 14
                    color: chipHover.hovered ? Theme.paper2 : Theme.paper1
                    border.color: Theme.line
                    HoverHandler { id: chipHover }
                    RowLayout {
                        id: chipRow
                        anchors.centerIn: parent
                        spacing: 6
                        Text { text: modelData; color: Theme.ink; font.family: Theme.sans; font.pixelSize: Theme.fsSmall }
                        Text {
                            text: "×"
                            color: delHover.hovered ? Theme.proof : Theme.inkFaint
                            font.pixelSize: 14
                            HoverHandler { id: delHover }
                            TapHandler { onTapped: bridge.call("delete_custom_word", JSON.stringify({ word: modelData })) }
                        }
                    }
                }
            }
        }
    }

    Card {
        SectionTitle { title: "Learning" }
        SliderRow {
            key: "suggest_after_reverts"; label: "Suggest a word after"; from: 1; to: 10; step: 1
            formatter: function (v) { return v + (v === 1 ? " undo" : " undos") }
        }
        SliderRow {
            key: "auto_learn_after_reverts"; label: "Add it automatically after"; from: 0; to: 10; step: 1
            description: "0 keeps everything manual."
            formatter: function (v) { return v === 0 ? "Never" : v + (v === 1 ? " undo" : " undos") }
        }
        ToggleRow { key: "learn_repeated_oov"; label: "Suggest unknown words you type often" }
        SliderRow {
            key: "learn_repeated_threshold"; label: "After"; from: 2; to: 50; step: 1; indent: true
            enabled: s.learn_repeated_oov === true
            formatter: function (v) { return v + " times" }
        }
        ToggleRow {
            key: "auto_add_repeated_oov"; label: "Add repeated words to dictionary automatically"; indent: true
            enabled: s.learn_repeated_oov === true
            description: "Promote words to your dictionary as soon as they reach the threshold above."
        }
    }

    Card {
        SectionTitle { title: "Leave alone"; description: "Kinds of word Typen should never try to correct." }
        ToggleRow { key: "ignore_words_with_digits"; label: "Words containing digits"; description: "b2b, mp3, 4k" }
        ToggleRow { key: "ignore_acronyms"; label: "ALL-CAPS acronyms" }
        ToggleRow { key: "ignore_symbol_words"; label: "Words with symbols"; description: "C#, file_name, foo-bar" }
        ToggleRow { key: "ignore_mentions"; label: "@mentions, #tags and URLs" }
        SliderRow {
            key: "ignore_longer_than"; label: "Words longer than"; from: 0; to: 64; step: 1
            formatter: function (v) { return v === 0 ? "No limit" : v + " letters" }
        }
    }

    FileDialog {
        id: exportDialog
        title: "Export dictionary"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "csv"
        nameFilters: ["CSV (*.csv)", "JSON (*.json)"]
        onAccepted: {
            var path = String(selectedFile)
            var isJson = path.toLowerCase().endsWith(".json")
            var res = JSON.parse(bridge.call(isJson ? "export_dictionary_json" : "export_dictionary_csv", "{}"))
            if (res.ok && bridge.writeTextFile(path, res.result)) bridge.toast("Dictionary exported.", false)
        }
    }
    FileDialog {
        id: importDialog
        title: "Import dictionary"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Dictionary files (*.csv *.json *.txt)"]
        onAccepted: {
            var path = String(selectedFile)
            var text = bridge.readTextFile(path)
            if (text === "") return
            var isJson = path.toLowerCase().endsWith(".json")
            var res = JSON.parse(bridge.call(isJson ? "import_dictionary_json" : "import_dictionary_csv", JSON.stringify(isJson ? { json_text: text } : { csv_text: text })))
            if (res.ok) bridge.toast("Dictionary imported.", false)
        }
    }
}
