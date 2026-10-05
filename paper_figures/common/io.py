"""Atomic small outputs and provenance, without reading scientific arrays."""
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n');tmp.replace(path)

def write_csv(path, frame):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+f'.{os.getpid()}.tmp')
    frame.to_csv(tmp,index=False,compression='gzip' if path.suffix=='.gz' else None)
    tmp.replace(path)

def complete(folder, artifact_paths=None, **metadata):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    artifacts=[Path(p) for p in artifact_paths] if artifact_paths is not None else list(folder.iterdir())
    if artifact_paths is not None and any(not p.is_file() for p in artifacts):raise FileNotFoundError('Declared completion artifact missing')
    files=[dict(path=str(p),bytes=p.stat().st_size) for p in sorted(artifacts) if p.is_file() and p.name!='complete.json' and '.tmp' not in p.name]
    root=Path(__file__).resolve().parents[2]
    code={str(p.relative_to(root)):digest(p) for p in sorted((root/'paper_figures').rglob('*.py')) if 'outputs' not in p.parts}
    write_json(folder/'complete.json',dict(code_sha256=code,status='COMPLETED',created_utc=datetime.now(timezone.utc).isoformat(),files=files,**metadata))

def require_complete(folder):
    p=Path(folder)/'complete.json';j=json.loads(p.read_text())
    if j['status']!='COMPLETED': raise ValueError(p)
    for item in j['files']:
        f=Path(item['path'])
        if not f.is_file() or f.stat().st_size!=item['bytes']: raise ValueError(f'Incomplete artifact: {f}')
    return j
