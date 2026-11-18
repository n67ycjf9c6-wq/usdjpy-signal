#!/usr/bin/env python3
"""Public FX price snapshot; no secrets or extra services required."""
import json, pathlib, datetime, urllib.request
p=pathlib.Path('data/background.json')
try:
    request=urllib.request.Request('https://biquote.io/api/USDJPY?allowStale=true',headers={'User-Agent':'NAKAMURA-LAB/4.2.0'})
    with urllib.request.urlopen(request,timeout=20) as f: result=json.load(f)
    now=datetime.datetime.now(datetime.timezone.utc)
    row={'capturedAt':now.isoformat(timespec='seconds'),'quoteAt':result.get('timestamp'),'mid':result.get('mid'),'bid':result.get('bid'),'ask':result.get('ask'),'marketState':result.get('marketState'),'stale':result.get('stale')}
    if row['mid'] is None:raise ValueError('no price')
    old=json.loads(p.read_text()) if p.exists() else {'samples':[]}
    rows=old.get('samples',[])
    if not any(x.get('capturedAt')==row['capturedAt'] for x in rows):rows.append(row)
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({'version':'4.2.0','samples':rows[-2016:]},ensure_ascii=False,indent=2)+'\n')
    print('Saved',row)
except Exception as e:
    print('No valid data, preserve existing archive:',e)
    raise
