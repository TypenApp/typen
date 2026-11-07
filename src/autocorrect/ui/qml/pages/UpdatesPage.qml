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
    readonly property string downloadUrl: String(app.download_page_url || "https://typen.org/download")
    readonly property string status: String(app.status || "idle")
    readonly property bool updateAvailable: status === "available" || status === "ready"
    readonly property bool unsignedUpdate: status === "unsigned"
    readonly property bool busy: status === "checking" || status === "downloading" || status === "applying"

    Timer {
        interval: 500
        running: page.busy
        repeat: true
        onTriggered: bridge.refresh()
    }

    function dateOnly(v) { return v ? String(v).slice(0, 10) : "—" }
    function statusLine() {
        if (status === "checking") return "Checking…"
        if (status === "downloading")
            return "Downloading " + Math.round(Number(app.download_progress || 0) * 100) + "%"
        if (status === "applying") return "Installing and restarting…"
        if (status === "available" || status === "ready")
            return "Update available: v" + (app.available_version || "—")
        if (status === "unsigned")
            return "v" + (app.available_version || "—") + " is available but not signed for in-app install"
        if (status === "up_to_date") return "You're up to date"
        if (status === "error") return String(app.error || "Couldn't check for updates. Try again.")
        return app.reason ? String(app.reason) : ""
    }

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
                Layout.fillWidth: true
                Layout.maximumWidth: 420
                spacing: 2
                Eyebrow { label: "Typen" }
                Text { text: "v" + (app.current_version || bridge.appVersion); color: Theme.ink; font.family: Theme.display; font.pixelSize: Theme.fsTitle; font.weight: Font.Bold; font.letterSpacing: -0.5 }
                Body { text: "Released " + page.dateOnly(app.released_at); font.pixelSize: Theme.fsSmall }
                Body {
                    visible: page.statusLine().length > 0
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    text: page.statusLine()
                    font.pixelSize: Theme.fsSmall
                    color: page.status === "error" ? Theme.proof : Theme.inkMuted
                }
            }
            Item { Layout.fillWidth: true }
            Pill { label: String(app.channel || "stable"); tone: app.channel === "beta" ? "proof" : "muted" }
            SecondaryButton {
                text: status === "checking" ? "Checking…" : (status === "downloading" || status === "applying" ? "Updating…" : "Check for updates")
                enabled: !page.busy
                onClicked: bridge.call("check_for_updates", "{}")
            }
            PrimaryButton {
                visible: page.updateAvailable
                text: "Update & restart"
                enabled: !page.busy
                onClicked: bridge.call("apply_app_update", "{}")
            }
            GhostButton {
                visible: page.unsignedUpdate
                text: "Download page"
                onClicked: bridge.openUrl(page.downloadUrl)
            }
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
