import UIKit

/// pyxpo-svg on iOS: a Core Graphics view (`PxSvg`) that draws the operations Python flattened from the SVG tree.
final class SvgModule: PxViewModule {
    static let moduleName = "Svg"
    static let viewTypes = ["PxSvg"]

    required init() {}

    func makeView(_ ctx: PxModuleContext, _ type: String, _ emit: @escaping (String, Any?) -> Void) -> PxNativeView {
        PxSvgView()
    }

    func call(_ ctx: PxModuleContext, _ method: String, _ args: [Any], _ reply: @escaping PxReply) {
        reply(nil, "Svg has no method \(method)")
    }
}

private func svgColor(_ v: UInt32) -> UIColor {
    UIColor(red: CGFloat((v >> 16) & 0xFF) / 255, green: CGFloat((v >> 8) & 0xFF) / 255,
            blue: CGFloat(v & 0xFF) / 255, alpha: CGFloat((v >> 24) & 0xFF) / 255)
}

private func num(_ any: Any?, _ fallback: CGFloat) -> CGFloat {
    (any as? NSNumber).map { CGFloat($0.doubleValue) } ?? fallback
}

/// One draw operation. Path steps are absolute: 0 M x y, 1 L x y, 2 C x1 y1 x2 y2 x y, 3 Q x1 y1 x y, 4 Z.
struct SvgOp {
    var text: String?
    var path = CGMutablePath()
    var evenOdd = false
    var fill: UInt32 = 0
    var stroke: UInt32 = 0
    var width: CGFloat = 1
    var cap = CGLineCap.butt
    var join = CGLineJoin.miter
    var miter: CGFloat = 4
    var dash: [CGFloat]?
    var phase: CGFloat = 0
    var matrix: CGAffineTransform?
    var x: CGFloat = 0
    var y: CGFloat = 0
    var size: CGFloat = 16
    var weight = 400
    var anchor = 0
    var family: String?

    init(_ o: [String: Any]) {
        text = o["text"] as? String
        evenOdd = (o["evenodd"] as? NSNumber)?.boolValue ?? false
        fill = (o["fill"] as? NSNumber)?.uint32Value ?? 0
        stroke = (o["stroke"] as? NSNumber)?.uint32Value ?? 0
        width = num(o["width"], 1)
        cap = [CGLineCap.butt, .round, .square][min(max((o["cap"] as? NSNumber)?.intValue ?? 0, 0), 2)]
        join = [CGLineJoin.miter, .round, .bevel][min(max((o["join"] as? NSNumber)?.intValue ?? 0, 0), 2)]
        miter = num(o["miter"], 4)
        dash = (o["dash"] as? [NSNumber])?.map { CGFloat($0.doubleValue) }
        phase = num(o["phase"], 0)
        if let m = (o["m"] as? [NSNumber])?.map({ CGFloat($0.doubleValue) }), m.count == 6 {
            matrix = CGAffineTransform(a: m[0], b: m[1], c: m[2], d: m[3], tx: m[4], ty: m[5])
        }
        x = num(o["x"], 0)
        y = num(o["y"], 0)
        size = num(o["size"], 16)
        weight = (o["weight"] as? NSNumber)?.intValue ?? 400
        anchor = (o["anchor"] as? NSNumber)?.intValue ?? 0
        family = o["family"] as? String
        guard let d = (o["d"] as? [NSNumber])?.map({ CGFloat($0.doubleValue) }) else { return }
        var i = 0
        func p(_ k: Int) -> CGPoint { CGPoint(x: d[i + k], y: d[i + k + 1]) }
        while i < d.count {
            switch Int(d[i]) {
            case 0 where i + 2 < d.count: path.move(to: p(1)); i += 3
            case 1 where i + 2 < d.count: path.addLine(to: p(1)); i += 3
            case 2 where i + 6 < d.count: path.addCurve(to: p(5), control1: p(1), control2: p(3)); i += 7
            case 3 where i + 4 < d.count: path.addQuadCurve(to: p(3), control: p(1)); i += 5
            case 4: path.closeSubpath(); i += 1
            default: i = d.count
            }
        }
    }

