import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

Page {
    id: page
    readonly property var lang: bridge.languages
    readonly property var regions: lang.available_regions || []
    readonly property var packs: lang.domain_packs || []

    // Local Domain Vocabulary Editor state
    property string editingPackId: ""
    property string editingPackName: ""
    property var packDetails: ({ words: [], direct_typos: [], word_count: 0, typo_count: 0, custom_count: 0, has_overrides: false })
    property string packFilter: ""
    property string editingOldWord: ""
    property bool confirmResetPack: false

    function enabledPackIds() {
        var ids = []
        for (var i = 0; i < packs.length; i++) if (packs[i].enabled) ids.push(packs[i].id)
        return ids
    }
    function setPack(id, on) {
        var ids = enabledPackIds().filter(function (x) { return x !== id })
        if (on) ids.push(id)
        bridge.call("set_enabled_domain_packs", JSON.stringify({ pack_ids: ids }))
    }
    function invokePackCall(method, payload) {
        var raw = bridge.call(method, JSON.stringify(payload))
        try {
            var parsed = JSON.parse(raw)
            if (parsed && parsed.ok && parsed.result) {
                page.packDetails = parsed.result
            }
        } catch (e) {}
    }
    function openPackEditor(packObj) {
        if (page.editingPackId === packObj.id) {
            page.editingPackId = ""
            page.editingOldWord = ""
            page.confirmResetPack = false
            return
        }
        page.editingPackId = packObj.id
        page.editingPackName = packObj.name
        page.packFilter = ""
        page.editingOldWord = ""
        page.confirmResetPack = false
        invokePackCall("get_domain_pack_details", { pack_id: packObj.id })
    }
    function filteredPackWords() {
        var all = (page.packDetails && page.packDetails.words) ? page.packDetails.words : []
        var f = page.packFilter.trim().toLowerCase()
        if (f === "") return all
        return all.filter(function (item) { return String(item.word).toLowerCase().indexOf(f) >= 0 })
    }
    function filteredPackTypos() {
        var all = (page.packDetails && page.packDetails.direct_typos) ? page.packDetails.direct_typos : []
        var f = page.packFilter.trim().toLowerCase()
        if (f === "") return all
        return all.filter(function (item) {
            return String(item.typo).toLowerCase().indexOf(f) >= 0
                || String(item.target).toLowerCase().indexOf(f) >= 0
        })
    }
    function submitAddPackWord() {
        var w = addPackWordField.text.trim()
        if (w === "" || page.editingPackId === "") return
        invokePackCall("add_domain_pack_word", { pack_id: page.editingPackId, word: w })
        addPackWordField.text = ""
    }
    function submitEditPackWord() {
        var nw = editPackWordField.text.trim()
        if (nw === "" || page.editingOldWord === "" || page.editingPackId === "") return
        invokePackCall("edit_domain_pack_word", {
            pack_id: page.editingPackId,
            old_word: page.editingOldWord,
            new_word: nw
        })
        page.editingOldWord = ""
        editPackWordField.text = ""
    }
    function submitAddPackTypo() {
        var t = packTypoField.text.trim()
        var tgt = packTargetField.text.trim()
        if (t === "" || tgt === "" || page.editingPackId === "") return
        invokePackCall("upsert_domain_pack_typo", {
            pack_id: page.editingPackId,
            typo: t,
            target: tgt
        })
        packTypoField.text = ""
        packTargetField.text = ""
    }

    PageHeader {
        number: "03"
        title: "Language"
        lead: "Which English Typen corrects towards, how firmly, and which specialist vocabularies it knows."
    }

    Card {
        SectionTitle {
            title: "English variant"
            description: lang.region_setting === "AUTO"
                ? "Following the system language: currently " + String(lang.active_region || "").replace("_", "-") + "."
                : "Fixed to " + String(lang.active_region || "").replace("_", "-") + "."
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Repeater {
                model: page.regions
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 48
                    color: hover.hovered ? Theme.paper1 : "transparent"
                    HoverHandler { id: hover }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 6
                        anchors.rightMargin: 6
                        spacing: 12
                        Rectangle {
                            width: 16; height: 16; radius: 8
                            color: "transparent"
                            border.color: modelData.code === lang.region_setting ? Theme.ink : Theme.lineStrong
                            border.width: modelData.code === lang.region_setting ? 5 : 1
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text { text: modelData.name; color: Theme.ink; font.family: Theme.sans; font.pixelSize: Theme.fsBody }
                            Body { visible: !!modelData.examples; text: modelData.examples || ""; font.pixelSize: Theme.fsSmall }
                        }
                        Pill { visible: modelData.code === "AUTO" && lang.region_setting === "AUTO"; label: String(lang.active_region || "").replace("_", "-"); tone: "ink" }
                    }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: bridge.call("set_region", JSON.stringify({ region_code: modelData.code })) }
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line; visible: index < page.regions.length - 1 }
                }
            }
        }
    }

    Card {
        SectionTitle { title: "Strictness" }
        ChoiceRow {
            key: "variant_enforcement"; label: "Cross-variant spellings"
            description: "Off accepts colour and color alike. Prefer converts only when a word looks mistyped. Strict always converts to your variant."
            options: [{ value: "off", label: "Off" }, { value: "prefer", label: "Prefer" }, { value: "strict", label: "Strict" }]
        }
        ToggleRow {
            key: "uk_ize_spelling"; label: "Oxford -ize spellings"
            description: "For UK English: keep organize / realize rather than converting to -ise."
            enabled: String(lang.active_region) === "EN_GB"
        }
    }

    Card {
        SectionTitle {
            title: "Domain vocabulary"
            description: "Specialist word lists and brand casings. Turn on the domains you write in, or edit any pack's words locally on this machine."
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Repeater {
                model: page.packs
                SettingRow {
                    label: modelData.name
                    description: modelData.description
                        + (modelData.word_count ? "  ·  " + Number(modelData.word_count).toLocaleString(Qt.locale(), "f", 0) + " words" : "")
                        + (modelData.custom_count ? "  ·  " + modelData.custom_count + " local" : "")
                    Layout.topMargin: 8
                    Layout.bottomMargin: 8
                    RowLayout {
                        spacing: 10
                        GhostButton {
                            text: page.editingPackId === modelData.id ? "Close" : "Edit words"
                            onClicked: page.openPackEditor(modelData)
                        }
                        Toggle { checked: modelData.enabled === true; onToggled: page.setPack(modelData.id, checked) }
                    }
                }
            }
        }
    }

    // --- Interactive Local Domain Pack Editor -----------------------------
    Card {
        visible: page.editingPackId !== ""
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            SectionTitle {
                title: page.editingPackName + " vocabulary"
                description: Number(page.packDetails.word_count || 0) + " words  ·  "
                    + Number(page.packDetails.typo_count || 0) + " typo shortcuts"
                    + (page.packDetails.custom_count ? "  ·  " + page.packDetails.custom_count + " local edits" : "")
                Layout.fillWidth: true
            }
            GhostButton {
                visible: page.packDetails.has_overrides === true && !page.confirmResetPack
                text: "Reset defaults"
                onClicked: page.confirmResetPack = true
            }
            PrimaryButton {
                visible: page.confirmResetPack
                danger: true
                text: "Confirm reset"
                onClicked: {
                    page.invokePackCall("reset_domain_pack", { pack_id: page.editingPackId })
                    page.confirmResetPack = false
                    page.editingOldWord = ""
                }
            }
            GhostButton {
                visible: page.confirmResetPack
                text: "Cancel"
                onClicked: page.confirmResetPack = false
            }
        }

        // Add words (single or comma-separated, preserves exact casing)
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Field {
                id: addPackWordField
                Layout.fillWidth: true
                placeholderText: "Add word or brand (e.g. FastHTML, Prisma, mRNA — comma-separate for multiple)…"
                onAccepted: page.submitAddPackWord()
            }
            PrimaryButton {
                text: "Add"
                enabled: addPackWordField.text.trim() !== ""
                onClicked: page.submitAddPackWord()
            }
        }

        // Inline word rename / casing editor (shown when a word chip is clicked)
        Rectangle {
            visible: page.editingOldWord !== ""
            Layout.fillWidth: true
            implicitHeight: editRow.implicitHeight + 16
            radius: 8
            color: Theme.paper1
            border.color: Theme.lineStrong
            RowLayout {
                id: editRow
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8
                Eyebrow { label: "Edit word" }
                Body { text: page.editingOldWord + "  →"; font.family: Theme.mono; font.pixelSize: Theme.fsSmall }
                Field {
                    id: editPackWordField
                    Layout.fillWidth: true
                    placeholderText: "Updated spelling or casing…"
                    onAccepted: page.submitEditPackWord()
                }
                PrimaryButton {
                    text: "Save"
                    enabled: editPackWordField.text.trim() !== ""
                    onClicked: page.submitEditPackWord()
                }
                GhostButton {
                    text: "Cancel"
                    onClicked: { page.editingOldWord = ""; editPackWordField.text = "" }
                }
            }
        }

        Field {
            Layout.fillWidth: true
            placeholderText: "Search words or shortcuts in " + page.editingPackName + "…"
            text: page.packFilter
            onTextChanged: page.packFilter = text
        }

        Body {
            text: "Click any word chip to edit its spelling or casing, or click × to remove it on this computer."
            font.pixelSize: Theme.fsSmall
        }

        Flow {
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: page.filteredPackWords()
                Rectangle {
                    readonly property bool isUserModified: modelData.source !== "builtin"
                    height: 28
                    width: pChipRow.implicitWidth + 16
                    radius: 14
                    color: pChipHover.hovered ? Theme.paper2 : Theme.paper1
                    border.color: isUserModified ? Theme.ink : Theme.line
                    HoverHandler { id: pChipHover }
                    RowLayout {
                        id: pChipRow
                        anchors.centerIn: parent
                        spacing: 6
                        Text {
                            text: modelData.word
                            color: Theme.ink
                            font.family: Theme.sans
                            font.pixelSize: Theme.fsSmall
                            font.weight: isUserModified ? Font.DemiBold : Font.Normal
                            TapHandler {
                                onTapped: {
                                    page.editingOldWord = modelData.word
                                    editPackWordField.text = modelData.word
                                    editPackWordField.forceActiveFocus()
                                }
                            }
                        }
                        Text {
                            text: "×"
                            color: pDelHover.hovered ? Theme.proof : Theme.inkFaint
                            font.pixelSize: 14
                            HoverHandler { id: pDelHover }
                            TapHandler {
                                onTapped: {
                                    if (page.editingOldWord === modelData.word) page.editingOldWord = ""
                                    page.invokePackCall("delete_domain_pack_word", {
                                        pack_id: page.editingPackId,
                                        word: modelData.word
                                    })
                                }
                            }
                        }
                    }
                }
            }
        }

        Divider {}
        SectionTitle {
            title: "Domain typo shortcuts"
            description: "Direct mistyped → target corrections active whenever " + page.editingPackName + " is enabled."
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Field {
                id: packTypoField
                Layout.fillWidth: true
                placeholderText: "mistyped word (e.g. fasthtlm)"
            }
            Body { text: "→" }
            Field {
                id: packTargetField
                Layout.fillWidth: true
                placeholderText: "target word (e.g. FastHTML)"
                onAccepted: page.submitAddPackTypo()
            }
            SecondaryButton {
                text: "Save shortcut"
                enabled: packTypoField.text.trim() !== "" && packTargetField.text.trim() !== ""
                onClicked: page.submitAddPackTypo()
            }
        }
        Repeater {
            model: page.filteredPackTypos()
            ListRow {
                primary: modelData.typo + "  →  " + modelData.target
                secondary: modelData.source !== "builtin" ? "local shortcut" : ""
                GhostButton {
                    text: "Remove"
                    onClicked: page.invokePackCall("delete_domain_pack_typo", {
                        pack_id: page.editingPackId,
                        typo: modelData.typo
                    })
                }
            }
        }
    }
}
