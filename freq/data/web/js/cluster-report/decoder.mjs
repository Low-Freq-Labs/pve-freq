// Supplied structure only. No transport, clock, recipient or action authority.
const FAILED = Object.freeze({state:'unavailable', reason:'cluster_supplied_document_unavailable'});
const ROOT = ['schema','profile','capture_ref','raw_sha256','evidence','state','cluster','nodes','reported_count_relation','authority','capabilities'];
const FLAGS = ['authenticated','authoritative','fresh','visibility_complete','cluster_identity_verified','node_identity_verified','quorum_verified','action_ready','live_effect'];
const encoder = new TextEncoder();
const utf8 = new TextDecoder('utf-8', {fatal:true});
const typed = Object.getPrototypeOf(Uint8Array.prototype);
const bufferOf = Object.getOwnPropertyDescriptor(typed, 'buffer').get;
const offsetOf = Object.getOwnPropertyDescriptor(typed, 'byteOffset').get;
const lengthOf = Object.getOwnPropertyDescriptor(typed, 'byteLength').get;
const nameOf = Object.getOwnPropertyDescriptor(typed, Symbol.toStringTag).get;
const bufferLengthOf = Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, 'byteLength').get;

function need(ok) { if (!ok) throw Error('unavailable'); }
function keys(value, names) {
  need(value !== null && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype);
  const actual = Object.keys(value);
  need(actual.length === names.length && actual.every(k => names.includes(k)));
}
function space(cp) {
  return cp >= 9 && cp <= 13 || cp >= 0x1c && cp <= 0x20 || cp === 0x85 || cp === 0xa0 || cp === 0x1680 ||
    cp >= 0x2000 && cp <= 0x200a || cp === 0x2028 || cp === 0x2029 || cp === 0x202f || cp === 0x205f || cp === 0x3000;
}
function text(value, limit, empty = false, unpadded = false) {
  need(typeof value === 'string' && (empty || value.length > 0));
  let count = 0, first, last;
  for (const char of value) {
    const cp = char.codePointAt(0);
    if (count === 0) first = cp;
    last = cp;
    need(++count <= limit && !(cp < 32 || cp >= 127 && cp <= 159 || cp >= 0xd800 && cp <= 0xdfff));
  }
  need(encoder.encode(value).length <= limit);
  if (unpadded) need(!space(first) && !space(last));
  return value;
}
function label(value) { return text(value, 256, false, true); }
function flag(value) { need(typeof value === 'boolean'); return value; }
function decimal(value, max, positive = false) {
  need(typeof value === 'string' && value.length <= max.length && /^(0|[1-9][0-9]*)(?![\s\S])/.test(value));
  need((!positive || value !== '0') && (value.length < max.length || value <= max));
  return value;
}
function ipv4(value) {
  const parts = value.split('.');
  return parts.length === 4 && parts.every(s => /^(0|[1-9][0-9]{0,2})(?![\s\S])/.test(s) && Number(s) <= 255);
}
function ip(value) {
  need(typeof value === 'string' && value.length > 0 && value.length <= 64 && /^[0-9a-fA-F:.]+(?![\s\S])/.test(value));
  if (!value.includes(':')) { need(ipv4(value)); return value; }
  const halves = value.split('::');
  need(halves.length <= 2);
  const compressed = halves.length === 2;
  const left = halves[0] === '' ? [] : halves[0].split(':');
  const right = compressed && halves[1] !== '' ? halves[1].split(':') : [];
  const groups = left.concat(right);
  let width = 0;
  groups.forEach((group, index) => {
    if (group.includes('.')) {
      // A dotted tail must follow every colon, including a compression marker.
      need(index === groups.length - 1 && value.endsWith(group) && ipv4(group));
      width += 2;
    } else {
      need(/^[0-9a-fA-F]{1,4}(?![\s\S])/.test(group));
      width++;
    }
  });
  need(compressed ? width < 8 : width === 8);
  return value;
}
function option(value, validate) {
  keys(value, ['present','value']);
  flag(value.present);
  if (!value.present) need(value.value === null);
  return Object.freeze({present:value.present, value:value.present ? validate(value.value) : null});
}
function validate(root) {
  keys(root, ROOT);
  need(root.schema === 'cluster-status-browser-v1' && root.profile === 'pve-cluster-status-supplied-v1' && root.evidence === 'supplied_only' && root.authority === 'none');
  need(typeof root.capture_ref === 'string' && /^[0-9a-f]{32}(?![\s\S])/.test(root.capture_ref));
  need(typeof root.raw_sha256 === 'string' && /^[0-9a-f]{64}(?![\s\S])/.test(root.raw_sha256));
  keys(root.capabilities, FLAGS);
  FLAGS.forEach(k => need(root.capabilities[k] === false));
  need(Array.isArray(root.nodes) && root.nodes.length <= 1024);
  const ids = new Set(), names = new Set();
  let local = 0;
  const nodes = root.nodes.map(row => {
    keys(row, ['id','name','type','ip','level','local','online','nodeid']);
    need(row.type === 'node');
    const id = label(row.id), name = label(row.name);
    need(!ids.has(id) && !names.has(name)); ids.add(id); names.add(name);
    const result = {id,name,type:'node', ip:option(row.ip, ip), level:option(row.level, v => text(v,64,true)),
      local:option(row.local,flag), online:option(row.online,flag), nodeid:option(row.nodeid,v => decimal(v,'4294967295',true))};
    if (result.local.value === true) local++;
    need(local <= 1);
    return Object.freeze(result);
  });
  let cluster = null, relation = 'unknown';
  if (root.cluster !== null) {
    const row = root.cluster;
    keys(row, ['id','name','type','nodes','quorate','version']);
    need(row.type === 'cluster');
    const id = label(row.id), name = label(row.name);
    need(!ids.has(id));
    cluster = Object.freeze({id,name,type:'cluster', nodes:option(row.nodes,v => decimal(v,'1024')),
      quorate:option(row.quorate,flag), version:option(row.version,v => decimal(v,'9223372036854775807'))});
    if (cluster.nodes.present) relation = cluster.nodes.value === String(nodes.length) ? 'equal' : 'different';
  }
  need(root.reported_count_relation === relation);
  const state = cluster === null && nodes.length === 0 ? 'supplied_empty' : 'supplied_rows';
  need(root.state === state);
  return Object.freeze({schema:root.schema,profile:root.profile,capture_ref:root.capture_ref,raw_sha256:root.raw_sha256,
    evidence:root.evidence,state,cluster,nodes:Object.freeze(nodes),reported_count_relation:relation,authority:'none',
    capabilities:Object.freeze(Object.fromEntries(FLAGS.map(k => [k,false])))});
}
function scan(value) {
  const stack = [];
  let punctuation = 0;
  for (let i = 0; i < value.length; i++) {
    if (value[i] === '"') {
      const start = i;
      let closed = false;
      for (++i; i < value.length; i++) {
        need(i - start + 1 <= 4096);
        if (value[i] === '\\') need(++i < value.length && i - start + 1 <= 4096);
        else if (value[i] === '"') { closed = true; break; }
      }
      need(closed);
    } else if ('[]{}:,'.includes(value[i])) {
      need(++punctuation <= 262144);
      if (value[i] === '[' || value[i] === '{') { stack.push(value[i]); need(stack.length <= 4); }
      else if (value[i] === ']' || value[i] === '}') need(stack.pop() === (value[i] === ']' ? '[' : '{'));
    }
  }
  need(stack.length === 0);
}
function canonical(value) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
}
export function decodeSuppliedCluster(bytes) {
  try {
    need(ArrayBuffer.isView(bytes) && Object.getPrototypeOf(bytes) === Uint8Array.prototype && nameOf.call(bytes) === 'Uint8Array');
    const buffer = bufferOf.call(bytes), offset = offsetOf.call(bytes), length = lengthOf.call(bytes);
    need(Object.getPrototypeOf(buffer) === ArrayBuffer.prototype && length > 0 && length <= 2097152);
    need(offset + length <= bufferLengthOf.call(buffer));
    const copy = new Uint8Array(length);
    copy.set(new Uint8Array(buffer,offset,length));
    need(!(copy[0] === 0xef && copy[1] === 0xbb && copy[2] === 0xbf));
    const content = utf8.decode(copy);
    scan(content);
    const document = validate(JSON.parse(content));
    const encoded = encoder.encode(canonical(document));
    need(encoded.length === copy.length && encoded.every((v,i) => v === copy[i]));
    return Object.freeze({state:'supplied_observation',document});
  } catch (_) { return FAILED; }
}
