from __future__ import annotations
import hashlib, json, os, shutil, time
from pathlib import Path

class ObjectStore:
    def __init__(self, root: Path):
        self.root=Path(root); self.objects=self.root/'objects'; self.meta=self.root/'metadata'; self.tmp=self.root/'tmp'
        for p in (self.root,self.objects,self.meta,self.tmp): p.mkdir(parents=True,exist_ok=True)
        self.index_path=self.meta/'index.json'; self.index=self._load(); self._migrate_legacy()
    def _load(self):
        try:return json.loads(self.index_path.read_text(encoding='utf-8'))
        except Exception:return {'aliases':{},'objects':{}}
    def _save(self):
        tmp=self.index_path.with_suffix('.tmp'); tmp.write_text(json.dumps(self.index,indent=2,ensure_ascii=False),encoding='utf-8'); os.replace(tmp,self.index_path)
    @staticmethod
    def sha256(path:Path):
        h=hashlib.sha256()
        with open(path,'rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
        return h.hexdigest()
    def ingest(self,path:Path,name:str,temporary=False):
        path=Path(path); digest=self.sha256(path); size=path.stat().st_size; obj=self.objects/digest
        if not obj.exists(): os.replace(path,obj)
        else: path.unlink(missing_ok=True)
        now=time.time(); existing=self.index['objects'].get(digest) or {}
        self.index['objects'][digest]={'size':size,'created_at':existing.get('created_at',now),'temporary':bool(temporary) and bool(existing.get('temporary',True))}
        old_digest=(self.index.get('aliases',{}).get(name) or {}).get('sha256')
        if not temporary:
            self.index['aliases'][name]={'sha256':digest,'size':size,'updated_at':now}
        self._save()
        if old_digest and old_digest != digest and not any(a.get('sha256')==old_digest for a in self.index.get('aliases',{}).values()) and not getattr(self,'attachment_referenced',lambda _d:False)(old_digest):
            (self.objects/old_digest).unlink(missing_ok=True); self.index.get('objects',{}).pop(old_digest,None); self._save()
        return {'name':name,'sha256':digest,'size':size,'path':obj}
    def resolve(self,name):
        rec=self.index.get('aliases',{}).get(name)
        if not rec:return None
        p=self.objects/rec['sha256']
        return ({**rec,'name':name,'path':p} if p.is_file() else None)
    def by_hash(self,digest):
        rec=self.index.get('objects',{}).get(digest); p=self.objects/digest
        return ({**(rec or {}),'sha256':digest,'path':p} if p.is_file() else None)
    def list(self):
        out=[]
        for name in self.index.get('aliases',{}):
            r=self.resolve(name)
            if r: out.append({k:r[k] for k in ('name','sha256','size')})
        return sorted(out,key=lambda x:x['name'].casefold())
    def release_temporary(self,digest):
        rec=self.index.get('objects',{}).get(digest)
        if not rec or not rec.get('temporary'):return False
        # Keep an object if any durable alias points to it.
        if any(a.get('sha256')==digest for a in self.index.get('aliases',{}).values()) or getattr(self,'attachment_referenced',lambda _d:False)(digest):return False
        (self.objects/digest).unlink(missing_ok=True); self.index['objects'].pop(digest,None); self._save(); return True
    def _migrate_legacy(self):
        for folder in ('uploads','share','downloads'):
            d=self.root/folder
            if not d.exists():continue
            for p in list(d.iterdir()):
                if p.is_file(): self.ingest(p,p.name,temporary=False)
            try:d.rmdir()
            except OSError:pass
