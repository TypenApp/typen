import QtQuick
import QtQuick.Layouts

// A boolean setting bound straight to the settings store by key.
SettingRow {
    id: row
    property string key: ""
    property bool checked: key !== "" ? (bridge.settings[key] === true) : false
    signal toggled(bool value)

    Toggle {
        checked: row.checked
        enabled: row.enabled
        onToggled: {
            if (row.key !== "") bridge.setSetting(row.key, checked)
            row.toggled(checked)
        }
    }
}
