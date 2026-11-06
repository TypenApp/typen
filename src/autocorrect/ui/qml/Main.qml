import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

ApplicationWindow {
    id: win
    width: 1120
    height: 760
    minimumWidth: 880
    minimumHeight: 560
    visible: true
    title: "Typen"
    color: Theme.paper

    // Theme follows the bridge (system/light/dark + Syne).
    Binding { target: Theme; property: "dark"; value: bridge.themeIsDark }
    Binding { target: Theme; property: "displayFamily"; value: bridge.fontFamily }

    // Screens. `title` strings here match SettingsController.SCREEN_NAMES exactly.
    ListModel {
        id: screens
        ListElement { title: "Overview";       number: "01"; file: "OverviewPage.qml" }
        ListElement { title: "General";        number: "02"; file: "GeneralPage.qml" }
        ListElement { title: "Language";       number: "03"; file: "LanguagePage.qml" }
        ListElement { title: "Corrections";    number: "04"; file: "CorrectionsPage.qml" }
        ListElement { title: "Dictionary";     number: "05"; file: "DictionaryPage.qml" }
        ListElement { title: "Apps";           number: "06"; file: "AppsPage.qml" }
        ListElement { title: "Text Expansion"; number: "07"; file: "SnippetsPage.qml" }
        ListElement { title: "Intelligence";   number: "08"; file: "IntelligencePage.qml" }
        ListElement { title: "Updates";        number: "09"; file: "UpdatesPage.qml" }
        ListElement { title: "Feedback";       number: "10"; file: "FeedbackPage.qml" }
        ListElement { title: "About";          number: "11"; file: "AboutPage.qml" }
    }

    property int currentIndex: 0

    function indexForScreen(name) {
        var wanted = String(name || "").trim().toLowerCase().replace(/[-_ ]+/g, " ")
        for (var i = 0; i < screens.count; i++) {
            var t = screens.get(i).title.toLowerCase()
            if (t === wanted || t.replace(/\s+/g, "") === wanted.replace(/\s+/g, "")) return i
        }
        if (wanted === "snippets" || wanted === "expansion") return 6
        if (wanted === "ai") return 7
        return 0
    }
    Component.onCompleted: {
        var initial = (typeof initialScreen === "string" && initialScreen) ? initialScreen : bridge.initialScreen
        if (initial) currentIndex = indexForScreen(initial)
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ---------------------------------------------------------------- Sidebar
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: Theme.sidebarWidth
            color: Theme.paper1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 0

                RowLayout {
                    spacing: 10
                    BrandMark { tileHeight: 28; paused: bridge.isPaused }
                    Text {
                        text: "Typen"
                        color: Theme.ink
                        font.family: Theme.display
                        font.pixelSize: 20
                        font.weight: Font.Bold
                        font.letterSpacing: -0.5
                    }
                    Item { Layout.fillWidth: true }
                }
                Item { height: 28 }

                Repeater {
                    model: screens
                    Rectangle {
                        required property int index
                        required property string title
                        required property string number
                        readonly property bool selected: index === win.currentIndex
                        Layout.fillWidth: true
                        implicitHeight: 34
                        radius: Theme.radiusSm
                        color: selected ? Theme.paper3 : (navHover.hovered ? Theme.paper2 : "transparent")
                        HoverHandler { id: navHover }
                        TapHandler { onTapped: win.currentIndex = index }
                        Rectangle {
                            visible: selected
                            width: 3; height: 16; radius: 1.5
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            color: Theme.proof
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 10
                            spacing: 10
                            Text {
                                text: number
                                color: selected ? Theme.proof : Theme.inkFaint
                                font.family: Theme.mono
                                font.pixelSize: 11
                            }
                            Text {
                                text: title
                                color: selected ? Theme.ink : Theme.inkMuted
                                font.family: Theme.sans
                                font.pixelSize: Theme.fsBody
                                font.weight: selected ? Font.DemiBold : Font.Normal
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                // Status footer
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: footCol.implicitHeight + 24
                    radius: Theme.radius
                    color: Theme.paper
                    border.color: Theme.line
                    ColumnLayout {
                        id: footCol
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 6
                        RowLayout {
                            spacing: 8
                            Rectangle {
                                width: 8; height: 8; radius: 4
                                color: !bridge.ipcConnected ? Theme.proof : (bridge.isPaused ? Theme.inkFaint : Theme.ok)
                            }
                            Text {
                                text: !bridge.ipcConnected ? "Not running" : (bridge.isPaused ? "Paused" : "Active")
                                color: Theme.ink
                                font.family: Theme.sans
                                font.pixelSize: Theme.fsSmall
                                font.weight: Font.DemiBold
                            }
                            Item { Layout.fillWidth: true }
                            Text { text: "v" + bridge.appVersion; color: Theme.inkFaint; font.family: Theme.mono; font.pixelSize: 11 }
                        }
                        SecondaryButton {
                            Layout.fillWidth: true
                            text: bridge.isPaused ? "Resume" : "Pause"
                            onClicked: bridge.togglePause()
                        }
                    }
                }
            }
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
        }

        // ---------------------------------------------------------------- Content
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            StackLayout {
                id: stack
                anchors.fill: parent
                currentIndex: win.currentIndex
                Repeater {
                    model: screens
                    Loader {
                        required property int index
                        required property string file
                        // Lazy: instantiate on first show, keep alive afterwards.
                        property bool shown: index === win.currentIndex
                        onShownChanged: if (shown) active = true
                        active: index === win.currentIndex
                        source: "pages/" + file
                        visible: shown
                    }
                }
            }

            // Toast overlay
            Rectangle {
                id: toastBox
                property bool isError: false
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 24
                width: toastText.implicitWidth + 32
                height: 38
                radius: 19
                color: isError ? Theme.proof : Theme.ink
                opacity: 0
                visible: opacity > 0
                Behavior on opacity { NumberAnimation { duration: 180 } }
                Text {
                    id: toastText
                    anchors.centerIn: parent
                    color: Theme.paper
                    font.family: Theme.sans
                    font.pixelSize: Theme.fsSmall
                    font.weight: Font.DemiBold
                }
                Timer { id: toastTimer; interval: 3200; onTriggered: toastBox.opacity = 0 }
            }
        }
    }

    Connections {
        target: bridge
        function onToast(message, isError) {
            toastText.text = message
            toastBox.isError = isError
            toastBox.opacity = 1
            toastTimer.restart()
        }
    }

    Shortcut { sequences: [StandardKey.Close]; onActivated: win.close() }
    Shortcut { sequence: "Ctrl+R"; onActivated: bridge.refresh() }
}
