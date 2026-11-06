import QtQuick
import QtQuick.Layouts

// Label + description on the left, any control on the right.
RowLayout {
    id: row
    property string label: ""
    property string description: ""
    property bool indent: false
    default property alias control: slot.data

    Layout.fillWidth: true
    Layout.leftMargin: indent ? 22 : 0
    spacing: 16

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 2
        Text {
            text: row.label
            color: row.enabled ? Theme.ink : Theme.inkFaint
            font.family: Theme.sans
            font.pixelSize: Theme.fsBody
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        Body {
            visible: row.description !== ""
            text: row.description
            font.pixelSize: Theme.fsSmall
        }
    }
    Item {
        id: slot
        implicitWidth: childrenRect.width
        implicitHeight: childrenRect.height
        Layout.alignment: Qt.AlignVCenter
    }
}
