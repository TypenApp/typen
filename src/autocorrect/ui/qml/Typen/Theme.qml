pragma Singleton
import QtQuick

// Typen design tokens: the same ink / paper / line / proof palette as the
// website (site/src/app/globals.css), in light and dark. Syne for display
// text, the system UI font for body copy, a monospace for eyebrows and code.
QtObject {
    id: theme

    property bool dark: false
    property string displayFamily: ""   // Syne, set by Main.qml from the bridge

    // --- palette --------------------------------------------------------
    readonly property color ink:        dark ? "#ffffff" : "#000000"
    readonly property color ink1:       dark ? "#f5f5f5" : "#0a0a0a"
    readonly property color ink2:       dark ? "#e8e8e8" : "#171717"
    readonly property color ink3:       dark ? "#d9d9d9" : "#262626"
    readonly property color inkMuted:   dark ? "#a6a6a6" : "#595959"
    readonly property color inkFaint:   dark ? "#757575" : "#8a8a8a"
    readonly property color paper:      dark ? "#000000" : "#ffffff"
    readonly property color paper1:     dark ? "#0a0a0a" : "#fafafa"
    readonly property color paper2:     dark ? "#111111" : "#f4f4f4"
    readonly property color paper3:     dark ? "#1a1a1a" : "#ececec"
    readonly property color line:       dark ? "#262626" : "#e4e4e4"
    readonly property color lineStrong: dark ? "#3a3a3a" : "#c9c9c9"
    readonly property color proof:      dark ? "#ff5a3c" : "#e5341a"
    readonly property color proofStrong:dark ? "#ff7b61" : "#c42a12"
    readonly property color proofSoft:  dark ? "#2a120c" : "#fdece8"
    readonly property color ok:         dark ? "#5fd38d" : "#1f8a4c"

    // --- type -----------------------------------------------------------
    readonly property string sans: Qt.application.font.family
    readonly property string display: displayFamily !== "" ? displayFamily : sans
    readonly property string mono: Qt.platform.os === "windows" ? "Cascadia Mono" : (Qt.platform.os === "osx" ? "Menlo" : "DejaVu Sans Mono")

    readonly property int fsEyebrow: 11
    readonly property int fsSmall: 12
    readonly property int fsBody: 13
    readonly property int fsLead: 15
    readonly property int fsTitle: 26
    readonly property int fsHero: 34

    // --- geometry -------------------------------------------------------
    readonly property int radius: 8
    readonly property int radiusSm: 4
    readonly property int gutter: 28
    readonly property int gap: 12
    readonly property int sidebarWidth: 236
    readonly property int controlHeight: 32
}
