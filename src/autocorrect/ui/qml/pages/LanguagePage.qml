import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

Page {
    id: page
    readonly property var lang: bridge.languages
    readonly property var regions: lang.available_regions || []
    readonly property var packs: lang.domain_packs || []

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
        SectionTitle { title: "Domain vocabulary"; description: "Specialist word lists that are never flagged as typos. Turn on the ones you write in." }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Repeater {
                model: page.packs
                SettingRow {
                    label: modelData.name
                    description: modelData.description + (modelData.word_count ? "  ·  " + Number(modelData.word_count).toLocaleString(Qt.locale(), "f", 0) + " words" : "")
                    Layout.topMargin: 8
                    Layout.bottomMargin: 8
                    Toggle { checked: modelData.enabled === true; onToggled: page.setPack(modelData.id, checked) }
                }
            }
        }
    }
}
