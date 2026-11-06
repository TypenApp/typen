import QtQuick
import QtQuick.Layouts

// A row in a list card: primary text, secondary text, trailing actions.
Rectangle {
    id: row
    property string primary: ""
    property string secondary: ""
    property bool mono: false
    default property alias actions: actionSlot.data

    Layout.fillWidth: true
    implicitHeight: 40
    color: hover.hovered ? Theme.paper1 : "transparent"
    HoverHandler { id: hover }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 6
        spacing: 10
        Text {
            text: row.primary
            color: Theme.ink
            font.family: row.mono ? Theme.mono : Theme.sans
            font.pixelSize: Theme.fsBody
            elide: Text.ElideRight
            Layout.preferredWidth: 220
        }
        Text {
            text: row.secondary
            color: Theme.inkMuted
            font.family: Theme.sans
            font.pixelSize: Theme.fsSmall
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        Row { id: actionSlot; spacing: 2 }
    }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
}
