package com.jarvis.companion

import android.content.Context
import android.graphics.*
import android.util.AttributeSet
import android.view.View
import kotlin.math.*

/** Android counterpart of the desktop HudCanvas "orb" reactor core. */
class JarvisOrbView @JvmOverloads constructor(c: Context, a: AttributeSet?=null): View(c,a) {
    private val p=Paint(Paint.ANTI_ALIAS_FLAG)
    private var phase=0f
    private var amp=0f
    private var targetAmp=0f
    var state:String="CONNECTING"; set(v){field=v; invalidate()}
    private val tick=object:Runnable{ override fun run(){ phase=(phase+1.25f)%360f; amp+=(targetAmp-amp)*.28f; targetAmp*=.90f; invalidate(); postDelayed(this,33) } }
    init { setLayerType(LAYER_TYPE_SOFTWARE,null); post(tick) }
    fun audioLevel(v:Float){ targetAmp=max(targetAmp,v.coerceIn(0f,1f)) }
    private fun col(alpha:Int=255)=Color.argb(alpha,22,217,245)
    private fun accent(alpha:Int=255)=when(state){"SPEAKING"->Color.argb(alpha,255,138,76);"THINKING","PROCESSING","CONNECTING"->Color.argb(alpha,245,185,66);"LISTENING"->Color.argb(alpha,48,217,154);else->col(alpha)}
    override fun onDraw(c:Canvas){ super.onDraw(c); val w=width.toFloat(); val h=height.toFloat(); val cx=w/2; val cy=h*.46f; val r=min(w,h)*.44f
        c.drawColor(Color.rgb(5,8,14)); p.style=Paint.Style.STROKE
        // full-canvas crosshair and corner framing, matching desktop reactor geometry
        p.strokeWidth=1f; p.color=col(38); c.drawLine(0f,cy,cx-r*.62f,cy,p); c.drawLine(cx+r*.62f,cy,w,cy,p); c.drawLine(cx,0f,cx,cy-r*.62f,p); c.drawLine(cx,cy+r*.62f,cx,h,p)
        val m=min(w,h)*.035f; val arm=min(w,h)*.055f; p.color=col(105)
        for(sx in intArrayOf(-1,1)) for(sy in intArrayOf(-1,1)){val x=cx+sx*(w/2-m);val y=cy+sy*(h/2-m);c.drawLine(x,y,x-sx*arm,y,p);c.drawLine(x,y,x,y-sy*arm,p)}
        // atmosphere
        p.style=Paint.Style.FILL; val g=RadialGradient(cx,cy,r*.70f, intArrayOf(col((80+amp*80).toInt()),col(28),Color.TRANSPARENT), floatArrayOf(0f,.55f,1f),Shader.TileMode.CLAMP);p.shader=g;c.drawCircle(cx,cy,r*.70f,p);p.shader=null;p.style=Paint.Style.STROKE
        for(k in arrayOf(1f to 86,.93f to 38)){p.color=col(k.second);p.strokeWidth=1.2f;c.drawCircle(cx,cy,r*k.first,p)}
        // 72 graduations
        for(i in 0 until 72){val an=Math.toRadians((i*5).toDouble()); val major=i%3==0; val r1=r*(if(major).885f else .945f); val r2=r*.985f;p.color=col(if(major)105 else 42);p.strokeWidth=if(major)1.5f else 1f;c.drawLine(cx+cos(an).toFloat()*r1,cy+sin(an).toFloat()*r1,cx+cos(an).toFloat()*r2,cy+sin(an).toFloat()*r2,p)}
        // rotating sparse arcs
        val specs=arrayOf(floatArrayOf(.955f,118f,2f,1f),floatArrayOf(.845f,82f,3f,-1f),floatArrayOf(.760f,150f,1f,1f),floatArrayOf(.660f,64f,4f,-1f),floatArrayOf(.545f,128f,2f,1f)); val rate=if(state=="THINKING"||state=="PROCESSING")2.9f else if(state=="SPEAKING")2.2f else 1f
        specs.forEachIndexed{k,s->val rr=r*s[0];val rect=RectF(cx-rr,cy-rr,cx+rr,cy+rr);p.color=if(k%2==0)accent(150) else col(80);p.strokeWidth=if(k%2==0)2f else 1.2f;val base=phase*rate*(.35f+k*.18f)*s[3];for(j in 0 until s[2].toInt())c.drawArc(rect,base+j*(360f/s[2]),s[1],false,p)}
        // live audio ring
        val ring=r*.415f; p.color=accent((75+amp*150).toInt());p.strokeWidth=1.7f
        for(i in 0 until 60){val an=Math.toRadians((i*6).toDouble());val wob=.5f+.5f*sin(phase*.04f+i*.42f);val hh=r*(.018f+amp*.20f*wob);c.drawLine(cx+cos(an).toFloat()*ring,cy+sin(an).toFloat()*ring,cx+cos(an).toFloat()*(ring+hh),cy+sin(an).toFloat()*(ring+hh),p)}
        val inner=r*.355f;p.color=accent((80+amp*110).toInt());p.strokeWidth=1.7f;c.drawCircle(cx,cy,inner,p)
        p.style=Paint.Style.FILL;p.color=Color.argb(235,221,251,255);p.textAlign=Paint.Align.CENTER;p.typeface=Typeface.create("sans-serif",Typeface.BOLD);p.textSize=max(13f,r*.105f);c.drawText("JARVIS",cx,cy-(p.ascent()+p.descent())/2,p)
        // Hermes-style 32-bar voice waveform under the reactor, driven by the same live amplitude.
        val bars=32; val waveW=w*.72f; val left=(w-waveW)/2f; val base=h*.965f; val gap=waveW/bars
        p.strokeCap=Paint.Cap.ROUND; p.strokeWidth=max(1f,gap-2f); p.color=if(amp>.05f) col(235) else Color.argb(165,8,122,140)
        for(i in 0 until bars){ val middle=(bars-1)/2f; val envelope=1f-abs(i-middle)/middle; val shimmer=.55f+.45f*sin(phase*.035f+i*.7f); val hh=2f+amp*h*.065f*envelope*shimmer; val x=left+i*gap+gap/2f; c.drawLine(x,base,x,base-hh,p) }
        p.strokeCap=Paint.Cap.BUTT
    }
    override fun onDetachedFromWindow(){ removeCallbacks(tick); super.onDetachedFromWindow() }
}
