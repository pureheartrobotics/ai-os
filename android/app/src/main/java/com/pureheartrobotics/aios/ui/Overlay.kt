package com.pureheartrobotics.aios.ui

import android.accessibilityservice.AccessibilityService
import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.math.abs

/**
 * Floating bubble drawn as an accessibility overlay, so it needs no "draw over other apps" permission.
 * Tap to talk or to stop; drag to move. The status pill next to it shows what the agent is doing.
 */
class Overlay(private val service: AccessibilityService, private val onTap: () -> Unit) {
    private val wm = service.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val root = LinearLayout(service).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }
    private val bubble = TextView(service).apply {
        text = "AI"
        setTextColor(Color.WHITE)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
        gravity = Gravity.CENTER
        background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(IDLE_COLOR)
        }
        elevation = dp(4).toFloat()
    }
    private val pill = TextView(service).apply {
        setTextColor(Color.WHITE)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        setPadding(dp(12), dp(6), dp(12), dp(6))
        maxWidth = service.resources.displayMetrics.widthPixels * 2 / 3
        maxLines = 2
        background = GradientDrawable().apply {
            cornerRadius = dp(16).toFloat()
            setColor(0xCC202124.toInt())
        }
        visibility = View.GONE
    }
    private val params = WindowManager.LayoutParams(
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT,
    ).apply {
        gravity = Gravity.TOP or Gravity.START
        x = 0
        y = service.resources.displayMetrics.heightPixels / 3
    }
    private var attached = false

    init {
        root.addView(bubble, LinearLayout.LayoutParams(dp(48), dp(48)))
        root.addView(pill, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            marginStart = dp(8)
        })
        setUpDrag()
    }

    fun attach() {
        if (attached) return
        wm.addView(root, params)
        attached = true
    }

    fun detach() {
        if (!attached) return
        wm.removeView(root)
        attached = false
    }

    fun status(text: String) {
        pill.text = text
        pill.visibility = View.VISIBLE
        (bubble.background as GradientDrawable).setColor(BUSY_COLOR)
        bubble.text = "■"
    }

    fun idle() {
        (bubble.background as GradientDrawable).setColor(IDLE_COLOR)
        bubble.text = "AI"
        pill.postDelayed({ if (bubble.text == "AI") pill.visibility = View.GONE }, 2500)
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun setUpDrag() {
        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0
        var moved = false
        bubble.setOnTouchListener { _, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX; downY = e.rawY
                    startX = params.x; startY = params.y
                    moved = false
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (abs(dx) > dp(6) || abs(dy) > dp(6)) moved = true
                    if (moved && attached) {
                        params.x = startX + dx.toInt()
                        params.y = startY + dy.toInt()
                        wm.updateViewLayout(root, params)
                    }
                }
                MotionEvent.ACTION_UP -> if (!moved) onTap()
            }
            true
        }
    }

    private fun dp(v: Int): Int = (v * service.resources.displayMetrics.density).toInt()

    companion object {
        private const val IDLE_COLOR = 0xFF1E5EFF.toInt()
        private const val BUSY_COLOR = 0xFFE5484D.toInt()
    }
}
