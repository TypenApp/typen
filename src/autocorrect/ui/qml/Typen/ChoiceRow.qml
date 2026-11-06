import QtQuick
import QtQuick.Layouts

// An enum setting bound to the store by key, rendered as a segmented control.
SettingRow {
    id: row
    property string key: ""
    property var options: []
    property var value: key !== "" ? bridge.settings[key] : null
    signal picked(var value)

    Choice {
        options: row.options
        value: row.value
        enabled: row.enabled
        onPicked: function (v) {
            if (row.key !== "") bridge.setSetting(row.key, v)
            row.picked(v)
        }
    }
}
