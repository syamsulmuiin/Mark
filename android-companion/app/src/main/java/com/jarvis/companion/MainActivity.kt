package com.jarvis.companion

import android.Manifest
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.content.pm.ApplicationInfo
import android.media.*
import android.hardware.camera2.*
import android.media.ImageReader
import android.util.Base64 as AndroidBase64
import android.view.Surface
import android.net.Uri
import android.os.*
import android.provider.Settings
import android.provider.MediaStore
import android.view.View
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
import kotlin.math.sqrt
import javax.net.ssl.*

class MainActivity : AppCompatActivity() {
    private lateinit var status: TextView
    private lateinit var pairStatus: TextView
    private lateinit var pairCode: EditText
    private lateinit var pairPanel: View
    private lateinit var voicePanel: View
    private lateinit var orb: JarvisOrbView
    private lateinit var transcript: TextView
    private lateinit var transcriptScroll: ScrollView
    private lateinit var endConversation: ImageButton
    private lateinit var startConversation: Button
    private lateinit var phoneControl: ImageButton
    private var ws: WebSocket? = null
    private val attachmentItems = linkedMapOf<String,JSONObject>()
    private var pendingAttachment: Pair<String,String>? = null
    private var pendingSaveUri: Uri? = null
    private var pendingSaveInfo: JSONObject? = null
    private var attachmentDialog: AlertDialog? = null
    private var sourcePickerLatch: CountDownLatch? = null
    private var pickedSourceUri: Uri? = null
    @Volatile private var intentionalVoiceEnd = false
    private var recorder: AudioRecord? = null
    private var player: AudioTrack? = null
    @Volatile private var micRunning = false
    private val prefs by lazy { getSharedPreferences("jarvis-device", MODE_PRIVATE) }
    private val client by lazy { lanClient() }
    private val serverBase: String get() = prefs.getString("server", BuildConfig.MARK_LIV_PUBLIC_URL) ?: BuildConfig.MARK_LIV_PUBLIC_URL

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        setContentView(R.layout.activity_main)
        status=findViewById(R.id.status); pairStatus=findViewById(R.id.pairStatus); pairCode=findViewById(R.id.pairCode)
        pairPanel=findViewById(R.id.pairPanel); voicePanel=findViewById(R.id.voicePanel)
        orb=findViewById(R.id.orb); transcript=findViewById(R.id.transcript); transcriptScroll=findViewById(R.id.transcriptScroll); endConversation=findViewById(R.id.endConversation)
        startConversation=findViewById(R.id.startConversation); phoneControl=findViewById(R.id.phoneControl)
        findViewById<Button>(R.id.pair).setOnClickListener { pairWithCode(pairCode.text.toString()) }
        endConversation.setOnClickListener { endVoice() }
        startConversation.setOnClickListener { connect() }
        phoneControl.setOnClickListener { showPhoneControlMenu(it) }
        findViewById<Button>(R.id.attachments).setOnClickListener { showAttachmentInbox() }
        if (Build.VERSION.SDK_INT>=33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 7)
        intent?.data?.getQueryParameter("code")?.let { pairCode.setText(it.uppercase()); pairWithCode(it) }
        if (intent?.data==null && prefs.getBoolean("paired", false)) { showVoice(); connect() }
    }

    private fun showVoice(){ runOnUiThread { pairPanel.visibility=View.GONE; voicePanel.visibility=View.VISIBLE; status.text=getString(R.string.connecting); orb.state="CONNECTING"; endConversation.visibility=View.VISIBLE; startConversation.visibility=View.GONE } }

    private fun showPhoneControlMenu(anchor: View) {
        PopupMenu(this, anchor).apply {
            if (Build.VERSION.SDK_INT >= 29) setForceShowIcon(true)
            menu.add(0, 1, 0, getString(R.string.enable_phone_control)).setIcon(R.drawable.ic_phone_control)
            setOnMenuItemClickListener { item ->
                if (item.itemId == 1) {
                    startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                    true
                } else false
            }
            show()
        }
    }
    private fun showPair(message:String){ stopMic(); runOnUiThread { voicePanel.visibility=View.GONE; pairPanel.visibility=View.VISIBLE; pairStatus.text=message } }

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

    private fun pairWithCode(rawCode:String) {
        val code=rawCode.trim().uppercase()
        if(code.length != 6){ pairStatus.text=getString(R.string.pair_code_help); return }
        pairStatus.text=getString(R.string.pairing)
        pairAgainstServer(code, BuildConfig.MARK_LIV_PUBLIC_URL)
    }

    private fun pairAgainstServer(code:String, base:String) {
        val ident=identity()
        val peer=JSONObject().put("device_id",ident.first).put("name",Build.MODEL).put("public_key",b64(ident.third))
        client.newCall(Request.Builder().url("$base/api/pairing/offer/$code").build()).enqueue(object:Callback{
            override fun onFailure(c:Call,e:java.io.IOException)=pairUi("Pairing failed: ${e.message}")
            override fun onResponse(c:Call,r:Response){ r.use { response ->
                if(!response.isSuccessful){ pairUi(if(response.code==502) "JARVIS tunnel is offline (502)" else "Pairing server error: ${response.code}"); return }
                val o=try { JSONObject(response.body?.string().orEmpty()) } catch(_:Exception){ pairUi("Invalid response from JARVIS"); return }
                val nonce=o.optString("nonce"); val serverKey=o.optString("public_key"); val serverId=o.optString("device_id")
                if(nonce.isBlank()||serverKey.isBlank()||serverId.isBlank()){pairUi("Pairing code invalid or expired");return}
                val caps=org.json.JSONArray(listOf("jarvis.command","notification","vibration","clipboard.write","open_url","app.launch","app.close","android.settings.open","camera.capture","file.upload","file.receive","android.ui.inspect","android.ui.click","android.ui.text","android.ui.scroll","android.ui.global","android.screen.lock","android.screen.wake"))
                val body=JSONObject()
                    .put("code",code)
                    .put("peer",peer)
                    .put("signature",sign("$nonce:$code".toByteArray()))
                    .put("capabilities",caps)
                val req=Request.Builder().url("$base/api/pairing/accept").post(body.toString().toRequestBody("application/json".toMediaType())).build()
                client.newCall(req).enqueue(object:Callback{
                    override fun onFailure(c:Call,e:java.io.IOException)=pairUi("Pair failed: ${e.message}")
                    override fun onResponse(c:Call,r:Response){ r.use {
                        if(!it.isSuccessful){pairUi("Pair rejected: ${it.code}");return}
                        prefs.edit().putString("server",base).putString("server_key",serverKey).putString("server_id",serverId).putBoolean("paired",true).apply()
                        showVoice(); connect()
                    }}
                })
            }}
        })
    }

    private fun connect(){
        intentionalVoiceEnd = false
        val server=prefs.getString("server",null)?:return; val id=identity().first
        val wsBase=server.replaceFirst("https://","wss://").replaceFirst("http://","ws://")
        ws=client.newWebSocket(Request.Builder().url("$wsBase/ws/device?device_id=$id").build(),object:WebSocketListener(){
            override fun onMessage(w:WebSocket,text:String){ try {
                val m=JSONObject(text); when(m.optString("type")){
                    "challenge"->{ val ch=m.getString("challenge"); val serverKey=prefs.getString("server_key","")!!; if(!verify(serverKey,"$id:$ch".toByteArray(),m.optString("server_signature"))){ ui("Server identity verification failed"); w.close(4003,"bad server proof"); return }; w.send(JSONObject().put("type","proof").put("signature",sign(ch.toByteArray())).put("capabilities", org.json.JSONArray(listOf("jarvis.command","notification","vibration","clipboard.write","open_url","app.launch","app.close","android.settings.open","camera.capture","file.upload","file.receive","android.ui.inspect","android.ui.click","android.ui.text","android.ui.scroll","android.ui.global","android.screen.lock","android.screen.wake"))).toString()) }
                    "attachment.inbox"->{ val arr=m.optJSONArray("attachments")?:JSONArray(); synchronized(attachmentItems){ attachmentItems.clear(); for(i in 0 until arr.length()){ val item=arr.getJSONObject(i); attachmentItems[item.getString("id")]=item } }; runOnUiThread { refreshAttachmentDialog() } }
                    "attachment.new"->{ val item=m.optJSONObject("attachment"); if(item!=null){ synchronized(attachmentItems){ attachmentItems[item.getString("id")]=item }; runOnUiThread { Toast.makeText(this@MainActivity,"Attachment: ${item.optString("name")}",Toast.LENGTH_LONG).show(); refreshAttachmentDialog() } } }
                    "attachment.download.ready"->{ val pending=pendingAttachment; if(pending!=null && pending.first==m.optString("id")){ pendingAttachment=null; handleAttachmentDownload(m,pending.second) } }
                    "attachment.error"->{ ui("Attachment: ${m.optString("error")}") }
                    "ready"->{ runOnUiThread { endConversation.visibility=View.VISIBLE; startConversation.visibility=View.GONE }; setVoiceState("LISTENING"); startMic() }
                    "status"->{ val st=m.optString("state").uppercase(); setVoiceState(if(st=="ACTIVE") "LISTENING" else st) }
                    "log"->{ appendTranscript(m.optString("speaker"),m.optString("text")); if(m.optString("speaker")=="jarvis") setVoiceState("LISTENING") }
                    "capability.call"->executeCapability(w,m)
                }
            } catch(_:Exception){ ui("Invalid message from JARVIS") } }
            override fun onMessage(w:WebSocket,bytes:ByteString){ setVoiceState("SPEAKING"); playAudio(bytes.toByteArray()) }
            override fun onClosing(w:WebSocket,code:Int,reason:String){ stopMic(); releasePlayer(); ws=null; if(code==4001||code==4003){ prefs.edit().putBoolean("paired",false).apply(); showPair("Pairing revoked. Enter a new Pair Code.") } else { setEnded(); scheduleReconnect() } }
            override fun onFailure(w:WebSocket,t:Throwable,r:Response?){ stopMic(); releasePlayer(); ws=null; runOnUiThread { status.text="Disconnected: ${t.message}"; orb.state="DISCONNECTED"; endConversation.visibility=View.GONE; startConversation.visibility=View.VISIBLE }; scheduleReconnect() }
        })
    }

    private fun scheduleReconnect(){
        if(intentionalVoiceEnd) return

        if(!prefs.getBoolean("paired",false)) return

        window.decorView.postDelayed({

            if(!intentionalVoiceEnd && ws==null && prefs.getBoolean("paired",false)){

                showVoice()

                connect()

            }

        },1500)

    }


    private fun startMic(){
        if(ActivityCompat.checkSelfPermission(this,Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED){ ActivityCompat.requestPermissions(this,arrayOf(Manifest.permission.RECORD_AUDIO),42); return }
        if(micRunning)return
        val min=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT).coerceAtLeast(2048)
        recorder=AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION,16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,min*2)
        recorder?.startRecording(); micRunning=true
        Thread {
            val buf=ByteArray(1024)
            while(micRunning){ val n=try{recorder?.read(buf,0,buf.size)?:-1}catch(_:Exception){-1}; if(n>0){ orb.audioLevel(pcmLevel(buf,n)); ws?.send(ByteString.of(*buf.copyOf(n))) } }
        }.apply { name="JarvisPhoneMic"; isDaemon=true; start() }
    }
    private fun stopMic(){ micRunning=false; try{recorder?.stop()}catch(_:Exception){}; recorder?.release(); recorder=null }
    private val audioLock=Any()

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
                val created=AudioTrack(AudioManager.STREAM_MUSIC,24000,AudioFormat.CHANNEL_OUT_MONO,AudioFormat.ENCODING_PCM_16BIT,min*4,AudioTrack.MODE_STREAM)
                if(created.state!=AudioTrack.STATE_INITIALIZED){
                    try{ created.release() }catch(_:Exception){}
                    null
                }else{
                    created.play()
                    player=created
                    created
                }
            }catch(_:Exception){ null }
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

    override fun onRequestPermissionsResult(requestCode:Int,permissions:Array<out String>,grantResults:IntArray){ super.onRequestPermissionsResult(requestCode,permissions,grantResults); if(requestCode==42){ if(grantResults.firstOrNull()==PackageManager.PERMISSION_GRANTED) startMic() else ui("Microphone permission is required for Live Voice") } }

    private fun setVoiceState(s:String)=runOnUiThread { status.text=s.lowercase().replaceFirstChar { it.uppercase() }; orb.state=s }
    private val transcriptTurns = ArrayDeque<String>()
    private fun appendTranscript(speaker:String,text:String){ if(text.isBlank()) return; runOnUiThread {
        val who=if(speaker.equals("user",true)) "YOU" else "JARVIS"
        transcriptTurns.addLast("$who  $text")
        while(transcriptTurns.size > 4) transcriptTurns.removeFirst()
        transcript.text=transcriptTurns.joinToString("\n\n")
        transcriptScroll.post { transcriptScroll.fullScroll(View.FOCUS_DOWN) }
    }}
    private fun endVoice(){ intentionalVoiceEnd=true; stopMic(); releasePlayer(); val current=ws; ws=null; current?.close(1000,"conversation ended"); setEnded() }
    private fun setEnded()=runOnUiThread { status.text=getString(R.string.conversation_ended); orb.state="SLEEPING"; endConversation.visibility=View.GONE; startConversation.visibility=View.VISIBLE }
    private fun pcmLevel(b:ByteArray,n:Int):Float { if(n<2)return 0f; var sum=0.0; var count=0; var i=0; while(i+1<n){ val v=((b[i+1].toInt() shl 8) or (b[i].toInt() and 255)).toShort().toInt(); sum+=v.toDouble()*v;count++;i+=2 }; if(count==0)return 0f; return (sqrt(sum/count)/3500.0).toFloat().coerceIn(0f,1f) }

    private fun executeCapability(w:WebSocket,m:JSONObject){ val cap=m.optString("capability"); val a=m.optJSONObject("args")?:JSONObject()
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
                    result=uploadTransferFile(a)
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
        "open_url"->{ startActivity(Intent(Intent.ACTION_VIEW,Uri.parse(a.getString("url"))).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
        "app.launch"->{ val query=a.optString("package").ifBlank { a.optString("app") }.ifBlank { a.optString("name") }; val pkg=resolveAppPackage(query)?:error("App not found: $query"); val i=packageManager.getLaunchIntentForPackage(pkg)?:error("App has no launch activity: $pkg"); startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); result="opened $pkg" }
        "app.close"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.global("home") }
        "android.settings.open"->{ val page=a.optString("page").ifBlank { a.optString("section") }; startActivity(settingsIntent(page)); result=if(page.isBlank()) "opened Android Settings" else "opened Android Settings: $page" }
        "camera.capture"->{ result=captureCameraFrame(a.optString("facing","back")) }
        "file.upload"->{ result=uploadTransferFile(a) }
        "file.receive"->{ result=receiveTransferFile(a) }
        "android.ui.inspect"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.inspect(a.optInt("max_nodes",120)).toString() }
        "android.ui.click"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.click(a.optString("text"),a.optString("view_id")) }
        "android.ui.text"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.setText(a.getString("text"),a.optString("target_text"),a.optString("view_id")) }
        "android.ui.scroll"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.scroll(a.optString("direction","down")) }
        "android.ui.global"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.global(a.getString("action")) }
        "android.screen.lock"->{ val svc=JarvisAccessibilityService.instance?:error("Accessibility control is disabled on the phone"); result=svc.global("lock") }
        "android.screen.wake"->{ val pm=getSystemService(POWER_SERVICE) as PowerManager; if(!pm.isInteractive){ @Suppress("DEPRECATION") val wl=pm.newWakeLock(PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP,"jarvis:wake"); wl.acquire(3000) }; result="screen awake; device authentication is still required" }
        else->{ok=false;result="Unsupported capability: $cap"}
    }}catch(e:Exception){ok=false;result=e.message?:e.toString()}; w.send(JSONObject().put("type","capability.result").put("call_id",m.optString("call_id")).put("ok",ok).put("result",result).toString()) }

    private fun showAttachmentInbox(){
        ws?.send(JSONObject().put("type","attachment.list").toString())
        val list=ListView(this)
        attachmentDialog=AlertDialog.Builder(this).setTitle("Attachments").setView(list)
            .setNegativeButton("Close",null).create()
        list.tag="attachment-list"
        list.setOnItemClickListener { _,_,position,_ ->
            val item=synchronized(attachmentItems){ attachmentItems.values.toList().getOrNull(position) }?:return@setOnItemClickListener
            val actions=arrayOf("Open","Save As","Share")
            AlertDialog.Builder(this).setTitle(item.optString("name")).setItems(actions){ _,which ->
                val action=when(which){0->"open";1->"save";else->"share"}
                if(action=="save"){
                    val intent=Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                        .setType("application/octet-stream").putExtra(Intent.EXTRA_TITLE,item.optString("name"))
                    pendingAttachment=Pair(item.getString("id"),action)
                    startActivityForResult(intent,91)
                }else requestAttachment(item.getString("id"),action)
            }.show()
        }
        attachmentDialog?.show(); refreshAttachmentDialog()
    }

    private fun refreshAttachmentDialog(){
        val list=attachmentDialog?.findViewById<ListView>(android.R.id.list)
            ?: (attachmentDialog?.window?.decorView?.findViewWithTag<View>("attachment-list") as? ListView)
        val names=synchronized(attachmentItems){ attachmentItems.values.map { "${it.optString("name")} · ${it.optLong("size")} bytes · ${it.optString("status","pending")}" } }
        list?.adapter=ArrayAdapter(this,android.R.layout.simple_list_item_1,names)
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

    private fun uploadTransferFile(a:JSONObject):String {
        val source=a.optString("source").trim(); if(source.isBlank()) error("source is required")
        val uri=if(source.startsWith("content://")) Uri.parse(source) else Uri.fromFile(File(source))
        val displayName=if(source.startsWith("content://")){
            contentResolver.query(uri,arrayOf(android.provider.OpenableColumns.DISPLAY_NAME),null,null,null)?.use { cursor ->
                if(cursor.moveToFirst())cursor.getString(0) else "file"
            }?:"file"
        }else File(source).name
        val digest=MessageDigest.getInstance("SHA-256"); var total=0L
        val body=object:RequestBody(){
            override fun contentType()="application/octet-stream".toMediaType()
            override fun writeTo(sink:okio.BufferedSink){
                val input=contentResolver.openInputStream(uri)?:error("Cannot open source file: $source")
                input.use { stream -> val buf=ByteArray(1024*1024); while(true){ val n=stream.read(buf); if(n<=0) break; digest.update(buf,0,n); total+=n; sink.write(buf,0,n) } }
            }
        }
        val req=Request.Builder().url(a.getString("url")).header("X-File-Name",displayName.replace(Regex("[\\/]+"),"_")).put(body).build()
        client.newCall(req).execute().use { r -> if(!r.isSuccessful) error("Upload failed: HTTP ${r.code}"); val server=JSONObject(r.body?.string()?:"{}"); val hash=digest.digest().joinToString(""){"%02x".format(it)}; if(server.optString("sha256")!=hash||server.optLong("size",-1)!=total) error("Server upload verification failed"); return JSONObject().put("name",displayName).put("sha256",hash).put("size",total).toString() }
    }

    private fun receiveTransferFile(a:JSONObject):String {
        if(Build.VERSION.SDK_INT<29) error("file.receive to shared Downloads is unsupported on Android below 10 without legacy storage permission")
        val name=a.optString("name","file").replace(Regex("[\\/]+"),"_")
        val values=ContentValues().apply { put(MediaStore.MediaColumns.DISPLAY_NAME,name); put(MediaStore.MediaColumns.MIME_TYPE,"application/octet-stream"); if(Build.VERSION.SDK_INT>=29) put(MediaStore.MediaColumns.RELATIVE_PATH,Environment.DIRECTORY_DOWNLOADS+"/MARK-LIV") }
        val collection=MediaStore.Downloads.EXTERNAL_CONTENT_URI
        val outUri=contentResolver.insert(collection,values)?:error("Cannot create destination file")
        val digest=MessageDigest.getInstance("SHA-256"); var total=0L
        try {
            val req=Request.Builder().url(a.getString("url")).get().build()
            client.newCall(req).execute().use { r -> if(!r.isSuccessful) error("Download failed: HTTP ${r.code}"); val input=r.body?.byteStream()?:error("Empty download body"); val output=contentResolver.openOutputStream(outUri)?:error("Cannot open destination file"); input.use { src -> output.use { dst -> val buf=ByteArray(1024*1024); while(true){ val n=src.read(buf); if(n<=0) break; dst.write(buf,0,n); digest.update(buf,0,n); total+=n } } } }
            val hash=digest.digest().joinToString(""){"%02x".format(it)}; if(hash!=a.getString("sha256")||total!=a.getLong("size")) error("Downloaded file failed SHA-256/size verification")
            return JSONObject().put("saved_to",outUri.toString()).put("sha256",hash).put("size",total).toString()
        } catch(e:Exception){ contentResolver.delete(outUri,null,null); throw e }
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

    override fun onDestroy(){ stopMic(); try{player?.stop()}catch(_:Exception){}; player?.release(); player=null; ws?.close(1000,"activity closed"); super.onDestroy() }
    private fun ui(s:String)=runOnUiThread{status.text=s}
    private fun pairUi(s:String)=runOnUiThread{pairStatus.text=s}
    private fun b64(b:ByteArray)=java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(b)
    private fun unb64(s:String)=java.util.Base64.getUrlDecoder().decode(s)
    private fun lanClient():OkHttpClient { val tm=object:X509TrustManager{override fun getAcceptedIssuers()=arrayOf<X509Certificate>();override fun checkClientTrusted(c:Array<X509Certificate>,a:String){};override fun checkServerTrusted(c:Array<X509Certificate>,a:String){}}; val sc=SSLContext.getInstance("TLS");sc.init(null,arrayOf<TrustManager>(tm),SecureRandom());return OkHttpClient.Builder().sslSocketFactory(sc.socketFactory,tm).hostnameVerifier{_,_->true}.pingInterval(20,TimeUnit.SECONDS).build() }
}
