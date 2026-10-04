"""Mark native desktop companion for Windows, Linux and macOS.
The server remains headless; text, microphone and speaker live on this client.
"""
from __future__ import annotations
import base64, json, os, queue, socket, threading, uuid, subprocess, sys, shutil, signal, time, secrets
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
from desktop_ui import DesktopWindow, AttachmentDialog, TextValue
import requests, websocket
from urllib.parse import urlparse
import ipaddress
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from runtime.core.network_config import PUBLIC_BASE_URL, DISCOVERY_PORT

APP_DIR=Path.home()/".mark-companion"; APP_DIR.mkdir(exist_ok=True)
STATE=APP_DIR/"state.json"
LOG_DIR=APP_DIR/"logs"; LOG_DIR.mkdir(exist_ok=True)
error_log=logging.getLogger('mark.companion')
error_log.setLevel(logging.WARNING)
error_handler=RotatingFileHandler(LOG_DIR/'error.log',maxBytes=2_000_000,backupCount=2,encoding='utf-8')
error_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
error_log.addHandler(error_handler)

def log_unhandled(kind, value, traceback):
    error_log.error('Unhandled desktop exception', exc_info=(kind, value, traceback))
    sys.__excepthook__(kind, value, traceback)
sys.excepthook=log_unhandled
NATIVE_CAPABILITIES=['jarvis.command','notifications.receive','open_url','app.launch','app.close','desktop.command','audio.volume','camera.capture','screen.capture','file.upload','file.receive','attachment.inbox','legacy.action']
def b64(b): return base64.urlsafe_b64encode(b).decode().rstrip('=')
def unb64(s): return base64.urlsafe_b64decode(s+'='*(-len(s)%4))
def load():
    try:return json.loads(STATE.read_text())
    except Exception:return {}
def save(d): STATE.write_text(json.dumps(d,indent=2))

def identity(st):
    if st.get('device_id') and st.get('private_key'): return st
    k=Ed25519PrivateKey.generate(); st.update(device_id=str(uuid.uuid4()),name=socket.gethostname(),private_key=b64(k.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())),public_key=b64(k.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw))); save(st); return st
def priv(st): return Ed25519PrivateKey.from_private_bytes(unb64(st['private_key']))
def verify(pub,data,sig):
    try: Ed25519PublicKey.from_public_bytes(unb64(pub)).verify(unb64(sig),data); return True
    except Exception:return False

