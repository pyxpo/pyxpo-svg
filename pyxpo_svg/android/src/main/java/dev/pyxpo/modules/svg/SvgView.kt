package dev.pyxpo.modules.svg

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Typeface
import android.os.Build
import android.view.View
import dev.pyxpo.moduleapi.PxNativeView
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.max
import kotlin.math.min

/** One draw operation from Python. Path steps are absolute: 0 M x y, 1 L x y, 2 C x1 y1 x2 y2 x y, 3 Q x1 y1 x y, 4 Z. */
class SvgOp(o: JSONObject) {
    val text: String? = if (o.has("text")) o.getString("text") else null
    val path = Path()
    val fill = o.optLong("fill", 0L).toInt()
    val stroke = o.optLong("stroke", 0L).toInt()
    val width = o.optDouble("width", 1.0).toFloat()
    val cap = when (o.optInt("cap", 0)) { 1 -> Paint.Cap.ROUND; 2 -> Paint.Cap.SQUARE; else -> Paint.Cap.BUTT }
    val join = when (o.optInt("join", 0)) { 1 -> Paint.Join.ROUND; 2 -> Paint.Join.BEVEL; else -> Paint.Join.MITER }
    val miter = o.optDouble("miter", 4.0).toFloat()
    val dash: FloatArray? = o.optJSONArray("dash")?.let { a -> FloatArray(a.length()) { a.getDouble(it).toFloat() } }
    val phase = o.optDouble("phase", 0.0).toFloat()
    val matrix: Matrix? = o.optJSONArray("m")?.let { m ->
        Matrix().apply {
            setValues(floatArrayOf(m.f(0), m.f(2), m.f(4), m.f(1), m.f(3), m.f(5), 0f, 0f, 1f))
        }
    }
    val x = o.optDouble("x", 0.0).toFloat()
    val y = o.optDouble("y", 0.0).toFloat()
    val size = o.optDouble("size", 16.0).toFloat()
    val weight = o.optInt("weight", 400)
    val anchor = when (o.optInt("anchor", 0)) { 1 -> Paint.Align.CENTER; 2 -> Paint.Align.RIGHT; else -> Paint.Align.LEFT }
    val family: String? = if (o.has("family")) o.getString("family") else null

    init {
        if (o.optBoolean("evenodd", false)) path.fillType = Path.FillType.EVEN_ODD
        val d = o.optJSONArray("d")
        if (d != null) {
            var i = 0
            while (i < d.length()) {
                when (d.getInt(i)) {
                    0 -> { path.moveTo(d.f(i + 1), d.f(i + 2)); i += 3 }
                    1 -> { path.lineTo(d.f(i + 1), d.f(i + 2)); i += 3 }
                    2 -> { path.cubicTo(d.f(i + 1), d.f(i + 2), d.f(i + 3), d.f(i + 4), d.f(i + 5), d.f(i + 6)); i += 7 }
                    3 -> { path.quadTo(d.f(i + 1), d.f(i + 2), d.f(i + 3), d.f(i + 4)); i += 5 }
                    4 -> { path.close(); i += 1 }
                    else -> i = d.length()
                }
            }
        }
    }

    fun draw(c: Canvas, paint: Paint) {
        if (matrix != null) { c.save(); c.concat(matrix) }
        if (text != null) {
            paint.reset()
            paint.isAntiAlias = true
            paint.style = Paint.Style.FILL
            paint.color = fill
            paint.textSize = size
            paint.textAlign = anchor
            paint.typeface = typeface(family, weight)
            c.drawText(text, x, y, paint)
        } else {
            if (fill != 0) {
                paint.reset()
                paint.isAntiAlias = true
                paint.style = Paint.Style.FILL
                paint.color = fill
                c.drawPath(path, paint)
            }
            if (stroke != 0) {
                paint.reset()
                paint.isAntiAlias = true
                paint.style = Paint.Style.STROKE
                paint.color = stroke
                paint.strokeWidth = width
                paint.strokeCap = cap
                paint.strokeJoin = join
                paint.strokeMiter = miter
                if (dash != null) paint.pathEffect = DashPathEffect(dash, phase)
                c.drawPath(path, paint)
            }
        }
        if (matrix != null) c.restore()
    }

    companion object {
        private fun JSONArray.f(i: Int) = getDouble(i).toFloat()

        fun typeface(family: String?, weight: Int): Typeface {
            val base = if (family != null) Typeface.create(family, Typeface.NORMAL) else Typeface.DEFAULT
            return if (Build.VERSION.SDK_INT >= 28) Typeface.create(base, weight.coerceIn(1, 1000), false)
            else Typeface.create(base, if (weight >= 600) Typeface.BOLD else Typeface.NORMAL)
        }
    }
}

class SvgView(context: Context) : PxNativeView {
    val canvas = SvgCanvasView(context)
    override val view: View get() = canvas

    override fun update(props: JSONObject, removed: Set<String>) {
        if (props.has("ops")) {
            val a = props.getJSONArray("ops")
            canvas.ops = (0 until a.length()).map { SvgOp(a.getJSONObject(it)) }
        }
        if (props.has("box")) {
            val v = props.getJSONArray("box")
            canvas.viewBox = FloatArray(4) { v.getDouble(it).toFloat() }
        }
        if (props.has("align")) canvas.align = props.getString("align")
        if (props.has("slice")) canvas.slice = props.getBoolean("slice")
        if ("ops" in removed) canvas.ops = emptyList()
        if ("box" in removed) canvas.viewBox = null
        if ("align" in removed) canvas.align = "xMidYMid"
        if ("slice" in removed) canvas.slice = false
        canvas.invalidate()
    }
}

/** Draws in user units: `viewBox` maps them onto the view as `preserveAspectRatio` says; without it one unit is 1 dp. */
@SuppressLint("ViewConstructor")
class SvgCanvasView(context: Context) : View(context) {
    var ops: List<SvgOp> = emptyList()
    var viewBox: FloatArray? = null
    var align = "xMidYMid"
    var slice = false
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val density = resources.displayMetrics.density

    override fun onDraw(c: Canvas) {
        super.onDraw(c)
        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 0f || h <= 0f) return
        c.save()
        c.clipRect(0f, 0f, w, h)
        val vb = viewBox
        if (vb == null || vb[2] <= 0f || vb[3] <= 0f) {
            c.scale(density, density)
        } else {
            var sx = w / vb[2]
            var sy = h / vb[3]
            var tx = 0f
            var ty = 0f
            if (align != "none") {
                val s = if (slice) max(sx, sy) else min(sx, sy)
                sx = s; sy = s
                val fx = when { align.startsWith("xMid") -> 0.5f; align.startsWith("xMax") -> 1f; else -> 0f }
                val fy = when { align.endsWith("YMid") -> 0.5f; align.endsWith("YMax") -> 1f; else -> 0f }
                tx = (w - vb[2] * s) * fx
                ty = (h - vb[3] * s) * fy
            }
            c.translate(tx, ty)
            c.scale(sx, sy)
            c.translate(-vb[0], -vb[1])
        }
        for (op in ops) op.draw(c, paint)
        c.restore()
    }
}
