package com.jarvis.companion

import android.Manifest
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.content.pm.ApplicationInfo
import android.media.*
import android.hardware.camera2.*
import android.media.ImageReader
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.util.Base64 as AndroidBase64
import android.view.Surface
import android.net.Uri
import android.os.*
import android.provider.Settings
import android.provider.MediaStore
import android.view.View
import android.text.Editable
import android.text.TextWatcher
import android.text.TextUtils
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.StyleSpan
import android.graphics.Typeface
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import okio.ByteString
import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters
import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import org.json.JSONObject
import org.json.JSONArray
import androidx.core.content.FileProvider
import java.security.SecureRandom
import java.security.MessageDigest
import java.io.File
import java.security.cert.X509Certificate
import java.util.*
import java.util.concurrent.TimeUnit
import java.util.concurrent.CountDownLatch
import java.util.concurrent.LinkedBlockingQueue
import kotlin.math.sqrt
import javax.net.ssl.*

class MainActivity : AppCompatActivity() {
    private lateinit var status: TextView
    private lateinit var pairStatus: TextView
    private lateinit var pairCode: EditText
    private lateinit var pairProgress: View
    private lateinit var pairProgressText: TextView
    private lateinit var pairPanel: View
    private lateinit var voicePanel: View
    private lateinit var orb: JarvisOrbView
    private lateinit var transcript: TextView
    private lateinit var transcriptScroll: ScrollView
    private lateinit var endConversation: ImageButton
    private lateinit var startConversation: Button
    private lateinit var phoneControl: ImageButton
    private lateinit var attachmentBadge: TextView
    private var deferredPickerRequest: JSONObject? = null
    private var ws: WebSocket? = null
    private val attachmentItems = linkedMapOf<String,JSONObject>()
    private val sentAttachmentItems = linkedMapOf<String,JSONObject>()
    private var attachmentTab = "received"
    private var attachmentSubtitle: TextView? = null
    private var attachmentReceivedTab: TextView? = null
    private var attachmentSentTab: TextView? = null
    private var pendingAttachment: Pair<String,String>? = null
    private var pendingSaveUri: Uri? = null
    private var pendingSaveInfo: JSONObject? = null
    private var attachmentDialog: AlertDialog? = null
    private var companionDialog: AlertDialog? = null
    private var companionBody: LinearLayout? = null
    private var companionTitle: TextView? = null
    private var companionSubtitle: TextView? = null
    private var companionBack: ImageButton? = null
    private var sourcePickerLatch: CountDownLatch? = null
    private var pickedSourceUri: Uri? = null
    private var pendingPickerRequestId: String? = null
    private var pendingCameraRequest: Pair<WebSocket, JSONObject>? = null
    @Volatile private var assistantTurnComplete = false
    @Volatile private var intentionalVoiceEnd = false
    private var recorder: AudioRecord? = null
    private var echoCanceler: AcousticEchoCanceler? = null
    private var noiseSuppressor: NoiseSuppressor? = null
    private var player: AudioTrack? = null
    private val playbackQueue = LinkedBlockingQueue<ByteArray>(512)
    // Never block OkHttp's WebSocket callback thread on AudioTrack backpressure.
    // A blocked callback stops ping/close processing and can disconnect the device.
    private val audioIngressQueue = LinkedBlockingQueue<ByteArray>(2048)
    @Volatile private var playbackRunning = false
    private var playbackThread: Thread? = null
    private var audioIngressThread: Thread? = null
    @Volatile private var micRunning = false
    @Volatile private var voiceState = "DISCONNECTED"
    @Volatile private var reconnectScheduled = false
    @Volatile private var reconnectDelayMs = 1500L
    private val heartbeatHandler = Handler(Looper.getMainLooper())
    private val heartbeatRunnable = object : Runnable {
        override fun run() {
            val current = ws
            if (!intentionalVoiceEnd && current != null) {
                current.send(JSONObject().put("type", "jarvis.heartbeat").put("ts", System.currentTimeMillis()).toString())
                heartbeatHandler.postDelayed(this, 15000L)
            }
        }
    }
    private val thinkingWatchdog = Runnable {
        if (voiceState == "THINKING" && !intentionalVoiceEnd) {
            ui("Respons terlalu lama, menyambungkan ulang…")
            val current = ws
            ws = null
            heartbeatHandler.removeCallbacks(heartbeatRunnable)
            current?.close(1012, "thinking watchdog")
            scheduleReconnect()
        }
    }
    @Volatile private var lastInterruptAt = 0L
    private var voicedFrames = 0
    private val interruptLevelThreshold = 0.22f
    private val interruptFrameCount = 14
    private val interruptCooldownMs = 1500L
    private val prefs by lazy { getSharedPreferences("jarvis-device", MODE_PRIVATE) }
    private val client by lazy { lanClient() }
    private val serverBase: String get() {
        val configured = prefs.getString("server", null)?.trimEnd('/')
        // Migrate APKs built with the retired dashboard origin. Keeping this
        // fallback prevents a stale persisted endpoint from producing an
        // Android UnknownHost/connection failure after the staging route moved.
        return if (configured.isNullOrBlank() || configured == "https://auth.kasirdigital.web.id") {
            BuildConfig.ASSISTANT_PUBLIC_URL.trimEnd('/')
        } else configured
    }

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        setContentView(R.layout.activity_main)
        status=findViewById(R.id.status); pairStatus=findViewById(R.id.pairStatus); pairCode=findViewById(R.id.pairCode)
        pairProgress=findViewById(R.id.pairProgress); pairProgressText=findViewById(R.id.pairProgressText)
        pairPanel=findViewById(R.id.pairPanel); voicePanel=findViewById(R.id.voicePanel)
        orb=findViewById(R.id.orb); transcript=findViewById(R.id.transcript); transcriptScroll=findViewById(R.id.transcriptScroll); endConversation=findViewById(R.id.endConversation)
        startConversation=findViewById(R.id.startConversation); phoneControl=findViewById(R.id.phoneControl); attachmentBadge=findViewById(R.id.attachmentBadge)
        findViewById<Button>(R.id.requestPairing).setOnClickListener { requestPairing() }
        findViewById<Button>(R.id.pair).setOnClickListener { pairWithCode(pairCode.text.toString()) }
        findViewById<ImageButton>(R.id.pairMenu).setOnClickListener { showPhoneControlMenu(it) }
        pairCode.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                findViewById<Button>(R.id.pair).isEnabled = s?.length == 8
            }
            override fun afterTextChanged(s: Editable?) = Unit
        })
        findViewById<Button>(R.id.pair).isEnabled = pairCode.text.length == 8
        findViewById<Button>(R.id.requestPairing).text = if (prefs.contains("pending_pairing_id")) "Minta kode baru" else "Minta kode pairing"
        endConversation.setOnClickListener { endVoice() }
        startConversation.setOnClickListener { connect() }
        phoneControl.setOnClickListener { showPhoneControlMenu(it) }
        if (Build.VERSION.SDK_INT>=33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 7)
        intent?.data?.getQueryParameter("code")?.let { pairCode.setText(it.uppercase()); pairWithCode(it) }
        if (intent?.data==null && prefs.getBoolean("paired", false)) { showVoice(); connect() }
    }

    private fun showVoice(){ runOnUiThread { pairPanel.visibility=View.GONE; voicePanel.visibility=View.VISIBLE; status.text=getString(R.string.connecting); orb.state="CONNECTING"; endConversation.visibility=View.VISIBLE; startConversation.visibility=View.GONE } }

    private fun showPhoneControlMenu(anchor: View) {
        companionDialog?.takeIf { it.isShowing }?.let { renderCompanionPage("menu"); return }
        val panel=LinearLayout(this).apply {
            orientation=LinearLayout.VERTICAL; setPadding(dp(20),dp(16),dp(20),dp(20))
            setBackgroundResource(R.drawable.bg_card)
        }
        val header=LinearLayout(this).apply { orientation=LinearLayout.HORIZONTAL; gravity=android.view.Gravity.CENTER_VERTICAL }
        companionBack=ImageButton(this).apply {
            setImageResource(R.drawable.ic_arrow_back); setColorFilter(android.graphics.Color.rgb(165,232,235))
            setBackgroundColor(android.graphics.Color.TRANSPARENT); setPadding(dp(10),dp(10),dp(10),dp(10))
            contentDescription="Back"; visibility=View.GONE
            setOnClickListener { renderCompanionPage(if(companionTitle?.text?.toString()=="Attachment actions") "attachments" else "menu") }
        }
        header.addView(companionBack,LinearLayout.LayoutParams(dp(44),dp(44)))
        companionTitle=TextView(this).apply {
            textSize=18f; setTypeface(typeface,android.graphics.Typeface.BOLD)
            setTextColor(android.graphics.Color.rgb(247,248,248))
        }
        header.addView(companionTitle,LinearLayout.LayoutParams(0,LinearLayout.LayoutParams.WRAP_CONTENT,1f))
        val close=ImageButton(this).apply {
            setImageResource(R.drawable.ic_close); setColorFilter(android.graphics.Color.rgb(145,153,173))
            setBackgroundColor(android.graphics.Color.TRANSPARENT); setPadding(dp(11),dp(11),dp(11),dp(11))
            contentDescription="Close"; setOnClickListener { companionDialog?.dismiss() }
        }
        header.addView(close,LinearLayout.LayoutParams(dp(44),dp(44)))
        panel.addView(header)
        companionSubtitle=TextView(this).apply {
            textSize=12f; setTextColor(android.graphics.Color.rgb(145,153,173))
            setPadding(0,dp(3),0,dp(14))
        }
        panel.addView(companionSubtitle)
        companionBody=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
        panel.addView(companionBody)
        val dialog=AlertDialog.Builder(this).setView(panel).create()
        companionDialog=dialog; attachmentDialog=dialog; panel.tag=dialog
        dialog.setOnDismissListener {
            if(companionDialog===dialog){
                companionDialog=null; attachmentDialog=null; companionBody=null
                companionTitle=null; companionSubtitle=null; companionBack=null
                attachmentSubtitle=null
                attachmentReceivedTab=null; attachmentSentTab=null
            }
        }
        dialog.show()
        dialog.window?.setBackgroundDrawableResource(android.R.color.transparent)
        dialog.window?.setLayout(minOf(resources.displayMetrics.widthPixels-dp(32),dp(480)),android.view.WindowManager.LayoutParams.WRAP_CONTENT)
        dialog.window?.setDimAmount(0.62f)
        renderCompanionPage("menu")
    }

    private fun renderCompanionPage(page:String) {
        val body=companionBody?:return
        body.removeAllViews()
        companionBack?.visibility=if(page=="menu")View.GONE else View.VISIBLE
        companionTitle?.text=when(page){ "attachments"->"Attachments"; "device"->"Device Control"; "actions"->"Attachment actions"; else->"Companion" }
        companionSubtitle?.text=when(page){ "attachments"->"Files received and sent from this device"; "device"->"Companion permissions"; "actions"->"Choose what to do with this file"; else->"Files and device access" }
        when(page){
            "attachments"->renderAttachmentContent(body)
            "device"->renderDeviceControlContent(body)
            else->{
                body.addView(menuActionRow(R.drawable.ic_attachment,"Attachments","Received files and sent history") { renderCompanionPage("attachments") })
                body.addView(View(this).apply { setBackgroundColor(android.graphics.Color.rgb(37,43,58)) },LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,dp(1)))
                body.addView(menuActionRow(R.drawable.ic_accessibility_control,"Device Control",
                    if(JarvisAccessibilityService.instance!=null) "Enabled · Accessibility available" else "Disabled · Permission required") { renderCompanionPage("device") })
            }
        }
        body.requestLayout()
        companionDialog?.window?.setLayout(minOf(resources.displayMetrics.widthPixels-dp(32),dp(480)),android.view.WindowManager.LayoutParams.WRAP_CONTENT)
    }

    private fun menuActionRow(icon:Int,title:String,subtitle:String,onClick:(AlertDialog)->Unit):View {
        val row=LinearLayout(this).apply {
            orientation=LinearLayout.HORIZONTAL; gravity=android.view.Gravity.CENTER_VERTICAL
            setPadding(dp(8),dp(12),dp(8),dp(12)); isClickable=true; isFocusable=true
        }
        val image=ImageView(this).apply {
            setImageResource(icon); setColorFilter(android.graphics.Color.rgb(165,232,235)); setPadding(dp(11),dp(11),dp(11),dp(11)); setBackgroundResource(R.drawable.bg_icon_action)
        }
        row.addView(image,LinearLayout.LayoutParams(dp(46),dp(46)))
        val copy=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(dp(14),0,0,0) }
        copy.addView(TextView(this).apply { text=title; textSize=15f; setTextColor(android.graphics.Color.rgb(247,248,248)); setTypeface(typeface,android.graphics.Typeface.BOLD) })
        copy.addView(TextView(this).apply { text=subtitle; textSize=12f; setTextColor(android.graphics.Color.rgb(145,153,173)); setPadding(0,dp(3),0,0) })
        row.addView(copy,LinearLayout.LayoutParams(0,LinearLayout.LayoutParams.WRAP_CONTENT,1f))
        row.setOnClickListener { (panelDialog(row) ?: return@setOnClickListener).let(onClick) }
        return row
    }

    private fun panelDialog(view:View):AlertDialog? {
        var current:View?=view
        while(current!=null){
            val tag=current.tag
            if(tag is AlertDialog)return tag
            current=current.parent as? View
        }
        return null
    }

    private fun renderDeviceControlContent(body:LinearLayout) {
        val enabled=JarvisAccessibilityService.instance!=null
        body.addView(TextView(this).apply {
            text=if(enabled) "●  Control available" else "○  Control requires permission"
            textSize=14f; setTextColor(if(enabled) android.graphics.Color.rgb(115,220,205) else android.graphics.Color.rgb(190,196,210))
            setPadding(dp(8),dp(8),dp(8),dp(10))
        })
        body.addView(TextView(this).apply {
            text=getString(R.string.device_control_description)
            textSize=13f; setTextColor(android.graphics.Color.rgb(145,153,173))
            setPadding(dp(8),0,dp(8),dp(12))
        })
        body.addView(menuActionRow(R.drawable.ic_accessibility_control,"Open Accessibility Settings","Manage device control permission") { dialog ->
            dialog.dismiss(); startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        })
    }

    private fun showPair(message:String){ stopMic(); runOnUiThread { voicePanel.visibility=View.GONE; pairPanel.visibility=View.VISIBLE; pairProgress.visibility=View.GONE; pairStatus.text=message; pairStatus.visibility=if(message.isBlank()) View.GONE else View.VISIBLE } }
    private fun pairLoading(message:String){ runOnUiThread { pairProgressText.text=message; pairProgress.visibility=View.VISIBLE; pairStatus.visibility=View.GONE; findViewById<Button>(R.id.pair).isEnabled=false; findViewById<Button>(R.id.requestPairing).isEnabled=false } }

    private fun identity(): Triple<String,ByteArray,ByteArray> {
        var id=prefs.getString("device_id",null); var priv=prefs.getString("private",null)
        if(id==null||priv==null){ val k=Ed25519PrivateKeyParameters(SecureRandom()); id=UUID.randomUUID().toString(); priv=b64(k.encoded); prefs.edit().putString("device_id",id).putString("private",priv).apply() }
        val stableId=id ?: error("Device identity is unavailable")
        val stablePriv=priv ?: error("Device private key is unavailable")
        val p=Ed25519PrivateKeyParameters(unb64(stablePriv),0)
        return Triple(stableId,p.encoded,p.generatePublicKey().encoded)
    }
    private fun sign(data:ByteArray):String { val p=Ed25519PrivateKeyParameters(identity().second,0); val s=Ed25519Signer(); s.init(true,p); s.update(data,0,data.size); return b64(s.generateSignature()) }
    private fun verify(pub:String,data:ByteArray,sig:String):Boolean = try { val v=Ed25519Signer(); v.init(false,Ed25519PublicKeyParameters(unb64(pub),0)); v.update(data,0,data.size); v.verifySignature(unb64(sig)) } catch(_:Exception){false}

    private fun requestPairing() {
        pairLoading("Meminta permintaan pairing…")
        val ident = identity()
        val peer = JSONObject().put("device_id", ident.first).put("name", Build.MODEL).put("public_key", b64(ident.third))
        val request = Request.Builder()
            .url("${serverBase}/api/pairing/request")
            .post(peer.toString().let { JSONObject().put("peer", peer).toString().toRequestBody("application/json".toMediaType()) })
            .build()
        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(c: Call, e: java.io.IOException) = pairUi("Permintaan pairing gagal: ${e.message}")
            override fun onResponse(c: Call, r: Response) { r.use {
                val body = it.body?.string().orEmpty()
                if (!it.isSuccessful) { pairUi("Pairing tidak tersedia: HTTP ${it.code}"); return }
                try {
                    val o = JSONObject(body)
                    prefs.edit()
                        .putString("server", serverBase)
                        .putString("pending_pairing_id", o.getString("pairing_id"))
                        .putString("pending_pairing_nonce", o.getString("nonce"))
                        .putString("server_key", o.getJSONObject("local").getString("public_key"))
                        .putString("server_id", o.getJSONObject("local").getString("device_id"))
                        .apply()
                    pairUi("Permintaan dibuat. Minta kode satu kali dari operator, lalu masukkan di bawah.")
                    runOnUiThread { findViewById<Button>(R.id.requestPairing).text = "Minta kode baru" }
                } catch (_: Exception) { pairUi("Respons pairing tidak valid") }
            }}
        })
    }

    private fun pairWithCode(rawCode: String) {
        val code = rawCode.trim().uppercase()
        val pairingId = prefs.getString("pending_pairing_id", null)
        val nonce = prefs.getString("pending_pairing_nonce", null)
        if (pairingId.isNullOrBlank() || nonce.isNullOrBlank()) {
            pairUi("Minta permintaan pairing terlebih dahulu.")
            return
        }
        if (!code.matches(Regex("[A-Z0-9]{8}"))) {
            pairStatus.text = "Kode pairing harus terdiri dari 8 karakter huruf/angka."
            pairStatus.visibility = View.VISIBLE
            return
        }
        pairLoading("Memverifikasi pairing…")
        val ident = identity()
        val signature = sign("$pairingId:$code:$nonce".toByteArray())
        val caps = org.json.JSONArray(listOf("jarvis.command", "notification", "vibration", "clipboard.write", "open_url", "browser.open", "browser.search", "app.launch", "app.close", "android.settings.open", "camera.capture", "file.upload", "file.receive", "attachment.inbox", "android.ui.inspect", "android.ui.click", "android.ui.text", "android.ui.scroll", "android.ui.global", "android.screen.lock", "android.screen.wake"))
        val body = JSONObject().put("pairing_id", pairingId).put("code", code).put("signature", signature).put("capabilities", caps)
        val request = Request.Builder().url("${serverBase}/api/pairing/claim")
            .post(body.toString().toRequestBody("application/json".toMediaType())).build()
        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(c: Call, e: java.io.IOException) = pairUi("Pairing gagal: ${e.message}")
            override fun onResponse(c: Call, r: Response) { r.use {
                val body = it.body?.string().orEmpty()
                if (!it.isSuccessful) {
                    val detail = try { JSONObject(body).optString("error").takeIf { value -> value.isNotBlank() } } catch(_: Exception) { null }
                    pairUi("Pairing ditolak: ${detail ?: "HTTP ${it.code}"}")
                    return
                }
                prefs.edit().remove("pending_pairing_id").remove("pending_pairing_nonce").putBoolean("paired", true).apply()
                showVoice(); connect()
            }}
        })
    }

    private fun connect(){
        if(ws != null) return
        intentionalVoiceEnd = false
        val server=prefs.getString("server",null)?:return; val id=identity().first
        val wsBase=server.replaceFirst("https://","wss://").replaceFirst("http://","ws://")
        ws=client.newWebSocket(Request.Builder().url("$wsBase/ws/device?device_id=$id").build(),object:WebSocketListener(){
            override fun onMessage(w:WebSocket,text:String){ try {
                val m=JSONObject(text); when(m.optString("type")){
                    "challenge"->{ val ch=m.getString("challenge"); val serverKey=prefs.getString("server_key","")!!; if(!verify(serverKey,"$id:$ch".toByteArray(),m.optString("server_signature"))){ ui("Server identity verification failed"); w.close(4003,"bad server proof"); return }; w.send(JSONObject().put("type","proof").put("signature",sign(ch.toByteArray())).put("capabilities", org.json.JSONArray(listOf("jarvis.command","notification","vibration","clipboard.write","open_url","browser.open","browser.search","app.launch","app.close","android.settings.open","camera.capture","file.upload","file.receive","attachment.inbox","android.ui.inspect","android.ui.click","android.ui.text","android.ui.scroll","android.ui.global","android.screen.lock","android.screen.wake"))).toString()) }
                    "attachment.inbox"->{ val arr=m.optJSONArray("attachments")?:JSONArray(); synchronized(attachmentItems){ attachmentItems.clear(); for(i in 0 until arr.length()){ val item=arr.getJSONObject(i); attachmentItems[item.getString("id")]=item } }; runOnUiThread { refreshAttachmentDialog(); refreshAttachmentBadge() } }
                    "attachment.sent"->{ val arr=m.optJSONArray("attachments")?:JSONArray(); synchronized(sentAttachmentItems){ sentAttachmentItems.clear(); for(i in 0 until arr.length()){ val item=arr.getJSONObject(i); sentAttachmentItems[item.getString("id")]=item } }; runOnUiThread { refreshAttachmentDialog() } }
                    "attachment.sent.new", "attachment.sent.update"->{ val item=m.optJSONObject("attachment"); if(item!=null){ synchronized(sentAttachmentItems){ sentAttachmentItems[item.getString("id")]=item }; runOnUiThread { refreshAttachmentDialog() } } }
                    "attachment.new"->{ val item=m.optJSONObject("attachment"); if(item!=null){ synchronized(attachmentItems){ attachmentItems[item.getString("id")]=item }; runOnUiThread { Toast.makeText(this@MainActivity,"New attachment · ${item.optString("name")}",Toast.LENGTH_LONG).show(); refreshAttachmentDialog(); refreshAttachmentBadge() } } }
                    "attachment.pick.request"->{
                        deferredPickerRequest=m
                        w.send(JSONObject().put("type","attachment.picker.received").put("request_id",m.optString("request_id")).toString())
                        if(assistantTurnComplete) runOnUiThread { launchDeferredAttachmentPicker() }
                    }
                    "attachment.transfer.status"->{ ui(m.optString("message","Attachment transfer updated")) }
                    "attachment.download.ready"->{ val pending=pendingAttachment; if(pending!=null && pending.first==m.optString("id")){ pendingAttachment=null; handleAttachmentDownload(m,pending.second) } }
                    "attachment.error"->{ ui("Attachment: ${m.optString("error")}") }
                    "ready"->{ reconnectScheduled=false; reconnectDelayMs=1500L; heartbeatHandler.removeCallbacks(heartbeatRunnable); heartbeatHandler.postDelayed(heartbeatRunnable,15000L); runOnUiThread { endConversation.visibility=View.VISIBLE; startConversation.visibility=View.GONE }; setVoiceState("LISTENING"); startMic() }
                    "status"->{ val st=m.optString("state").uppercase(); if(st=="SPEAKING"||st=="THINKING") assistantTurnComplete=false; setVoiceState(if(st=="ACTIVE") "LISTENING" else st) }
                    "assistant.turn.complete"->{ assistantTurnComplete=true; if(deferredPickerRequest!=null) runOnUiThread { launchDeferredAttachmentPicker() } }
                    "conversation.snapshot"->{
                        val arr=m.optJSONArray("entries")?:JSONArray()
                        runOnUiThread {
                            transcriptTurns.clear()
                            for(i in 0 until arr.length()){
                                val item=arr.optJSONObject(i)?:continue
                                val who=if(item.optString("speaker").equals("user",true)) "YOU" else "JARVIS"
                                transcriptTurns.addLast("$who\u0000${item.optString("text")}")
                            }
                            streamingSpeaker=""; streamingText=""
                            renderTranscript(transcriptTurns.map { it.substringBefore("\u0000") to it.substringAfter("\u0000") })
                            transcriptScroll.post { transcriptScroll.fullScroll(View.FOCUS_DOWN) }
                        }
                    }
                    "transcript.delta"->{ updateTranscriptDelta(m.optString("speaker"),m.optString("text")) }
                    "log"->{
                        if(!m.optBoolean("progress",false)) appendTranscript(m.optString("speaker"),m.optString("text"))
                    }
                    "capability.call"->executeCapability(w,m)
                }
            } catch(_:Exception){ ui("Invalid message from JARVIS") } }
            override fun onMessage(w:WebSocket,bytes:ByteString){
                setVoiceState("SPEAKING")
                enqueueAudio(bytes.toByteArray())
            }
            override fun onClosing(w:WebSocket,code:Int,reason:String){
                // A stale socket may close after a newer reconnect has already
                // taken ownership. Never let that old callback stop the active
                // microphone/playback session or null the current socket.
                if(ws !== w) return
                heartbeatHandler.removeCallbacks(heartbeatRunnable)
                stopMic(); stopPlayback(); ws=null
                if(code==4001||code==4003){ prefs.edit().putBoolean("paired",false).apply(); showPair("Pairing revoked. Enter a new Pair Code.") } else { setEnded(); scheduleReconnect() }
            }
            override fun onFailure(w:WebSocket,t:Throwable,r:Response?){
                if(ws !== w) return
                heartbeatHandler.removeCallbacks(heartbeatRunnable)
                stopMic(); stopPlayback(); ws=null
                runOnUiThread { status.text="Disconnected: ${t.message}"; orb.state="DISCONNECTED"; endConversation.visibility=View.GONE; startConversation.visibility=View.VISIBLE }
                scheduleReconnect()
            }
        })
    }

    private fun scheduleReconnect(){
        if(intentionalVoiceEnd) return
        synchronized(this){ if(reconnectScheduled) return; reconnectScheduled=true }
        if(!prefs.getBoolean("paired",false)){ reconnectScheduled=false; return }
        val delay = reconnectDelayMs
        reconnectDelayMs = (reconnectDelayMs * 2L).coerceAtMost(30000L)
        window.decorView.postDelayed({
            reconnectScheduled=false
            if(!intentionalVoiceEnd && ws==null && prefs.getBoolean("paired",false)){
                showVoice()
                connect()
            }
        },delay)
    }


    private fun startMic(){
        if(ActivityCompat.checkSelfPermission(this,Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED){ ActivityCompat.requestPermissions(this,arrayOf(Manifest.permission.RECORD_AUDIO),42); return }
        if(micRunning)return
        val min=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT).coerceAtLeast(2048)
        recorder=AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION,16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,min*2)
        recorder?.let { input ->
            if (AcousticEchoCanceler.isAvailable()) {
                echoCanceler = AcousticEchoCanceler.create(input.audioSessionId)?.apply { enabled = true }
            }
            if (NoiseSuppressor.isAvailable()) {
                noiseSuppressor = NoiseSuppressor.create(input.audioSessionId)?.apply { enabled = true }
            }
        }
        recorder?.startRecording(); micRunning=true
        Thread {
            val buf=ByteArray(1024)
            while(micRunning){
                val n=try{recorder?.read(buf,0,buf.size)?:-1}catch(_:Exception){-1}
                if(n>0){
                    val level=pcmLevel(buf,n)
                    orb.audioLevel(level)
                    if(speechLike(buf,n,level)) voicedFrames++ else voicedFrames=0
                    val now=android.os.SystemClock.elapsedRealtime()
                    if(voicedFrames >= interruptFrameCount &&
                        (voiceState=="SPEAKING" || voiceState=="THINKING") &&
                        now-lastInterruptAt >= interruptCooldownMs){
                        lastInterruptAt=now
                        voicedFrames=0
                        ws?.send(JSONObject().put("type","jarvis.interrupt").toString())
                        stopPlayback()
                        setVoiceState("LISTENING")
                    }
                    ws?.send(ByteString.of(*buf.copyOf(n)))
                }
            }
        }.apply { name="JarvisPhoneMic"; isDaemon=true; start() }
    }
    private fun stopMic(){
        micRunning=false
        try{recorder?.stop()}catch(_:Exception){}
        recorder?.release()
        recorder=null
        try{echoCanceler?.release()}catch(_:Exception){}
        echoCanceler=null
        try{noiseSuppressor?.release()}catch(_:Exception){}
        noiseSuppressor=null
    }
    private val audioLock=Any()

    private fun enqueueAudio(pcm:ByteArray){
        if(pcm.isEmpty()) return
        if(!playbackRunning){
            playbackRunning=true
            playbackThread=Thread {
                while(playbackRunning){
                    val next=try{ playbackQueue.take() }catch(_:InterruptedException){ break }
                    playAudio(next)
                }
            }.apply { name="JarvisAudioPlayback"; isDaemon=true; start() }
            audioIngressThread=Thread {
                while(playbackRunning){
                    val next=try{ audioIngressQueue.take() }catch(_:InterruptedException){ break }
                    try{ playbackQueue.put(next) }catch(_:InterruptedException){ break }
                }
            }.apply { name="JarvisAudioIngress"; isDaemon=true; start() }
        }
        if(!audioIngressQueue.offer(pcm)){
            ui("Audio output backlog exceeded safe limit")
        }
    }

    private fun stopPlayback(){
        playbackRunning=false
        audioIngressQueue.clear()
        playbackQueue.clear()
        audioIngressThread?.interrupt()
        audioIngressThread=null
        playbackThread?.interrupt()
        playbackThread=null
        releasePlayer()
    }

    private fun releasePlayer(){
        synchronized(audioLock){
            val p=player
            player=null
            if(p!=null){
                try{ p.pause() }catch(_:Exception){}
                try{ p.flush() }catch(_:Exception){}
                try{ p.stop() }catch(_:Exception){}
                try{ p.release() }catch(_:Exception){}
            }
        }
    }

    private fun ensurePlayer():AudioTrack?{
        synchronized(audioLock){
            val current=player
            if(current!=null && current.state==AudioTrack.STATE_INITIALIZED){
                try{
                    if(current.playState!=AudioTrack.PLAYSTATE_PLAYING) current.play()
                    return current
                }catch(_:Exception){
                    try{ current.release() }catch(_:Exception){}
                    player=null
                }
            }else if(current!=null){
                try{ current.release() }catch(_:Exception){}
                player=null
            }
            return try{
                val min=AudioTrack.getMinBufferSize(24000,AudioFormat.CHANNEL_OUT_MONO,AudioFormat.ENCODING_PCM_16BIT).coerceAtLeast(4096)
                val format=AudioFormat.Builder()
                    .setSampleRate(24000)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
                val attrs=AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
                val created=AudioTrack.Builder()
                    .setAudioAttributes(attrs)
                    .setAudioFormat(format)
                    .setBufferSizeInBytes(min*8)
                    .setTransferMode(AudioTrack.MODE_STREAM)
                    .build()
                if(created.state!=AudioTrack.STATE_INITIALIZED){
                    try{ created.release() }catch(_:Exception){}
                    ui("Audio output unavailable")
                    null
                }else{
                    created.setVolume(1.0f)
                    created.play()
                    player=created
                    created
                }
            }catch(e:Exception){ ui("Audio output error: ${e.message ?: e::class.java.simpleName}"); null }
        }
    }

    private fun playAudio(pcm:ByteArray){
        if(pcm.isEmpty()) return
        orb.audioLevel(pcmLevel(pcm,pcm.size))
        var p=ensurePlayer() ?: return
        var written=try{ p.write(pcm,0,pcm.size,AudioTrack.WRITE_BLOCKING) }catch(_:Exception){ AudioTrack.ERROR_DEAD_OBJECT }
        if(written==AudioTrack.ERROR_DEAD_OBJECT || written==AudioTrack.ERROR_INVALID_OPERATION || written==AudioTrack.ERROR_BAD_VALUE){
            releasePlayer()
            p=ensurePlayer() ?: return
            written=try{ p.write(pcm,0,pcm.size,AudioTrack.WRITE_BLOCKING) }catch(_:Exception){ -1 }
        }
        if(written<0) releasePlayer()
    }

    override fun onRequestPermissionsResult(requestCode:Int,permissions:Array<out String>,grantResults:IntArray){
        super.onRequestPermissionsResult(requestCode,permissions,grantResults)
        if(requestCode==42){ if(grantResults.firstOrNull()==PackageManager.PERMISSION_GRANTED) startMic() else ui("Microphone permission is required for Live Voice") }
        if(requestCode==43){
            val pending=pendingCameraRequest
            pendingCameraRequest=null
            if(grantResults.firstOrNull()==PackageManager.PERMISSION_GRANTED && pending!=null) executeCapability(pending.first,pending.second)
            else if(pending!=null) pending.first.send(JSONObject().put("type","capability.result").put("call_id",pending.second.optString("call_id")).put("ok",false).put("result","Camera permission was denied on the companion").toString())
        }
    }

    private fun setVoiceState(s:String){
        voiceState=s.uppercase()
        heartbeatHandler.removeCallbacks(thinkingWatchdog)
        if(voiceState=="THINKING") heartbeatHandler.postDelayed(thinkingWatchdog,60000L)
        runOnUiThread { status.text=s.lowercase().replaceFirstChar { it.uppercase() }; orb.state=s }
    }
    private val transcriptTurns = ArrayDeque<String>()
    private var streamingSpeaker = ""
    private var streamingText = ""
    private fun renderTranscript(lines:List<Pair<String,String>>){
        val out=SpannableStringBuilder()
        lines.takeLast(20).forEachIndexed { index, item ->
            if(index>0) out.append("\n\n")
            val label="${item.first}:"
            val start=out.length
            out.append(label)
            out.setSpan(StyleSpan(Typeface.BOLD),start,out.length,Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            out.append("  ").append(item.second)
        }
        transcript.text=out
    }
    private fun updateTranscriptDelta(speaker:String,text:String){ if(text.isBlank()) return; runOnUiThread {
        val who=if(speaker.equals("user",true)) "YOU" else "JARVIS"
        if(streamingSpeaker != who){ streamingSpeaker=who; streamingText="" }
        streamingText=text
        val rendered=ArrayList<Pair<String,String>>()
        transcriptTurns.forEach { row -> rendered.add(row.substringBefore("\u0000") to row.substringAfter("\u0000")) }
        rendered.add(who to streamingText)
        renderTranscript(rendered)
        transcriptScroll.post { transcriptScroll.fullScroll(View.FOCUS_DOWN) }
    }}
    private fun appendTranscript(speaker:String,text:String){ if(text.isBlank()) return; runOnUiThread {
        streamingSpeaker=""; streamingText=""
        val who=if(speaker.equals("user",true)) "YOU" else "JARVIS"
        transcriptTurns.addLast("$who\u0000$text")
        while(transcriptTurns.size > 4) transcriptTurns.removeFirst()
        renderTranscript(transcriptTurns.map { it.substringBefore("\u0000") to it.substringAfter("\u0000") })
        transcriptScroll.post { transcriptScroll.fullScroll(View.FOCUS_DOWN) }
    }}
    private fun endVoice(){ intentionalVoiceEnd=true; heartbeatHandler.removeCallbacks(heartbeatRunnable); stopMic(); stopPlayback(); val current=ws; ws=null; current?.close(1000,"conversation ended"); setEnded() }
    private fun setEnded()=runOnUiThread { status.text=getString(R.string.conversation_ended); orb.state="SLEEPING"; endConversation.visibility=View.GONE; startConversation.visibility=View.VISIBLE }
    private fun speechLike(b:ByteArray,n:Int,level:Float):Boolean {
        if(level < interruptLevelThreshold || n < 4) return false
        var crossings=0
        var diffEnergy=0.0
        var energy=0.0
        var previous=0
        var count=0
        var i=0
        while(i+1<n){
            val sample=((b[i+1].toInt() shl 8) or (b[i].toInt() and 255)).toShort().toInt()
            if(count>0 && ((sample>=0) != (previous>=0))) crossings++
            if(count>0){ val diff=(sample-previous).toDouble(); diffEnergy += diff*diff }
            energy += sample.toDouble()*sample
            previous=sample; count++; i+=2
        }
        if(count<2 || energy<=0.0) return false
        val zeroCrossRate=crossings.toFloat()/(count-1).toFloat()
        val diffRatio=kotlin.math.sqrt(diffEnergy/(count-1)).toFloat() /
            kotlin.math.sqrt(energy/count).toFloat()
        // Speech has voiced/low-frequency structure; steady hiss and isolated
        // clicks usually have a high zero-crossing or frame-difference ratio.
        return zeroCrossRate in 0.01f..0.35f && diffRatio < 1.35f
    }
    private fun pcmLevel(b:ByteArray,n:Int):Float { if(n<2)return 0f; var sum=0.0; var count=0; var i=0; while(i+1<n){ val v=((b[i+1].toInt() shl 8) or (b[i].toInt() and 255)).toShort().toInt(); sum+=v.toDouble()*v;count++;i+=2 }; if(count==0)return 0f; return (sqrt(sum/count)/3500.0).toFloat().coerceIn(0f,1f) }

    private fun executeCapability(w:WebSocket,m:JSONObject){ val cap=m.optString("capability"); val a=m.optJSONObject("args")?:JSONObject()
        if(cap=="camera.capture" && ActivityCompat.checkSelfPermission(this,Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED){
            pendingCameraRequest=w to m
            runOnUiThread { ActivityCompat.requestPermissions(this,arrayOf(Manifest.permission.CAMERA),43) }
            return
        }
        if(cap=="file.upload" && a.optString("source").isBlank()){
            val latch=CountDownLatch(1); sourcePickerLatch=latch; pickedSourceUri=null
            runOnUiThread { try {
                startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"),92)
            }catch(e:Exception){sourcePickerLatch=null;latch.countDown()} }
            Thread {
                var ok=true; var result="done"
                try{
                    if(!latch.await(120,TimeUnit.SECONDS))error("File selection timed out")
                    val selected=pickedSourceUri?:error("File selection cancelled")
                    a.put("source",selected.toString())
                    result=AttachmentTransfer.upload(this,client,a)
                }catch(e:Exception){ok=false;result=e.message?:e.toString()}
                finally{sourcePickerLatch=null;pickedSourceUri=null}
                w.send(JSONObject().put("type","capability.result").put("call_id",m.optString("call_id"))
                    .put("ok",ok).put("result",result).toString())
            }.start()
            return
        }
        var ok=true; var result="done"; try { when(cap){
        "notification"->{ val nm=getSystemService(NotificationManager::class.java); val cid="jarvis"; if(Build.VERSION.SDK_INT>=26)nm.createNotificationChannel(NotificationChannel(cid,"JARVIS",NotificationManager.IMPORTANCE_DEFAULT)); nm.notify((System.currentTimeMillis()%Int.MAX_VALUE).toInt(),Notification.Builder(this,cid).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("JARVIS").setContentText(a.optString("text")).build()) }
        "vibration"->{ val v=if(Build.VERSION.SDK_INT>=31)getSystemService(VibratorManager::class.java).defaultVibrator else @Suppress("DEPRECATION") getSystemService(VIBRATOR_SERVICE) as Vibrator; v.vibrate(VibrationEffect.createOneShot(a.optLong("ms",300),VibrationEffect.DEFAULT_AMPLITUDE)) }
        "clipboard.write"->{ (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("JARVIS",a.optString("text"))) }
        "open_url", "browser.open"->{
            val rawUrl=a.optString("url").trim().ifBlank { error("URL is required") }
            val parsed=Uri.parse(rawUrl)
            if(parsed.scheme !in listOf("http","https")){ error("Only http/https browser URLs are supported") }
            startActivity(Intent(Intent.ACTION_VIEW,parsed).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            result="opened browser: $rawUrl"
        }
        "browser.search"->{
            val query=a.optString("query").trim().ifBlank { error("Search query is required") }
            val engine=a.optString("engine","google").lowercase()
            val base=when(engine){
                "bing"->"https://www.bing.com/search?q="
                "duckduckgo"->"https://duckduckgo.com/?q="
                else->"https://www.google.com/search?q="
            }
            val searchUrl=base+Uri.encode(query)
            startActivity(Intent(Intent.ACTION_VIEW,Uri.parse(searchUrl)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            result="opened browser search: $query"
        }
        "app.launch"->{ val query=a.optString("package").ifBlank { a.optString("app") }.ifBlank { a.optString("name") }; val pkg=resolveAppPackage(query)?:error("App not found: $query"); val i=packageManager.getLaunchIntentForPackage(pkg)?:error("App has no launch activity: $pkg"); startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); result="opened $pkg" }
        "app.close"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.global("home") }
        "android.settings.open"->{ val page=a.optString("page").ifBlank { a.optString("section") }; startActivity(settingsIntent(page)); result=if(page.isBlank()) "opened Android Settings" else "opened Android Settings: $page" }
        "camera.capture"->{ result=captureCameraFrame(a.optString("facing","back")) }
        "file.upload"->{ result=AttachmentTransfer.upload(this,client,a) }
        "file.receive"->{ result=AttachmentTransfer.receive(this,client,a) }
        "android.ui.inspect"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.inspect(a.optInt("max_nodes",120)).toString() }
        "android.ui.click"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.click(a.optString("text"),a.optString("view_id")) }
        "android.ui.text"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.setText(a.getString("text"),a.optString("target_text"),a.optString("view_id")) }
        "android.ui.scroll"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.scroll(a.optString("direction","down")) }
        "android.ui.global"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.global(a.getString("action")) }
        "android.screen.lock"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.global("lock") }
        "android.screen.wake"->{ val pm=getSystemService(POWER_SERVICE) as PowerManager; if(!pm.isInteractive){ @Suppress("DEPRECATION") val wl=pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP,"jarvis:wake"); wl.acquire(3000) }; result="screen awake; device authentication is still required" }
        else->{ok=false;result="Unsupported capability: $cap"}
    }}catch(e:Exception){ok=false;result=e.message?:e.toString()}; w.send(JSONObject().put("type","capability.result").put("call_id",m.optString("call_id")).put("ok",ok).put("result",result).toString()) }

    private fun refreshAttachmentBadge(){
        val count=synchronized(attachmentItems){ attachmentItems.values.count { it.optString("status","pending") != "saved" } }
        attachmentBadge.visibility=if(count>0) View.VISIBLE else View.GONE
        attachmentBadge.text=if(count>99) "99+" else count.toString()
    }

    private fun launchDeferredAttachmentPicker(){
        val req=deferredPickerRequest ?: return
        deferredPickerRequest=null
        val intent=Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true)
        intent.putExtra("assistant_attachment_request",req.optString("request_id"))
        pendingPickerRequestId=req.optString("request_id")
        try {
            ws?.send(JSONObject().put("type","attachment.picker.opened").put("request_id",req.optString("request_id")).toString())
            startActivityForResult(intent,93)
        } catch(e:Exception) {
            pendingPickerRequestId=null
            ws?.send(JSONObject().put("type","attachment.source.cancelled").put("request_id",req.optString("request_id")).put("error",e.message).toString())
        }
    }

    private fun showAttachmentInbox(){ renderCompanionPage("attachments") }

    private fun renderAttachmentContent(panel:LinearLayout){
        ws?.send(JSONObject().put("type","attachment.list").toString())
        val tabs=LinearLayout(this).apply { orientation=LinearLayout.HORIZONTAL; setPadding(0,0,0,dp(12)) }
        fun tab(label:String,mode:String)=TextView(this).apply {
            text=label; textSize=14f; gravity=android.view.Gravity.CENTER
            setPadding(dp(8),dp(10),dp(8),dp(12))
            setOnClickListener { attachmentTab=mode; refreshAttachmentDialog() }
        }
        attachmentReceivedTab=tab("Received","received")
        attachmentSentTab=tab("Sent","sent")
        tabs.addView(attachmentReceivedTab,LinearLayout.LayoutParams(0,dp(42),1f))
        tabs.addView(attachmentSentTab,LinearLayout.LayoutParams(0,dp(42),1f))
        panel.addView(tabs)
        attachmentSubtitle=TextView(this).apply {
            textSize=12f; setTextColor(android.graphics.Color.rgb(145,153,173))
            setPadding(dp(4),0,0,dp(12))
        }
        panel.addView(attachmentSubtitle)
        val list=ListView(this).apply {
            tag="attachment-list"; dividerHeight=0
            setBackgroundColor(android.graphics.Color.TRANSPARENT)
        }
        panel.addView(list,LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,dp(320)))
        list.setOnItemClickListener { _,_,position,_ ->
            if(attachmentTab=="received"){
                val item=synchronized(attachmentItems){ attachmentItems.values.toList().getOrNull(position) }?:return@setOnItemClickListener
                showAttachmentActions(item)
            }
        }
        refreshAttachmentDialog()
    }

    private fun showAttachmentActions(item:JSONObject){
        val body=companionBody?:return
        body.removeAllViews()
        companionBack?.visibility=View.VISIBLE
        companionTitle?.text="Attachment actions"
        companionSubtitle?.text=item.optString("name","File")
        val size=formatBytes(item.optLong("size"))
        val status=item.optString("status","pending").replaceFirstChar { it.uppercase() }
        body.addView(TextView(this).apply {
            text="$size  ·  $status"; textSize=12f
            setTextColor(android.graphics.Color.rgb(145,153,173)); setPadding(dp(8),0,dp(8),dp(10))
        })
        body.addView(menuActionRow(R.drawable.ic_open_file,"Open","Preview using an available app") { dialog -> dialog.dismiss(); requestAttachment(item.getString("id"),"open") })
        body.addView(menuActionRow(R.drawable.ic_save_file,"Save As","Choose a location on this device") { dialog ->
            dialog.dismiss(); val intent=Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType("application/octet-stream").putExtra(Intent.EXTRA_TITLE,item.optString("name"))
            pendingAttachment=Pair(item.getString("id"),"save"); startActivityForResult(intent,91)
        })
        body.addView(menuActionRow(R.drawable.ic_share_file,"Share","Send with another app on this device") { dialog -> dialog.dismiss(); requestAttachment(item.getString("id"),"share") })
    }

    private fun refreshAttachmentDialog(){
        val list=attachmentDialog?.findViewById<ListView>(android.R.id.list)
            ?: (attachmentDialog?.window?.decorView?.findViewWithTag<View>("attachment-list") as? ListView)
        if(list==null)return
        val received=synchronized(attachmentItems){ attachmentItems.values.toList() }
        val sent=synchronized(sentAttachmentItems){ sentAttachmentItems.values.toList() }
        val isSent=attachmentTab=="sent"
        attachmentReceivedTab?.apply {
            setBackgroundResource(if(isSent) android.R.color.transparent else R.drawable.bg_attachment_tab_selected)
            setTextColor(if(isSent) android.graphics.Color.rgb(145,164,170) else android.graphics.Color.rgb(165,232,235))
            setTypeface(null,if(isSent) android.graphics.Typeface.NORMAL else android.graphics.Typeface.BOLD)
        }
        attachmentSentTab?.apply {
            setBackgroundResource(if(isSent) R.drawable.bg_attachment_tab_selected else android.R.color.transparent)
            setTextColor(if(isSent) android.graphics.Color.rgb(165,232,235) else android.graphics.Color.rgb(145,164,170))
            setTypeface(null,if(isSent) android.graphics.Typeface.BOLD else android.graphics.Typeface.NORMAL)
        }
        attachmentSubtitle?.text=if(isSent) "Sent history · Only recipients can open or save these files" else "Received files · Open, save or share on this device"
        companionTitle?.text="Attachments · ${if(isSent) sent.size else received.size}"
        val items=if(isSent) sent else received
        list.adapter=object:BaseAdapter(){
            override fun getCount()=items.size
            override fun getItem(position:Int)=items[position]
            override fun getItemId(position:Int)=position.toLong()
            override fun getView(position:Int,convertView:View?,parent:android.view.ViewGroup):View {
                val item=items[position]
                val row=LinearLayout(this@MainActivity).apply {
                    orientation=LinearLayout.HORIZONTAL; gravity=android.view.Gravity.CENTER_VERTICAL
                    setPadding(dp(8),dp(10),dp(8),dp(10)); setBackgroundResource(R.drawable.bg_button_secondary)
                }
                val icon=ImageView(this@MainActivity).apply {
                    setImageResource(R.drawable.ic_attachment); setColorFilter(android.graphics.Color.rgb(165,232,235))
                    setPadding(dp(10),dp(10),dp(10),dp(10)); setBackgroundResource(R.drawable.bg_icon_action)
                }
                row.addView(icon,LinearLayout.LayoutParams(dp(44),dp(44)))
                val copy=LinearLayout(this@MainActivity).apply { orientation=LinearLayout.VERTICAL; setPadding(dp(13),0,0,0) }
                copy.addView(TextView(this@MainActivity).apply {
                    text=item.optString("name","file"); textSize=13f
                    setTextColor(android.graphics.Color.rgb(247,248,248)); maxLines=1; ellipsize=TextUtils.TruncateAt.MIDDLE
                })
                copy.addView(TextView(this@MainActivity).apply {
                    val status=item.optString("status","pending")
                    text=if(isSent) "To ${item.optString("destination_name","device")} · ${if(item.optBoolean("server_upload")) "Stored on server" else if(item.optBoolean("assistant_upload")) "Uploaded to assistant" else if(status=="saved") "Saved by recipient" else "Sent to inbox"}"
                         else "${formatBytes(item.optLong("size"))} · ${status.replaceFirstChar { c -> c.uppercase() }}"
                    textSize=11f; setTextColor(android.graphics.Color.rgb(145,153,173)); setPadding(0,dp(4),0,0)
                    maxLines=1; ellipsize=TextUtils.TruncateAt.END
                })
                row.addView(copy,LinearLayout.LayoutParams(0,LinearLayout.LayoutParams.WRAP_CONTENT,1f))
                return row
            }
        }
    }

    private fun dp(value:Int):Int=(value*resources.displayMetrics.density).toInt()
    private fun formatBytes(bytes:Long):String=when {
        bytes>=1024L*1024L -> String.format(Locale.US,"%.1f MB",bytes/(1024.0*1024.0))
        bytes>=1024L -> String.format(Locale.US,"%.1f KB",bytes/1024.0)
        else -> "$bytes B"
    }

    private fun requestAttachment(id:String,action:String){
        pendingAttachment=Pair(id,action)
        ws?.send(JSONObject().put("type","attachment.download").put("id",id).toString())
    }

    @Deprecated("Activity result used for native document picker compatibility")
    override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?){
        super.onActivityResult(requestCode,resultCode,data)
        if(requestCode==92){
            if(resultCode==RESULT_OK)pickedSourceUri=data?.data
            sourcePickerLatch?.countDown()
        }
        if(requestCode==93){
            val requestId=pendingPickerRequestId; pendingPickerRequestId=null
            if(requestId!=null){
                if(resultCode==RESULT_OK && data!=null){
                    val sources=JSONArray()
                    val clips=data.clipData
                    if(clips!=null){
                        for(i in 0 until clips.itemCount) sources.put(clips.getItemAt(i).uri.toString())
                    }else data.data?.let { sources.put(it.toString()) }
                    if(sources.length()>0) ws?.send(JSONObject().put("type","attachment.sources.selected").put("request_id",requestId).put("sources",sources).toString())
                    else ws?.send(JSONObject().put("type","attachment.source.cancelled").put("request_id",requestId).toString())
                } else ws?.send(JSONObject().put("type","attachment.source.cancelled").put("request_id",requestId).toString())
            }
        }
        if(requestCode==91){
            if(resultCode==RESULT_OK && data?.data!=null){ pendingSaveUri=data.data; pendingAttachment?.let { requestAttachment(it.first,"save") } }
            else { pendingAttachment=null; pendingSaveUri=null }
        }
    }

    private fun handleAttachmentDownload(info:JSONObject,action:String){
        Thread {
            val id=info.getString("id"); val name=info.getString("name").replace(Regex("[\\/]+"),"_")
            val destUri=if(action=="save")pendingSaveUri else null
            if(action=="save" && destUri==null){ui("No destination selected");return@Thread}
            val cached=File(File(cacheDir,"attachments").apply{mkdirs()},"$id-$name")
            val temp=File(cached.absolutePath+".part")
            val hash=MessageDigest.getInstance("SHA-256"); var total=0L
            try{
                val response=client.newCall(Request.Builder().url(info.getString("url")).build()).execute()
                response.use { r ->
                    if(!r.isSuccessful)error("Download failed: HTTP ${r.code}")
                    val input=r.body?.byteStream()?:error("Empty attachment")
                    temp.outputStream().use { out -> input.use { src ->
                        val buffer=ByteArray(1024*1024)
                        while(true){val n=src.read(buffer);if(n<=0)break;out.write(buffer,0,n);hash.update(buffer,0,n);total+=n}
                    } }
                }
                val digest=hash.digest().joinToString(""){"%02x".format(it)}
                if(digest!=info.getString("sha256")||total!=info.getLong("size"))error("Attachment verification failed")
                if(!temp.renameTo(cached))error("Cannot prepare attachment")
                if(action=="save"){
                    contentResolver.openOutputStream(destUri!!)?.use { out -> cached.inputStream().use { it.copyTo(out) } }?:error("Cannot save attachment")
                    val savedDigest=MessageDigest.getInstance("SHA-256")
                    var savedSize=0L
                    contentResolver.openInputStream(destUri)?.use { stream ->
                        val buf=ByteArray(1024*1024)
                        while(true){val n=stream.read(buf);if(n<=0)break;savedDigest.update(buf,0,n);savedSize+=n}
                    }?:error("Cannot verify saved attachment")
                    val savedHash=savedDigest.digest().joinToString(""){"%02x".format(it)}
                    if(savedHash!=digest||savedSize!=total)error("Saved attachment verification failed")
                    ws?.send(JSONObject().put("type","attachment.saved").put("id",id).toString())
                    ui("Attachment saved")
                }else{
                    val uri=FileProvider.getUriForFile(this,"${packageName}.files",cached)
                    val mime=java.net.URLConnection.guessContentTypeFromName(name)?:"application/octet-stream"
                    val intent=if(action=="share") Intent(Intent.ACTION_SEND).setType(mime)
                        .putExtra(Intent.EXTRA_STREAM,uri)
                    else Intent(Intent.ACTION_VIEW).setDataAndType(uri,mime)
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    runOnUiThread { try { startActivity(if(action=="share")Intent.createChooser(intent,"Share attachment") else intent) }
                        catch(e:Exception){ ui("No app can open this attachment: ${e.message}") } }
                }
            }catch(e:Exception){temp.delete();ui("Attachment failed: ${e.message}")}
            finally{ if(action=="save")pendingSaveUri=null }
        }.start()
    }

    private fun captureCameraFrame(rawFacing:String):String {
        if(ActivityCompat.checkSelfPermission(this,Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED){
            runOnUiThread { ActivityCompat.requestPermissions(this,arrayOf(Manifest.permission.CAMERA),43) }
            error("Camera permission is required. Grant it on the companion, then retry the camera request.")
        }
        val facing=if(rawFacing.lowercase(Locale.ROOT).contains("front")) CameraCharacteristics.LENS_FACING_FRONT else CameraCharacteristics.LENS_FACING_BACK
        val manager=getSystemService(CAMERA_SERVICE) as CameraManager
        val cameraId=manager.cameraIdList.firstOrNull { id -> manager.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING)==facing }
            ?: error("Requested ${if(facing==CameraCharacteristics.LENS_FACING_FRONT) "front" else "back"} camera is unavailable")
        val thread=HandlerThread("JarvisCameraCapture").apply { start() }
        val handler=Handler(thread.looper)
        val reader=ImageReader.newInstance(1280,720,android.graphics.ImageFormat.JPEG,2)
        val latch=CountDownLatch(1)
        var payload:ByteArray?=null
        var failure:String?=null
        var device:CameraDevice?=null
        var session:CameraCaptureSession?=null
        reader.setOnImageAvailableListener({ r ->
            try { r.acquireLatestImage()?.use { image -> val buf=image.planes[0].buffer; payload=ByteArray(buf.remaining()); buf.get(payload) } }
            catch(e:Exception){ failure=e.message?:e.toString() }
            finally { latch.countDown() }
        },handler)
        try {
            manager.openCamera(cameraId,object:CameraDevice.StateCallback(){
                override fun onOpened(cam:CameraDevice){
                    device=cam
                    cam.createCaptureSession(listOf(reader.surface),object:CameraCaptureSession.StateCallback(){
                        override fun onConfigured(cs:CameraCaptureSession){
                            session=cs
                            try {
                                val warmup=cam.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                                    addTarget(reader.surface)
                                }.build()
                                var warmupFrames=0
                                var stillStarted=false
                                val callback=object:CameraCaptureSession.CaptureCallback(){
                                    override fun onCaptureCompleted(session:CameraCaptureSession,request:CaptureRequest,result:TotalCaptureResult){
                                        if(stillStarted) return
                                        warmupFrames++
                                        val ae=result.get(CaptureResult.CONTROL_AE_STATE)
                                        val awb=result.get(CaptureResult.CONTROL_AWB_STATE)
                                        val af=result.get(CaptureResult.CONTROL_AF_STATE)
                                        val aeReady=ae==null || ae==CaptureResult.CONTROL_AE_STATE_CONVERGED || ae==CaptureResult.CONTROL_AE_STATE_FLASH_REQUIRED || ae==CaptureResult.CONTROL_AE_STATE_LOCKED
                                        val awbReady=awb==null || awb==CaptureResult.CONTROL_AWB_STATE_CONVERGED || awb==CaptureResult.CONTROL_AWB_STATE_LOCKED
                                        val afReady=af==null || af==CaptureResult.CONTROL_AF_STATE_PASSIVE_FOCUSED || af==CaptureResult.CONTROL_AF_STATE_FOCUSED_LOCKED || af==CaptureResult.CONTROL_AF_STATE_NOT_FOCUSED_LOCKED || af==CaptureResult.CONTROL_AF_STATE_INACTIVE
                                        if((warmupFrames>=3 && aeReady && awbReady && afReady) || warmupFrames>=12){
                                            stillStarted=true
                                            try {
                                                cs.stopRepeating()
                                                val still=cam.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                                                    addTarget(reader.surface)
                                                }.build()
                                                cs.capture(still,null,handler)
                                            } catch(e:Exception){ failure=e.message?:e.toString(); latch.countDown() }
                                        }
                                    }
                                }
                                cs.setRepeatingRequest(warmup,callback,handler)
                            } catch(e:Exception){ failure=e.message?:e.toString(); latch.countDown() }
                        }
                        override fun onConfigureFailed(cs:CameraCaptureSession){ failure="Camera capture session configuration failed"; latch.countDown() }
                    },handler)
                }
                override fun onDisconnected(cam:CameraDevice){ failure="Camera disconnected"; cam.close(); latch.countDown() }
                override fun onError(cam:CameraDevice,error:Int){ failure="Camera error: $error"; cam.close(); latch.countDown() }
            },handler)
            if(!latch.await(10,TimeUnit.SECONDS)) error("Camera capture timed out")
            failure?.let { error(it) }
            val bytes=payload?:error("Camera returned no image frame")
            return JSONObject().put("mime_type","image/jpeg").put("data",AndroidBase64.encodeToString(bytes,AndroidBase64.NO_WRAP))
                .put("source","camera").put("facing",if(facing==CameraCharacteristics.LENS_FACING_FRONT) "front" else "back").toString()
        } finally {
            try { session?.stopRepeating() } catch(_:Exception){}
            try { session?.close() } catch(_:Exception){}
            try { device?.close() } catch(_:Exception){}
            try { reader.close() } catch(_:Exception){}
            thread.quitSafely()
        }
    }

    private fun normalizeName(s:String)=s.lowercase(Locale.ROOT).replace(Regex("[^a-z0-9]"), "")
    private fun resolveAppPackage(query:String):String? {
        if(query.isBlank()) return null
        packageManager.getLaunchIntentForPackage(query)?.let { return query }
        val q=normalizeName(query)
        val aliases=mapOf("whatsapp" to "com.whatsapp", "wa" to "com.whatsapp", "youtube" to "com.google.android.youtube", "chrome" to "com.android.chrome", "gmail" to "com.google.android.gm", "maps" to "com.google.android.apps.maps", "googlemaps" to "com.google.android.apps.maps")
        aliases[q]?.let { if(packageManager.getLaunchIntentForPackage(it)!=null) return it }
        val launcher=Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val acts=if(Build.VERSION.SDK_INT>=33) packageManager.queryIntentActivities(launcher,PackageManager.ResolveInfoFlags.of(0)) else @Suppress("DEPRECATION") packageManager.queryIntentActivities(launcher,0)
        return acts.asSequence().map { it.activityInfo.packageName to it.loadLabel(packageManager).toString() }.sortedByDescending { val n=normalizeName(it.second); when { n==q -> 3; n.contains(q)||q.contains(n) -> 2; normalizeName(it.first).contains(q) -> 1; else -> 0 } }.firstOrNull { val n=normalizeName(it.second); n==q || n.contains(q) || q.contains(n) || normalizeName(it.first).contains(q) }?.first
    }

    private fun settingsIntent(raw:String):Intent {
        val p=normalizeName(raw)
        val action=when {
            p.contains("bluetooth") -> Settings.ACTION_BLUETOOTH_SETTINGS
            p.contains("wifi") || p.contains("wireless") -> Settings.ACTION_WIFI_SETTINGS
            p.contains("accessibility") -> Settings.ACTION_ACCESSIBILITY_SETTINGS
            p.contains("notification") -> "android.settings.NOTIFICATION_SETTINGS"
            p.contains("display") || p.contains("screen") -> Settings.ACTION_DISPLAY_SETTINGS
            p.contains("sound") || p.contains("audio") -> Settings.ACTION_SOUND_SETTINGS
            p.contains("location") -> Settings.ACTION_LOCATION_SOURCE_SETTINGS
            p.contains("security") -> Settings.ACTION_SECURITY_SETTINGS
            p.contains("application") || p=="apps" || p=="app" -> Settings.ACTION_APPLICATION_SETTINGS
            p.contains("battery") -> Settings.ACTION_BATTERY_SAVER_SETTINGS
            p.contains("date") || p.contains("time") -> Settings.ACTION_DATE_SETTINGS
            p.contains("language") || p.contains("keyboard") -> Settings.ACTION_INPUT_METHOD_SETTINGS
            else -> Settings.ACTION_SETTINGS
        }
        return Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }

    override fun onDestroy(){ stopMic(); stopPlayback(); ws?.close(1000,"activity closed"); super.onDestroy() }
    private fun ui(s:String)=runOnUiThread{status.text=s}
    private fun pairUi(s:String)=runOnUiThread {
        pairProgress.visibility=View.GONE
        pairStatus.text=s
        pairStatus.visibility=View.VISIBLE
        findViewById<Button>(R.id.pair).isEnabled=pairCode.text.length==8
        findViewById<Button>(R.id.requestPairing).isEnabled=true
    }
    private fun b64(b:ByteArray)=java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(b)
    private fun unb64(s:String)=java.util.Base64.getUrlDecoder().decode(s)
    private fun lanClient():OkHttpClient { val tm=object:X509TrustManager{override fun getAcceptedIssuers()=arrayOf<X509Certificate>();override fun checkClientTrusted(c:Array<X509Certificate>,a:String){};override fun checkServerTrusted(c:Array<X509Certificate>,a:String){}}; val sc=SSLContext.getInstance("TLS");sc.init(null,arrayOf<TrustManager>(tm),SecureRandom());return OkHttpClient.Builder().sslSocketFactory(sc.socketFactory,tm).hostnameVerifier{_,_->true}.retryOnConnectionFailure(true).readTimeout(0,TimeUnit.MILLISECONDS).writeTimeout(0,TimeUnit.MILLISECONDS).pingInterval(15,TimeUnit.SECONDS).build() }
}
