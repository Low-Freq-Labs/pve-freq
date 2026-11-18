// Format/display component only; original HTTP/session/card admission remains a caller duty.
import {decodeClusterObservation} from './observation-decoder.mjs?v=pve-lab-window-20261113-r1';

const consumed=new WeakSet();
let serial=0;
const inert=Object.freeze({show:()=>false,dispose:()=>{}});
const notice='Provider-reported observation. Completeness unknown. This response does not establish measured health, independent identity, verified quorum or permission to act.';
const unavailable='Cluster observation unavailable.';

export function createClusterObservationDisplay({root,isCurrent,onRetire}={}) {
  if (!(root instanceof HTMLElement) || root.ownerDocument!==document || !root.isConnected ||
      root.childNodes.length || consumed.has(root) || typeof isCurrent!=='function' || typeof onRetire!=='function') return inert;
  consumed.add(root);
  const ancestors=[];
  for(let n=root;n;n=n.parentNode)ancestors.push(n);
  let live=true,busy=false,epoch=0,selected='',documentValue=null,observer=null,unsubscribe=null;
  let shell=null,select=null,status=null,detail=null,options=[],owned=[],pending=[];
  const scrubbed=new WeakSet();
  const id='cluster-observation-choice-'+(++serial);
  // Every acquired handle has its own consumed slot. Missing handles are not
  // consumed: a subscription returned after retirement is closed immediately.
  function closeObserver(){const h=observer;observer=null;if(h)try{h.disconnect();}catch{}}
  function closeSubscription(){const h=unsubscribe;unsubscribe=null;if(h)try{h();}catch{}}
  function clearOwned(){
    // Consume retained ownership before any cleanup collaborator can reenter.
    const oldShell=shell,oldOwned=owned;
    owned=[];shell=select=status=detail=null;options=[];
    if(!oldShell)return;
    let fault=false;
    const safe=()=>oldShell.parentNode===null||
      (oldShell.parentNode===root&&(!root.isConnected||chain()));
    function retained(n){while(n!==oldShell){const pair=oldOwned.find(([x])=>x===n);if(!pair||n.parentNode!==pair[1])return false;n=pair[1];}return true;}
    function cleanupWrite(effect,type,target,removed=[]){
      try{
        const connectedBefore=target.isConnected;
        effect();
        if(type==='characterData'?target.nodeValue!=='':removed.some(n=>n.parentNode===target))fault=true;
        if(live&&observer){
          const records=observer.takeRecords();
          // Detached subtree observation can persist until removal delivery.
          // Acknowledge only this exact cleanup operation, never a blanket drain.
          // No record is also legal after the native transient observer expires.
          if((connectedBefore&&records.length!==1)||records.length>1||(records.length===1&&
            (records[0].type!==type||records[0].target!==target||
             (type==='childList'&&(!sameNodes(records[0].removedNodes,removed)||records[0].addedNodes.length)))))fault=true;
        }
      }catch{fault=true;}
    }
    for(const [n,parent] of oldOwned)if(safe()&&n.nodeType===Node.TEXT_NODE&&n.parentNode===parent&&retained(n))
      cleanupWrite(()=>{n.nodeValue='';},'characterData',n);
    for(const [n,parent] of oldOwned)if(parent===oldShell&&safe()&&n.parentNode===oldShell)
      cleanupWrite(()=>oldShell.removeChild(n),'childList',oldShell,[n]);
    if(safe()&&oldShell.parentNode===root)cleanupWrite(()=>root.removeChild(oldShell),'childList',root,[oldShell]);
    if(fault&&live)dispose();
  }
  function pendingPart(top,target,list){
    const lineage=[];
    for(let n=target;n;n=n.parentNode)lineage.push(n);
    return {top,target,list,lineage,lost:false};
  }
  function clearPending(){
    // Text and removal are independent obligations. A detached top may be
    // inserted by an in-flight publication after disposal; its unattempted
    // removal remains eligible, but lost placement never becomes eligible again.
    for(const part of pending.slice()){
      const {top,target,list,lineage}=part;
      const safe=()=>{
        if(part.lost)return false;
        const allowed=target.isConnected&&lineage.every((n,i)=>
          i===lineage.length-1?n===document:n.parentNode===lineage[i+1])&&
          (top.parentNode===null||top.parentNode===target);
        if(!allowed)part.lost=true;
        return allowed;
      };
      function retained(n){while(n!==top){const pair=list.find(([x])=>x===n);if(!pair||n.parentNode!==pair[1])return false;n=pair[1];}return true;}
      for(const [n,parent] of list)if(safe()&&n.nodeType===Node.TEXT_NODE&&n.parentNode===parent&&retained(n)&&!scrubbed.has(n)){
        scrubbed.add(n);try{n.nodeValue='';}catch{}
      }
      if(safe()&&top.parentNode===target&&!scrubbed.has(top)){scrubbed.add(top);try{target.removeChild(top);}catch{}}
    }
  }
  function dispose(){
    if(!live)return;
    live=false;epoch++;documentValue=null;selected='';
    closeObserver();clearOwned();clearPending();closeSubscription();
  }
  function sameNodes(actual,wanted){return actual.length===wanted.length&&Array.from(actual).every((n,i)=>n===wanted[i]);}
  function chain(){return ancestors.every((n,i)=>i===ancestors.length-1?n===document:n.parentNode===ancestors[i+1])&&root.isConnected;}
  function relevant(record){
    if(record.type==='childList'){
      if(record.target===root||root.contains(record.target))return true;
      if(Array.from(record.addedNodes).concat(Array.from(record.removedNodes)).some(n=>n.nodeType===1&&(n.id===id||n.querySelector('[id="'+id+'"]'))))return true;
      return Array.from(record.removedNodes).some(n=>ancestors.some(a=>n===a||(n.contains&&n.contains(a))));
    }
    return record.target===root||root.contains(record.target)||ancestors.includes(record.target)||
      (record.type==='attributes'&&record.attributeName==='id'&&(record.oldValue===id||record.target.id===id));
  }
  function history(records){if(live&&records.some(relevant))dispose();}
  function drain(){if(observer)history(observer.takeRecords());}
  function topology(){
    if(!chain())return false;
    if(!shell)return root.childNodes.length===0;
    return root.childNodes.length===1&&root.firstChild===shell&&
      owned.every(([n,p])=>n.parentNode===p)&&(!select||(select.id===id&&
      document.querySelectorAll('[id="'+id+'"]').length===1&&
      select.options.length===options.length&&options.every((o,i)=>select.options[i]===o)));
  }
  function guard(){
    if(!live)return false;
    try{
      drain();if(!live||!topology()){dispose();return false;}
      const yes=isCurrent();
      drain();if(!live||yes!==true||!topology()){dispose();return false;}
      return true;
    }catch{dispose();return false;}
  }
  function ownReplace(target,nodes){
    if(!guard())return false;
    const before=Array.from(target.childNodes),generation=epoch;
    try{
      target.replaceChildren(...nodes);
      const records=observer?observer.takeRecords():[];
      // Exactly the native replace-all childList record, or no record for an
      // empty-to-empty no-op. No arbitrary drained records are acknowledged.
      const expected=before.length||nodes.length;
      if(!live||generation!==epoch||records.length!==(expected?1:0)||
        (expected&&(records[0].type!=='childList'||records[0].target!==target||
          !sameNodes(records[0].removedNodes,before)||!sameNodes(records[0].addedNodes,nodes)))){
        dispose();clearPending();return false;
      }
      return true;
    }catch{dispose();clearPending();return false;}
  }
  function node(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
  function census(n,parent,list){list.push([n,parent]);for(const child of n.childNodes)census(child,n,list);}
  function reported(field){
    if(!field.present)return 'Not reported';
    if(typeof field.value==='boolean')return field.value?'Reported true':'Reported false';
    return field.value===''?'Reported as empty':field.value;
  }
  function build(value){
    const box=node('section');box.style.cssText='min-width:0;max-width:100%;overflow-wrap:anywhere';
    const heading=node('h3','Provider-reported cluster observation'),copy=node('p',notice),state=node('p');
    state.setAttribute('role','status');state.setAttribute('aria-live','polite');
    box.append(heading,copy,state);
    let choice=null,body=null,choices=[];
    if(value){
      state.textContent=value.state==='reported_empty'?'No cluster or node rows were reported. Completeness unknown.':'Provider-reported cluster and node observations. Completeness unknown.';
      const optional=(label,field)=>node('p',label+': '+reported(field));
      if(value.cluster){
        const row=value.cluster;
        box.append(node('p','Cluster ID: '+row.id),node('p','Cluster name: '+row.name),
          optional('Reported cluster node count',row.nodes),optional('Reported quorate',row.quorate),optional('Reported version',row.version));
      }else box.append(node('p','No cluster row was reported.'));
      box.append(node('p','Provider-reported node rows: '+value.nodes.length),node('p',{
        equal:'Reported count matches returned rows; completeness unknown',different:'Reported count differs from returned rows; completeness unknown',unknown:'Reported count comparison unavailable'
      }[value.reported_count_relation]));
      const label=node('label','Select a provider-reported node');label.htmlFor=id;
      choice=node('select');choice.id=id;choice.style.cssText='max-width:100%;width:100%;min-width:0';
      const empty=node('option','No node selected');empty.value='';choice.append(empty);choices.push(empty);
      value.nodes.forEach((row,i)=>{const o=node('option',row.name);o.value=String(i);choice.append(o);choices.push(o);});
      body=node('div');body.style.cssText='max-height:24rem;overflow:auto;overflow-wrap:anywhere;min-width:0';
      choice.addEventListener('change',change);box.append(label,choice,body);
    }else state.textContent=unavailable;
    const all=[];census(box,root,all);
    return {box,state,choice,body,choices,all};
  }
  function publish(next){
    pending=[pendingPart(next.box,root,next.all)];
    if(!ownReplace(root,[next.box])){clearPending();pending=[];return false;}
    pending=[];
    shell=next.box;status=next.state;select=next.choice;detail=next.body;options=next.choices;owned=next.all;
    return guard();
  }
  function change(event){
    if(busy||!live||event.isTrusted!==true||event.target!==select)return;
    busy=true;
    try{
      if(!guard()||!documentValue||select.matches(':disabled')||select.hidden||!select.getClientRects().length)return;
      const index=select.selectedIndex,option=options[index];
      if(index<0||select.options[index]!==option||option.parentNode!==select||option.value!==(index===0?'':String(index-1))){dispose();return;}
      if(selected===option.value)return;
      const generation=epoch,nodes=[];
      if(index){
        const row=documentValue.nodes[index-1];
        nodes.push(node('h4',row.name),node('p','Node ID: '+row.id),node('p','Reported IP: '+reported(row.ip)),
          node('p','Reported level: '+reported(row.level)),node('p','Reported local: '+reported(row.local)),
          node('p','Reported online: '+reported(row.online)),node('p','Reported node ID: '+reported(row.nodeid)));
      }
      if(!guard()||generation!==epoch)return;
      const old=Array.from(detail.childNodes);
      pending=nodes.map(top=>{const list=[];census(top,detail,list);return pendingPart(top,detail,list);});
      if(!ownReplace(detail,nodes)){clearPending();pending=[];return;}
      pending=[];
      owned=owned.filter(([n])=>!old.some(o=>n===o||o.contains(n)));
      nodes.forEach(n=>census(n,detail,owned));selected=option.value;
      guard();
    }catch{dispose();}finally{busy=false;}
  }
  function show(bytes){
    if(busy||!live)return false;
    busy=true;
    try{
      if(!guard())return false;
      epoch++;documentValue=null;selected='';
      if(!ownReplace(root,[]))return false;
      clearOwned();
      if(!guard())return false;
      const decoded=decodeClusterObservation(bytes);
      if(!guard())return false;
      const value=decoded.state==='decoded_cluster_observation'?decoded.document:null;
      const next=build(value);
      if(!guard()||!publish(next))return false;
      documentValue=value;
      return value!==null;
    }catch{dispose();return false;}finally{busy=false;}
  }
  const api=Object.freeze({show,dispose});
  try{
    // Observe before either external constructor callback can mutate custody.
    observer=new MutationObserver(records=>history(records));
    if(!live){closeObserver();return api;}
    observer.observe(document,{subtree:true,childList:true,attributes:true,attributeOldValue:true,characterData:true});
    if(!guard())return api;
    const handle=onRetire(dispose);
    if(typeof handle!=='function'){dispose();return api;}
    unsubscribe=handle;
    if(!live){closeSubscription();return api;}
    if(!guard())return api;
  }catch{dispose();}
  return api;
}
