import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A numeric setting (int or float) bound to the store by key, with a live value label.
SettingRow {
    id: row
    property string key: ""
    property real from: 0
    property real to: 1
    property real step: 1
    property string suffix: ""
    property var formatter: null          // function(value) -> string
    property real value: key !== "" ? Number(bridge.settings[key]) : from

    function display(v) {
        if (formatter) return formatter(v)
        var txt = (step >= 1) ? String(Math.round(v)) : v.toFixed(step < 0.1 ? 2 : 1)
        return txt + suffix
    }

    RowLayout {
        spacing: 10
        Slider {
            id: slider
            implicitWidth: 180
            from: row.from
            to: row.to
            stepSize: row.step
            value: row.value
            enabled: row.enabled
            snapMode: Slider.SnapAlways
            onMoved: valueLabel.text = row.display(value)
            onPressedChanged: {
                if (!pressed && row.key !== "" && Math.abs(value - row.value) > 1e-9)
                    bridge.setSetting(row.key, row.step >= 1 ? Math.round(value) : value)
            }
            background: Rectangle {
                x: slider.leftPadding
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: slider.availableWidth
                height: 3
                radius: 1.5
                color: Theme.line
                Rectangle {
                    width: slider.visualPosition * parent.width
                    height: parent.height
                    radius: 1.5
                    color: Theme.ink
                }
            }
            handle: Rectangle {
                x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
                y: slider.topPadding + slider.availableHeight / 2 - height / 2
                width: 16
                height: 16
                radius: 8
                color: Theme.paper
                border.color: Theme.ink
                border.width: 2
            }
        }
        Text {
            id: valueLabel
            text: row.display(row.value)
            color: Theme.ink
            font.family: Theme.mono
            font.pixelSize: Theme.fsSmall
            Layout.minimumWidth: 56
            horizontalAlignment: Text.AlignRight
        }
    }
    onValueChanged: valueLabel.text = display(value)
}
