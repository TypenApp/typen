import QtQuick
import QtQuick.Layouts

// Segmented control. `options` is [{value, label}] (or plain strings).
Row {
    id: choice
    property var options: []
    property var value: null
    signal picked(var value)
    spacing: 6

    Repeater {
        model: choice.options
        SecondaryButton {
            readonly property var opt: modelData
            readonly property var optValue: (typeof opt === "object" && opt !== null) ? opt.value : opt
            text: (typeof opt === "object" && opt !== null) ? opt.label : String(opt)
            active: String(choice.value) === String(optValue)
            onClicked: choice.picked(optValue)
        }
    }
}
