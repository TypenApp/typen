import QtQuick

// Six alternating quadratic humps (the site's --squiggle), drawn on a Canvas.
Canvas {
    id: canvas
    property color color: Theme.proof
    property real strokeWidth: 1.5
    property int humps: 6

    onColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        ctx.clearRect(0, 0, width, height)
        ctx.strokeStyle = canvas.color
        ctx.lineWidth = strokeWidth
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        var w = width / humps
        var baseline = height * 0.6
        var amp = height * 0.5
        ctx.beginPath()
        ctx.moveTo(0, baseline)
        for (var i = 0; i < humps; i++) {
            var dir = (i % 2 === 0) ? -1 : 1
            ctx.quadraticCurveTo(w * (i + 0.5), baseline + dir * amp, w * (i + 1), baseline)
        }
        ctx.stroke()
    }
}