class App:
    def __init__(self):
        self.st=identity(load()); self.ws=None; self.mic=None; self.out=None; self.running=False; self.speaking=False
        self.muted=False;self.input_device=None;self.output_device=None
        self.attachments={}; self.sent_attachments={}; self.attachment_mode="received"; self.pending_attachment=None; self.deferred_attachment_pick=None; self.assistant_turn_complete=False
        self.qt_app=QApplication.instance() or QApplication(sys.argv)
        self.root=DesktopWindow(self)
        self.code=TextValue(self.root.code_input)
        self.cmd=TextValue(self.root.command_input)
        self.status=type('Status', (), {'set': lambda _, value: self.root.after(0, lambda: self.root.set_status(value))})()
        self.log=self.root.log
        if self.st.get('paired'): self.root.after(300,self.connect)
    def note(self,s):
        self.log.append_log(str(s))
    def fault(self,context,exc):
        error_log.error('%s: %s: %s',context,type(exc).__name__,str(exc).split('?',1)[0])
        self.note(f'{context}: {exc}')
    def discover(self, code, timeout=4.0):
        msg=json.dumps({'magic':'ASSISTANT_DISCOVER_V1','code':code}).encode()
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); sock.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1); sock.settimeout(0.5)
        try:
            deadline=time.time()+timeout
            while time.time()<deadline:
                sock.sendto(msg,('255.255.255.255',DISCOVERY_PORT))
                try:
                    data,_=sock.recvfrom(4096); r=json.loads(data.decode())
                    if r.get('magic')=='ASSISTANT_DISCOVER_V1' and r.get('code')==code:return r['server'].rstrip('/')
                except socket.timeout: pass
            raise RuntimeError('Server with this Pair Code was not found on the local network')
        finally:sock.close()
    def discover_paired(self, timeout=4.0):
        """Find a paired server on the same LAN using mutual signed identity."""
        device_id=self.st['device_id']; nonce=secrets.token_urlsafe(24)
        request={'magic':'ASSISTANT_DISCOVER_V1','device_id':device_id,'nonce':nonce,
                 'signature':b64(priv(self.st).sign(f'discover:{device_id}:{nonce}'.encode()))}
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1);sock.settimeout(.5)
        try:
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                sock.sendto(json.dumps(request).encode(),('255.255.255.255',DISCOVERY_PORT))
                try:data,_=sock.recvfrom(4096)
                except socket.timeout:continue
                try:
                    reply=json.loads(data.decode())
                    base=str(reply['server']).rstrip('/')
                    if (reply.get('magic')=='ASSISTANT_DISCOVER_V1' and reply.get('nonce')==nonce
                            and reply.get('device_id')==self.st.get('server_id')
                            and reply.get('public_key')==self.st.get('server_key')
                            and base.startswith('http://')
                            and verify(self.st['server_key'],f'discover:{device_id}:{nonce}:{base}'.encode(),reply.get('server_signature',''))):
                        return base
                except (ValueError,KeyError,TypeError):continue
        finally:sock.close()
        return None
    def _tls_verify(self, url):
        """Public HTTPS must use trusted certificates; private LAN may be self-signed."""
        hostname = urlparse(str(url)).hostname or ''
        if hostname.lower() == 'localhost':
            return False
        try:
            return not ipaddress.ip_address(hostname).is_private
        except ValueError:
            return True
    def pair(self):
        code=self.code.get().strip().upper()
        if len(code)!=6:
            self.root.show_login(paired=False,message='Enter the 6-character Pair Code from the server.')
            return
        if getattr(self,'_pairing',False):return
        self._pairing=True
        self.root.pair_button.setEnabled(False)
        self.status.set('Pairing')
        threading.Thread(target=self._pair_worker,args=(code,),daemon=True).start()
    def _pair_worker(self,code):
        base=PUBLIC_BASE_URL
        try:
            response=requests.get(f'{base}/api/pairing/offer/{code}',timeout=8,verify=self._tls_verify(base))
            if response.status_code==502:
                base=self.discover(code)
                response=requests.get(f'{base}/api/pairing/offer/{code}',timeout=8,verify=self._tls_verify(base))
            if response.status_code==404:
                raise ValueError('Pair Code invalid or expired. Generate a new code on the server.')
            response.raise_for_status()
            try: offer=response.json()
            except ValueError: raise ValueError('Pairing endpoint did not return JSON. Check the server address and tunnel.') from None
            if not isinstance(offer,dict) or not all(offer.get(k) for k in ('nonce','public_key','device_id')):
                raise ValueError(str(offer.get('error') or 'Pairing offer is incomplete; check the server and Pair Code.') if isinstance(offer,dict) else 'Pairing offer is invalid.')
            peer={'device_id':self.st['device_id'],'name':self.st['name'],'public_key':self.st['public_key']}
            sig=b64(priv(self.st).sign(f"{offer['nonce']}:{code}".encode()))
            reply=requests.post(f'{base}/api/pairing/accept',json={'code':code,'peer':peer,'signature':sig,'capabilities':list(NATIVE_CAPABILITIES)},timeout=8,verify=self._tls_verify(base))
            if not reply.ok:
                try: reason=reply.json().get('error')
                except ValueError: reason=None
                raise ValueError(str(reason or f'Pairing rejected (HTTP {reply.status_code}).'))
            self.st.update(server=base,server_key=offer['public_key'],server_id=offer['device_id'],paired=True)
            save(self.st)
            self.root.after(0,self._paired)
        except Exception as exc:
            message=str(exc)
            if isinstance(exc,ValueError):self.note('Pairing: '+message)
            else:self.fault('Pair failed',exc)
            self.root.after(0,lambda message=message:self._pair_failed(message))
    def _paired(self):
        self._pairing=False
        self.root.pair_button.setEnabled(True)
        self.root.show_connecting()
        self.connect()
    def _pair_failed(self,message):
        self._pairing=False
        self.root.pair_button.setEnabled(True)
        self.status.set('Disconnected')
        self.root.show_login(paired=False,message=message)
    def connect(self):
        if self.ws:return
        base=getattr(self,'_lan_base',None) or self.st.get('server');
        if not base:
            self.root.show_login(paired=False,message='Enter a Pair Code to connect.')
            return
        self.root.show_connecting()
        wsbase=base.replace('https://','wss://').replace('http://','ws://'); url=f"{wsbase}/ws/device?device_id={self.st['device_id']}"
        ws=websocket.WebSocketApp(url,on_message=self.on_message,on_data=self.on_data,on_close=self.on_close,on_error=self.on_error)
        self.ws=ws
        threading.Thread(target=lambda:ws.run_forever(sslopt=({'cert_reqs':0} if not self._tls_verify(base) else None)),daemon=True).start()
    def on_error(self,ws,error):
        if ws is not self.ws:return
        if getattr(error,'status_code',None)==502:
            self.fault('Remote gateway unavailable (HTTP 502)',RuntimeError('Check the server and Cloudflare tunnel; looking for the paired server on this LAN'))
            if not getattr(self,'_lan_base',None):
                self._fallback_ws=ws
                self.root.after(0,lambda:self.root.show_connection_error('Remote gateway is unavailable. Checking this LAN…'))
                threading.Thread(target=self._retry_on_lan,args=(ws,),daemon=True).start()
            return
        self.fault('Connection error',error)
        self.root.after(0,lambda:self.root.show_connection_error('Connection failed. Check the server and retry.'))
    def _retry_on_lan(self,failed_ws):
        base=self.discover_paired()
        if failed_ws is not self.ws:return
        self._fallback_ws=None
        self.ws=None
        if base:
            self._lan_base=base
            self.root.after(0,self.connect)
        else:
            self.root.after(0,lambda:self.root.show_connection_error('Remote gateway returned HTTP 502. Start the server and check its Cloudflare tunnel, then reconnect.'))
    def on_message(self,_w,text):
        # websocket-client also calls on_message for binary audio frames.
        if not isinstance(text,str):return
        try:m=json.loads(text)
        except json.JSONDecodeError:
            self.note('Ignored malformed server text frame')
            return
        if not isinstance(m,dict):return
        typ=m.get('type')
        if typ=='challenge':
            ch=m['challenge']; expected=self.st.get('server_key','')
            if not verify(expected,f"{self.st['device_id']}:{ch}".encode(),m.get('server_signature','')): self.note('Server identity verification failed'); self.disconnect(); return
            self.ws.send(json.dumps({'type':'proof','signature':b64(priv(self.st).sign(ch.encode())),'capabilities':list(NATIVE_CAPABILITIES)}))
        elif typ=='ready':
            self.root.after(0,self.root.show_dashboard)
            self.start_audio()
        elif typ=='status':
            state=str(m.get('state','')).upper()
            # Keep one stable input stream for the whole interactive session.
            # Only gate network transmission while JARVIS is speaking; stopping and
            # restarting PortAudio streams each turn caused the desktop companion
            # to become silent after the first response on some devices/backends.
            if state=='SPEAKING':
                self.speaking=True; self.assistant_turn_complete=False
            elif state=='THINKING':
                self.speaking=False; self.assistant_turn_complete=False
            elif state in ('LISTENING','ACTIVE'):
                self.speaking=False
            label = 'Listening' if state=='ACTIVE' else state.title()
            self.root.after(0, lambda value=label: self.status.set(value))
        elif typ=='log': self.note(f"{m.get('speaker','JARVIS')}: {m.get('text','')}")
        elif typ=='attachment.pick.request':
            self.deferred_attachment_pick=m
            if self.ws:self.ws.send(json.dumps({'type':'attachment.picker.received','request_id':m.get('request_id','')}))
            if self.assistant_turn_complete:self.root.after(0,self._launch_deferred_attachment_picker)
        elif typ=='assistant.turn.complete':
            self.assistant_turn_complete=True
            if self.deferred_attachment_pick:self.root.after(0,self._launch_deferred_attachment_picker)
        elif typ=='attachment.transfer.status': self.note(str(m.get('message') or 'Attachment transfer updated'))
        elif typ=='attachment.inbox':
            self.attachments={x['id']:x for x in m.get('attachments',[])}
            self.root.after(0,self.refresh_attachment_list)
        elif typ=='attachment.sent':
            self.sent_attachments={x['id']:x for x in m.get('attachments',[])}
            self.root.after(0,self.refresh_attachment_list)
        elif typ in ('attachment.sent.new','attachment.sent.update'):
            item=m.get('attachment') or {}
            if item.get('id'):
                self.sent_attachments[item['id']]=item
                self.root.after(0,self.refresh_attachment_list)
        elif typ=='attachment.new':
            item=m.get('attachment') or {}
            if item.get('id'):
                self.attachments[item['id']]=item
                self.note('New attachment: '+str(item.get('name')))
                self.root.after(0,self.refresh_attachment_list)
        elif typ=='attachment.download.ready':
            if self.pending_attachment and m.get('id')==self.pending_attachment.get('id'):
                pending=self.pending_attachment; self.pending_attachment=None
                threading.Thread(target=self._download_attachment,args=(m,pending),daemon=True).start()
        elif typ=='attachment.error': self.note('Attachment: '+str(m.get('error')))
        elif typ=='capability.call': self.capability(m)
    def on_data(self,_w,data,opcode,_fin):
        if opcode==websocket.ABNF.OPCODE_BINARY and self.out:
            self.speaking=True
            self.root.hud.set_audio_level(min(1.0, (sum(abs(int.from_bytes(data[i:i+2], 'little', signed=True)) for i in range(0, min(len(data), 512), 2)) / 256) / 12000))
            try:self.out.write(data)
            except Exception as e:self.fault('Audio output error',e)
    def start_audio(self):
        if self.running:return
        self.running=True
        try:
            import sounddevice as sd
            self.out=sd.RawOutputStream(samplerate=24000,channels=1,dtype='int16',device=self.output_device); self.out.start()
            def cb(indata,frames,time_info,status):
                if self.running and not self.speaking and not self.muted and self.ws and self.ws.sock and self.ws.sock.connected:
                    try:self.ws.send(bytes(indata),opcode=websocket.ABNF.OPCODE_BINARY)
                    except Exception:pass
            self.mic=sd.RawInputStream(samplerate=16000,channels=1,dtype='int16',blocksize=1024,callback=cb,device=self.input_device); self.mic.start()
        except Exception as e:self.running=False; self.fault('Audio device error',e)
    def pause_mic(self):
        # Compatibility hook: do not stop/recreate the PortAudio stream per turn.
        self.speaking=True
    def resume_mic(self):
        # The callback remains alive; transmission resumes immediately.
        self.speaking=False
    def toggle_mic(self):
        self.muted=not self.muted
        self.root.mute_action.setText('Unmute microphone' if self.muted else 'Mute microphone')
        self.note('Microphone muted' if self.muted else 'Microphone active')
    def interrupt(self):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            self.ws.send(json.dumps({'type':'jarvis.interrupt'}))
    def choose_audio_devices(self):
        try:
            import sounddevice as sd
            devices=sd.query_devices()
        except Exception as exc:
            QMessageBox.warning(self.root,'Audio devices',str(exc));return
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QDialogButtonBox
        dialog=QDialog(self.root);dialog.setWindowTitle('Audio devices')
        layout=QVBoxLayout(dialog);inputs=QComboBox();outputs=QComboBox()
        inputs.addItem('System default',None);outputs.addItem('System default',None)
        for i,device in enumerate(devices):
            if device['max_input_channels']>0:inputs.addItem(f"{device['name']} ({i})",i)
            if device['max_output_channels']>0:outputs.addItem(f"{device['name']} ({i})",i)
        for box,selected in ((inputs,self.input_device),(outputs,self.output_device)):
            at=box.findData(selected)
            box.setCurrentIndex(max(at,0))
        layout.addWidget(QLabel('Microphone'));layout.addWidget(inputs)
        layout.addWidget(QLabel('Speaker'));layout.addWidget(outputs)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        self.input_device=inputs.currentData();self.output_device=outputs.currentData()
        if self.ws:
            self.running=False
            for stream in (self.mic,self.out):
                try:stream.stop();stream.close()
                except Exception:pass
            self.mic=self.out=None
            self.start_audio()
    def on_close(self, *_args):
        if _args and _args[0] is getattr(self,'_fallback_ws',None):return
        if _args and _args[0] is not self.ws:return
        self.running=False
        self.speaking=False
        for x in (self.mic,self.out):
            try:x.stop(); x.close()
            except Exception:pass
        self.mic=self.out=None
        self.ws=None
        revoked=len(_args)>1 and _args[1] in (4001,4003)
        if revoked:
            self.st['paired']=False
            save(self.st)
        message=('Device pairing was rejected. Enter a new Pair Code.' if revoked
                 else 'Connection closed. Reconnect to continue.')
        self.root.after(0,lambda message=message:(self.status.set('Disconnected'),self.root.show_connection_error(message)))
    def send(self):
        text=self.cmd.get().strip()
        if text and self.ws: self.ws.send(json.dumps({'type':'jarvis.command','text':text})); self.note('YOU: '+text); self.cmd.set('')
    def _launch_app(self, name):
        name=str(name or '').strip()
        if not name: raise ValueError('app name is required')
        if sys.platform == 'win32':
            # start uses Windows App Paths/registered shell names and also accepts paths.
            subprocess.Popen(['cmd','/c','start','',name], creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        elif sys.platform == 'darwin':
            subprocess.Popen(['open','-a',name])
        else:
            exe=shutil.which(name) or shutil.which(name.lower().replace(' ', '-')) or shutil.which(name.lower().replace(' ', ''))
            if exe: subprocess.Popen([exe])
            else:
                # gtk-launch resolves desktop application IDs without requiring the executable name.
                r=subprocess.run(['gtk-launch', name], capture_output=True, text=True) if shutil.which('gtk-launch') else subprocess.CompletedProcess([], 127, '', 'gtk-launch not installed')
                if r.returncode: raise FileNotFoundError(f'app not found: {name}')
        return f'launched {name}'
    def _close_app(self, name):
        name=str(name or '').strip()
        if not name: raise ValueError('app name is required')
        if sys.platform == 'win32':
            # Resolve both a supplied exe and a natural process name. /T closes its child tree.
            image=name if name.lower().endswith('.exe') else name+'.exe'
            r=subprocess.run(['taskkill','/IM',image,'/T'],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if r.returncode: raise RuntimeError((r.stderr or r.stdout or f'{name} is not running').strip())
        elif sys.platform == 'darwin':
            r=subprocess.run(['osascript','-e',f'tell application {json.dumps(name)} to quit'],capture_output=True,text=True)
            if r.returncode: raise RuntimeError((r.stderr or f'{name} is not running').strip())
        else:
            r=subprocess.run(['pkill','-TERM','-f',name],capture_output=True,text=True)
            if r.returncode not in (0,1): raise RuntimeError((r.stderr or 'close failed').strip())
            if r.returncode==1: raise RuntimeError(f'{name} is not running')
        return f'closed {name}'
    def _desktop_command(self, a):
        action=str(a.get('action') or '').lower().strip()
        if action=='lock':
            if sys.platform=='win32': subprocess.Popen(['rundll32.exe','user32.dll,LockWorkStation'])
            elif sys.platform=='darwin': subprocess.Popen(['/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession','-suspend'])
            else: subprocess.Popen(['loginctl','lock-session'])
            return 'desktop locked'
        raise ValueError('unsupported desktop.command action: '+action)
    def _capture_camera(self, args):
        # Windows, Linux and macOS share this runtime. OpenCV selects the host
        # backend; camera identity is never guessed from an OS or application name.
        from runtime.actions.screen_processor import _capture_camera
        requested=str((args or {}).get('facing') or 'default').strip().lower()
        image_bytes, mime_type = _capture_camera()
        if not image_bytes or not str(mime_type).startswith('image/'):
            raise RuntimeError('Camera returned invalid image data.')
        return json.dumps({
            'mime_type': str(mime_type),
            'data': base64.b64encode(image_bytes).decode('ascii'),
            # Generic desktop webcams do not expose a reliable front/back semantic.
            # Report the real selection rather than pretending the requested facing.
            'facing': 'default',
            'requested_facing': requested,
        })
    def _capture_screen(self):
        from runtime.actions.screen_processor import _capture_screen
        image_bytes,mime_type=_capture_screen()
        if not image_bytes or not str(mime_type).startswith('image/'):
            raise RuntimeError('Desktop screen capture did not return an image')
        return json.dumps({'mime_type':str(mime_type),'data':base64.b64encode(image_bytes).decode('ascii')})
    def _launch_deferred_attachment_picker(self):
        req=self.deferred_attachment_pick
        if not req:return
        self.deferred_attachment_pick=None
        if self.ws:self.ws.send(json.dumps({'type':'attachment.picker.opened','request_id':req.get('request_id','')}))
        selected=list(QFileDialog.getOpenFileNames(self.root,'Choose attachments')[0])
        if self.ws:
            if selected:self.ws.send(json.dumps({'type':'attachment.sources.selected','request_id':req.get('request_id',''),'sources':selected}))
            else:self.ws.send(json.dumps({'type':'attachment.source.cancelled','request_id':req.get('request_id','')}))

    def show_attachments(self):
        if getattr(self,'attachment_window',None) and self.attachment_window.isVisible():
            self.attachment_window.raise_(); self.attachment_window.activateWindow(); return
        self.attachment_mode='received'
        self.attachment_window=AttachmentDialog(self)
        self.attachment_list=self.attachment_window.items
        self.attachment_window.show()
        self.refresh_attachment_list()
        if self.ws:self.ws.send(json.dumps({'type':'attachment.list'}))

    def _show_attachment_mode(self,mode):
        self.attachment_mode=mode
        self.attachment_window.set_mode(mode)
        self.refresh_attachment_list()

    def refresh_attachment_list(self):
        widget=getattr(self,'attachment_list',None)
        if widget is None or not self.attachment_window.isVisible():return
        items=self.sent_attachments if self.attachment_mode=='sent' else self.attachments
        self.attachment_order=list(items)
        widget.clear()
        for key in self.attachment_order:
            item=items[key]
            if self.attachment_mode=='sent':
                status='Stored on server' if item.get('destination_device')=='server' else ('Saved by recipient' if item.get('status')=='saved' else 'Sent to inbox')
                widget.addItem(f"{item['name']}  ·  To {item.get('destination_name','device')}  ·  {status}")
            else:
                widget.addItem(f"{item['name']}  ·  {item['size']:,} bytes  ·  {item.get('status','pending')}")

    def request_attachment(self,action):
        if self.attachment_mode!='received':return
        widget=getattr(self,'attachment_list',None)
        if widget is None or widget.currentRow()<0:return
        item=self.attachments[self.attachment_order[widget.currentRow()]]
        if action=='share':
            QMessageBox.information(self.root,'Share attachment','Save the attachment first, then use your desktop share application. Native share sheets are not available consistently on every desktop OS.')
            return
        target=None
        if action=='save':
            target=QFileDialog.getSaveFileName(self.root,'Save attachment',item['name'])[0]
            if not target:return
        if not self.ws:self.note('Connect to receive attachments');return
        self.pending_attachment={'id':item['id'],'action':action,'target':target}
        self.ws.send(json.dumps({'type':'attachment.download','id':item['id']}))

    def _download_attachment(self,info,pending):
        import hashlib, tempfile
        try:
            name=Path(str(info['name'])).name
            if pending['action']=='save': dest=Path(pending['target'])
            else:
                cache=APP_DIR/'attachment-cache';cache.mkdir(exist_ok=True)
                dest=cache/(str(pending['id'])+'-'+name)
            dest.parent.mkdir(parents=True,exist_ok=True)
            tmp=dest.with_name(dest.name+'.part'); h=hashlib.sha256(); size=0
            try:
                with requests.get(info['url'],stream=True,timeout=300,verify=self._tls_verify(info['url'])) as resp:
                    resp.raise_for_status()
                    with open(tmp,'wb') as out:
                        for chunk in resp.iter_content(1024*1024):
                            if chunk:out.write(chunk);h.update(chunk);size+=len(chunk)
                if h.hexdigest()!=info['sha256'] or size!=int(info['size']):
                    raise RuntimeError('Attachment failed SHA-256/size verification')
                os.replace(tmp,dest)
            except Exception:
                tmp.unlink(missing_ok=True);raise
            if pending['action']=='save' and self.ws:
                self.ws.send(json.dumps({'type':'attachment.saved','id':pending['id']}))
            if pending['action']=='open':
                if sys.platform=='win32':os.startfile(str(dest))
                elif sys.platform=='darwin':subprocess.Popen(['open',str(dest)])
                else:subprocess.Popen(['xdg-open',str(dest)])
            self.note('Attachment '+pending['action']+': '+str(dest))
        except Exception as exc:self.fault('Attachment failed',exc)

    def _file_upload(self, a):
        import hashlib
        source_name=str(a.get('source') or '').strip()
        if not source_name:
            selected=[]; done=threading.Event()
            def pick():
                try:selected.append(QFileDialog.getOpenFileName(self.root,'Attach a file')[0])
                finally:done.set()
            self.root.after(0,pick)
            if not done.wait(120):raise TimeoutError('File selection timed out')
            source_name=selected[0] if selected else ''
            if not source_name:raise RuntimeError('File selection cancelled')
        source=Path(source_name).expanduser()
        if not source.is_file(): raise FileNotFoundError(f'File not found: {source}')
        h=hashlib.sha256(); size=0
        def chunks():
            nonlocal size
            with open(source,'rb') as f:
                while True:
                    b=f.read(1024*1024)
                    if not b: break
                    h.update(b); size+=len(b); yield b
        r=requests.put(str(a['url']),data=chunks(),headers={'X-File-Name':source.name},timeout=300,verify=self._tls_verify(a['url'])); r.raise_for_status(); server=r.json()
        digest=h.hexdigest()
        if server.get('sha256')!=digest or int(server.get('size',-1))!=size: raise RuntimeError('Server upload verification failed')
        return json.dumps({'name':source.name,'stored_name':server.get('name',source.name),'sha256':digest,'size':size})
    def _file_receive(self, a):
        import hashlib
        name=Path(str(a.get('name') or 'file')).name
        requested=str(a.get('destination') or '').strip()
        dest=(Path(requested).expanduser() if requested else Path.home()/'Downloads'/name)
        if dest.exists() and dest.is_dir(): dest=dest/name
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            stem,suffix=dest.stem,dest.suffix; i=1
            while dest.exists(): dest=dest.with_name(f'{stem}_{i}{suffix}'); i+=1
        tmp=dest.with_name(dest.name+'.part'); h=hashlib.sha256(); size=0
        try:
            with requests.get(str(a['url']),stream=True,timeout=300,verify=self._tls_verify(a['url'])) as r:
                r.raise_for_status()
                with open(tmp,'wb') as f:
                    for b in r.iter_content(1024*1024):
                        if not b: continue
                        f.write(b); h.update(b); size+=len(b)
            digest=h.hexdigest()
            if digest!=str(a.get('sha256')) or size!=int(a.get('size',-1)): raise RuntimeError('Downloaded file failed SHA-256/size verification')
            os.replace(tmp,dest)
            return json.dumps({'saved_to':str(dest),'sha256':digest,'size':size})
        except Exception:
            tmp.unlink(missing_ok=True); raise
    def capability(self,m):
        import webbrowser
        cap=m.get('capability'); a=m.get('args') or {}; ok=True; result='done'
        try:
            if cap=='open_url': webbrowser.open(str(a['url'])); result='opened URL'
            elif cap=='camera.capture': result=self._capture_camera(a)
            elif cap=='screen.capture': result=self._capture_screen()
            elif cap=='file.upload': result=self._file_upload(a)
            elif cap=='file.receive': result=self._file_receive(a)
            elif cap=='app.launch': result=self._launch_app(a.get('app') or a.get('name'))
            elif cap=='app.close': result=self._close_app(a.get('app') or a.get('name'))
            elif cap=='desktop.command': result=self._desktop_command(a)
            elif cap=='audio.volume':
                from local_runtime import invoke
                action=str(a.get('action') or 'up').strip().lower()
                mapped={'up':'volume_up','increase':'volume_up','down':'volume_down','decrease':'volume_down','mute':'mute','unmute':'unmute'}
                if action=='set':
                    value=max(0,min(100,int(a.get('value',a.get('percent',50)))))
                    result=invoke('computer_settings', {'action':'volume_set','value':value}, player=self.root)
                elif action in mapped:
                    result=invoke('computer_settings', {'action':mapped[action]}, player=self.root)
                else:
                    raise ValueError('Unsupported audio.volume action')
            elif cap=='legacy.action':
                from local_runtime import invoke
                tool=str(a.get('tool') or '').strip()
                if not tool:raise ValueError('Missing local tool name in legacy.action request')
                result=invoke(tool, a.get('parameters') or {}, player=self.root)
            else: ok=False; result='unsupported capability: '+str(cap)
        except Exception as e:ok=False; result=str(e); self.fault('Capability '+str(cap),e)
        self.ws.send(json.dumps({'type':'capability.result','call_id':m.get('call_id',''),'ok':ok,'result':result}))
    def disconnect(self):
        self._lan_base=None
        self.running=False
        self.speaking=False
        for x in (self.mic,self.out):
            try:x.stop();x.close()
            except Exception:pass
        self.mic=self.out=None
        if self.ws:
            try:self.ws.close()
            except Exception:pass
        self.ws=None
        self.root.show_login(paired=bool(self.st.get('paired')),
            message='Disconnected. Reconnect to continue.' if self.st.get('paired') else '')
    def prepare_new_pair_code(self):
        self.disconnect()
        self.root.show_login(paired=False)
    def close(self): self.root.close()
    def run(self): self.root.show(); return self.qt_app.exec()
if __name__=='__main__':App().run()
