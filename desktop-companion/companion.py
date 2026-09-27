"""MARK LIV native desktop companion for Windows, Linux and macOS.
The server remains headless; text, microphone and speaker live on this client.
"""
from __future__ import annotations
import base64, json, os, queue, socket, threading, uuid, subprocess, sys, shutil, signal, time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import requests, websocket, sounddevice as sd
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from runtime.core.network_config import PUBLIC_BASE_URL, DISCOVERY_PORT

APP_DIR=Path.home()/".mark-liv-companion"; APP_DIR.mkdir(exist_ok=True)
STATE=APP_DIR/"state.json"
NATIVE_CAPABILITIES=['jarvis.command','notifications.receive','open_url','app.launch','app.close','desktop.command','camera.capture','file.upload','file.receive','attachment.inbox','legacy.action']
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
        self.attachments={}; self.pending_attachment=None
        self.root=tk.Tk(); self.root.title('MARK LIV Companion'); self.root.geometry('620x520')
        f=ttk.Frame(self.root,padding=14); f.pack(fill='both',expand=True)
        ttk.Label(f,text='Pair Code').grid(row=0,column=0,sticky='w'); self.code=tk.StringVar(); ttk.Entry(f,textvariable=self.code,width=16).grid(row=0,column=1,sticky='w'); ttk.Button(f,text='Pair',command=self.pair).grid(row=0,column=2)
        self.status=tk.StringVar(value='Disconnected'); ttk.Label(f,textvariable=self.status).grid(row=2,column=0,columnspan=3,sticky='w',pady=8)
        self.log=tk.Text(f,height=18,state='disabled'); self.log.grid(row=3,column=0,columnspan=3,sticky='nsew')
        self.cmd=tk.StringVar(); e=ttk.Entry(f,textvariable=self.cmd); e.grid(row=4,column=0,columnspan=2,sticky='ew',pady=8); e.bind('<Return>',lambda _e:self.send()); ttk.Button(f,text='Send',command=self.send).grid(row=4,column=2)
        ttk.Button(f,text='Connect voice',command=self.connect).grid(row=5,column=0,sticky='w'); ttk.Button(f,text='Disconnect',command=self.disconnect).grid(row=5,column=1,sticky='w')
        ttk.Button(f,text='Attachments',command=self.show_attachments).grid(row=5,column=2,sticky='e')
        f.columnconfigure(1,weight=1); f.rowconfigure(3,weight=1)
        if self.st.get('paired'): self.root.after(300,self.connect)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
    def note(self,s): self.root.after(0,lambda:(self.log.configure(state='normal'),self.log.insert('end',s+'\n'),self.log.see('end'),self.log.configure(state='disabled')))
    def discover(self, code, timeout=4.0):
        msg=json.dumps({'magic':'MARKLIV_DISCOVER_V1','code':code}).encode()
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); sock.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1); sock.settimeout(0.5)
        try:
            deadline=time.time()+timeout
            while time.time()<deadline:
                sock.sendto(msg,('255.255.255.255',DISCOVERY_PORT))
                try:
                    data,_=sock.recvfrom(4096); r=json.loads(data.decode())
                    if r.get('magic')=='MARKLIV_DISCOVER_V1' and r.get('code')==code:return r['server'].rstrip('/')
                except socket.timeout: pass
            raise RuntimeError('Server with this Pair Code was not found on the local network')
        finally:sock.close()
    def pair(self):
        try:
            code=self.code.get().strip().upper(); base=PUBLIC_BASE_URL; o=requests.get(f'{base}/api/pairing/offer/{code}',timeout=8,verify=False).json(); nonce=o['nonce']
            peer={'device_id':self.st['device_id'],'name':self.st['name'],'public_key':self.st['public_key']}; sig=b64(priv(self.st).sign(f'{nonce}:{code}'.encode()))
            caps=list(NATIVE_CAPABILITIES)
            r=requests.post(f'{base}/api/pairing/accept',json={'code':code,'peer':peer,'signature':sig,'capabilities':caps},timeout=8,verify=False); r.raise_for_status()
            self.st.update(server=base,server_key=o['public_key'],server_id=o['device_id'],paired=True); save(self.st); self.status.set('Paired'); self.connect()
        except Exception as e: messagebox.showerror('Pair failed',str(e))
    def connect(self):
        if self.ws:return
        base=self.st.get('server');
        if not base: self.note('Not paired'); return
        wsbase=base.replace('https://','wss://').replace('http://','ws://'); url=f"{wsbase}/ws/device?device_id={self.st['device_id']}"
        self.ws=websocket.WebSocketApp(url,on_message=self.on_message,on_data=self.on_data,on_close=self.on_close,on_error=lambda _w,e:self.note(f'Connection error: {e}'))
        threading.Thread(target=lambda:self.ws.run_forever(sslopt={'cert_reqs':0}),daemon=True).start()
    def on_message(self,_w,text):
        m=json.loads(text); typ=m.get('type')
        if typ=='challenge':
            ch=m['challenge']; expected=self.st.get('server_key','')
            if not verify(expected,f"{self.st['device_id']}:{ch}".encode(),m.get('server_signature','')): self.note('Server identity verification failed'); self.disconnect(); return
            self.ws.send(json.dumps({'type':'proof','signature':b64(priv(self.st).sign(ch.encode())),'capabilities':list(NATIVE_CAPABILITIES)}))
        elif typ=='ready': self.root.after(0,lambda:self.status.set('Connected · voice on client')); self.start_audio()
        elif typ=='status':
            state=str(m.get('state','')).upper()
            # Keep one stable input stream for the whole interactive session.
            # Only gate network transmission while JARVIS is speaking; stopping and
            # restarting PortAudio streams each turn caused the desktop companion
            # to become silent after the first response on some devices/backends.
            if state=='SPEAKING': self.speaking=True
            elif state in ('LISTENING','ACTIVE','THINKING'): self.speaking=False
            label = 'Listening' if state=='ACTIVE' else state.title()
            self.root.after(0, lambda value=label: self.status.set(value))
        elif typ=='log': self.note(f"{m.get('speaker','JARVIS')}: {m.get('text','')}")
        elif typ=='attachment.inbox':
            self.attachments={x['id']:x for x in m.get('attachments',[])}
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
            try:self.out.write(data)
            except Exception as e:self.note(f'Audio output error: {e}')
    def start_audio(self):
        if self.running:return
        self.running=True
        try:
            self.out=sd.RawOutputStream(samplerate=24000,channels=1,dtype='int16'); self.out.start()
            def cb(indata,frames,time_info,status):
                if self.running and not self.speaking and self.ws and self.ws.sock and self.ws.sock.connected:
                    try:self.ws.send(bytes(indata),opcode=websocket.ABNF.OPCODE_BINARY)
                    except Exception:pass
            self.mic=sd.RawInputStream(samplerate=16000,channels=1,dtype='int16',blocksize=1024,callback=cb); self.mic.start()
        except Exception as e:self.note(f'Audio device error: {e}')
    def pause_mic(self):
        # Compatibility hook: do not stop/recreate the PortAudio stream per turn.
        self.speaking=True
    def resume_mic(self):
        # The callback remains alive; transmission resumes immediately.
        self.speaking=False
    def on_close(self, *_args):
        self.running=False
        self.speaking=False
        for x in (self.mic,self.out):
            try:x.stop(); x.close()
            except Exception:pass
        self.mic=self.out=None
        self.ws=None
        self.root.after(0,lambda:self.status.set('Disconnected'))
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
    def show_attachments(self):
        if getattr(self,'attachment_window',None) and self.attachment_window.winfo_exists():
            self.attachment_window.lift(); return
        w=tk.Toplevel(self.root); w.title('Attachments'); w.geometry('520x340')
        self.attachment_window=w
        self.attachment_list=tk.Listbox(w,selectmode='browse')
        self.attachment_list.pack(fill='both',expand=True,padx=12,pady=12)
        buttons=ttk.Frame(w); buttons.pack(fill='x',padx=12,pady=8)
        ttk.Button(buttons,text='Open',command=lambda:self.request_attachment('open')).pack(side='left')
        ttk.Button(buttons,text='Save As',command=lambda:self.request_attachment('save')).pack(side='left',padx=8)
        ttk.Button(buttons,text='Share',command=lambda:self.request_attachment('share')).pack(side='left')
        ttk.Button(buttons,text='Refresh',command=lambda:self.ws and self.ws.send(json.dumps({'type':'attachment.list'}))).pack(side='right')
        self.refresh_attachment_list()
        if self.ws:self.ws.send(json.dumps({'type':'attachment.list'}))

    def refresh_attachment_list(self):
        widget=getattr(self,'attachment_list',None)
        if widget is None or not widget.winfo_exists():return
        self.attachment_order=list(self.attachments)
        widget.delete(0,'end')
        for key in self.attachment_order:
            a=self.attachments[key]
            widget.insert('end',f"{a['name']}  ·  {a['size']:,} bytes  ·  {a.get('status','pending')}")

    def request_attachment(self,action):
        widget=getattr(self,'attachment_list',None)
        if widget is None or not widget.curselection():return
        item=self.attachments[self.attachment_order[widget.curselection()[0]]]
        if action=='share':
            messagebox.showinfo('Share attachment','Save the attachment first, then use your desktop share application. Native share sheets are not available consistently on every desktop OS.')
            return
        target=None
        if action=='save':
            target=filedialog.asksaveasfilename(initialfile=item['name'])
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
                with requests.get(info['url'],stream=True,timeout=300,verify=False) as resp:
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
        except Exception as exc:self.note('Attachment failed: '+str(exc))

    def _file_upload(self, a):
        import hashlib
        source_name=str(a.get('source') or '').strip()
        if not source_name:
            selected=[]; done=threading.Event()
            def pick():
                try:selected.append(filedialog.askopenfilename(title='Attach a file'))
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
        r=requests.put(str(a['url']),data=chunks(),headers={'X-File-Name':source.name},timeout=300,verify=False); r.raise_for_status(); server=r.json()
        digest=h.hexdigest()
        if server.get('sha256')!=digest or int(server.get('size',-1))!=size: raise RuntimeError('Server upload verification failed')
        return json.dumps({'name':source.name,'sha256':digest,'size':size})
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
            with requests.get(str(a['url']),stream=True,timeout=300,verify=False) as r:
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
            elif cap=='file.upload': result=self._file_upload(a)
            elif cap=='file.receive': result=self._file_receive(a)
            elif cap=='app.launch': result=self._launch_app(a.get('app') or a.get('name'))
            elif cap=='app.close': result=self._close_app(a.get('app') or a.get('name'))
            elif cap=='desktop.command': result=self._desktop_command(a)
            elif cap=='legacy.action':
                from local_runtime import invoke
                result=invoke(str(a.get('tool') or ''), a.get('parameters') or {})
            else: ok=False; result='unsupported capability: '+str(cap)
        except Exception as e:ok=False; result=str(e)
        self.ws.send(json.dumps({'type':'capability.result','call_id':m.get('call_id',''),'ok':ok,'result':result}))
    def disconnect(self):
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
    def close(self): self.disconnect(); self.root.destroy()
    def run(self):self.root.mainloop()
if __name__=='__main__':App().run()
