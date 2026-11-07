import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

Page {
    id: page
    readonly property var up: bridge.updates
    readonly property var app: up.app || {}
    readonly property var res: up.language_resources || {}
    readonly property var models: up.local_models || {}
    readonly property string releasesUrl: String(bridge.about.source_url || "https://github.com/TypenApp/typen") + "/releases"
    readonly property string downloadUrl: "https://typen.org/download"

    function dateOnly(v) { return v ? String(v).slice(0, 10) : "—" }

    PageHeader {
        number: "09"
        title: "Updates"
        lead: "The app, the language data and the on-device model each update on their own schedule."
    }

    Card {
        RowLayout {
            Layout.fillWidth: true
            spacing: 28
            ColumnLayout {
                spacing: 2
                Eyebrow { label: "Typen" }
                Text { text: "v" + (app.current_version || bridge.appVersion); color: Theme.ink; font.family: Theme.display; font.pixelSize: Theme.fsTitle; font.weight: Font.Bold; font.letterSpacing: -0.5 }
                Body { text: "Released " + page.dateOnly(app.released_at); font.pixelSize: Theme.fsSmall }
            }
            Item { Layout.fillWidth: true }
            Pill { label: String(app.channel || "stable"); tone: app.channel === "beta" ? "proof" : "muted" }
            SecondaryButton { text: "Check for updates"; onClicked: bridge.openUrl(page.downloadUrl) }
            GhostButton { text: "Release notes"; onClicked: bridge.openUrl(page.releasesUrl) }
        }
        Divider {}
        ToggleRow { key: "updates_check_on_launch"; label: "Check for updates on launch" }
        ChoiceRow {
            key: "update_channel"; label: "Channel"
            description: "Beta builds arrive first and may change between releases."
            options: [{ value: "stable", label: "Stable" }, { value: "beta", label: "Beta" }]
        }
    }

    Card {
        RowLayout {
            Layout.fillWidth: true
            spacing: 28
            ColumnLayout {
                spacing: 2
                Eyebrow { label: "Language data" }
                Text { text: "v" + (res.active_version || "—"); color: Theme.ink; font.family: Theme.display; font.pixelSize: Theme.fsTitle; font.weight: Font.Bold; font.letterSpacing: -0.5 }
                Body { text: Number(res.word_count || 0).toLocaleString(Qt.locale(), "f", 0) + " words  ·  schema " + (res.schema_version || "—") + "  ·  " + page.dateOnly(res.released_at); font.pixelSize: Theme.fsSmall }
            }
            Item { Layout.fillWidth: true }
            GhostButton { text: "Roll back"; onClicked: bridge.call("rollback_language_resources", "{}") }
        }
        Divider {}
        ToggleRow { key: "updates_auto_language_data"; label: "Download language data automatically"; description: "Word lists and typo tables are signed and verified before they are used; the previous bundle is kept for rollback." }
        Body { text: "Bundle: " + (res.bundle_dir || "—"); font.family: Theme.mono; font.pixelSize: 11 }
    }

    Card {
        RowLayout {
            Layout.fillWidth: true
            spacing: 28
            ColumnLayout {
                spacing: 2
                Eyebrow { label: "On-device model" }
                Text { text: String(models.recommended_model_id || "none"); color: Theme.ink; font.family: Theme.display; font.pixelSize: Theme.fsTitle; font.weight: Font.Bold; font.letterSpacing: -0.5 }
                Body { text: "Accelerator: " + (models.accelerator || "cpu"); font.pixelSize: Theme.fsSmall }
            }
            Item { Layout.fillWidth: true }
            Pill { label: models.is_loaded ? "loaded" : "not loaded"; tone: models.is_loaded ? "ok" : "muted" }
        }
    }
}
