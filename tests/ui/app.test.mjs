import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { Script } from 'node:vm';
import { JSDOM, VirtualConsole } from 'jsdom';

const html = await readFile(new URL('../../receipt_bridge/static/index.html', import.meta.url), 'utf8');
const settingsScript = await readFile(new URL('../../receipt_bridge/static/settings.js', import.meta.url), 'utf8');
const appScript = await readFile(new URL('../../receipt_bridge/static/app.js', import.meta.url), 'utf8');
const scripts = new Map([['/settings.js',settingsScript],['/app.js',appScript]]);
const settings = {
  timezone: 'Asia/Seoul', ledger_url: 'http://mock.invalid/api/v1', allowed_users: [1], allowed_chats: [1],
  user_accounts: {'1': 'test-account'}, chat_accounts: {}, ai_provider: 'ollama', ai_model: 'test-vision',
  allow_external_ai: false, ollama_url: 'http://mock.invalid', ai_runner_url: 'http://ai-runner:8090',
  ai_timeout: 180, ocr_languages: 'kor+eng', max_download_mb: 20, max_attempts: 5,
  retry_seconds: 30, max_amount_minor: 9000000000000, auto_save: false,
  auto_max_amount_minor: 50000, auto_max_age_days: 7,
};
const job = {id: 'test-job', state: 'waiting', account: 'test-account', created_at: Date.now()/1000,
  attempts: 0, extraction: {merchant: '<img src=x onerror=alert(1)>', amount: '12000', currency: 'KRW',
  date: '2026-11-01', time: '12:30', category: 'food'}, has_image: true, has_original: true,
  events: [{at:Date.now()/1000,state:'received'},{at:Date.now()/1000,state:'waiting'}]};
const status = {demo:true,ready:true,paused:false,revision:0,applied_revision:0,
  checks:{telegram:true,ledger:true,ai:true,account:true,allowlist:true}};
const flush = async () => {for(let i=0;i<12;i++) await new Promise(resolve=>setImmediate(resolve));};

