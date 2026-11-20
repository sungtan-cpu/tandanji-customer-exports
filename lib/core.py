import sys,json,zipfile,io,re,datetime,decimal
from pathlib import Path
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parents[1]
class Tables(HTMLParser):
 def __init__(self):super().__init__();self.tables=[];self.table=None;self.row=None;self.cell=None;self.depth=0
 def handle_starttag(self,t,a):
  if t=='table':
   self.depth+=1
   if self.depth==1:self.table=[];self.tables.append(self.table)
  elif t=='tr' and self.depth==1:
   if self.row is not None and self.table is not None:self.table.append(self.row)
   self.row=[]
  elif t in ('td','th') and self.depth==1:self.cell=[]
  elif t=='br' and self.cell is not None:self.cell.append(' ')
 def handle_data(self,d):
  if self.cell is not None:self.cell.append(d)
 def handle_endtag(self,t):
  if t in ('td','th') and self.depth==1 and self.cell is not None:
   if self.row is not None:self.row.append(''.join(self.cell).strip())
   self.cell=None
  elif t=='tr' and self.depth==1 and self.row is not None:
   if self.table is not None:self.table.append(self.row)
   self.row=None
  elif t=='table':
   if self.depth==1 and self.row is not None:
    self.table.append(self.row);self.row=None
   self.depth-=1
def load(meta):
 data=Path(meta['path']).read_bytes()
 if Path(meta['path']).suffix=='.zip':
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   members=[n for n in z.namelist() if Path(n).suffix.lower() in ('.xls','.xlsx')]
   if len(members)!=1:raise ValueError('원본 주문 파일 수 오류')
   data=z.read(members[0],pwd=meta['password'].encode())
 if data.startswith(b'PK'):
  import openpyxl
  w=openpyxl.load_workbook(io.BytesIO(data),read_only=True,data_only=True)
  tables=[[list(r) for r in s.iter_rows(values_only=True)] for s in w];w.close()
 else:
  try:text=data.decode('utf-8-sig')
  except UnicodeDecodeError:text=data.decode('cp949')
  p=Tables();p.feed(text);tables=p.tables
 valid=[t for t in tables if t and any('주문' in str(c) and '번호' in str(c) for c in t[0])]
 if len(valid)!=1:raise ValueError('주문 표를 하나로 확인할 수 없습니다.')
 return valid[0]
def norm(v):return re.sub(r'\s+','',str(v or ''))
def process(meta,table):
 headers=table[0];lookup={norm(h):i for i,h in enumerate(headers)}
 def col(names):
  found=[lookup[n] for n in names if n in lookup]
  if not found:raise ValueError('필수 열 누락: '+names[0])
  return found[0]
 customer_name=col(['주문자이름']);order=col(['주문번호']);email=col(['주문자e-mail','주문자이메일','이메일','주문자이메일주소']);phone=col(['주문자핸드폰번호','주문자휴대폰번호','휴대폰번호']);amount=col(['총결제금액','결제금액']);date=col(['주문일자','주문일']);goods=col(['주문상품명','상품명'])
 source_orders=sorted({str(r[order] or '').strip() for r in table[1:] if any(v not in ('',None) for v in r)})
 fingerprint=2166136261
 for ch in '\n'.join(source_orders):fingerprint=((fingerprint^ord(ch))*16777619)&0xffffffff
 proof=meta.get('proof') or json.loads((ROOT/'work/half/search.json').read_text('utf-8'))
 if len(source_orders)!=proof['orderCount'] or fingerprint!=proof['orderFingerprint']:raise ValueError('화면 검색 주문과 다운로드 주문 불일치')
 seen=set();matrix=[];audit=[];duplicates=zero=empty=0;total=0
 for rownum,row in enumerate(table[1:],2):
  if not any(v not in ('',None) for v in row):continue
  total+=1
  if len(row)!=len(headers):raise ValueError(f'{rownum}행 열 수 오류')
  oid=str(row[order] or '').strip()
  if not oid:raise ValueError(f'{rownum}행 주문번호 누락')
  day=str(row[date])[:10]
  if not meta['start']<=day<=meta['end']:raise ValueError(f'{rownum}행 검색 기간 불일치')
  if oid in seen:duplicates+=1;continue
  seen.add(oid)
  raw=str(row[amount]).replace(',','').replace('원','').strip()
  money=decimal.Decimal(raw)
  if money==0:zero+=1;continue
  e=str(row[email] or '').strip()
  if not e:empty+=1
  if e and (e.startswith(('=','+','-','@')) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',e)):raise ValueError(f'{rownum}행 이메일 형식 확인 필요')
  value=str(row[phone] or '').strip();digits=re.sub(r'\D','',value)
  if not value:formatted=''
  elif re.fullmatch(r'010\d{8}',digits):formatted='+82-10-'+digits[3:7]+'-'+digits[7:]
  elif re.fullmatch(r'8210\d{8}',digits):formatted='+82-10-'+digits[4:8]+'-'+digits[8:]
  else:raise ValueError(f'{rownum}행 휴대폰 번호 형식 확인 필요')
  matrix.append([e,e,e,formatted,formatted,formatted]);audit.append({'name':str(row[customer_name] or '').strip(),'order':oid,'amount':str(money),'email':e,'phone':formatted})
 if not total:raise ValueError('원본 데이터가 비어 있습니다. 검색 결과를 확인하세요.')
 return {'month':meta['month'],'start':meta['start'],'end':meta['end'],'dateBasis':meta['dateBasis'],'template':meta['template'],'sourceRows':total,'duplicatesRemoved':duplicates,'zeroRemoved':zero,'customers':len(matrix),'missingEmails':empty,'headers':['EMAIL','EMAIL','EMAIL','PHONE','PHONE','PHONE'],'rows':matrix,'audit':audit}
