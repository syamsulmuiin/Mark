package com.jarvis.companion

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.os.Bundle
import android.graphics.Path
import android.graphics.Rect
import android.accessibilityservice.GestureDescription
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

/**
 * User-enabled Android UI bridge. Android itself displays the Accessibility
 * consent screen; the companion cannot silently enable this service.
 */
class JarvisAccessibilityService : AccessibilityService() {
    companion object {
        @Volatile var instance: JarvisAccessibilityService? = null
        fun enabled(): Boolean = instance != null
    }

    override fun onServiceConnected() {
        instance = this
        serviceInfo = serviceInfo.apply {
            flags = flags or AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                    AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
        }
    }

    override fun onDestroy() { instance = null; super.onDestroy() }
    override fun onInterrupt() {}
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}

    fun global(action: String): String {
        val a = when (action.lowercase()) {
            "back" -> GLOBAL_ACTION_BACK
            "home" -> GLOBAL_ACTION_HOME
            "recents" -> GLOBAL_ACTION_RECENTS
            "notifications" -> GLOBAL_ACTION_NOTIFICATIONS
            "quick_settings" -> GLOBAL_ACTION_QUICK_SETTINGS
            "lock", "lock_screen" -> if (android.os.Build.VERSION.SDK_INT >= 28) GLOBAL_ACTION_LOCK_SCREEN else error("Lock screen requires Android 9 or newer")
            else -> error("Unsupported global action: $action")
        }
        if (!performGlobalAction(a)) error("Android rejected global action: $action")
        return "performed $action"
    }

    fun click(text: String, viewId: String = ""): String {
        // LLM/tool JSON can occasionally preserve JSON's optional escaped slash
        // (e.g. com.whatsapp:id\/button) as a literal backslash. Android view
        // resource names never contain that escape, so canonicalise before match.
        val canonicalViewId = viewId.replace("\\/", "/").trim()
        repeat(3) { attempt ->
            val root = rootInActiveWindow ?: if (attempt < 2) { Thread.sleep(250); return@repeat } else error("No active Android window")
            val all = mutableListOf<AccessibilityNodeInfo>()
            collectNodes(root, all)
            val wanted = normalize(text)
            val candidates = all.filter { n ->
                (canonicalViewId.isNotBlank() && n.viewIdResourceName == canonicalViewId) ||
                (wanted.isNotBlank() && (normalize(n.text?.toString().orEmpty()) == wanted || normalize(n.contentDescription?.toString().orEmpty()) == wanted))
            } + all.filter { n ->
                wanted.isNotBlank() && (normalize(n.text?.toString().orEmpty()).contains(wanted) || normalize(n.contentDescription?.toString().orEmpty()).contains(wanted))
            }
            for (target in candidates.distinct()) {
                var n: AccessibilityNodeInfo? = target
                while (n != null) {
                    if (n.isClickable && n.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return "clicked"
                    n = n.parent
                }
                // Some modern apps expose a meaningful accessibility node but mark
                // neither it nor its parents clickable. Accessibility can still tap
                // the visible node safely at its screen bounds.
                val bounds = Rect()
                target.getBoundsInScreen(bounds)
                if (!bounds.isEmpty && tap(bounds.centerX().toFloat(), bounds.centerY().toFloat())) return "clicked by bounds"
            }
            if (attempt < 2) Thread.sleep(250)
        }
        error("UI element not found or not clickable")
    }

    fun setText(text: String, targetText: String = "", viewId: String = ""): String {
        val root = rootInActiveWindow ?: error("No active Android window")
        val candidates = mutableListOf<AccessibilityNodeInfo>()
        if (viewId.isNotBlank()) candidates += root.findAccessibilityNodeInfosByViewId(viewId)
        if (targetText.isNotBlank()) candidates += root.findAccessibilityNodeInfosByText(targetText)
        if (candidates.isEmpty()) collectEditable(root, candidates)
        val node = candidates.firstOrNull { it.isEditable } ?: error("Editable field not found")
        if (isCredentialField(node)) error("AUTHENTICATION_REQUIRED: credential input is blocked; waiting for user instruction")
        val b = Bundle(); b.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        if (!node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, b)) error("Android rejected text input")
        return "text entered"
    }

    fun scroll(direction: String): String {
        val root = rootInActiveWindow ?: error("No active Android window")
        val scrollable = findFirst(root) { it.isScrollable } ?: error("No scrollable element found")
        val action = when (direction.lowercase()) {
            "up", "backward" -> AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
            "down", "forward" -> AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
            else -> error("Direction must be up/down/forward/backward")
        }
        if (!scrollable.performAction(action)) error("Android rejected scroll")
        return "scrolled $direction"
    }

    fun inspect(maxNodes: Int = 120): JSONObject {
        val root = rootInActiveWindow ?: error("No active Android window")
        val arr = JSONArray(); var count = 0
        fun walk(n: AccessibilityNodeInfo, depth: Int) {
            if (count >= maxNodes) return
            val text = n.text?.toString().orEmpty(); val desc = n.contentDescription?.toString().orEmpty()
            val id = n.viewIdResourceName.orEmpty()
            if (text.isNotBlank() || desc.isNotBlank() || id.isNotBlank() || n.isClickable || n.isEditable) {
                arr.put(JSONObject().put("text", text).put("description", desc).put("view_id", id)
                    .put("class", n.className?.toString().orEmpty()).put("clickable", n.isClickable)
                    .put("editable", n.isEditable).put("credential", isCredentialField(n))
                    .put("scrollable", n.isScrollable).put("depth", depth).apply {
                        val b = Rect(); n.getBoundsInScreen(b)
                        put("bounds", JSONObject().put("left", b.left).put("top", b.top).put("right", b.right).put("bottom", b.bottom))
                    })
                count++
            }
            for (i in 0 until n.childCount) n.getChild(i)?.let { walk(it, depth + 1) }
        }
        walk(root, 0)
        return JSONObject().put("package", root.packageName?.toString().orEmpty()).put("nodes", arr)
    }


    private fun isCredentialField(n: AccessibilityNodeInfo): Boolean {
        if (n.isPassword) return true
        val hints = listOf(
            n.text?.toString().orEmpty(),
            n.contentDescription?.toString().orEmpty(),
            n.viewIdResourceName.orEmpty(),
            n.hintText?.toString().orEmpty()
        ).joinToString(" ").lowercase()
        return Regex("(^|[^a-z])(password|passwd|passcode|pin|credential|kata\\s*sandi|sandi)([^a-z]|$)").containsMatchIn(hints)
    }

    private fun tap(x: Float, y: Float): Boolean {
        if (android.os.Build.VERSION.SDK_INT < 24) return false
        val path = Path().apply { moveTo(x, y) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 80))
            .build()
        return dispatchGesture(gesture, null, null)
    }

    private fun normalize(s: String) = s.lowercase().replace(Regex("""[^\p{L}\p{N}]+"""), "").trim()
    private fun collectNodes(n: AccessibilityNodeInfo, out: MutableList<AccessibilityNodeInfo>) {
        out += n
        for (i in 0 until n.childCount) n.getChild(i)?.let { collectNodes(it, out) }
    }

    private fun collectEditable(n: AccessibilityNodeInfo, out: MutableList<AccessibilityNodeInfo>) {
        if (n.isEditable) out += n
        for (i in 0 until n.childCount) n.getChild(i)?.let { collectEditable(it, out) }
    }
    private fun findFirst(n: AccessibilityNodeInfo, test: (AccessibilityNodeInfo)->Boolean): AccessibilityNodeInfo? {
        if (test(n)) return n
        for (i in 0 until n.childCount) n.getChild(i)?.let { findFirst(it, test)?.let { found -> return found } }
        return null
    }
}