    var font: UIFont {
        let w: UIFont.Weight
        switch weight {
        case ..<150: w = .ultraLight
        case ..<250: w = .thin
        case ..<350: w = .light
        case ..<450: w = .regular
        case ..<550: w = .medium
        case ..<650: w = .semibold
        case ..<750: w = .bold
        case ..<850: w = .heavy
        default: w = .black
        }
        if let family = family, let f = UIFont(name: family, size: size) { return f }
        return UIFont.systemFont(ofSize: size, weight: w)
    }

    func draw(_ c: CGContext) {
        c.saveGState()
        defer { c.restoreGState() }
        if let m = matrix { c.concatenate(m) }
        if let text = text {
            let f = font
            let s = text as NSString
            let attrs: [NSAttributedString.Key: Any] = [.font: f, .foregroundColor: svgColor(fill)]
            let w = s.size(withAttributes: attrs).width
            let left = anchor == 1 ? x - w / 2 : anchor == 2 ? x - w : x
            // `y` is the baseline, as in SVG; NSString draws from the top of the line.
            s.draw(at: CGPoint(x: left, y: y - f.ascender), withAttributes: attrs)
            return
        }
        if fill != 0 {
            c.addPath(path)
            c.setFillColor(svgColor(fill).cgColor)
            c.fillPath(using: evenOdd ? .evenOdd : .winding)
        }
        if stroke != 0 {
            c.addPath(path)
            c.setStrokeColor(svgColor(stroke).cgColor)
            c.setLineWidth(width)
            c.setLineCap(cap)
            c.setLineJoin(join)
            c.setMiterLimit(miter)
            if let dash = dash { c.setLineDash(phase: phase, lengths: dash) }
            c.strokePath()
        }
    }
}

final class PxSvgView: PxNativeView {
    let canvas = PxSvgCanvasView()
    var view: UIView { canvas }

    func update(_ props: [String: Any], _ removed: [String]) {
        if let ops = props["ops"] as? [[String: Any]] { canvas.ops = ops.map(SvgOp.init) }
        if let vb = (props["box"] as? [NSNumber])?.map({ CGFloat($0.doubleValue) }), vb.count == 4 { canvas.viewBox = vb }
        if let a = props["align"] as? String { canvas.align = a }
        if let s = props["slice"] as? NSNumber { canvas.slice = s.boolValue }
        for key in removed {
            switch key {
            case "ops": canvas.ops = []
            case "box": canvas.viewBox = nil
            case "align": canvas.align = "xMidYMid"
            case "slice": canvas.slice = false
            default: break
            }
        }
        canvas.setNeedsDisplay()
    }
}

/// Draws in user units: `viewBox` maps them onto the view as `preserveAspectRatio` says; without it one unit is 1 pt.
final class PxSvgCanvasView: UIView {
    var ops: [SvgOp] = []
    var viewBox: [CGFloat]?
    var align = "xMidYMid"
    var slice = false

    init() {
        super.init(frame: .zero)
        isOpaque = false
        backgroundColor = .clear
        contentMode = .redraw
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override func draw(_ rect: CGRect) {
        guard let c = UIGraphicsGetCurrentContext(), bounds.width > 0, bounds.height > 0 else { return }
        c.saveGState()
        defer { c.restoreGState() }
        c.clip(to: bounds)
        if let vb = viewBox, vb[2] > 0, vb[3] > 0 {
            var sx = bounds.width / vb[2], sy = bounds.height / vb[3]
            var tx: CGFloat = 0, ty: CGFloat = 0
            if align != "none" {
                let s = slice ? max(sx, sy) : min(sx, sy)
                (sx, sy) = (s, s)
                let fx: CGFloat = align.hasPrefix("xMid") ? 0.5 : align.hasPrefix("xMax") ? 1 : 0
                let fy: CGFloat = align.hasSuffix("YMid") ? 0.5 : align.hasSuffix("YMax") ? 1 : 0
                tx = (bounds.width - vb[2] * s) * fx
                ty = (bounds.height - vb[3] * s) * fy
            }
            c.translateBy(x: tx, y: ty)
            c.scaleBy(x: sx, y: sy)
            c.translateBy(x: -vb[0], y: -vb[1])
        }
        for op in ops { op.draw(c) }
    }
}
