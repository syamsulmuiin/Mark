package com.jarvis.companion

import android.app.Activity
import android.net.Uri
import android.content.ContentValues
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

object AttachmentTransfer {
    fun upload(activity: Activity, client: OkHttpClient, args: JSONObject): String {
        val source=args.optString("source").trim(); if(source.isBlank()) error("source is required")
        val uri=if(source.startsWith("content://")) Uri.parse(source) else Uri.fromFile(File(source))
        val displayName=if(source.startsWith("content://")){
            activity.contentResolver.query(uri,arrayOf(android.provider.OpenableColumns.DISPLAY_NAME),null,null,null)?.use { cursor ->
                if(cursor.moveToFirst())cursor.getString(0) else "file"
            }?:"file"
        }else File(source).name
        val digest=MessageDigest.getInstance("SHA-256"); var total=0L
        val body=object:RequestBody(){
            override fun contentType()="application/octet-stream".toMediaType()
            override fun writeTo(sink:okio.BufferedSink){
                val input=activity.contentResolver.openInputStream(uri)?:error("Cannot open source file: $source")
                input.use { stream -> val buf=ByteArray(1024*1024); while(true){ val n=stream.read(buf); if(n<=0) break; digest.update(buf,0,n); total+=n; sink.write(buf,0,n) } }
            }
        }
        val req=Request.Builder().url(args.getString("url")).header("X-File-Name",displayName.replace(Regex("[\\/]+"),"_")).put(body).build()
        client.newCall(req).execute().use { r ->
            if(!r.isSuccessful) error("Upload failed: HTTP ${r.code}")
            val server=JSONObject(r.body?.string()?:"{}"); val hash=digest.digest().joinToString(""){"%02x".format(it)}
            if(server.optString("sha256")!=hash||server.optLong("size",-1)!=total) error("Server upload verification failed")
            return JSONObject().put("name",displayName).put("sha256",hash).put("size",total).toString()
        }
    }
    fun receive(activity: Activity, client: OkHttpClient, args: JSONObject): String {
        if(Build.VERSION.SDK_INT<29) error("file.receive to shared Downloads is unsupported on Android below 10 without legacy storage permission")
        val name=args.optString("name","file").replace(Regex("[\\/]+"),"_")
        val values=ContentValues().apply { put(MediaStore.MediaColumns.DISPLAY_NAME,name); put(MediaStore.MediaColumns.MIME_TYPE,"application/octet-stream"); put(MediaStore.MediaColumns.RELATIVE_PATH,Environment.DIRECTORY_DOWNLOADS+"/MARK-LIV") }
        val outUri=activity.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,values)?:error("Cannot create destination file")
        val digest=MessageDigest.getInstance("SHA-256"); var total=0L
        try {
            client.newCall(Request.Builder().url(args.getString("url")).get().build()).execute().use { r ->
                if(!r.isSuccessful) error("Download failed: HTTP ${r.code}")
                val input=r.body?.byteStream()?:error("Empty download body"); val output=activity.contentResolver.openOutputStream(outUri)?:error("Cannot open destination file")
                input.use { src -> output.use { dst -> val buf=ByteArray(1024*1024); while(true){ val n=src.read(buf); if(n<=0) break; dst.write(buf,0,n); digest.update(buf,0,n); total+=n } } }
            }
            val hash=digest.digest().joinToString(""){"%02x".format(it)}
            if(hash!=args.getString("sha256")||total!=args.getLong("size")) error("Downloaded file failed SHA-256/size verification")
            return JSONObject().put("saved_to",outUri.toString()).put("sha256",hash).put("size",total).toString()
        } catch(e:Exception){ activity.contentResolver.delete(outUri,null,null); throw e }
    }
}
