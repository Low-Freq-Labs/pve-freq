// Format validation only. Original authenticated inventory/recipient custody is
// established by the original application, never by these document strings.
// Sorted compact UTF-8 follows the accepted producer/consumer WIRE-JOIN-R1.
const FAILED = Object.freeze({state:'unavailable',reason:'cluster_observation_entry_unavailable'});
const encoder = new TextEncoder();
const utf8 = new TextDecoder('utf-8',{fatal:true});
const typed = Object.getPrototypeOf(Uint8Array.prototype);
const bufferOf = Object.getOwnPropertyDescriptor(typed,'buffer').get;
const offsetOf = Object.getOwnPropertyDescriptor(typed,'byteOffset').get;
const lengthOf = Object.getOwnPropertyDescriptor(typed,'byteLength').get;
const nameOf = Object.getOwnPropertyDescriptor(typed,Symbol.toStringTag).get;
const bufferLengthOf = Object.getOwnPropertyDescriptor(ArrayBuffer.prototype,'byteLength').get;
function need(ok){if(!ok)throw Error('unavailable');}
function keys(value,names){
  need(value!==null&&typeof value==='object'&&Object.getPrototypeOf(value)===Object.prototype);
  const actual=Object.keys(value);
  need(actual.length===names.length&&actual.every(k=>names.includes(k)));
}
function reference(value){
  need(typeof value==='string'&&/^[0-9a-f]{32}(?![\s\S])/.test(value));return value;
}
function label(value){
  need(typeof value==='string'&&value.length>0&&value.length<=256);
  for(const char of value){const cp=char.codePointAt(0);
    need(!(cp<32||cp>=127&&cp<=159||cp>=0xd800&&cp<=0xdfff));}
  need(encoder.encode(value).length<=256);return value;
}
function scan(content,depth,punctuationLimit){
  const stack=[];let punctuation=0;
  for(let i=0;i<content.length;i++){
    if(content[i]==='"'){
      const start=i;let closed=false;
      for(++i;i<content.length;i++){
        need(i-start+1<=4096);
        if(content[i]==='\\')need(++i<content.length&&i-start+1<=4096);
        else if(content[i]==='"'){closed=true;break;}
      }
      need(closed);
    }else if('[]{}:,'.includes(content[i])){
      need(++punctuation<=punctuationLimit);
      if(content[i]==='['||content[i]==='{'){stack.push(content[i]);need(stack.length<=depth);}
      else if(content[i]===']'||content[i]==='}')need(stack.pop()===(content[i]===']'?'[':'{'));
    }
  }
  need(stack.length===0);
}
function canonical(value){
  if(value===null||typeof value==='string'||typeof value==='boolean'||typeof value==='number')return JSON.stringify(value);
  if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
  return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
}
function decode(bytes,cap,depth,punctuation,validate,state){
  try{
    need(ArrayBuffer.isView(bytes)&&Object.getPrototypeOf(bytes)===Uint8Array.prototype&&nameOf.call(bytes)==='Uint8Array');
    const buffer=bufferOf.call(bytes),offset=offsetOf.call(bytes),length=lengthOf.call(bytes);
    need(Object.getPrototypeOf(buffer)===ArrayBuffer.prototype&&length>0&&length<=cap);
    need(offset+length<=bufferLengthOf.call(buffer));
    const copy=new Uint8Array(length);copy.set(new Uint8Array(buffer,offset,length));
    need(!(copy[0]===0xef&&copy[1]===0xbb&&copy[2]===0xbf));
    const content=utf8.decode(copy);scan(content,depth,punctuation);
    const document=validate(JSON.parse(content)),encoded=encoder.encode(canonical(document));
    // Equality refuses duplicate keys, noncanonical escapes, whitespace, numeric
    // spellings and reordered keys after bounded parsing and exact validation.
    need(encoded.length===copy.length&&encoded.every((v,i)=>v===copy[i]));
    return Object.freeze({state,document});
  }catch(_){return FAILED;}
}
function inventory(root){
  keys(root,['schema','scope','nodes']);
  need(root.schema==='cluster-observation-inventory-v1'&&root.scope==='configured_source');
  need(Array.isArray(root.nodes)&&root.nodes.length<=1024);
  const labels=new Set(),references=new Set();
  const nodes=root.nodes.map(row=>{
    keys(row,['label','selection_ref']);const name=label(row.label);
    need(!labels.has(name));labels.add(name);
    const ref=row.selection_ref===null?null:reference(row.selection_ref);
    // Two displayed selections must not alias a single non-null server grant.
    if(ref!==null){need(!references.has(ref));references.add(ref);}
    return Object.freeze({label:name,selection_ref:ref});
  });
  return Object.freeze({schema:root.schema,scope:root.scope,nodes:Object.freeze(nodes)});
}
function binding(root){
  keys(root,['schema','binding_ref','expires_in_ms']);
  need(root.schema==='cluster-observation-binding-v1');
  const ref=reference(root.binding_ref);
  need(Number.isInteger(root.expires_in_ms)&&root.expires_in_ms>=1&&root.expires_in_ms<=30000);
  return Object.freeze({schema:root.schema,binding_ref:ref,expires_in_ms:root.expires_in_ms});
}
export function decodeClusterObservationInventory(bytes){
  return decode(bytes,1048576,3,16384,inventory,'decoded_cluster_observation_inventory');
}
export function decodeClusterObservationBinding(bytes){
  return decode(bytes,1024,1,16,binding,'decoded_cluster_observation_binding');
}
