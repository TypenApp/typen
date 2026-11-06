import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A scrollable settings page: gutter, max content width, vertical rhythm.
ScrollView {
    id: page
    default property alias content: column.data
    property int maxWidth: 820
    clip: true
    contentWidth: availableWidth
    contentHeight: wrapper.implicitHeight
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

    Item {
        id: wrapper
        width: page.availableWidth
        implicitHeight: column.implicitHeight + Theme.gutter * 2

        ColumnLayout {
            id: column
            x: Theme.gutter
            y: Theme.gutter
            width: Math.min(wrapper.width - Theme.gutter * 2, page.maxWidth)
            spacing: 18
        }
    }
}
