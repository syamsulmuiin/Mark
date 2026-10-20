from __future__ import annotations
import copy, hashlib, json, os, re, shutil, tempfile, time
from pathlib import Path

class ObjectStore:
    def __init__(self, root: Path):
        self.root=Path(root); self.objects=self.root/'objects'; self.meta=self.root/'metadata'; self.tmp=self.root/'tmp'
        for p in (self.root,self.objects,self.meta,self.tmp): p.mkdir(parents=True,exist_ok=True)
        self.index_path=self.meta/'index.json'; self.index=self._load(); self._migrate_legacy()
    def _load(self):
        try:
            data = json.loads(self.index_path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {'aliases': {}, 'objects': {}}
        if (not isinstance(data, dict) or not isinstance(data.get('aliases'), dict)
                or not isinstance(data.get('objects'), dict)
                or any(not isinstance(rec, dict) or not self._valid_digest(rec.get('sha256'))
                       for rec in data['aliases'].values())
                or any(not self._valid_digest(digest) or not isinstance(rec, dict)
                       for digest, rec in data['objects'].items())):
            raise ValueError('Invalid object store metadata')
        return data
    @staticmethod
    def _valid_digest(digest):
        return isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest) is not None
    def _save(self):
        fd, name = tempfile.mkstemp(prefix='index-', suffix='.tmp', dir=self.meta)
        tmp = Path(name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(self.index, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.index_path)
        finally:
            tmp.unlink(missing_ok=True)
    def _persist(self, candidate):
        previous = self.index
        self.index = candidate
        try:
            self._save()
        except Exception:
            self.index = previous
            raise
    @staticmethod
    def sha256(path:Path):
        h=hashlib.sha256()
        with open(path,'rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
        return h.hexdigest()
    def ingest(self,path:Path,name:str,temporary=False):
        path=Path(path); digest=self.sha256(path); size=path.stat().st_size; obj=self.objects/digest
        if obj.is_symlink():
            raise ValueError('Object path must not be a symlink')
        if not obj.exists():
            fd, staging_name = tempfile.mkstemp(prefix='object-', dir=self.tmp)
            os.close(fd)
            staging = Path(staging_name)
            try:
                shutil.copyfile(path, staging)
                with staging.open('rb') as stream:
                    os.fsync(stream.fileno())
                os.replace(staging, obj)
            finally:
                staging.unlink(missing_ok=True)
        now=time.time(); candidate=copy.deepcopy(self.index)
        existing=candidate['objects'].get(digest) or {}
        candidate['objects'][digest]={'size':size,'created_at':existing.get('created_at',now),'temporary':bool(temporary) and bool(existing.get('temporary',True))}
        old_digest=(candidate.get('aliases',{}).get(name) or {}).get('sha256')
        if not temporary:
            candidate['aliases'][name]={'sha256':digest,'size':size,'updated_at':now}
        obsolete = old_digest and old_digest != digest and not any(a.get('sha256')==old_digest for a in candidate['aliases'].values()) and not getattr(self,'attachment_referenced',lambda _d:False)(old_digest)
        if obsolete:
            candidate['objects'].pop(old_digest, None)
        self._persist(candidate)
        # Source and superseded bytes remain recoverable until metadata commits.
        if path.absolute() != obj.absolute():
            path.unlink(missing_ok=True)
        if obsolete:
            (self.objects/old_digest).unlink(missing_ok=True)
        return {'name':name,'sha256':digest,'size':size,'path':obj}
    def resolve(self,name):
        rec=self.index.get('aliases',{}).get(name)
        if not rec:return None
        if not self._valid_digest(rec.get('sha256')):return None
        p=self.objects/rec['sha256']
        return ({**rec,'name':name,'path':p} if p.is_file() and not p.is_symlink() else None)
    def by_hash(self,digest):
        if not self._valid_digest(digest):return None
        rec=self.index.get('objects',{}).get(digest); p=self.objects/digest
        return ({**(rec or {}),'sha256':digest,'path':p} if p.is_file() and not p.is_symlink() else None)
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
        candidate=copy.deepcopy(self.index); candidate['objects'].pop(digest,None)
        self._persist(candidate)
        (self.objects/digest).unlink(missing_ok=True)
        return True
    def delete_attachment_copy(self, digest, name):
        """Remove an unshared attachment object; never delete arbitrary source paths."""
        if not self._valid_digest(digest):return False
        if getattr(self, 'attachment_referenced', lambda _d: False)(digest):
            return False
        candidate = copy.deepcopy(self.index)
        alias = candidate.get('aliases', {}).get(name)
        if alias and alias.get('sha256') == digest:
            candidate['aliases'].pop(name)
        if any(alias.get('sha256') == digest for alias in candidate['aliases'].values()):
            self._persist(candidate)
            return False
        candidate['objects'].pop(digest, None)
        self._persist(candidate)
        (self.objects / digest).unlink(missing_ok=True)
        return True

    def _migrate_legacy(self):
        for folder in ('uploads','share','downloads'):
            d=self.root/folder
            if not d.exists():continue
            for p in list(d.iterdir()):
                if p.is_file(): self.ingest(p,p.name,temporary=False)
            try:d.rmdir()
            except OSError:pass
