from __future__ import annotations

import json
import subprocess
from collections import Counter

CONTAINER='tvsumare_web'
FILES=['videos_ia.json','social_queue.json','boletins_ia.json','noticias.json']


def exec_json(name: str):
    cmd=['docker','exec',CONTAINER,'php','-r',(
        "$p='/var/www/html/data/"+name+"';"
        "if(!file_exists($p)){echo json_encode(['exists'=>false]);exit;}"
        "$raw=file_get_contents($p);$d=json_decode($raw,true);"
        "echo json_encode(['exists'=>true,'valid'=>is_array($d),'count'=>is_array($d)?count($d):0,'data'=>is_array($d)?$d:[]],JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);"
    )]
    p=subprocess.run(cmd,text=True,capture_output=True)
    if p.returncode!=0:
        return {'error':p.stderr.strip() or p.stdout.strip()}
    try:
        return json.loads(p.stdout)
    except Exception:
        return {'error':'invalid audit output','raw':p.stdout[:500]}


def summarize_jobs(items):
    c=Counter(str(x.get('status','')) for x in items if isinstance(x,dict))
    print('STATUS_COUNTS='+json.dumps(c,ensure_ascii=False,sort_keys=True))
    active=[]
    dup=Counter()
    for x in items:
        if not isinstance(x,dict): continue
        st=str(x.get('status',''))
        if st not in {'publicado','published','cancelado','cancelled','canceled','heygen_falhou','failed','falhou','erro','superseded'}:
            active.append({k:x.get(k) for k in ['id','news_id','title','status','created_at','updated_at','heygen_session_id','heygen_video_id']})
        key=str(x.get('news_id') or x.get('title') or '')
        if key: dup[key]+=1
    print('ACTIVE_COUNT='+str(len(active)))
    for x in active[:20]: print('ACTIVE '+json.dumps(x,ensure_ascii=False))
    dups={k:v for k,v in dup.items() if v>1}
    print('DUP_KEYS='+json.dumps(dups,ensure_ascii=False,sort_keys=True))


def summarize_social(items):
    c=Counter(str(x.get('status','')) for x in items if isinstance(x,dict))
    print('STATUS_COUNTS='+json.dumps(c,ensure_ascii=False,sort_keys=True))
    for x in items[:20]:
        if isinstance(x,dict):
            print('ITEM '+json.dumps({k:x.get(k) for k in ['id','video_id','title','status','targets','network_status','created_at','updated_at']},ensure_ascii=False))


def main():
    print('TVSUMARE_STATE_AUDIT=START')
    for name in FILES:
        print('\n=== '+name+' ===')
        r=exec_json(name)
        if 'error' in r:
            print('ERROR='+str(r['error'])); continue
        print('EXISTS='+('YES' if r.get('exists') else 'NO'))
        if not r.get('exists'): continue
        print('VALID='+('YES' if r.get('valid') else 'NO'))
        print('COUNT='+str(r.get('count',0)))
        data=r.get('data') or []
        if name=='videos_ia.json': summarize_jobs(data)
        elif name=='social_queue.json': summarize_social(data)
        else:
            c=Counter(str(x.get('status','')) for x in data if isinstance(x,dict))
            if c: print('STATUS_COUNTS='+json.dumps(c,ensure_ascii=False,sort_keys=True))
            for x in data[:10]:
                if isinstance(x,dict): print('ITEM '+json.dumps({k:x.get(k) for k in ['id','title','status','created_at','updated_at']},ensure_ascii=False))
    print('\nTVSUMARE_STATE_AUDIT=END')


if __name__=='__main__':
    main()
