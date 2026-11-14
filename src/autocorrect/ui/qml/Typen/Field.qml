import QtQuick
import QtQuick.Controls

// .field: single-line text input with a visible, theme-aware blinking caret.
TextField {
    id: field
    implicitHeight: Theme.controlHeight
    leftPadding: 10
    rightPadding: 10
    color: Theme.ink
    placeholderTextColor: Theme.inkFaint
    selectionColor: Theme.ink
    selectedTextColor: Theme.paper
    font.family: Theme.sans
    font.pixelSize: Theme.fsBody
    cursorDelegate: Rectangle {
        width: 1.5
        color: Theme.ink
        visible: field.activeFocus && !field.readOnly && field.selectionStart === field.selectionEnd
        SequentialAnimation on opacity {
            running: field.activeFocus && !field.readOnly
            loops: Animation.Infinite
            NumberAnimation { from: 1.0; to: 1.0; duration: 520 }
            NumberAnimation { from: 0.0; to: 0.0; duration: 480 }
        }
    }
    background: Rectangle {
        radius: Theme.radiusSm
        color: Theme.paper
        border.color: field.activeFocus ? Theme.ink : Theme.line
        border.width: 1
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
}
