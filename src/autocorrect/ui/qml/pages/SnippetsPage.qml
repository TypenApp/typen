import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

Page {
    id: page
    readonly property var snip: bridge.snippets
    readonly property var snippets: snip.snippets || []
    readonly property string prefix: String(bridge.settings.snippet_prefix || ";")
    property string editingTrigger: ""

    function save() {
        var t = trig.text.trim(), e = expansion.text
        if (t === "" || e.trim() === "") return
        if (t.indexOf(page.prefix) === 0) t = t.slice(page.prefix.length)
        bridge.call("upsert_snippet", JSON.stringify({ trigger: t, expansion: e, description: desc.text.trim() }))
        trig.text = ""; expansion.text = ""; desc.text = ""; editingTrigger = ""
    }
    function edit(s) {
        editingTrigger = s.trigger
        trig.text = s.trigger; expansion.text = s.expansion; desc.text = s.description || ""
        trig.forceActiveFocus()
    }

    PageHeader {
        number: "07"
        title: "Text Expansion"
        lead: "Short triggers that grow into longer text the moment you type a space after them."
    }

    Card {
        SectionTitle { title: "How triggers work" }
        ChoiceRow {
            key: "snippet_prefix"; label: "Trigger prefix"
            description: "Every snippet starts with this so ordinary words never expand by accident."
            options: [{ value: ";", label: ";" }, { value: "@@", label: "@@" }, { value: "//", label: "//" }]
        }
        ToggleRow { key: "snippet_case_matching"; label: "Match capitals"; description: "Typing " + page.prefix + "Sig instead of " + page.prefix + "sig capitalises the first letter of the expansion." }
    }

    Card {
        SectionTitle { title: page.editingTrigger !== "" ? "Edit snippet" : "New snippet" }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            ColumnLayout {
                Layout.preferredWidth: 180
                spacing: 4
                Eyebrow { label: "Trigger" }
                RowLayout {
                    spacing: 0
                    Text { text: page.prefix; color: Theme.inkMuted; font.family: Theme.mono; font.pixelSize: Theme.fsBody; rightPadding: 6 }
                    Field { id: trig; Layout.fillWidth: true; placeholderText: "sig" }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Eyebrow { label: "Description (optional)" }
                Field { id: desc; Layout.fillWidth: true; placeholderText: "Email signature" }
            }
        }
        Eyebrow { label: "Expands to" }
        TextBox { id: expansion; Layout.fillWidth: true; placeholderText: "Kind regards,\nEnwon" }
        RowLayout {
            Layout.fillWidth: true
            Body { text: "Type " + page.prefix + (trig.text.trim() || "trigger") + " then Space."; font.pixelSize: Theme.fsSmall }
            Item { Layout.fillWidth: true }
            GhostButton { visible: page.editingTrigger !== ""; text: "Cancel"; onClicked: { page.editingTrigger = ""; trig.text = ""; expansion.text = ""; desc.text = "" } }
            PrimaryButton { text: page.editingTrigger !== "" ? "Save" : "Add snippet"; enabled: trig.text.trim() !== "" && expansion.text.trim() !== ""; onClicked: page.save() }
        }
    }

    Card {
        SectionTitle { title: "Your snippets"; description: page.snippets.length === 0 ? "" : page.snippets.length + (page.snippets.length === 1 ? " snippet" : " snippets") }
        EmptyNote { visible: page.snippets.length === 0; text: "No snippets yet. Try " + page.prefix + "addr for your address or " + page.prefix + "sig for a sign-off." }
        Repeater {
            model: page.snippets
            ListRow {
                primary: page.prefix + modelData.trigger
                mono: true
                secondary: (modelData.description ? modelData.description + "  ·  " : "") + String(modelData.expansion).replace(/\s+/g, " ")
                GhostButton { text: "Edit"; onClicked: page.edit(modelData) }
                GhostButton { text: "Delete"; danger: true; onClicked: bridge.call("delete_snippet", JSON.stringify({ trigger: modelData.trigger })) }
            }
        }
    }
}
