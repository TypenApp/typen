import QtQuick
import QtQuick.Controls

// .field: single-line text input.
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
    background: Rectangle {
        radius: Theme.radiusSm
        color: Theme.paper
        border.color: field.activeFocus ? Theme.ink : Theme.line
        border.width: 1
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }
}
