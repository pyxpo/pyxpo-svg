package dev.pyxpo.modules.svg

import dev.pyxpo.moduleapi.PxModule
import dev.pyxpo.moduleapi.PxModuleContext
import dev.pyxpo.moduleapi.PxNativeView
import dev.pyxpo.moduleapi.PxReply
import org.json.JSONArray

/** pyxpo-svg on Android: a `Canvas` view (`PxSvg`) that draws the operations Python flattened from the SVG tree. */
class SvgModule : PxModule() {
    override val name = "Svg"
    override val viewTypes = setOf("PxSvg")

    override fun makeView(ctx: PxModuleContext, type: String, emit: (name: String, value: Any?) -> Unit): PxNativeView =
        SvgView(ctx.activity)

    override fun call(ctx: PxModuleContext, method: String, args: JSONArray, reply: PxReply) {
        reply(null, "Svg has no method $method")
    }
}
