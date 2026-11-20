const fs=require('fs'),path=require('path'),crypto=require('crypto');
const {chromium}=require('playwright');
const adminHost=process.env.GODO_ADMIN_HOST;if(!adminHost||!/^[a-zA-Z0-9.-]+$/.test(adminHost)||adminHost.includes('YOUR_'))throw Error('관리자 도메인 로컬 설정 필요');
const job=process.argv[5];if(!['half','mundil'].includes(job))throw Error('업무 구분 필요');
async function main(){
 const keyword=process.argv[4]||'50%';
 const start=process.argv[2],end=process.argv[3];if(!/^\d{4}-\d{2}-\d{2}$/.test(start)||!/^\d{4}-\d{2}-\d{2}$/.test(end)||start>end)throw Error('검색 기간 오류');const month=end.slice(0,7);
 const out=path.resolve(__dirname,'work/raw');fs.mkdirSync(out,{recursive:true});fs.mkdirSync(path.join(__dirname,'work/half'),{recursive:true});
 const name='반값고객'+start.replaceAll('-','')+end.replaceAll('-','')+Date.now(),password='Md!'+crypto.randomBytes(5).toString('hex');
 let b;let captured=null,downloadError=null;const pending=[];
 try{
  const endpoint=process.env.GODO_CDP_URL||'http://127.0.0.1:9222';const u=new URL(endpoint);if(u.protocol!=='http:'||!['127.0.0.1','localhost'].includes(u.hostname))throw Error('로컬 브라우저 연결만 허용');b=await chromium.connectOverCDP(endpoint,{timeout:4000});
  if(!b)throw Error('기존 고도몰 Chrome 연결이 필요합니다.');
  const c=b.contexts()[0];const p=await c.newPage();p.setDefaultTimeout(12000);
  function watch(q){q.on('dialog',async d=>{if(['alert','confirm'].includes(d.type())){await d.accept();}else await d.dismiss();});q.on('download',d=>{const job=(async()=>{try{const ext=path.extname(d.suggestedFilename()).toLowerCase();if(!['.zip','.xls','.xlsx'].includes(ext))throw Error('다운로드 형식 오류');const target=path.join(out,name+ext);try{await d.saveAs(target);}catch{const url=d.url();if(new URL(url).hostname!==adminHost)throw Error('다운로드 호스트 오류');const r=await c.request.get(url);if(!r.ok())throw Error('다운로드 실패');fs.writeFileSync(target,await r.body());}captured=target;}catch(e){downloadError=e;}})();pending.push(job);});}
  watch(p);const owned=new Set([p]);c.on('page',async q=>{if(await q.opener()===p){owned.add(q);watch(q);}});
  await p.goto('https://'+adminHost+'/order/order_list_all.php',{waitUntil:'domcontentloaded'});
  if(p.url().includes('/login.php')){await p.waitForTimeout(1500);const ready=await p.locator('input[type=password]').evaluateAll(es=>es.some(e=>e.getClientRects().length&&e.value.length>0));if(!ready)throw Error('고도몰 로그인 필요');await p.getByRole('button',{name:'로그인',exact:true}).click();await p.waitForTimeout(1500);await p.goto('https://'+adminHost+'/order/order_list_all.php',{waitUntil:'domcontentloaded'});if(p.url().includes('/login.php'))throw Error('고도몰 로그인 필요');}
  await p.locator('#key').selectOption({label:'상품명'});await p.locator('input[name=keyword]').fill(keyword);await p.locator('#treatDateFl').selectOption({label:'주문일'});await p.locator('input[name="treatDate[]"]').nth(0).fill(start);await p.locator('input[name="treatDate[]"]').nth(1).fill(end);
  const detail=p.getByText('상세검색 펼침',{exact:false});if(await detail.count()===1&&await detail.isVisible())await detail.click();await p.getByLabel('첫주문',{exact:true}).setChecked(job==='half');await p.getByLabel('탈퇴회원 주문',{exact:true}).setChecked(job==='mundil');
  await p.getByRole('button',{name:'검색',exact:true}).click();await p.waitForLoadState('domcontentloaded');
  const actual={start:await p.locator('input[name="treatDate[]"]').nth(0).inputValue(),end:await p.locator('input[name="treatDate[]"]').nth(1).inputValue(),keyword:await p.locator('input[name=keyword]').inputValue(),dateBasis:await p.locator('#treatDateFl').inputValue(),key:await p.locator('#key').inputValue(),first:await p.getByLabel('첫주문',{exact:true}).isChecked(),withdrawn:await p.getByLabel('탈퇴회원 주문',{exact:true}).isChecked()};
  if(actual.start!==start||actual.end!==end||actual.keyword!==keyword||actual.dateBasis!=='o.regDt'||actual.key!=='og.goodsNm'||actual.first!==(job==='half')||actual.withdrawn!==(job==='mundil'))throw Error('검색 조건 검증 실패');
  await p.locator('select[name=pageNum]').selectOption('500');await p.waitForLoadState('domcontentloaded');
  const orderIds=await p.locator('input[name^="statusCheck["]').evaluateAll(es=>[...new Set(es.map(e=>e.value.split('||')[0]))].sort());actual.orderCount=orderIds.length;actual.orderFingerprint=orderIds.join('\n').split('').reduce((h,c)=>Math.imul(h^c.charCodeAt(0),16777619)>>>0,2166136261);
  if(actual.orderCount>=500)throw Error('500개 한도에 도달했습니다. 전체 페이지 확인 필요');
  if(actual.orderCount===0){fs.writeFileSync(path.resolve(__dirname,'work/half/search.json'),JSON.stringify(actual));fs.writeFileSync(path.resolve(__dirname,'work/half/download.json'),JSON.stringify({month,start,end,path:null,template:'주문통합리스트_주문별',dateBasis:'주문일'}));await p.close();return;}
  fs.writeFileSync(path.resolve(__dirname,'work/half/search.json'),JSON.stringify(actual));console.log('기간·상품명·첫주문·탈퇴회원 조건 검증 완료');
  await p.getByText(/^\s*엑셀\s*다운로드\s*$/).click();
  const row=p.locator("xpath=//*[self::th or self::td][normalize-space(.)='양식 선택']/parent::tr");await row.locator('select').selectOption({label:'주문통합리스트_주문별'});await p.getByLabel('검색내역',{exact:true}).check();await p.locator('input[name=downloadFileName]').fill(name);await p.getByLabel('사용',{exact:true}).check();await p.locator('input[name=password]').fill(password);await p.locator('input[name=rePassword]').fill(password);
  const scope=p.locator('input[name=downloadFileName]').locator("xpath=ancestor::*[.//*[self::button or self::a or self::input][normalize-space(.)='요청' or @value='요청']][1]");await scope.locator("xpath=.//*[self::button or self::a or self::input][normalize-space(.)='요청' or @value='요청']").filter({visible:true}).click();
  console.log('반값 '+start+'~'+end+' 주문별 다운로드 요청');
  let clicked=false,reason=false;const deadline=Date.now()+150000;
  while(!captured&&!downloadError&&Date.now()<deadline){
   for(const q of owned){if(q.isClosed())continue;for(const f of q.frames()){
    if(captured||downloadError)break;
    try{
     const notice=f.getByText('다운로드할 엑셀파일 생성이 완료되었습니다. 파일을 선택하여 다운로드하시기 바랍니다.',{exact:true});if(await notice.count()===1&&await notice.isVisible()){await notice.locator("xpath=ancestor::*[.//*[self::button or self::a or self::input][normalize-space(.)='확인' or @value='확인']][1]").locator("xpath=.//*[self::button or self::a or self::input][normalize-space(.)='확인' or @value='확인']").filter({visible:true}).click();}
     if(!reason){for(const menu of await f.locator('select').all()){if(await menu.isVisible()&&await menu.locator('option').filter({hasText:/^\s*주문관리\s*$/}).count()===1){await menu.selectOption({label:'주문관리'});await menu.locator("xpath=ancestor::*[.//*[self::button or self::a or self::input][normalize-space(.)='확인' or @value='확인']][1]").locator("xpath=.//*[self::button or self::a or self::input][normalize-space(.)='확인' or @value='확인']").filter({visible:true}).click();reason=true;clicked=false;break;}}}
     if(!clicked){const r=f.locator("xpath=//tr[td[contains(normalize-space(.),'"+name+"')] and td[normalize-space(.)='생성완료']]").filter({visible:true});if(await r.count()){await r.first().locator("xpath=.//*[self::button or self::a or self::input][normalize-space(.)='다운로드' or @value='다운로드']").filter({visible:true}).click();clicked=true;}}
    }catch(e){if(!q.isClosed()&&!/closed|detached/i.test(e.message))throw e;}
   }}await new Promise(r=>setTimeout(r,350));
  }
  await Promise.all(pending);if(downloadError)throw downloadError;if(!captured)throw Error('다운로드 시간 초과');
  fs.writeFileSync(path.resolve(__dirname,'work/half/download.json'),JSON.stringify({month,start,end,path:captured,password,template:'주문통합리스트_주문별',dateBasis:'주문일'}));console.log('다운로드 저장 완료');await p.close();
 }finally{if(b)await b.close();}
}
main().catch(()=>{console.error('고도몰 다운로드 중단: 로그인·검색조건·페이지 수·생성 상태를 확인하세요.');process.exit(1)});
