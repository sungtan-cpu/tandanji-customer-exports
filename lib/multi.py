import json,datetime,collections
from pathlib import Path
from . import core

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent

def fingerprint(ids):
 value=2166136261
 for ch in '\n'.join(sorted(set(ids))):value=((value^ord(ch))*16777619)&0xffffffff
 return value

def stamp(value):
 text=str(value).strip().replace('T',' ')
 return datetime.datetime.fromisoformat(text).strftime('%Y-%m-%d %H:%M:%S')

def validate_audit(data):
 rules={r['id']:r for r in data['rules']}
 for a in data['audit']:
  assert a['rule'] in rules
  r=rules[a['rule']]
  assert r['from']<=a['orderedAt']<=r['until']
  assert data['start']<=a['orderedAt'][:10]<=data['end']
  if data.get('asOf'):assert a['orderedAt']<=data['asOf']
 assert dict(collections.Counter(a['rule'] for a in data['audit']))==data['ruleCounts']

def main():
 meta=json.loads((ROOT/'work/half/download.json').read_text('utf-8'))
 rules=json.loads((ROOT/'rules.json').read_text('utf-8'));byid={r['id']:r for r in rules}
 active={r['id'] for r in rules if r['from'][:10]<=meta['end'] and r['until'][:10]>=meta['start']}
 assert {s['rule'] for s in meta['sources']}==active,'필요한 상품 검색 원본 누락'
 headers=None;rows=[];mapping={};source_count=excluded=0;stats=[]
 for source in meta['sources']:
  rule=byid[source['rule']];proof=source['proof']
  assert all(proof[k]==v for k,v in {'start':meta['start'],'end':meta['end'],'keyword':rule['keyword'],'dateBasis':'o.regDt','key':'og.goodsNm','first':True,'withdrawn':False}.items())
  if proof['orderCount']==0:
   assert source['path'] is None
   stats.append({'rule':rule['id'],'searchOrders':0,'eligibleOrders':0,'firstOrderAt':None,'lastOrderAt':None});continue
  table=core.load(source)
  if headers is None:headers=table[0]
  assert headers==table[0],'원본 양식 불일치'
  cols={core.norm(c):i for i,c in enumerate(headers)};o=cols['주문번호'];dt=cols['주문일자']
  ids={str(r[o]).strip() for r in table[1:] if any(r)}
  assert len(ids)==proof['orderCount'] and fingerprint(ids)==proof['orderFingerprint'],'검색화면과 원본 주문 불일치'
  times=[];accepted=set()
  for row in table[1:]:
   if not any(row):continue
   source_count+=1
   assert len(row)==len(headers)
   when=stamp(row[dt]);assert meta['start']<=when[:10]<=meta['end']
   if not rule['from']<=when<=rule['until'] or (meta.get('asOf') and when>meta['asOf']):excluded+=1;continue
   oid=str(row[o]).strip();mapping.setdefault(oid,{'rule':rule['id'],'orderedAt':when});accepted.add(oid);times.append(when);rows.append(row)
  stats.append({'rule':rule['id'],'searchOrders':len(ids),'eligibleOrders':len(accepted),'firstOrderAt':min(times) if times else None,'lastOrderAt':max(times) if times else None})
 assert rows,'적합한 주문이 없습니다'
 rows.sort(key=lambda r:stamp(r[dt]),reverse=True)
 ids={str(r[o]).strip() for r in rows}
 combined={**meta,'proof':{'orderCount':len(ids),'orderFingerprint':fingerprint(ids)}}
 result=core.process(combined,[headers,*rows])
 for a in result['audit']:a.update(mapping[a['order']])
 for key in ['runKey','fileSuffix','asOf']:
  if key in meta:result[key]=meta[key]
 result.update(ruleVersion='2026-10-19',rules=rules,ruleCounts=dict(collections.Counter(a['rule'] for a in result['audit'])),sourceSearches=stats,downloadRows=source_count,timeExcludedRows=excluded)
 validate_audit(result)
 (ROOT/'work/half/customers.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
 proof={'start':meta['start'],'end':meta['end'],'keyword':'상품별 변경시각 적용','dateBasis':'o.regDt','key':'og.goodsNm','first':True,'withdrawn':False,'sources':[s['proof'] for s in meta['sources']]}
 (ROOT/'work/half/search.json').write_text(json.dumps(proof,ensure_ascii=False),encoding='utf-8')
 print(json.dumps({k:result[k] for k in ['customers','duplicatesRemoved','zeroRemoved','missingEmails','ruleCounts','sourceSearches','timeExcludedRows']},ensure_ascii=True))

if __name__=='__main__':main()