async function app(setupRequired=false,responseStatus=status,savedSecrets={},pathname="/", initialSettings=settings, detailJob=job, accountResponses=null){
  const errors=[];
  const console = new VirtualConsole();
  console.on('jsdomError', error=>errors.push(error.message));
  const dom = new JSDOM(html,{url:'http://localhost:18089'+pathname,runScripts:'outside-only',virtualConsole:console});
  const w=dom.window, requests=[];
  w.setInterval=()=>0;
  w.confirm=()=>true;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.fetch=async (path,options={})=>{
    requests.push({path,options});
    let body,code=200;
    if(path==='/api/session')body={authenticated:false,setup_required:setupRequired};
    else if(path==='/api/setup'){body={csrf:'TEST_CSRF'};setupRequired=false;}
    else if(path==='/api/login')body={csrf:'TEST_CSRF'};
    else if(path==='/api/logout')body={ok:true};
    else if(path==='/api/overview')body={status:responseStatus,settings,summary:{total:1,today:1,counts:{waiting:1},dates:[],inbox:0,outbox:0},recent:{items:[job]}};
    else if(path==='/api/settings')body={settings:initialSettings,status:responseStatus,secrets:savedSecrets};
    else if(path==='/api/ai/check')body={installed:true,auth:'unknown',message:'모델 목록을 불러왔습니다. 로그인은 별도 확인하세요.',models:['gemini-test-low']};
    else if(path==='/api/ai/credentials')body={ok:true};
    else if(path==='/api/settings/reveal-secret')body={value:'TEST_SAVED_SECRET'};
    else if(path==='/api/control')body={...status,paused:JSON.parse(options.body).paused};
    else if(path.startsWith('/api/jobs?'))body={items:[job],total:1,page:1,page_size:20};
    else if(path.startsWith('/api/logs?'))body={items:[{id:1,at:Date.parse('2026-11-02T15:11:00Z')/1000,level:'info',message:'테스트 로그',job_id:job.id}],total:1,page:1,page_size:50,timezone:'Asia/Seoul'};
    else if(path==='/api/accounts'){
      body=accountResponses?.length ? accountResponses.shift() : {accounts:[{id:'test-account',name:'테스트 계좌',currency:'KRW'}]};
      if(body.error)code=502;
      else body={...body,status:{...responseStatus,web_ready:responseStatus.web_ready??true}};
    }
    else if(path==='/api/uploads')body={id:'test-job',state:'received'};
    else if(path==='/api/jobs/test-job/categories')body={categories:[{code:'food',name:'식비'}]};
    else if(path==='/api/jobs/test-job/control'){
      const data=JSON.parse(options.body);
      if(data.action==='edit')detailJob={...detailJob,state:'waiting',error:null,revision:(detailJob.revision||0)+1,extraction:{...detailJob.extraction,...data.values}};
      if(data.action==='confirm')detailJob={...detailJob,state:'creating'};
      if(data.action==='cancel')detailJob={...detailJob,state:'cancelled'};
      body=detailJob;
    }
    else if(path==='/api/jobs/test-job')body=detailJob;
    else throw Error('Unexpected API request '+path);
    return {ok:code===200,status:code,json:async()=>structuredClone(body)};
  };
  for (const element of w.document.querySelectorAll('script[src]')) {
    const path=element.getAttribute('src');
    new Script(scripts.get(path), {filename:path}).runInContext(dom.getInternalVMContext());
  }
  await flush();
  return {dom,w,requests,errors};
}
async function login(w){
  const d=w.document;
  d.querySelector('#password').value='TEST_ADMIN_PASSWORD';
  d.querySelector('#login-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await flush();
}

test('login, dashboard, navigation and safe rendering of receipt content',async()=>{
  const {dom,w,requests,errors}=await app();
  const d=w.document;
  assert.equal(d.querySelector('#login').hidden,false);
  await login(w);
  assert.equal(d.querySelector('#app').hidden,false);
  assert.equal(d.querySelectorAll('.stat').length,4);
  assert.match(d.querySelector('#content').textContent, /사진 한 장이/);
  assert.equal(d.querySelectorAll('[onerror]').length,0);
  assert.match(d.querySelector('#content').textContent, /<img src=x/);
  d.querySelector('[data-page="jobs"]').click();
  await flush();
  assert.equal(d.querySelector('#breadcrumb').textContent,'작업 내역');
  d.querySelector('tr[data-id]').click();
  await flush();
  assert.equal(d.querySelector('#detail').open,true);
  assert.match(d.querySelector('#detail-body').textContent,/확인·저장/);
  d.querySelector('#close-detail').click();
  d.querySelector('[data-page="logs"]').click();
  await flush();
  assert.match(d.querySelector('#content').textContent,/테스트 로그/);
  d.querySelectorAll('.tabs button')[1].click();
  await flush();
  assert.ok(requests.some(request=>request.path.includes('kind=events')));
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('settings populate, validate and save with CSRF; logout clears the screen',async()=>{
  const {dom,w,requests,errors}=await app();
  const d=w.document;
  await login(w);
  d.querySelector('[data-page="settings"]').click();
  await flush();
  assert.equal(d.querySelector('[name="ai_model"]').value,'test-vision');
  assert.equal(d.querySelector('[name="telegram_token"]').value,'');
  assert.equal(d.querySelector('[name="ledger_password"]').value,'');
  d.querySelector('[name="ai_model"]').value='updated-vision';
  d.querySelector('[name="ai_model"]').dispatchEvent(new w.Event('input',{bubbles:true}));
  d.querySelector('#settings-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await flush();
  const request=requests.find(request=>request.path==='/api/settings'&&request.options.method==='POST');
  assert.ok(request);
  const values=JSON.parse(request.options.body);
  assert.equal(values.ai_model,'updated-vision');
  assert.equal(values.auto_save,false);
  assert.deepEqual(values.allowed_users,[1]);
  assert.deepEqual(values.user_accounts,{'1':'test-account'});
  assert.equal(request.options.headers['X-CSRF-Token'],'TEST_CSRF');
  assert.equal(Object.keys(values).length,Object.keys(settings).length+1);
  assert.deepEqual(values.secrets,{});
  d.querySelector('#logout').click();
  await flush();
  assert.equal(d.querySelector('#app').hidden,true);
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('first visitor sets and confirms the administrator password on screen', async()=>{
  const {dom,w,requests,errors}=await app(true);
  const d=w.document;
  assert.match(d.querySelector('#login-heading').textContent,/처음/);
  assert.equal(d.querySelector('#password-confirm-row').hidden,false);
  d.querySelector('#setup-password').value='FIRST_ADMIN_PASSWORD';
  d.querySelector('#password-confirm').value='WRONG';
  d.querySelector('#setup-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await flush();
  assert.match(d.querySelector('#setup-error').textContent,/일치/);
  assert.equal(requests.some(r=>r.path==='/api/setup'),false);
  d.querySelector('#password-confirm').value='FIRST_ADMIN_PASSWORD';
  d.querySelector('#setup-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await flush();
  const sent=requests.find(r=>r.path==='/api/setup');
  assert.equal(JSON.parse(sent.options.body).confirmation,'FIRST_ADMIN_PASSWORD');
  assert.equal(d.querySelector('#app').hidden,false);
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('connection secret fields and Antigravity are configurable without echoing saved values',async()=>{
  const {dom,w,requests}=await app();
  const d=w.document;
  await login(w);
  d.querySelector('[data-page="settings"]').click();
  await flush();
  d.querySelector('[name="telegram_token"]').value='123:TEST_BOT_TOKEN';
  d.querySelector('[name="ledger_password"]').value='TEST_APP_PASSWORD';
  d.querySelector('[name="ai_provider"]').value='agy';
  d.querySelector('[name="allow_external_ai"]').checked=true;
  d.querySelector('#settings-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await flush();
  const sent=requests.filter(r=>r.path==='/api/settings'&&r.options.method==='POST').at(-1);
  const payload=JSON.parse(sent.options.body);
  assert.deepEqual(payload.secrets,{telegram_token:'123:TEST_BOT_TOKEN',ledger_password:'TEST_APP_PASSWORD'});
  assert.equal(payload.ai_provider,'agy');
  assert.equal(payload.allow_external_ai,true);
  assert.equal(d.querySelector('[name="telegram_token"]').value,'');
  assert.equal(d.querySelector('[name="ledger_password"]').value,'');
  d.querySelector('[name="remove_telegram_token"]').checked=true;
  d.querySelector('#settings-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await flush();
  const cleared=requests.filter(r=>r.path==='/api/settings'&&r.options.method==='POST').at(-1);
  assert.equal(JSON.parse(cleared.options.body).secrets.telegram_token,null);
  dom.window.close();
});

test('log timestamps are exact, range filters survive tab changes and can reset',async()=>{
  const {dom,w,requests,errors}=await app();
  const d=w.document;
  await login(w);
  d.querySelector('[data-page="logs"]').click();
  await flush();
  assert.equal(d.querySelector('.log-time').textContent,'2026-11-03 00:11');
  d.querySelector('#log-from').value='2026-11-03T00:00';
  d.querySelector('#log-to').value='2026-11-03T00:11';
  d.querySelector('#log-search').value='연결';
  d.querySelector('form.log-filters').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await flush();
  let query=new URL(requests.filter(r=>r.path.startsWith('/api/logs?')).at(-1).path,'http://localhost').searchParams;
  assert.equal(query.get('from'),'2026-11-03T00:00');
  assert.equal(query.get('to'),'2026-11-03T00:11');
  assert.equal(query.get('search'),'연결');
  d.querySelectorAll('.tabs button')[1].click();
  await flush();
  query=new URL(requests.filter(r=>r.path.startsWith('/api/logs?')).at(-1).path,'http://localhost').searchParams;
  assert.equal(query.get('kind'),'events');
  assert.equal(query.get('to'),'2026-11-03T00:11');
  d.querySelector('#log-reset').click();
  await flush();
  query=new URL(requests.filter(r=>r.path.startsWith('/api/logs?')).at(-1).path,'http://localhost').searchParams;
  assert.equal(query.get('from'),'');
  assert.equal(query.get('to'),'');
  assert.equal(query.get('search'),'');
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('settings group credentials by service and show only the selected AI configuration', async()=>{
  const {dom,w,requests,errors}=await app();
  const d=w.document;
  await login(w);
  d.querySelector('[data-page="settings"]').click();
  await flush();
  assert.match(d.querySelector('[name="ledger_password"]').closest('section').textContent,/가계부 연결/);
  assert.equal(d.querySelector('[name="ledger_password"]').closest('section').querySelector('[name="telegram_token"]'),null);
  assert.match(d.querySelector('[name="telegram_token"]').closest('section').textContent,/메신저 연결 · Telegram/);
  assert.equal(d.querySelectorAll('.planned-connection').length,2);
  const provider=d.querySelector('[name="ai_provider"]');
  const visible=key=>!d.querySelector(`[data-setting="${key}"]`).hidden;
  assert.equal(visible('ollama_url'),true);
  assert.equal(visible('ai_runner_url'),false);
  for (const choice of ['agy','codex','claude']) {
    provider.value=choice;
    provider.dispatchEvent(new w.Event('change',{bubbles:true}));
    assert.equal(visible('ollama_url'),false);
    assert.equal(visible('ai_runner_url'),true);
    assert.equal(d.querySelector('[name="allow_external_ai"]').closest('.toggle-row').hidden,false);
    assert.equal(d.querySelector('[name="allow_external_ai"]').checked,false);
    assert.equal(d.querySelector('[name="ai_model"]').value,'');
  }
  provider.value='ollama';
  provider.dispatchEvent(new w.Event('change',{bubbles:true}));
  assert.equal(d.querySelector('[name="ai_model"]').value,'test-vision');
  assert.equal(d.querySelector('[name="allow_external_ai"]').closest('.toggle-row').hidden,true);
  d.querySelector('#settings-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await flush();
  const payload=JSON.parse(requests.filter(r=>r.path==='/api/settings'&&r.options.method==='POST').at(-1).options.body);
  assert.equal(payload.ai_runner_url,settings.ai_runner_url);
  assert.equal(payload.allow_external_ai,false);
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('log range inputs use an explicit 24 hour format and send normalized timestamps',async()=>{
  const {dom,w,requests}=await app();
  const d=w.document;
  await login(w);
  d.querySelector('[data-page="logs"]').click();
  await flush();
  const start=d.querySelector('#log-from'), end=d.querySelector('#log-to');
  assert.equal(start.type,'text');
  start.value='2026-11-03 23:10'; end.value='2026-11-03 23:59';
  assert.equal(start.checkValidity(),true);
  end.value='2026-11-03 24:00';
  assert.equal(end.checkValidity(),false);
  end.value='2026-11-03 23:59';
  d.querySelector('.log-filters').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await flush();
  const query=new URL(requests.filter(r=>r.path.startsWith('/api/logs?')).at(-1).path,'http://localhost').searchParams;
  assert.equal(query.get('from'),'2026-11-03T23:10');
  assert.equal(query.get('to'),'2026-11-03T23:59');
  assert.ok(d.querySelector('link[rel="icon"][href="/favicon.svg"]'));
  dom.window.close();
});

test('incomplete setup shows the exact missing steps in the page and checklist',async()=>{
  const missing=['메신저 연결 · Telegram → 허용 채팅 ID를 입력하세요.','AI 분석 → 외부 AI 전송 허용을 켜세요.'];
  const {dom,w}=await app(false,{...status,demo:false,ready:false,missing});
  await login(w);
  w.document.querySelector('[data-page="settings"]').click();
  await flush();
  const d=w.document;
  assert.equal(d.querySelectorAll('.setup-checklist li').length,2);
  for (const text of missing) assert.ok(d.querySelector('.notice.warn').textContent.includes(text));
  dom.window.close();
});

test('dashboard setup notice is short, links to settings, and button icons have explicit size',async()=>{
  const {dom,w}=await app(false,{...status,demo:false,ready:false,paused:true,missing:['PRIVATE_DETAIL']});
  const d=w.document;
  await login(w);
  const notice=d.querySelector('.notice.warn');
  assert.match(notice.textContent,/서비스 설정에서 연결하기/);
  assert.equal(notice.textContent.includes('PRIVATE_DETAIL'),false);
  const button=d.querySelector('.page-head button');
  assert.match(button.textContent,/처리 재개/);
  assert.equal(button.querySelector('svg').getAttribute('width'),'18');
  assert.equal(button.querySelector('svg').getAttribute('height'),'18');
  notice.querySelector('button').click();
  await flush();
  const save=d.querySelector('.save-bar button[type="submit"]');
  assert.match(save.textContent,/변경 사항 저장/);
  assert.equal(save.querySelector('svg').getAttribute('width'),'18');
  assert.equal(save.querySelector('svg path').getAttribute('d'),'M5 12l4 4L19 6');
  dom.window.close();
});

test('log picker supports 24-hour selection, manual edits and clearing both filters',async()=>{
  const {dom,w,requests,errors}=await app();
  const d=w.document;
  await login(w);
  d.querySelector('[data-page="logs"]').click(); await flush();
  for (const [id,value] of [['log-from','2026-11-04 00:00'],['log-to','2026-11-04 23:59']]) {
    const input=d.querySelector('#'+id);
    const button=input.parentElement.querySelector('.date-picker-button');
    button.click();
    assert.equal(button.getAttribute('aria-expanded'),'true');
    const picker=d.querySelector('#'+id+'-picker');
    picker.querySelector('input[type="date"]').value=value.slice(0,10);
    const choices=picker.querySelectorAll('select');
    assert.equal(choices[0].options.length,24);
    assert.equal(choices[1].options.length,60);
    choices[0].value=value.slice(11,13); choices[1].value=value.slice(14,16);
    picker.querySelector('button').click();
    assert.equal(input.value,value);
    assert.equal(picker.hidden,true);
    assert.equal(button.getAttribute('aria-expanded'),'false');
  }
  d.querySelector('.log-filters').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true})); await flush();
  let query=new URL(requests.filter(r=>r.path.startsWith('/api/logs?')).at(-1).path,'http://localhost').searchParams;
  assert.equal(query.get('to'),'2026-11-04T23:59');
  d.querySelector('#log-from').value='2026-11-04 01:15';
  d.querySelector('#log-from').parentElement.querySelector('.date-picker-button').click();
  assert.equal(d.querySelector('#log-from-picker select').value,'01');
  d.querySelector('#log-from-picker').dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  assert.equal(d.querySelector('#log-from-picker').hidden,true);
  d.querySelector('#log-reset').click(); await flush();
  query=new URL(requests.filter(r=>r.path.startsWith('/api/logs?')).at(-1).path,'http://localhost').searchParams;
  assert.equal(query.get('from'),''); assert.equal(query.get('to'),'');
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('amount fields group thousands while saving integer values and rejecting invalid input',async()=>{
  const {dom,w,requests}=await app();
  const d=w.document;
  await login(w); d.querySelector('[data-page="settings"]').click(); await flush();
  const input=d.querySelector('[name="max_amount_minor"]');
  assert.equal(input.value,'9,000,000,000,000');
  assert.equal(d.querySelector('[name="auto_max_amount_minor"]').value,'50,000');
  input.value='1234567'; input.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.equal(input.value,'1,234,567');
  d.querySelector('#settings-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true})); await flush();
  const post=requests.filter(r=>r.path==='/api/settings'&&r.options.method==='POST');
  assert.equal(JSON.parse(post.at(-1).options.body).max_amount_minor,1234567);
  d.querySelector('[name="max_amount_minor"]').value='12.5';
  d.querySelector('#settings-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true})); await flush();
  assert.equal(requests.filter(r=>r.path==='/api/settings'&&r.options.method==='POST').length,post.length);
  assert.match(d.querySelector('#settings-error').textContent,/정수/);
  assert.match(d.querySelector('#content').textContent,/Telegram 없이 하나만/);
  dom.window.close();
});

test('sidebar hint can be dismissed and the browser preference is retained',async()=>{
  const {dom,w}=await app();
  const d=w.document;
  await login(w);
  assert.equal(d.querySelector('.sidebar-note').hidden,false);
  d.querySelector('#dismiss-sidebar-note').click();
  assert.equal(d.querySelector('.sidebar-note').hidden,true);
  assert.equal(w.localStorage.getItem('rb-hide-sidebar-note'),'1');
  d.querySelector('[data-page="logs"]').click(); await flush();
  assert.equal(d.querySelector('.sidebar-note').hidden,true);
  dom.window.close();
});

test('secret buttons toggle typed values without submitting or sending them to the server',async()=>{
  const {dom,w,requests}=await app();
  const d=w.document;
  const loginInput=d.querySelector('#password');
  const loginToggle=loginInput.parentElement.querySelector('button');
  loginInput.value='TEST_PASSWORD'; loginToggle.click();
  assert.equal(loginInput.type,'text');
  assert.equal(loginToggle.getAttribute('aria-pressed'),'true');
  assert.equal(requests.some(r=>r.path==='/api/login'),false);
  loginToggle.click(); assert.equal(loginInput.type,'password');
  await login(w);
  d.querySelector('[data-page="settings"]').click(); await flush();
  for(const name of ['telegram_token','ledger_password']) {
    const input=d.querySelector(`[name="${name}"]`), toggle=input.parentElement.querySelector('button');
    input.value='TEST_TYPED_SECRET';
    toggle.click(); assert.equal(input.type,'text');
    toggle.click(); assert.equal(input.type,'password');
    assert.equal(input.value,'TEST_TYPED_SECRET');
  }
  assert.equal(requests.some(r=>r.path==='/api/settings/reveal-secret'),false);
  assert.equal(requests.some(r=>r.path==='/api/settings'&&r.options.method==='POST'),false);
  dom.window.close();
});

test('stored secrets are revealed only on demand and previews are not saved or retained on logout',async()=>{
  const {dom,w,requests}=await app(false,status,{telegram_token:true});
  const d=w.document;
  await login(w); d.querySelector('[data-page="settings"]').click(); await flush();
  let input=d.querySelector('[name="telegram_token"]');
  assert.equal(input.value,'');
  assert.equal(requests.some(r=>r.path==='/api/settings/reveal-secret'),false);
  let toggle=input.parentElement.querySelector('button');
  toggle.click(); await flush();
  assert.equal(input.type,'text'); assert.equal(input.value,'TEST_SAVED_SECRET'); assert.equal(input.readOnly,true);
  const reveal=requests.find(r=>r.path==='/api/settings/reveal-secret');
  assert.equal(reveal.options.headers['X-CSRF-Token'],'TEST_CSRF');
  toggle.click();
  assert.equal(input.type,'password'); assert.equal(input.value,''); assert.equal(input.readOnly,false);
  toggle.click(); await flush();
  d.querySelector('#settings-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true})); await flush();
  const saved=JSON.parse(requests.filter(r=>r.path==='/api/settings'&&r.options.method==='POST').at(-1).options.body);
  assert.deepEqual(saved.secrets,{});
  input=d.querySelector('[name="telegram_token"]');
  input.parentElement.querySelector('button').click(); await flush();
  d.querySelector('#logout').click(); await flush();
  assert.equal(input.value,''); assert.equal(input.type,'password');
  dom.window.close();
});

test('direct links, browser back and forward preserve routes and unsaved settings',async()=>{
  const {dom,w}=await app(false,status,{},'/settings');
  const d=w.document;
  await login(w);
  assert.equal(w.location.pathname,'/settings');
  assert.equal(d.querySelector('#breadcrumb').textContent,'서비스 설정');
  d.querySelector('[data-page="logs"]').click(); await flush();
  assert.equal(w.location.pathname,'/logs');
  d.querySelector('[data-page="settings"]').click(); await flush();
  const model=d.querySelector('[name="ai_model"]');
  model.value='UNSAVED'; model.dispatchEvent(new w.Event('input',{bubbles:true}));
  w.confirm=()=>false;
  w.history.back(); await new Promise(resolve=>setTimeout(resolve,60)); await flush();
  assert.equal(w.location.pathname,'/settings');
  assert.equal(d.querySelector('[name="ai_model"]').value,'UNSAVED');
  w.confirm=()=>true;
  w.history.back(); await new Promise(resolve=>setTimeout(resolve,30)); await flush();
  assert.equal(w.location.pathname,'/logs');
  assert.equal(d.querySelector('#breadcrumb').textContent,'로그 조회');
  w.history.forward(); await new Promise(resolve=>setTimeout(resolve,30)); await flush();
  assert.equal(w.location.pathname,'/settings');
  assert.equal(d.querySelector('#breadcrumb').textContent,'서비스 설정');
  dom.window.close();
});


test('CLI connection checks, model selection and API keys stay out of general settings',async()=>{
  const chosen={...settings,ai_provider:'agy',allow_external_ai:true};
  const {dom,w,requests,errors}=await app(false,status,{},"/",chosen);
  const d=w.document;
  await login(w);
  d.querySelector('[data-page="settings"]').click();
  await flush();
  assert.equal(d.querySelector('#ai-setup').hidden,false);
  assert.equal(d.querySelector('#ai-claude-key').hidden,true);
  assert.match(d.querySelector('#ai-login-command').textContent,/--entrypoint agy/);
  assert.match(d.querySelector('#ai-login-command').textContent,/cd "\/실제\/설치\/폴더" &&/);
  assert.match(d.querySelector('#ai-login-guide').textContent,/compose.yaml.*설치 폴더/);
  d.querySelector('#ai-check').click();
  await flush();
  const call=requests.find(r=>r.path==='/api/ai/check');
  assert.ok(call);
  assert.equal(call.options.headers['X-CSRF-Token'],'TEST_CSRF');
  assert.match(d.querySelector('#ai-check-result').textContent,/로그인/);
  d.querySelector('#ai-model-options button').click();
  assert.equal(d.querySelector('[name="ai_model"]').value,'gemini-test-low');
  d.querySelector('#ai-check').click();
  await flush();
  assert.equal(requests.filter(r=>r.path==='/api/ai/check').length,1);
  assert.match(d.querySelector('#ai-check-result').textContent,/먼저 변경 사항 저장/);
  assert.deepEqual(errors,[]);
  dom.window.close();

  const claude=await app(false,status,{},"/",{...settings,ai_provider:'claude',allow_external_ai:true});
  await login(claude.w);
  claude.w.document.querySelector('[data-page="settings"]').click();
  await flush();
  const c=claude.w.document;
  assert.equal(c.querySelector('#ai-login-guide').hidden,true);
  const input=c.querySelector('#ai-api-key');
  input.value='TEST_CLAUDE_KEY';
  input.dispatchEvent(new claude.w.Event('input',{bubbles:true}));
  c.querySelector('#ai-key-save').click();
  await flush();
  const saved=claude.requests.find(r=>r.path==='/api/ai/credentials');
  assert.deepEqual(JSON.parse(saved.options.body),{key:'TEST_CLAUDE_KEY'});
  assert.equal(input.value,'');
  assert.equal(claude.requests.filter(r=>r.path==='/api/settings' && r.options.method==='POST').length,0);
  assert.deepEqual(claude.errors,[]);
  claude.dom.window.close();
});


test('text expense detail shows the original input safely without a missing-photo warning',async()=>{
  const source='오늘 <img src=x onerror=alert(1)>에서 5000원, BB에서 43500원';
  const textJob={...job,input_kind:'text',input_text:source,batch_size:2,part:1,has_image:false,has_original:false};
  const {dom,w,errors}=await app(false,status,{},"/",settings,textJob);
  await login(w);
  w.document.querySelector('[data-page="jobs"]').click();
  await flush();
  w.document.querySelector('tr[data-id]').click();
  await flush();
  const body=w.document.querySelector('#detail-body');
  assert.match(body.textContent,/텍스트로 입력한 지출/);
  assert.match(body.textContent,/2건 중 2번째/);
  assert.equal(body.querySelector('.input-source').textContent,source);
  assert.equal(body.querySelectorAll('[onerror]').length,0);
  assert.equal(body.querySelectorAll('img').length,0);
  assert.deepEqual(errors,[]);
  dom.window.close();
});


test('password-manager button click submits the login form without input events',async()=>{
  const {dom,w,requests,errors}=await app();
  const d=w.document;
  const form=d.querySelector('#login-form');
  assert.equal(form.method,'post');
  assert.equal(form.getAttribute('action'),'/api/login');
  assert.equal(form.querySelectorAll('input[type="password"]').length,1);
  assert.equal(d.querySelector('#setup-form').hidden,true);
  assert.equal(d.querySelector('#password-confirm').disabled,true);
  d.querySelector('#password').value='TEST_ADMIN_PASSWORD';
  d.querySelector('#login-submit').click();
  await flush();
  assert.equal(requests.filter(r=>r.path==='/api/login').length,1);
  assert.equal(d.querySelector('#app').hidden,false);
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('browser uploads multiple photos with CSRF and distinct stable upload keys',async()=>{
  const {dom,w,requests,errors}=await app();
  await login(w);
  const d=w.document;
  d.querySelector('[data-page="upload"]').click();
  await flush();
  assert.equal(w.location.pathname,'/upload');
  const files=[new w.File(['TEST_ONE'],'first.png',{type:'image/png'}),new w.File(['TEST_TWO'],'second.png',{type:'image/png'})];
  Object.defineProperty(d.querySelector('#upload-files'),'files',{value:files,configurable:true});
  d.querySelector('#upload-caption').value='식비';
  d.querySelector('#upload-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await flush();
  const calls=requests.filter(r=>r.path==='/api/uploads');
  assert.equal(calls.length,2);
  assert.equal(new Set(calls.map(r=>r.options.headers['Idempotency-Key'])).size,2);
  for(const call of calls){
    assert.equal(call.options.headers['X-CSRF-Token'],'TEST_CSRF');
    assert.equal(call.options.headers['Content-Type'],undefined);
    assert.equal(call.options.body.get('account'),'test-account');
    assert.equal(call.options.body.get('caption'),'식비');
  }
  assert.match(d.querySelector('#upload-feedback').textContent,/2\/2장/);
  d.querySelector('#upload-results button').click();
  await flush();
  assert.equal(d.querySelector('#detail').open,true);
  assert.ok(d.querySelector('[data-job-action="confirm"]'));
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('browser receipt editor preserves revision when confirming',async()=>{
  const {dom,w,requests,errors}=await app();
  await login(w);
  const d=w.document;
  d.querySelector('[data-page="jobs"]').click();
  await flush();
  d.querySelector('tr[data-id]').click();
  await flush();
  Array.from(d.querySelectorAll('#detail-body button')).find(b=>b.textContent==='거래 정보 수정').click();
  await flush();
  d.querySelector('#edit-amount').value='15000';
  d.querySelector('.job-edit-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  await flush();
  const edit=requests.filter(r=>r.path==='/api/jobs/test-job/control').at(-1);
  assert.equal(JSON.parse(edit.options.body).values.amount,'15000');
  assert.equal(JSON.parse(edit.options.body).revision,0);
  d.querySelector('[data-job-action="confirm"]').click();
  await flush();
  const confirm=requests.filter(r=>r.path==='/api/jobs/test-job/control').at(-1);
  assert.equal(JSON.parse(confirm.options.body).action,'confirm');
  assert.equal(JSON.parse(confirm.options.body).revision,1);
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('upload account lookup failure and empty results stay disabled until successful retry',async()=>{
  const {dom,w,requests,errors}=await app(false,status,{},'/',settings,job,[
    {error:'가계부 연결 실패 · 같은 Docker 네트워크를 확인하세요'},
    {accounts:[]},
    {accounts:[{id:'test-account',name:'테스트 계좌',currency:'KRW'}]},
  ]);
  await login(w);
  const d=w.document;
  d.querySelector('[data-page="upload"]').click(); await flush();
  assert.match(d.querySelector('#upload-feedback').textContent,/Docker 네트워크/);
  assert.equal(d.querySelector('#upload-account').disabled,true);
  const files=d.querySelector('#upload-files');
  Object.defineProperty(files,'files',{value:[new w.File(['TEST'],'test.png',{type:'image/png'})]});
  files.dispatchEvent(new w.Event('change'));
  assert.equal(d.querySelector('#upload-form button[type="submit"]').disabled,true);
  d.querySelector('#upload-form').dispatchEvent(new w.Event('submit',{cancelable:true})); await flush();
  assert.equal(requests.some(r=>r.path==='/api/uploads'),false);
  d.querySelector('#upload-reload-accounts').click(); await flush();
  assert.match(d.querySelector('#upload-feedback').textContent,/read·create·receipts/);
  files.dispatchEvent(new w.Event('change'));
  assert.equal(d.querySelector('#upload-form button[type="submit"]').disabled,true);
  d.querySelector('#upload-reload-accounts').click(); await flush();
  assert.equal(d.querySelector('#upload-account').value,'test-account');
  assert.equal(d.querySelector('#upload-form button[type="submit"]').disabled,false);
  d.querySelector('#upload-form').dispatchEvent(new w.Event('submit',{cancelable:true})); await flush();
  assert.equal(requests.filter(r=>r.path==='/api/uploads').length,1);
  d.querySelector('#upload-reload-accounts').click(); await flush();
  assert.equal(d.querySelector('#upload-form button[type="submit"]').disabled,true);
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('30MB browser upload uses configured limit and settings show supported range',async()=>{
  const {dom,w,requests,errors}=await app(false,status,{},'/',{...settings,max_download_mb:30});
  await login(w);
  const d=w.document;
  d.querySelector('[data-page="settings"]').click(); await flush();
  const limit=d.querySelector('[name="max_download_mb"]');
  assert.equal(limit.min,'1'); assert.equal(limit.max,'100');
  assert.match(limit.parentElement.textContent,/Telegram.*20MB/);
  d.querySelector('[data-page="upload"]').click(); await flush();
  assert.match(d.querySelector('#upload-feedback').textContent,/30MB/);
  const file=new w.File(['TEST'],'large.png',{type:'image/png'});
  Object.defineProperty(file,'size',{value:30*1024*1024});
  const files=d.querySelector('#upload-files');
  Object.defineProperty(files,'files',{value:[file]});
  files.dispatchEvent(new w.Event('change'));
  d.querySelector('#upload-form').dispatchEvent(new w.Event('submit',{cancelable:true})); await flush();
  assert.equal(requests.filter(r=>r.path==='/api/uploads').length,1);
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('failed analysis without AI extraction allows manual entry before explicit confirmation',async()=>{
  const failed={...job,state:'failed',extraction:null,error:'AI 분석 실패'};
  const {dom,w,requests,errors}=await app(false,status,{},'/',settings,failed);
  await login(w);
  const d=w.document;
  d.querySelector('[data-page="jobs"]').click(); await flush();
  d.querySelector('tr[data-id]').click(); await flush();
  assert.equal(d.querySelector('[data-job-action="confirm"]'),null);
  d.querySelector('[data-job-action="edit"]').click(); await flush();
  for(const [key,value] of Object.entries({merchant:'테스트 상점',amount:'5000',date:'2026-01-15',currency:'KRW',category:'food'}))d.querySelector('#edit-'+key).value=value;
  assert.equal(d.querySelector('#edit-time').value,'');
  d.querySelector('.job-edit-form').dispatchEvent(new w.Event('submit',{cancelable:true})); await flush();
  const calls=requests.filter(r=>r.path==='/api/jobs/test-job/control');
  assert.equal(calls.length,1); assert.equal(JSON.parse(calls[0].options.body).action,'edit');
  assert.equal(JSON.parse(calls[0].options.body).values.merchant,'테스트 상점');
  assert.ok(d.querySelector('[data-job-action="confirm"]'));
  assert.deepEqual(errors,[]);
  dom.window.close();
});

test('receipt amounts show grouping, preserve decimals and submit plain exact strings',async()=>{
  const {dom,w,requests,errors}=await app();
  await login(w);
  const d=w.document;
  assert.match(d.querySelector('td.amount').textContent,/12,000원/);
  d.querySelector('[data-page="jobs"]').click(); await flush();
  d.querySelector('tr[data-id]').click(); await flush();
  assert.match(d.querySelector('.detail-facts').textContent,/12,000원/);
  d.querySelector('[data-job-action="edit"]').click(); await flush();
  const amount=d.querySelector('#edit-amount');
  assert.equal(amount.value,'12,000');
  amount.value='100000000';amount.dispatchEvent(new w.InputEvent('input',{inputType:'insertText'}));
  assert.equal(amount.value,'100,000,000');
  assert.equal(amount.selectionStart,amount.value.length);
  amount.value='1,2';amount.dispatchEvent(new w.InputEvent('input',{inputType:'insertFromPaste'}));
  d.querySelector('.job-edit-form').dispatchEvent(new w.Event('submit',{cancelable:true})); await flush();
  assert.equal(requests.filter(r=>r.path==='/api/jobs/test-job/control').length,0);
  amount.value='9007199254740993.010';amount.dispatchEvent(new w.InputEvent('input',{inputType:'insertText'}));
  assert.equal(amount.value,'9,007,199,254,740,993.010');
  d.querySelector('.job-edit-form').dispatchEvent(new w.Event('submit',{cancelable:true})); await flush();
  const call=requests.filter(r=>r.path==='/api/jobs/test-job/control').at(-1);
  assert.equal(JSON.parse(call.options.body).values.amount,'9007199254740993.010');
  assert.deepEqual(errors,[]);
  dom.window.close();
});
