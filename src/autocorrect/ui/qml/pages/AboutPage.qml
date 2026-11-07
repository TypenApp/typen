import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

Page {
    id: page
    readonly property var about: bridge.about
    property string diagPath: ""

    PageHeader {
        number: "11"
        title: "About"
        lead: "Typen is free, open source and local-first. No account, no telemetry, no cloud in the typing path."
    }

    Card {
        RowLayout {
            Layout.fillWidth: true
            spacing: 20
            BrandMark { tileHeight: 56; Layout.alignment: Qt.AlignTop }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Text { text: "Typen"; color: Theme.ink; font.family: Theme.display; font.pixelSize: Theme.fsHero; font.weight: Font.Bold; font.letterSpacing: -1 }
                Body { text: "Version " + (about.app_version || bridge.appVersion) + "  ·  " + (about.licence || "MIT") + " licence" }
                Body { text: String(about.status_message || "") ; visible: !!about.status_message; font.pixelSize: Theme.fsSmall }
            }
        }
        Squiggle { Layout.fillWidth: true; height: 10 }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            SecondaryButton { text: "Source on GitHub"; onClicked: bridge.call("open_source_repository", "{}") }
            SecondaryButton { text: "Sponsor"; onClicked: bridge.call("open_sponsors_page", "{}") }
            GhostButton { text: "Website"; onClicked: bridge.openUrl("https://typen.org") }
        }
    }

    Card {
        SectionTitle { title: "Diagnostics"; description: "A JSON file with version, hook state and settings, for bug reports. It never contains anything you typed." }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            SecondaryButton { text: "Export diagnostics"; onClicked: page.diagPath = bridge.exportDiagnostics() }
            GhostButton { text: "Open data folder"; onClicked: bridge.openDataFolder() }
            Item { Layout.fillWidth: true }
        }
        Body { visible: page.diagPath !== ""; text: page.diagPath; font.family: Theme.mono; font.pixelSize: 11 }
    }

    Card {
        SectionTitle { title: "Open-source components" }
        Repeater {
            model: [
                { n: "Qt / PySide6", l: "LGPL v3", d: "User interface framework. Relinkable: replace the Qt libraries in the install folder." },
                { n: "Syne", l: "SIL Open Font Licence 1.1", d: "Display typeface by Bonjour Monde." },
                { n: "pystray, pynput, comtypes", l: "MIT / LGPL", d: "Tray icon, keyboard hook helpers and UI Automation access." },
                { n: "Lexicon data", l: "Various permissive", d: "Word frequency lists and misspelling corpora; see the resources folder for each source." }
            ]
            ListRow {
                primary: modelData.n
                secondary: modelData.l + "  ·  " + modelData.d
            }
        }
    }
}
