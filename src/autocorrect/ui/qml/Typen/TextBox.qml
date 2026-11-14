import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// .field, multi-line with a visible, theme-aware blinking caret.
Rectangle {
    id: box
    property alias text: area.text
    property alias placeholderText: area.placeholderText
    property alias readOnly: area.readOnly
    property alias textArea: area
    property int minimumHeight: 96

    Layout.fillWidth: true
    implicitHeight: Math.max(minimumHeight, area.implicitHeight + 16)
    radius: Theme.radiusSm
    color: Theme.paper
    border.color: area.activeFocus ? Theme.ink : Theme.line
    border.width: 1
    Behavior on border.color { ColorAnimation { duration: 120 } }

    ScrollView {
        anchors.fill: parent
        anchors.margins: 1
        clip: true
        TextArea {
            id: area
            padding: 8
            wrapMode: TextEdit.Wrap
            color: Theme.ink
            placeholderTextColor: Theme.inkFaint
            selectionColor: Theme.ink
            selectedTextColor: Theme.paper
            font.family: Theme.sans
            font.pixelSize: Theme.fsBody
            background: null
            cursorDelegate: Rectangle {
                width: 1.5
                color: Theme.ink
                visible: area.activeFocus && !area.readOnly && area.selectionStart === area.selectionEnd
                SequentialAnimation on opacity {
                    running: area.activeFocus && !area.readOnly
                    loops: Animation.Infinite
                    NumberAnimation { from: 1.0; to: 1.0; duration: 520 }
                    NumberAnimation { from: 0.0; to: 0.0; duration: 480 }
                }
            }
        }
    }
}
