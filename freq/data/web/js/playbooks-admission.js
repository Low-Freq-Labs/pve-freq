// Isolated observation admission. No product imports, I/O, DOM or execution.
export const MAX_BYTES = 1048576;
const WS = new Set(Array.from(' \t\n\r\v\f\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000'));
const ROW = ['filename', 'name', 'description', 'trigger', 'steps'];
const STEP = ['name', 'type', 'command', 'target', 'expect', 'confirm', 'timeout'];
class ExactNumber { constructor(token) { this.token = token; } }
function freeze(value) {
  const pending = [value];
  while (pending.length) {
    const item = pending.pop();
    if (!item || typeof item !== 'object' || Object.isFrozen(item)) continue;
    pending.push(...Object.values(item)); Object.freeze(item);
  }
  return value;
}
function unavailable(reason, generation) {
  return freeze({state:'unavailable', reason, returned_count:null, accepted_count:null,
    rejected_count:null, rows:[], source_complete:null, execution_authorized:false,
    generation:Number.isSafeInteger(generation) && generation >= 0 ? generation : null});
}
function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value) && !(value instanceof ExactNumber); }
function closed(value, keys) { return object(value) && Object.keys(value).length === keys.length && keys.every(k => Object.hasOwn(value,k)); }
function validText(value, max, multiline=false, nonblank=false) {
  if (typeof value !== 'string') return false;
  let count=0, nonspace=false;
  for (const c of value) {
    if (++count > max) return false;
    const n=c.codePointAt(0);
    if (n>=0xd800 && n<=0xdfff) return false;
    if ((n<32 || (n>=127 && n<=159)) && !(multiline && '\t\r\n'.includes(c))) return false;
    if (!WS.has(c)) nonspace=true;
  }
  return !nonblank || nonspace;
}
function filename(value) {
  if (!validText(value,255,false,true) || value.length<=5 || !value.endsWith('.toml') ||
      WS.has(value[0]) || WS.has(value.at(-1)) || value.includes('/') || value.includes('\\') || value.includes('..')) return false;
  let bytes=0;
  for (const c of value) { const n=c.codePointAt(0); bytes+=n<=127?1:n<=2047?2:n<=65535?3:4; }
  return bytes<=255;
}
function timeout(value) {
  if (!(value instanceof ExactNumber)) return null;
  const m=/^(-?)(0|[1-9][0-9]*)(?:\.([0-9]+))?(?:[eE]([+-]?[0-9]+))?$/.exec(value.token);
  if (!m || m[1]) return null;
  const fraction=m[3] || '';
  const digits=(m[2]+fraction).replace(/^0+/,'');
  if (!digits) return null;
  let end=digits.length;
  while (end>0 && digits[end-1]==='0') end--;
  const core=digits.slice(0,end);
  const exp=m[4] || '0';
  const significant=exp.replace(/^[+-]/,'').replace(/^0+/,'') || '0';
  if (significant.length>7) return null;
  const scale=Number(significant)*(exp.startsWith('-')?-1:1)-fraction.length+digits.length-core.length;
  if (scale<0 || core.length+scale>4) return null;
  const number=Number(core)*10**scale;
  return number>=1 && number<=3600 ? number : null;
}
function validStep(s) {
  return closed(s,STEP) && validText(s.name,256) && (s.type==='check'||s.type==='action') &&
    validText(s.command,8192,true) && validText(s.target,256) && validText(s.expect,4096,true) &&
    typeof s.confirm==='boolean' && timeout(s.timeout)!==null;
}
function rowReason(r) {
  if (!closed(r,ROW)) return 'row_shape';
  if (!filename(r.filename)) return 'filename';
  if (!validText(r.name,256,false,true)) return 'name';
  if (!validText(r.description,2048,true)||!validText(r.trigger,256)) return 'metadata';
  if (!Array.isArray(r.steps)||r.steps.length>128) return 'steps';
  if (!r.steps.every(validStep)) return 'step_schema';
  return null;
}
// Iterative JSON parser: stack frames track exact punctuation and decoded keys.
function parse(raw) {
  let pos=0, root, hasRoot=false;
  const stack=[];
  const number=/-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/y;
  function skip() { while (pos<raw.length && ' \t\r\n'.includes(raw[pos])) pos++; }
  function fail() { throw new SyntaxError('json'); }
  function string() {
    const start=pos++;
    while (pos<raw.length) {
      const c=raw[pos++];
      if (c==='"') return JSON.parse(raw.slice(start,pos));
      if (c==='\\') pos++;
      else if (c.charCodeAt(0)<32) fail();
    }
    fail();
  }
  function attach(value) {
    if (!stack.length) { if (hasRoot) fail(); root=value; hasRoot=true; return; }
    const f=stack.at(-1);
    if (f.kind==='array') f.value.push(value);
    else f.value[f.key]=value;
    f.state='after';
  }
  function value() {
    skip(); const c=raw[pos];
    if (c==='{'||c==='[') {
      pos++; const v=c==='{'?Object.create(null):[]; attach(v);
      stack.push({kind:c==='{'?'object':'array',value:v,state:'first',keys:new Set()}); return;
    }
    if (c==='"') { attach(string()); return; }
    for (const [word,v] of [['true',true],['false',false],['null',null]]) {
      if (raw.startsWith(word,pos)) { pos+=word.length; attach(v); return; }
    }
    number.lastIndex=pos; const m=number.exec(raw);
    if (!m) fail(); pos=number.lastIndex; attach(new ExactNumber(m[0]));
  }
  value();
  while (stack.length) {
    skip(); const f=stack.at(-1), c=raw[pos];
    const close=f.kind==='array'?']':'}';
    if (f.state==='after') {
      if (c===close) { pos++; stack.pop(); continue; }
      if (c!==',') fail(); pos++; f.state='next'; continue;
    }
    if (f.state==='first' && c===close) { pos++; stack.pop(); continue; }
    if (f.kind==='array') { value(); continue; }
    if (c!=='"') fail();
    const key=string(); if (f.keys.has(key)) fail(); f.keys.add(key); f.key=key;
    skip(); if (raw[pos++]!==':') fail(); value();
  }
  skip(); if (pos!==raw.length) fail(); return root;
}
export function admitBytes(bytes, {generation}={}) {
  if (!Number.isSafeInteger(generation)||generation<0) return unavailable('context',generation);
  if (typeof Uint8Array!=='function' || !(bytes instanceof Uint8Array)) return unavailable('unsupported_transport',generation);
  if (bytes.byteLength>MAX_BYTES) return unavailable('body_limit',generation);
  if (typeof TextDecoder!=='function') return unavailable('unsupported_transport',generation);
  let data,decoder;
  try { decoder=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}); }
  catch { return unavailable('unsupported_transport',generation); }
  if (decoder.fatal!==true || decoder.ignoreBOM!==true || decoder.encoding!=='utf-8') return unavailable('unsupported_transport',generation);
  try {
    // ignoreBOM=true preserves U+FEFF, which the JSON grammar rejects.
    const raw=decoder.decode(bytes);
    data=parse(raw);
  } catch { return unavailable('json',generation); }
  if (!closed(data,['playbooks'])||!Array.isArray(data.playbooks)) return unavailable('envelope',generation);
  const rows=data.playbooks;
  if (rows.length>256) return unavailable('row_limit',generation);
  const counts=new Map();
  for (const r of rows) if (object(r)&&filename(r.filename)) counts.set(r.filename,(counts.get(r.filename)||0)+1);
  const accepted=[], rejected=[];
  rows.forEach((r,index)=>{
    let reason=rowReason(r);
    if (object(r)&&filename(r.filename)&&counts.get(r.filename)>1) reason='duplicate_filename';
    if (reason) { rejected.push({index,reason}); return; }
    const row={filename:r.filename,name:r.name,description:r.description,trigger:r.trigger,
      steps:r.steps.map(s=>({name:s.name,type:s.type,command:s.command,target:s.target,expect:s.expect,confirm:s.confirm,timeout:timeout(s.timeout)}))};
    accepted.push({index,filename:r.filename,name:r.name,step_count:r.steps.length,
      selection:'observed_only',execution_authorized:false,generation,row});
  });
  return freeze({state:rejected.length?'partial':rows.length?'reported':'reported_empty',
    returned_count:rows.length,accepted_count:accepted.length,rejected_count:rejected.length,
    rows:accepted,rejected,source_complete:null,execution_authorized:false,generation});
}
export async function consumeResponse(response, {generation,isCurrent,signal}={}) {
  const no=reason=>unavailable(reason,generation);
  if (!Number.isSafeInteger(generation)||generation<0) return no('context');
  if (typeof isCurrent!=='function'||!signal||typeof signal.aborted!=='boolean'||
      typeof signal.addEventListener!=='function'||typeof signal.removeEventListener!=='function') return no('context');
  function current() { try { return !signal.aborted && isCurrent()===true; } catch { return false; } }
  let reader, body, cancelled=false, success=false, retired=false, abortResolve;
  const abortResult=Symbol('retired');
  function cancel() {
    if (cancelled) return; cancelled=true;
    try {
      const target=reader||body;
      if (target&&typeof target.cancel==='function') Promise.resolve(target.cancel()).catch(()=>{});
    } catch { /* cancellation is best effort; never expose transport errors */ }
  }
  function onAbort() { retired=true; cancel(); abortResolve?.(abortResult); }
  try {
    signal.addEventListener('abort',onAbort,{once:true});
    if (!current()) { onAbort(); return no('retired'); }
    if (!response || typeof response.headers?.get!=='function') return no('unsupported_transport');
    // Retain body only for cancellation; do not interpret an error entity.
    body=response.body;
    if (response.status!==200) return no('http_status');
    const media=response.headers.get('content-type');
    if (typeof media!=='string'||media.split(';',1)[0].trim().toLowerCase()!=='application/json') return no('media_type');
    if (response.bodyUsed || !body || body.locked || typeof body.getReader!=='function' || typeof TextDecoder!=='function' || typeof Uint8Array!=='function') return no('unsupported_transport');
    if (!current()) { onAbort(); return no('retired'); }
    try { reader=body.getReader(); } catch { return no('unsupported_transport'); }
    if (!reader||typeof reader.read!=='function'||typeof reader.cancel!=='function'||typeof reader.releaseLock!=='function') return no('unsupported_transport');
    const bytes=new Uint8Array(MAX_BYTES); let length=0;
    while (true) {
      if (retired||!current()) { onAbort(); return no('retired'); }
      const pending=Promise.resolve().then(()=>current()&&!retired?reader.read():abortResult);
      // One abort waiter per pending read; no accumulating reactions on a
      // shared never-settled abort promise across an arbitrary chunk count.
      const abortPromise=new Promise(resolve=>{abortResolve=resolve;});
      let part;
      try { part=await Promise.race([pending,abortPromise]); }
      finally { abortResolve=null; }
      if (part===abortResult||retired||!current()) { onAbort(); return no('retired'); }
      if (!part || typeof part.done!=='boolean') return no('unsupported_transport');
      if (part.done) break;
      if (!(part.value instanceof Uint8Array)) return no('unsupported_transport');
      if (part.value.byteLength>MAX_BYTES-length) return no('body_limit');
      bytes.set(part.value,length); length+=part.value.byteLength;
    }
    if (!current()) { onAbort(); return no('retired'); }
    const result=admitBytes(bytes.subarray(0,length),{generation});
    if (!current()) { onAbort(); return no('retired'); }
    success=result.state!=='unavailable'; return result;
  } catch { return no(retired||!current()?'retired':'transport'); }
  finally {
    if (!success) cancel();
    try { signal.removeEventListener('abort',onAbort); } catch { /* no side effects */ }
    try { reader?.releaseLock(); } catch { /* custom pending read may retain lock */ }
  }
}
