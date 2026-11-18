/* QCT1 + corrected decoded-value profile. Passive observations only. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory();
  else root.FreqQuickCt=factory();
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const MAX_BYTES=8388608,MAX_ROWS=10000;
  const FIELDS=['ctid','name','status','node','cpu','maxcpu','mem','maxmem','mem_pct','disk','maxdisk','uptime','tags','template'];
  function integer(v,max=Number.MAX_SAFE_INTEGER){return typeof v==='number'&&Number.isSafeInteger(v)&&v>=0&&v<=max&&!Object.is(v,-0);}
  function number(v,max){return typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=max&&!Object.is(v,-0);}
  function scalarBytes(s){
    let bytes=0,scalars=0;
    for(let i=0;i<s.length;i++){
      const c=s.charCodeAt(i);scalars++;
      if(c>=0xd800&&c<=0xdbff){const low=s.charCodeAt(++i);if(!(low>=0xdc00&&low<=0xdfff))throw Error('unicode');bytes+=4;}
      else if(c>=0xdc00&&c<=0xdfff)throw Error('unicode');
      else bytes+=c<0x80?1:c<0x800?2:3;
    }
    return {bytes,scalars};
  }
  function resources(value){
    let bytes=0;const stack=[[value,1]];
    while(stack.length){
      const [v,depth]=stack.pop();
      if(typeof v==='string')bytes+=scalarBytes(v).bytes;
      else if(v!==null&&typeof v==='object'){
        if(depth>8)throw Error('depth');
        if(Array.isArray(v)){for(let i=0;i<v.length;i++){if(!Object.hasOwn(v,i))throw Error('sparse');stack.push([v[i],depth+1]);}}
        else {if(Object.getPrototypeOf(v)!==Object.prototype&&Object.getPrototypeOf(v)!==null)throw Error('object');for(const key of Object.keys(v)){bytes+=scalarBytes(key).bytes;stack.push([v[key],depth+1]);}}
      }
      if(bytes>MAX_BYTES)throw Error('strings');
    }
    return bytes;
  }
  function keys(v,names){return v!==null&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length===names.length&&names.every(k=>Object.hasOwn(v,k));}
  function text(v,max,nonblank){return typeof v==='string'&&v.length<=max*2&&scalarBytes(v).scalars<=max&&!/[\x00-\x1f\x7f]/.test(v)&&(!nonblank||v.trim().length>0);}
  function decode(v){
    try{
      if(!keys(v,['containers','count','running','stopped'])||!Array.isArray(v.containers)||v.containers.length>MAX_ROWS||!['count','running','stopped'].every(k=>integer(v[k])))return null;
      const ids=new Set(),rows=[];let running=0;
      for(const c of v.containers){
        if(!keys(c,FIELDS)||!integer(c.ctid)||c.ctid===0||ids.has(c.ctid)||!text(c.name,256,false)||!text(c.node,256,true)||!text(c.status,64,true)||!text(c.tags,4096,false)||!integer(c.template,1)||!number(c.cpu,1)||!integer(c.maxcpu,4096)||!number(c.mem_pct,100)||!['mem','maxmem','disk','maxdisk','uptime'].every(k=>integer(c[k]))||c.mem>c.maxmem||c.disk>c.maxdisk)return null;
        ids.add(c.ctid);if(c.status==='running')running++;
        const row={};for(const key of FIELDS)row[key]=c[key];rows.push(Object.freeze(row));
      }
      if(v.count!==rows.length||v.running!==running||v.stopped!==rows.length-running)return null;
      // Only the bounded, primitive-field schema reaches the resource walk.
      resources(v);
      return Object.freeze({containers:Object.freeze(rows),count:rows.length,running,stopped:v.stopped});
    }catch(_){return null;}
  }
  function create(env){
    const doc=env.document,ids=['fleet-view','metrics-cards','metrics-summary','fleet-ct-observation','fleet-lab-section','fleet-lab-cards'];
    const roots=Object.create(null),paths=[],nodes=[],originalIds=new Map(),parents=new Map(),identity=new Map();
    let registered=true,latest=null,sample=null,attempt='none',authEpoch={},viewEpoch={};
    const grants=new WeakMap();
    for(const id of ids){const found=doc.querySelectorAll('[id="'+id+'"]');if(found.length!==1){registered=false;continue;}roots[id]=found[0];}
    if(registered){
      if(roots['metrics-cards'].parentNode.parentNode.id!=='fleet-sec-infra'||roots['metrics-summary'].parentNode.parentNode.id!=='fleet-sec-stats'||roots['metrics-cards'].parentNode.parentNode.parentNode!==roots['fleet-view']||roots['metrics-summary'].parentNode.parentNode.parentNode!==roots['fleet-view']||!roots['metrics-cards'].parentNode.matches('.section-body')||!roots['metrics-summary'].parentNode.matches('.section-body')||roots['metrics-cards'].parentNode!==roots['fleet-ct-observation'].parentNode||!roots['fleet-view'].contains(roots['metrics-summary'])||!roots['fleet-view'].contains(roots['metrics-cards']))registered=false;
      for(const node of Object.values(roots)){
        const path=[];for(let n=node;n&&n!==doc;n=n.parentNode){path.push(n);if(!nodes.includes(n))nodes.push(n);}paths.push(path);
      }
      for(const n of nodes){parents.set(n,n.parentNode);originalIds.set(n,n.getAttribute('id'));if(n.id){if(identity.has(n.id)&&identity.get(n.id)!==n)registered=false;identity.set(n.id,n);}}
    }
    function retire(){if(latest){latest.live=false;if(latest.dispose)latest.dispose();}latest=null;}
    function foreign(n){return n.nodeType===1&&identity.has(n.id)&&identity.get(n.id)!==n;}
    function collisionTree(n){return n.nodeType===1&&(foreign(n)||Array.from(n.querySelectorAll('[id]')).some(foreign));}
    function rooted(n){return nodes.some(original=>n===original||(n.contains&&n.contains(original)));}
    function outputTarget(n){return ['metrics-cards','metrics-summary','fleet-ct-observation'].some(id=>roots[id]&&(n===roots[id]||roots[id].contains(n)));}
    function records(list,expected){
      let consumed=false;
      for(const r of list){
        if(r.type==='attributes'){
          if(expected&&expected.attribute&&!consumed&&r.target===expected.node&&r.attributeName===expected.attribute&&r.oldValue===expected.before&&r.target.getAttribute(r.attributeName)===expected.after){consumed=true;continue;}
          if(nodes.includes(r.target)||r.attributeName==='id'&&(identity.has(r.oldValue)||foreign(r.target)))retire();
          continue;
        }
        for(const n of r.removedNodes){if(rooted(n)){registered=false;retire();}}
        if([...r.addedNodes,...r.removedNodes].some(collisionTree))retire();
        const own=expected&&!consumed&&r.type==='childList'&&r.target===expected.node&&same([...r.removedNodes],expected.before)&&same([...r.addedNodes],expected.after);
        if(own){consumed=true;continue;}
        // Sibling rendering happens only after CT publication is complete.
        // Its records are still examined for structure/identity; no CT writer
        // capability survives that phase transition.
        if(outputTarget(r.target)&&latest&&latest.phase!=='siblings')retire();
      }
    }
    function same(a,b){return a.length===b.length&&a.every((n,i)=>n===b[i]);}
    const watch=new MutationObserver(list=>records(list));
    watch.observe(doc,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['id'],attributeOldValue:true});
    for(const n of nodes)watch.observe(n,{attributes:true,attributeFilter:['id','class','style','hidden','inert','disabled','aria-hidden','aria-disabled'],attributeOldValue:true});
    function drain(){records(watch.takeRecords());}
    function structure(){
      if(!registered)return false;
      if(!nodes.every(n=>n.isConnected&&n.parentNode===parents.get(n))){registered=false;return false;}
      return nodes.every(n=>n.getAttribute('id')===originalIds.get(n))&&Array.from(identity).every(([id,n])=>doc.getElementById(id)===n&&Array.from(doc.querySelectorAll('[id]')).filter(e=>e.id===id).length===1);
    }
    if(!structure())registered=false;
    function available(){
      return nodes.filter(n=>!roots['fleet-lab-section'].contains(n)).every(n=>{
        const css=env.style(n);return !n.hidden&&!n.inert&&!n.hasAttribute('disabled')&&n.getAttribute('aria-hidden')!=='true'&&n.getAttribute('aria-disabled')!=='true'&&!['hidden','collapse'].includes(n.style.visibility)&&css.display!=='none'&&css.visibility==='visible';
      });
    }
    function current(t){
      drain();const c=env.context();
      const ok=!!(t&&latest===t&&t.live&&t.authEpoch===authEpoch&&t.viewEpoch===viewEpoch&&c.view==='fleet'&&c.auth[5]===true&&same(c.auth,t.auth)&&structure()&&available());
      if(!ok&&latest===t)retire();return ok;
    }
    function capability(t){const g=Object.freeze({});grants.set(g,t);return g;}
    function allowed(g){return current(grants.get(g));}
    function replace(g,node,children){
      const t=grants.get(g);if(!allowed(g)||t.phase==='siblings'||!Object.values(roots).includes(node))return false;
      const expected={node,before:[...node.childNodes],after:[...children]};
      node.replaceChildren(...children);records(watch.takeRecords(),expected);return allowed(g);
    }
    function html(g,node,markup){const template=doc.createElement('template');template.innerHTML=markup;return replace(g,node,[...template.content.childNodes]);}
    function writeText(g,node,value){return replace(g,node,[doc.createTextNode(value)]);}
    function display(g,node,value){
      if(!allowed(g)||grants.get(g).phase==='siblings'||!Object.values(roots).includes(node))return false;
      const expected={node,attribute:'style',before:node.getAttribute('style')};node.style.display=value;expected.after=node.getAttribute('style');
      records(watch.takeRecords(),expected);return allowed(g);
    }
    // Existing summary readers keep their own lifetime checks. Account for
    // their one known synchronous descendant write, without granting CT writes.
    function summaryHtml(node,markup,readCurrent){
      drain();if(readCurrent&&!readCurrent())return;
      const template=doc.createElement('template');template.innerHTML=markup;
      const children=[...template.content.childNodes];
      if(readCurrent&&!readCurrent())return;
      const expected=roots['metrics-summary']&&node!==roots['metrics-summary']&&roots['metrics-summary'].contains(node)?{node,before:[...node.childNodes],after:children}:null;
      if(readCurrent&&!readCurrent())return;
      node.replaceChildren(...children);records(watch.takeRecords(),expected);
    }
    function presentation(fo,hd){
      const result={admitted:!!sample,containers:[],unplaced:0,filtered:0,running:0,stopped:0,unknown:0};if(!sample)return result;
      const counts=new Map();for(const n of fo&&Array.isArray(fo.pve_nodes)?fo.pve_nodes:[])if(n&&typeof n.name==='string')counts.set(n.name,(counts.get(n.name)||0)+1);
      const lab=env.labLabels(hd&&hd.hosts),settings=env.settings();
      for(const row of sample.data.containers){
        if(row.status==='running')result.running++;else if(row.status==='stopped')result.stopped++;else result.unknown++;
        if(row.template===1&&!settings.showTemplates||Object.hasOwn(lab,row.name)&&lab[row.name]||/\blab\b/i.test(row.tags)){result.filtered++;continue;}
        if(counts.get(row.node)!==1){result.unplaced++;continue;}
        result.containers.push({...row});
      }
      return result;
    }
    function evidence(g,fo,hd){
      if(!allowed(g))return false;const p=presentation(fo,hd);
      let message=attempt==='failed'?'Latest CT observation unavailable or unsupported. ':attempt==='pending'?'CT observation pending. ':attempt==='issuance_refused'?'CT observation could not be issued. ':'';
      if(sample){message+=(attempt!=='accepted'?'Retained earlier CT response. ':'CT response received. ')+
        'Reported containers: '+sample.data.count+'; reported running: '+p.running+'; reported stopped: '+p.stopped+'; unknown state: '+p.unknown+'. Filtered: '+p.filtered+'; unplaced: '+p.unplaced+'. Browser receipt: '+new Date(sample.receipt).toISOString()+'. ';if(!sample.data.count)message+='No containers reported by this response. ';}
      else message+='No admitted CT observation. Container counts unknown. ';
      message+='Reported node labels only; estate completeness and current state unverified. Metrics unknown: legacy defaults may replace missing values. Measurement age unknown.';
      return writeText(g,roots['fleet-ct-observation'],message);
    }
    function begin(){
      retire();drain();const c=env.context();
      const t={live:true,phase:'eager',auth:c.auth.slice(),authEpoch,viewEpoch};latest=t;
      if(!current(t)){attempt='issuance_refused';return null;}attempt='pending';
      const grant=capability(t);return {grant,current:()=>current(t),attach:dispose=>{if(current(t))t.dispose=dispose;},
        pending:()=>{if(current(t)){t.phase='pending';return true;}return false;},
        terminal:(valid,data)=>{if(!current(t)||t.phase!=='pending'||!valid)return null;t.phase='publishing';if(data){sample={data,receipt:Date.now()};attempt='accepted';}else attempt='failed';return grant;},
        failed:()=>{if(!current(t))return null;attempt='failed';t.phase='publishing';return grant;},
        end:()=>{if(latest===t){t.live=false;latest=null;if(t.dispose)t.dispose();}}};
    }
    function resetAuth(){retire();sample=null;attempt='none';authEpoch={};}
    function resetView(){retire();viewEpoch={};}
    function siblings(g){if(!allowed(g))return false;grants.get(g).phase='siblings';return true;}
    function snapshot(g,fo,hd){return allowed(g)?presentation(fo,hd):null;}
    return Object.freeze({begin,allowed,replace,html,text:writeText,display,summaryHtml,evidence,snapshot,siblings,resetAuth,resetView,roots:Object.freeze(roots)});
  }
  return Object.freeze({decode,resources,scalarBytes,create});
});
