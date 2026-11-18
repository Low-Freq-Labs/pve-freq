(function(){
  'use strict';

  var SCHEMA = 'zero-state-web-v1';
  var DEFAULT_SERVICE_ACCOUNT = 'freq-admin';
  var API = {
    status: '/api/setup/status',
    verify: '/api/auth/verify',
    createAdmin: '/api/setup/create-admin',
    discoveryStart: '/api/setup/discovery/start',
    discoveryStatus: '/api/setup/discovery/status',
    contract: '/api/setup/contract',
    credentials: '/api/setup/device-credentials',
    initStart: '/api/setup/init/start',
    initCancel: '/api/setup/init/cancel',
    initStatus: '/api/setup/init/status',
    initLogs: '/api/setup/init/logs'
  };
  var STEP_ORDER = ['operator','connect','discover','credentials','launch','progress'];
  var model = {
    csrf: '', setupId: '', discoveryId: '', contractId: '', initJobId: '',
    discovery: null, contract: null, selections: {}, unlocked: 0,
    discoveryTimer: 0, initTimer: 0, handoffRetried: false
  };

  // BEGIN original setup cancellation lifetime (private; DATA grants no owner).
  var initOwner = null, initRecipient = null, initStep = '';
  var initSessionGeneration = {}, initAttemptHistory = new Map();
  var INIT_ATTEMPT_LIMIT = 32;
  function retireInitRecipient(){
    var timer=model.initTimer;model.initTimer=0;initRecipient=null;
    if(timer){window.clearTimeout(timer);}
  }
  function retireInitOwner(){initOwner=null;retireInitRecipient();}
  function setInitContext(key,value){
    if(model[key]!==value){retireInitOwner();}
    model[key]=value;
  }
  function currentInitOwner(owner){
    return !!owner && owner===initOwner && owner.session===initSessionGeneration &&
      owner.jobId===model.initJobId && owner.setupId===model.setupId &&
      owner.contractId===model.contractId && owner.discoveryId===model.discoveryId &&
      owner.csrf===model.csrf;
  }
  function bindInitOwner(){
    retireInitOwner();
    if(typeof model.initJobId!=='string' || !/^[0-9a-f]{32}$/.test(model.initJobId) || !model.csrf){return;}
    initOwner={jobId:model.initJobId,setupId:model.setupId,contractId:model.contractId,
      discoveryId:model.discoveryId,csrf:model.csrf,session:initSessionGeneration,statusSequence:0};
  }
  function activateInitRecipient(){
    retireInitRecipient();
    if(initStep!=='progress' || !currentInitOwner(initOwner)){return;}
    var ids=['cancel-init','cancellation-status','launch-form','step-progress','retry-init',
      'progress-state','init-as-of','phase-log','progress-phase','progress-count',
      'progress-message','progress-bar','completion-card','setup-health','setup-reason','form-error'];
    var nodes={};ids.forEach(function(id){nodes[id]=$(id);});
    initRecipient={owner:initOwner,nodes:nodes,nodeIds:ids,button:nodes['cancel-init'],
      status:nodes['cancellation-status'],form:nodes['launch-form'],progress:nodes['step-progress'],
      retry:nodes['retry-init'],snapshot:null};
  }
  function currentInitRecipient(recipient){
    return !!recipient && recipient===initRecipient && initStep==='progress' &&
      currentInitOwner(recipient.owner) && recipient.button===$('cancel-init') &&
      recipient.status===$('cancellation-status') && recipient.form===$('launch-form') &&
      recipient.progress===$('step-progress') && recipient.retry===$('retry-init') &&
      recipient.nodeIds.every(function(id){return !!recipient.nodes[id] && recipient.nodes[id]===$(id);});
  }
  function initEffect(recipient,effect,sequence){
    function current(){return currentInitRecipient(recipient) &&
      (sequence===undefined || sequence===recipient.owner.statusSequence);}
    if(!current()){return false;}
    effect();return current();
  }
  function ownedInitError(recipient,message,sequence){
    var box=recipient.nodes['form-error'];
    if(!initEffect(recipient,function(){box.hidden=!message;},sequence)){return;}
    if(!initEffect(recipient,function(){box.replaceChildren();},sequence)){return;}
    if(!message){return;}
    var line;
    if(!initEffect(recipient,function(){line=document.createElement('div');},sequence)){return;}
    if(!initEffect(recipient,function(){line.className='error-message';},sequence)){return;}
    if(!initEffect(recipient,function(){line.textContent=message;},sequence)){return;}
    if(!initEffect(recipient,function(){box.appendChild(line);},sequence)){return;}
    initEffect(recipient,function(){box.scrollIntoView({behavior:'smooth',block:'nearest'});},sequence);
  }
  function ownedInitProgress(recipient,data,sequence){
    var p=data || {},n=Number(p.current || 0),total=Number(p.total || 0);
    var phase=stripAnsi(p.phase_name || p.phase || 'Working');
    var terminalZero=total===0 && phase.toLowerCase()==='complete';
    if(!initEffect(recipient,function(){recipient.nodes['progress-phase'].textContent=phase;},sequence)){return;}
    if(!initEffect(recipient,function(){recipient.nodes['progress-count'].textContent=total?n+' / '+total:(terminalZero?'0 / 0':'in progress');},sequence)){return;}
    if(!initEffect(recipient,function(){recipient.nodes['progress-message'].textContent=stripAnsi(p.message || 'Waiting for the next verified update.');},sequence)){return;}
    initEffect(recipient,function(){recipient.nodes['progress-bar'].style.width=total?Math.min(100,(n/total)*100)+'%':(terminalZero?'100%':'12%');},sequence);
  }
  function ownedInitLog(recipient,lines,sequence){
    if(!Array.isArray(lines)){return;}
    var value=lines.map(stripAnsi).join('\n') || 'No redacted log lines returned.';
    initEffect(recipient,function(){recipient.nodes['phase-log'].textContent=value;},sequence);
  }
  function initCancellation(job){
    var c=job && job.cancellation;
    if(!c || typeof c!=='object' || typeof c.requested!=='boolean' ||
      typeof c.retryable!=='boolean' || c.retryable!==false || typeof c.delivery!=='string'){
      return {requested:true,delivery:'unknown',valid:false};
    }
    if(c.requested===false && c.delivery==='not_requested'){
      return {requested:false,delivery:'not_requested',valid:true};
    }
    if(c.requested===true && (c.delivery==='pending' || c.delivery==='sent' || c.delivery==='unknown')){
      return {requested:true,delivery:c.delivery,valid:true};
    }
    return {requested:true,delivery:'unknown',valid:false};
  }
  function retainObservedInitCancellation(recipient,cancellation){
    // This is a retained refusal, not a signal grant or proof of delivery.
    if(!cancellation.valid || cancellation.requested){
      var prior=initAttemptHistory.get(recipient.owner.jobId);
      var uncertain=!cancellation.valid || cancellation.delivery==='unknown';
      if(prior){
        if(uncertain){prior.observedUnknown=true;}
        return;
      }
      // A full history globally refuses every new send. Never evict uncertainty.
      if(initAttemptHistory.size>=INIT_ATTEMPT_LIMIT){return;}
      initAttemptHistory.set(recipient.owner.jobId,{owner:recipient.owner,recipient:recipient,
        state:'observed',observedUnknown:uncertain});
    }
  }
  function initAttempt(recipient){return initAttemptHistory.get(recipient.owner.jobId);}
  function beginInitAttempt(recipient){
    if(!currentInitRecipient(recipient) || initAttempt(recipient) || initAttemptHistory.size>=INIT_ATTEMPT_LIMIT){return null;}
    var snapshot=recipient.snapshot;
    if(!snapshot || snapshot.sequence!==recipient.owner.statusSequence || !snapshot.active ||
      !snapshot.cancellation.valid || snapshot.cancellation.requested || snapshot.cancellation.delivery!=='not_requested'){
      return null;
    }
    var attempt={owner:recipient.owner,recipient:recipient,state:'unknown'};
    // Suppression only, including same textual IDs after a different owner/session.
    // This retained entry never grants backend authority or proves closure.
    initAttemptHistory.set(recipient.owner.jobId,attempt);return attempt;
  }
  function holdInitRetry(recipient,sequence){
    return initEffect(recipient,function(){recipient.retry.hidden=true;},sequence);
  }
  // END original setup cancellation lifetime.

  function $(id){return document.getElementById(id);}
  function text(value){return value == null ? '' : String(value);}
  function stripAnsi(value){
    return text(value).replace(/[\u001B\u009B][[\]()#;?]*(?:(?:(?:[a-zA-Z\d]*(?:;[-a-zA-Z\d\/#&.:=?%@~_]+)*)?\u0007)|(?:(?:\d{1,4}(?:[;:]\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))/g,'');
  }
  function renderInitLog(lines){
    if(!Array.isArray(lines)){return;}
    $('phase-log').textContent=lines.map(stripAnsi).join('\n') || 'No redacted log lines returned.';
  }
  function trim(id){var el=$(id);return el ? el.value.trim() : '';}
  function clampPoll(value,fallback){
    var n=Number(value || fallback || 1000);
    return Math.max(500,Math.min(5000,isFinite(n) ? n : fallback || 1000));
  }
  function uuid(){
    if(window.crypto && typeof window.crypto.randomUUID === 'function'){
      return window.crypto.randomUUID();
    }
    var bytes=new Uint8Array(16);
    if(window.crypto && window.crypto.getRandomValues){window.crypto.getRandomValues(bytes);}
    else{for(var i=0;i<bytes.length;i+=1){bytes[i]=Math.floor(Math.random()*256);}}
    bytes[6]=(bytes[6]&15)|64; bytes[8]=(bytes[8]&63)|128;
    return Array.prototype.map.call(bytes,function(b,i){
      return (i===4||i===6||i===8||i===10?'-':'')+b.toString(16).padStart(2,'0');
    }).join('');
  }
  function el(tag,className,content){
    var node=document.createElement(tag);
    if(className){node.className=className;}
    if(content != null){node.textContent=text(content);}
    return node;
  }
  function setBusy(button,busy,label){
    if(!button){return;}
    if(busy){button.dataset.label=button.textContent;button.textContent=label || 'Working…';}
    else if(button.dataset.label){button.textContent=button.dataset.label;delete button.dataset.label;}
    button.disabled=!!busy;
  }
  function setupErrorDetailText(detail){
    if(!detail || typeof detail !== 'object'){return '';}
    var code=text(detail.code || 'invalid value').replace(/_/g,' ');
    var resource=typeof detail.resource_id === 'string' ? detail.resource_id.slice(0,160) : '';
    return code+(resource ? ' · '+resource : '');
  }
  function setError(message,field,details){
    var box=$('form-error');
    box.hidden=!message;
    box.replaceChildren();
    if(message){box.appendChild(el('div','error-message',message));}
    var readable=Array.isArray(details) ? details.map(setupErrorDetailText).filter(Boolean).slice(0,8) : [];
    if(readable.length){
      var list=el('ul','error-details');readable.forEach(function(item){list.appendChild(el('li','',item));});box.appendChild(list);
      if(details.length>readable.length){box.appendChild(el('p','error-more','+'+(details.length-readable.length)+' more validation results'));}
    }
    if(message){box.scrollIntoView({behavior:'smooth',block:'nearest'});}
    if(field){
      var target=document.querySelector('[data-api-field="'+CSS.escape(field)+'"]');
      if(target){target.focus();}
    }
  }
  function errorMessage(data,status,url){
    var error=data && data.error;
    if(error && typeof error === 'object'){
      return {message:error.message || error.code || (url+' returned HTTP '+status),field:error.field || '',code:error.code || '',details:Array.isArray(error.details)?error.details:[]};
    }
    return {message:text(error || (url+' returned HTTP '+status)),field:'',code:'',details:[]};
  }
  function request(url,options,timeoutMs){
    var opts=options || {};
    var controller=typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer=controller ? window.setTimeout(function(){controller.abort();},timeoutMs || 20000) : 0;
    opts.credentials='same-origin';
    opts.headers=Object.assign({'Accept':'application/json'},opts.headers || {});
    opts.signal=controller ? controller.signal : undefined;
    return fetch(url,opts).then(function(response){
      return response.text().then(function(raw){
        var data={};
        try{data=raw ? JSON.parse(raw) : {};}catch(ignore){data={};}
        if(!response.ok){
          var detail=errorMessage(data,response.status,url);
          var failure=new Error(detail.message);
          failure.status=response.status;failure.code=detail.code;failure.field=detail.field;failure.details=detail.details;
          throw failure;
        }
        return data;
      });
    }).catch(function(error){
      if(error && error.name === 'AbortError'){throw new Error(url+' timed out. No success was assumed.');}
      throw error;
    }).finally(function(){if(timer){window.clearTimeout(timer);}});
  }
  function getJson(url){return request(url,{method:'GET'},15000);}
  function postJson(url,payload,authenticated){
    var headers={'Content-Type':'application/json'};
    if(authenticated){
      if(!model.csrf){return Promise.reject(new Error('Setup session has no CSRF token. Recheck the session before continuing.'));}
      headers['X-Freq-CSRF']=model.csrf;
    }
    return request(url,{method:'POST',headers:headers,body:JSON.stringify(payload)},30000);
  }
  function rememberStatus(data){
    setInitContext('setupId',text(data.setup_id || model.setupId));
    setInitContext('discoveryId',text(data.active_discovery_id || model.discoveryId));
    setInitContext('contractId',text(data.active_contract_id || model.contractId));
    setInitContext('initJobId',text(data.active_init_job_id || model.initJobId));
    var recovering=!!data.active_init_job_id && (data.state==='blocked' || data.state==='initializing');
    $('setup-health').textContent=recovering?'recovering':text(data.state || data.setup_health || 'unknown').replace(/_/g,' ');
    $('setup-reason').textContent=recovering?'Recovering the owner-bound init result. No retry has started.':(data.setup_reason || 'Setup state received without additional detail.');
  }
  function setLocalTruth(state,reason){
    $('setup-health').textContent=text(state).replace(/_/g,' ');
    $('setup-reason').textContent=reason;
  }
  function rememberSession(data){
    retireInitOwner();initSessionGeneration={};
    setInitContext('csrf',text(data.csrf_token));
    var ttl=Number(data.session_ttl_s || 0);
    $('session-state').textContent=data.valid === false ? 'session required' : (ttl ? 'admin session · '+Math.ceil(ttl/60)+'m idle TTL' : 'admin session active');
  }
  function unlockThrough(step){
    var index=STEP_ORDER.indexOf(step);
    if(index>model.unlocked){model.unlocked=index;}
    document.querySelectorAll('[data-step-target]').forEach(function(button){
      button.disabled=STEP_ORDER.indexOf(button.dataset.stepTarget)>model.unlocked;
    });
  }
  function showStep(step){
    if(STEP_ORDER.indexOf(step)>model.unlocked){return;}
    retireInitRecipient();initStep=step;
    document.querySelectorAll('[data-step]').forEach(function(section){section.hidden=section.dataset.step!==step;});
    document.querySelectorAll('[data-step-target]').forEach(function(button){
      var active=button.dataset.stepTarget===step;
      if(active){button.setAttribute('aria-current','step');}else{button.removeAttribute('aria-current');}
    });
    setError('');
    var current=$('step-'+step);
    if(current){current.focus({preventScroll:true});window.scrollTo({top:0,behavior:'smooth'});}
    activateInitRecipient();
    if(initStep==='progress' && currentInitRecipient(initRecipient)){scheduleInit(0,initRecipient);}
  }
  function advance(step){unlockThrough(step);showStep(step);}
  function formatAsOf(value){
    if(!value){return 'AS OF unavailable';}
    var date=new Date(value);
    return isNaN(date.getTime()) ? 'AS OF '+text(value) : 'AS OF '+date.toLocaleString();
  }
  function progress(prefix,progressData){
    var p=progressData || {};
    var current=Number(p.current || 0), total=Number(p.total || 0);
    var phase=stripAnsi(p.phase_name || p.phase || 'Working'),terminalZero=total===0 && phase.toLowerCase()==='complete';
    $(prefix+'-phase').textContent=phase;
    $(prefix+'-count').textContent=total ? current+' / '+total : (terminalZero ? '0 / 0' : 'in progress');
    $(prefix+'-message').textContent=stripAnsi(p.message || 'Waiting for the next verified update.');
    $(prefix+'-bar').style.width=total ? Math.min(100,(current/total)*100)+'%' : (terminalZero ? '100%' : '12%');
  }

  function addNode(data){
    var row=el('div','list-row node-row');
    var nameLabel=el('label');nameLabel.appendChild(document.createTextNode('Node name (optional)'));
    var name=document.createElement('input');name.type='text';name.className='node-name';name.placeholder='pve01';name.value=text(data && data.name);nameLabel.appendChild(name);
    var hostLabel=el('label');hostLabel.appendChild(document.createTextNode('Node IP'));
    var host=document.createElement('input');host.type='text';host.className='node-host';host.placeholder='10.25.255.26';host.inputMode='decimal';host.required=true;host.dataset.apiField='cluster.nodes['+document.querySelectorAll('.node-row').length+'].host';host.value=text(data && (data.host || data.ip));hostLabel.appendChild(host);
    var remove=el('button','icon-btn','Remove');remove.type='button';remove.dataset.action='remove-node';remove.setAttribute('aria-label','Remove PVE node');
    row.append(nameLabel,hostLabel,remove);$('pve-node-list').appendChild(row);
  }
  function collectNodes(){
    return Array.prototype.map.call(document.querySelectorAll('.node-row'),function(row){
      return {host:row.querySelector('.node-host').value.trim(),name:row.querySelector('.node-name').value.trim()};
    }).filter(function(node){return node.host;});
  }
  function claimFailureGuidance(code){
    var guidance={
      claim_secret_required:{message:'The first-boot claim is required.',action:'provide_claim',focus:'operator-claim',retryable:false,terminal:false},
      claim_secret_invalid:{message:'Use the newest first-boot claim or follow the local first-admin claim reset procedure in the zero-state runbook.',action:'replace_claim',focus:'operator-claim',retryable:true,terminal:false},
      claim_state_unavailable:{message:'First-admin setup is temporarily unavailable; retry.',action:'retry',focus:'create-operator',retryable:true,terminal:false},
      claim_rate_limited:{message:'Wait for the current rate window, then retry.',action:'retry',focus:'create-operator',retryable:true,terminal:false},
      claim_consumed:{message:'Follow the local first-admin claim reset procedure in the zero-state runbook.',action:'local_reset',focus:null,retryable:false,terminal:true},
      setup_closed:{message:'First-admin setup is complete; sign in through the dashboard and resume setup.',action:'sign_in',focus:'resume-sign-in',retryable:false,terminal:true}
    };
    return guidance[code] || {message:'',action:null,focus:null,retryable:false,terminal:false};
  }
  function validateOperator(){
    var user=trim('operator-user').toLowerCase(), password=$('operator-pass').value;
    if(!/^[a-z_][a-z0-9_-]{0,31}$/.test(user)){return 'Operator username must use lowercase letters, numbers, underscores, or hyphens.';}
    if(password.length<8){return 'Operator password must be at least 8 characters.';}
    if(password!==$('operator-pass2').value){return 'Operator passwords do not match.';}
    return '';
  }
  function createOperator(event){
    event.preventDefault();setError('');
    var invalid=validateOperator();if(invalid){setError(invalid);return;}
    if(!$('operator-claim').value){setError('First-boot claim secret is required.','claim_secret');return;}
    var button=$('create-operator'),focusTarget='';setBusy(button,true,'Creating secure session…');
    postJson(API.createAdmin,{schema:SCHEMA,username:trim('operator-user').toLowerCase(),password:$('operator-pass').value,claim_secret:$('operator-claim').value,client_request_id:uuid()},false)
      .then(function(data){
        if(!data.session_started || !data.csrf_token){throw new Error('The operator was not given an authenticated setup session.');}
        setInitContext('setupId',text(data.setup_id));rememberSession(data);
        setLocalTruth(data.state || 'collecting','Operator session established. Cluster access has not been submitted.');
        $('operator-claim').value='';$('operator-pass').value='';$('operator-pass2').value='';
        advance('connect');
      }).catch(function(error){
        if(error.code==='operator_exists'){
          $('operator-form').hidden=true;$('resume-session').hidden=false;focusTarget='resume-sign-in';
        }else{
          var guidance=claimFailureGuidance(error.code);
          if(guidance.action==='sign_in'){$('operator-form').hidden=true;$('resume-session').hidden=false;}
          focusTarget=guidance.focus || '';
        }
        setError(error.message,'',error.details);
      }).finally(function(){
        setBusy(button,false);
        if(focusTarget){var target=$(focusTarget);if(target){target.focus();}}
      });
  }
  function verifySession(){
    return getJson(API.verify).then(function(data){
      if(!data.valid || data.role!=='admin'){throw new Error('A valid admin setup session is required.');}
      rememberSession(data);return data;
    });
  }
  function checkSession(){
    setError('');
    verifySession().then(function(){return refreshStatus(true);}).catch(function(error){
      $('operator-form').hidden=true;$('resume-session').hidden=false;$('session-state').textContent='session required';setError(error.message);
    });
  }

  function validateDiscovery(){
    var nodes=collectNodes();
    if(!trim('cluster-name')){return 'Cluster name is required.';}
    if(!trim('bootstrap-user')){return 'Bootstrap SSH user is required.';}
    if(!$('bootstrap-pass').value){return 'Bootstrap SSH password is required.';}
    if(nodes.length<1 || nodes.length>16){return 'Enter between 1 and 16 PVE node IPs.';}
    var unique={};
    for(var i=0;i<nodes.length;i+=1){if(unique[nodes[i].host]){return 'PVE node IPs must be unique.';}unique[nodes[i].host]=true;}
    return '';
  }
  function startDiscovery(event){
    if(event){event.preventDefault();}
    setError('');var invalid=validateDiscovery();if(invalid){setError(invalid);return;}
    var button=$('start-discovery');setBusy(button,true,'Starting discovery…');
    postJson(API.discoveryStart,{
      schema:SCHEMA,setup_id:model.setupId,client_request_id:uuid(),
      cluster:{name:trim('cluster-name'),nodes:collectNodes()},
      bootstrap:{username:trim('bootstrap-user'),password:$('bootstrap-pass').value}
    },true).then(function(data){
      setInitContext('discoveryId',text(data.discovery && data.discovery.id));setInitContext('contractId','');model.contract=null;model.selections={};
      setLocalTruth('discovering','Bounded discovery is running against the declared PVE nodes.');
      $('bootstrap-pass').value='';advance('discover');
      progress('discovery',{phase:'queued',message:'Discovery accepted and queued.'});
      scheduleDiscovery(data.discovery && data.discovery.poll_after_ms);
    }).catch(function(error){setError(error.message,error.field,error.details);}).finally(function(){setBusy(button,false);});
  }
  function scheduleDiscovery(delay){
    window.clearTimeout(model.discoveryTimer);
    model.discoveryTimer=window.setTimeout(pollDiscovery,clampPoll(delay,1000));
  }
  function pollDiscovery(){
    if(!model.discoveryId){setError('No active discovery ID was returned.');return;}
    getJson(API.discoveryStatus+'?id='+encodeURIComponent(model.discoveryId)).then(function(data){
      var discovery=data.discovery || {};progress('discovery',discovery.progress);
      $('discovery-as-of').textContent=formatAsOf(discovery.updated_at);
      if(discovery.state==='succeeded'){
        model.discovery=discovery;renderDiscovery(discovery);return;
      }
      if(discovery.state==='failed'){setError((discovery.error && discovery.error.message) || 'Discovery failed. Return to Connect and retry.');return;}
      scheduleDiscovery(discovery.poll_after_ms);
    }).catch(function(error){setError(error.message,error.field,error.details);});
  }
  function resourceTitle(item){return item.label || item.name || item.host || item.id;}
  function resourceMeta(item,isDevice){
    if(isDevice){return [item.kind,item.host,item.reachable===false?'unreachable':'reachable'].filter(Boolean).join(' · ');}
    return [item.kind,item.vmid!=null?'VMID '+item.vmid:'',item.node,item.status].filter(Boolean).join(' · ');
  }
  function discoveryWarningText(warning){
    if(typeof warning === 'string'){return warning;}
    if(!warning || typeof warning !== 'object'){return 'Discovery warning';}
    if(typeof warning.message === 'string' && warning.message.trim()){return warning.message.trim();}
    var code=text(warning.code || 'discovery_warning').replace(/_/g,' ');
    var resource=typeof warning.resource_id === 'string' ? warning.resource_id.trim() : '';
    return code+(resource ? ' · '+resource : '');
  }
  function renderNodeTruth(nodes){
    var root=$('node-truth');root.replaceChildren();
    (nodes || []).forEach(function(node){
      var card=el('div','node-card');
      card.append(el('strong','',node.name || node.host),el('span','',node.host),el('small',node.reachable===false?'unreachable':('PVE '+text(node.version || 'reachable'))));
      if(node.reachable===false){card.classList.add('is-blocked');}
      root.appendChild(card);
    });
  }
  function renderDiscovery(discovery){
    var results=discovery.results || {}, rows=[];
    (results.resources || []).forEach(function(item){rows.push({item:item,group:'virtual'});});
    (results.devices || []).forEach(function(item){rows.push({item:item,group:'device'});});
    renderNodeTruth(results.pve_nodes || []);
    var warnings=$('discovery-warnings');warnings.replaceChildren();
    (results.warnings || []).forEach(function(warning){warnings.appendChild(el('p','',discoveryWarningText(warning)));});
    warnings.hidden=!warnings.children.length;
    var body=$('resource-rows');body.replaceChildren();model.selections={};
    rows.forEach(function(entry,index){body.appendChild(renderResourceRow(entry.item,entry.group,index));});
    if(!rows.length){
      var emptyRow=el('tr','empty-resource-row');var emptyCell=el('td','','Discovery reached the declared PVE cluster and found no selectable resources or devices. Freeze the empty contract to continue.');emptyCell.colSpan=4;emptyRow.appendChild(emptyCell);body.appendChild(emptyRow);
    }
    $('review-surface').hidden=false;
    setLocalTruth('selecting','Discovery succeeded. Every discovered row still requires an explicit decision.');
    progress('discovery',{phase:'complete',current:rows.length,total:rows.length,message:'Discovery complete. Review every row before freezing the contract.'});
    updateReviewCount();
  }
  function renderResourceRow(item,group,index){
    var row=document.createElement('tr');row.dataset.resourceId=item.id;row.dataset.group=group;row.dataset.decided='false';
    var identity=document.createElement('td');identity.append(el('strong','resource-name',resourceTitle(item)),el('span','resource-id',item.id));
    var truth=document.createElement('td');truth.append(el('span','kind-chip',text(item.kind).toUpperCase()),el('small','',resourceMeta(item,group==='device')));
    if(item.suggested_disposition){truth.appendChild(el('em','suggestion','hint: '+item.suggested_disposition+(item.suggested_placement?' / '+item.suggested_placement:'')));}
    var choice=document.createElement('td');var choices=el('div','row-choices');
    var unknown=group==='device' && item.kind==='unknown';
    ['owned','acknowledged'].forEach(function(value){
      var label=el('label','choice-pill');var input=document.createElement('input');input.type='radio';input.name='selection-'+index;input.value=value;input.disabled=unknown && value==='owned';input.dataset.resourceId=item.id;
      label.append(input,document.createTextNode(value==='owned'?'Owned':'Acknowledge'));if(input.disabled){label.title='Unknown devices are acknowledged-only in v1.';label.classList.add('is-disabled');}choices.appendChild(label);
    });
    if(unknown){choices.appendChild(el('small','honest-note','Unknown kind: ownership is unavailable in v1.'));}
    choice.appendChild(choices);
    var placementCell=document.createElement('td');var select=document.createElement('select');select.className='placement-select';select.disabled=true;select.dataset.resourceId=item.id;select.setAttribute('aria-label','Placement for '+resourceTitle(item));
    [['','Choose placement'],['production','Production'],['lab','Lab']].forEach(function(option){var node=document.createElement('option');node.value=option[0];node.textContent=option[1];select.appendChild(node);});
    placementCell.appendChild(select);
    row.append(identity,truth,choice,placementCell);return row;
  }
  function selectionChanged(target){
    var id=target.dataset.resourceId,row=document.querySelector('tr[data-resource-id="'+CSS.escape(id)+'"]'),placement=row.querySelector('.placement-select');
    model.selections[id]={resource_id:id,disposition:target.value};
    placement.disabled=target.value!=='owned';
    if(target.value!=='owned'){placement.value='';delete model.selections[id].placement;}
    row.dataset.decided='true';updateReviewCount();
  }
  function placementChanged(target){
    var choice=model.selections[target.dataset.resourceId];if(choice){choice.placement=target.value || '';}
    updateReviewCount();
  }
  function updateReviewCount(){
    var rows=Array.prototype.slice.call(document.querySelectorAll('#resource-rows tr[data-resource-id]'));
    var complete=rows.filter(function(row){var choice=model.selections[row.dataset.resourceId];return choice && (choice.disposition==='acknowledged' || (choice.disposition==='owned' && choice.placement));}).length;
    $('review-count').textContent=complete+' of '+rows.length+' decided';$('save-contract').disabled=!model.discovery || complete!==rows.length;
  }
  function filterRows(filter){
    document.querySelectorAll('.filter-btn').forEach(function(button){var active=button.dataset.filter===filter;button.classList.toggle('is-active',active);button.setAttribute('aria-pressed',text(active));});
    document.querySelectorAll('#resource-rows tr[data-resource-id]').forEach(function(row){row.hidden=!(filter==='all' || row.dataset.group===filter || (filter==='undecided' && row.dataset.decided!=='true'));});
  }
  function saveContract(){
    setError('');var button=$('save-contract');if(button.disabled){return;}setBusy(button,true,'Freezing contract…');
    postJson(API.contract,{schema:SCHEMA,setup_id:model.setupId,discovery_id:model.discoveryId,client_request_id:uuid(),selections:Object.keys(model.selections).map(function(id){return model.selections[id];})},true)
      .then(function(data){model.contract=data.contract || {};setInitContext('contractId',text(model.contract.id));setLocalTruth(model.contract.ready?'ready':'credentials',model.contract.ready?'The frozen contract is ready for init.':'The frozen contract still requires owned-device credentials.');renderContractSummary();renderCredentials();})
      .catch(function(error){setError(error.message,error.field,error.details);}).finally(function(){setBusy(button,false);});
  }
  function deviceFor(id){
    var devices=model.discovery && model.discovery.results && model.discovery.results.devices || [];
    return devices.find(function(item){return item.id===id;}) || {id:id,label:id,credential_fields:[]};
  }
  function renderCredentials(){
    var requirements=model.contract && model.contract.credential_requirements || [],root=$('credential-list');root.replaceChildren();
    $('credential-count').textContent=requirements.length+' required';
    if(!requirements.length){root.appendChild(el('div','empty-state','No owned devices require credentials. The frozen contract is ready for init.'));$('save-credentials').textContent='Continue to launch';}
    else{$('save-credentials').textContent='Store device credentials';requirements.forEach(function(requirement){root.appendChild(credentialCard(requirement));});}
    advance('credentials');
    if(model.contract.ready && !requirements.length){renderContractSummary();}
  }
  function credentialCard(requirement){
    var device=deviceFor(requirement.resource_id),card=el('fieldset','credential-card');card.dataset.resourceId=requirement.resource_id;card.tabIndex=-1;
    var legend=document.createElement('legend');legend.append(el('strong','',resourceTitle(device)),el('span','',resourceMeta(device,true)));card.appendChild(legend);
    if(String(device.kind||'').toLowerCase()==='opnsense'){
      opnsenseCredentialCard(card,requirement);
      return card;
    }
    var alternatives=(requirement.required_any || []).map(function(group){return group.join(' + ');}).join(' or ');
    card.appendChild(el('p','requirement-copy','Required: '+(alternatives || 'server-requested credential')));
    if((requirement.stored_fields || []).length){card.appendChild(el('p','stored-fields','Stored: '+requirement.stored_fields.join(', ')+' (values never returned)'));}
    var fields={};(requirement.required_any || []).forEach(function(group){group.forEach(function(name){fields[name]=true;});});
    (device.credential_fields || []).forEach(function(name){fields[name]=true;});
    var grid=el('div','field-row credential-fields');
    Object.keys(fields).forEach(function(name){
      var label=el('label');label.appendChild(document.createTextNode(name.replace(/_/g,' ')));
      var input=document.createElement(name==='ssh_private_key'?'textarea':'input');input.dataset.credentialField=name;input.autocomplete=name==='username'?'username':'new-password';input.dataset.secret=name==='username'?'false':'true';
      if(input.tagName==='INPUT'){input.type=name==='username'?'text':'password';}
      if(name==='ssh_private_key'){input.rows=4;input.spellcheck=false;}
      label.appendChild(input);grid.appendChild(label);
    });
    card.appendChild(grid);return card;
  }
  function opnsenseCredentialCard(card,requirement){
    card.classList.add('opnsense-credential-card');
    card.appendChild(el('p','requirement-copy','Choose one ephemeral bootstrap route and one explicit TLS trust decision. Bootstrap secrets are never returned.'));
    if((requirement.stored_fields || []).length){card.appendChild(el('p','stored-fields','Stored: '+requirement.stored_fields.join(', ')+' (values never returned)'));}
    var grid=el('div','field-row credential-fields');
    function field(name,labelText,type,group,secret){
      var label=el('label');if(group){label.dataset.opnModeFields=group;}
      label.appendChild(document.createTextNode(labelText));
      var input=document.createElement('input');input.type=type||'text';input.dataset.credentialField=name;input.dataset.secret=secret?'true':'false';input.autocomplete=secret?'new-password':'off';
      label.appendChild(input);grid.appendChild(label);return input;
    }
    var modeLabel=el('label');modeLabel.appendChild(document.createTextNode('Bootstrap route'));
    var mode=document.createElement('select');mode.dataset.credentialField='bootstrap_mode';mode.dataset.secret='false';
    [['web','WebGUI username + password'],['api','Existing API key + secret']].forEach(function(pair){var option=document.createElement('option');option.value=pair[0];option.textContent=pair[1];mode.appendChild(option);});
    modeLabel.appendChild(mode);grid.appendChild(modeLabel);
    field('username','WebGUI username','text','web',false);
    field('password','WebGUI password','password','web',true);
    field('api_key','API key','password','api',true);
    field('api_secret','API secret','password','api',true);
    var pin=field('tls_sha256','TLS SHA-256 fingerprint','text','',false);pin.inputMode='text';pin.spellcheck=false;pin.placeholder='64 hex characters';
    var tofuLabel=el('label','opn-tofu-choice');
    var tofu=document.createElement('input');tofu.type='checkbox';tofu.dataset.credentialField='trust_on_first_use';tofu.dataset.secret='false';
    tofuLabel.append(tofu,document.createTextNode(' Deliberately trust the first observed certificate (TOFU)'));grid.appendChild(tofuLabel);
    function syncMode(){
      card.querySelectorAll('[data-opn-mode-fields]').forEach(function(node){
        var active=node.dataset.opnModeFields===mode.value;node.hidden=!active;
        node.querySelectorAll('[data-credential-field]').forEach(function(input){input.disabled=!active;if(!active && input.dataset.secret==='true'){input.value='';}});
      });
    }
    function syncTrust(){pin.disabled=tofu.checked;if(tofu.checked){pin.value='';}}
    if(requirement.bootstrap_mode==='api'||requirement.bootstrap_mode==='web'){mode.value=requirement.bootstrap_mode;}
    if(requirement.tls_sha256){pin.value=requirement.tls_sha256;}
    tofu.checked=requirement.trust_on_first_use===true;
    mode.addEventListener('change',syncMode);tofu.addEventListener('change',syncTrust);
    card.appendChild(grid);syncMode();syncTrust();
  }
  function collectCredentials(){
    var collected=[];
    Array.prototype.forEach.call(document.querySelectorAll('.credential-card'),function(card){
      delete card.dataset.apiField;
      card.querySelectorAll('[data-credential-field]').forEach(function(input){delete input.dataset.apiField;});
      var item={resource_id:card.dataset.resourceId,secrets:{}};
      card.querySelectorAll('[data-credential-field]').forEach(function(input){
        if(input.disabled){return;}var field=input.dataset.credentialField;
        if(card.classList.contains('opnsense-credential-card')){
          if(field==='trust_on_first_use'){if(input.checked){item.trust_on_first_use=true;}return;}
          var opnValue=input.value;if(!opnValue){return;}
          if(field==='username'||field==='bootstrap_mode'||field==='tls_sha256'){item[field]=opnValue.trim();}else{item.secrets[field]=opnValue;}
          return;
        }
        var value=input.value;if(!value){return;}
        if(field==='username'){item.username=value.trim();}else{item.secrets[field]=value;}
      });
      if(item.username || item.bootstrap_mode || item.tls_sha256 || item.trust_on_first_use || Object.keys(item.secrets).length){
        var index=collected.length;card.dataset.apiField='credentials['+index+'].resource_id';
        card.querySelectorAll('[data-credential-field]').forEach(function(input){
          var field=input.dataset.credentialField;
          if(card.classList.contains('opnsense-credential-card')){
            input.dataset.apiField='credentials['+index+'].'+((field==='username'||field==='bootstrap_mode'||field==='tls_sha256'||field==='trust_on_first_use')?field:'secrets.'+field);
          }else{
            input.dataset.apiField='credentials['+index+'].'+(field==='username'?'username':'secrets.'+field);
          }
        });
        collected.push(item);
      }
    });
    return collected;
  }
  function mergeCredentialPresence(rows){
    var presence={};
    (rows || []).forEach(function(row){if(row && row.resource_id){presence[row.resource_id]=row;}});
    (model.contract.credential_requirements || []).forEach(function(requirement){
      var update=presence[requirement.resource_id];if(!update){return;}
      requirement.stored_fields=Array.isArray(update.stored_fields)?update.stored_fields.slice():[];
      requirement.complete=!!update.complete;
      if(update.bootstrap_mode==='api'||update.bootstrap_mode==='web'){requirement.bootstrap_mode=update.bootstrap_mode;}
      requirement.tls_sha256=typeof update.tls_sha256==='string'?update.tls_sha256:'';
      requirement.trust_on_first_use=update.trust_on_first_use===true;
    });
  }
  function clearCredentialInputs(){document.querySelectorAll('[data-credential-field]').forEach(function(input){if(!input.closest('.opnsense-credential-card')||input.dataset.secret==='true'){input.value='';}});}
  function saveCredentials(event){
    event.preventDefault();setError('');
    var requirements=model.contract && model.contract.credential_requirements || [];
    if(!requirements.length){renderContractSummary();advance('launch');return;}
    var button=$('save-credentials');setBusy(button,true,'Storing in vault…');
    postJson(API.credentials,{schema:SCHEMA,setup_id:model.setupId,contract_id:model.contractId,client_request_id:uuid(),credentials:collectCredentials()},true)
      .then(function(data){
        clearCredentialInputs();mergeCredentialPresence(data.credentials);model.contract.ready=!!data.ready;
        if(!data.ready){setLocalTruth('credentials','Credential presence was stored successfully. Complete the remaining required fields.');renderCredentials();return;}
        setLocalTruth('ready','Contract and required credential presence are complete. Init may start.');renderContractSummary();advance('launch');
      })
      .catch(function(error){clearCredentialInputs();setError(error.message,error.field,error.details);}).finally(function(){setBusy(button,false);});
  }
  function renderContractSummary(){
    var counts=model.contract && model.contract.counts || {},root=$('contract-summary');root.replaceChildren();
    [['Owned virtual',counts.owned_virtual],['Templates',counts.templates],['Acknowledged virtual',counts.acknowledged_virtual],['Owned devices',counts.owned_devices],['Acknowledged devices',counts.acknowledged_devices]].forEach(function(pair){var item=el('div');item.append(el('span','',pair[0]),el('strong','',pair[1] == null ? '—' : pair[1]));root.appendChild(item);});
  }
  function validateLaunch(){
    if(!trim('service-account')){return 'Service account username is required.';}
    if($('service-pass').value.length<8){return 'Service account password must be at least 8 characters.';}
    if($('service-pass').value!==$('service-pass2').value){return 'Service account passwords do not match.';}
    return '';
  }
  function startInit(event){
    event.preventDefault();setError('');var invalid=validateLaunch();if(invalid){setError(invalid);return;}
    if(model.initJobId){setError('A new init requires separately confirmed original launch and cancellation settlement.');return;}
    retireInitOwner();
    $('retry-init').hidden=true;$('completion-card').hidden=true;$('cancel-init').hidden=true;$('cancel-init').disabled=true;
    setCancellationTruth('Cancellation becomes available while init is queued or running.','not-requested');
    var button=$('start-init');setBusy(button,true,'Starting init…');
    postJson(API.initStart,{schema:SCHEMA,setup_id:model.setupId,discovery_id:model.discoveryId,contract_id:model.contractId,client_request_id:uuid(),service_account:{username:trim('service-account'),password:$('service-pass').value},options:{ssh_mode:'sudo',pdm:{mode:'skip'},ssl:{mode:'defer'}}},true)
      .then(function(data){$('service-pass').value='';$('service-pass2').value='';setInitContext('initJobId',text(data.job && data.job.id));bindInitOwner();model.handoffRetried=false;setLocalTruth('initializing','Browser-launched init is running. Completion has not been assumed.');advance('progress');progress('progress',{phase:'queued',message:'Init accepted and queued.'});scheduleInit(data.job && data.job.poll_after_ms);})
      .catch(function(error){$('service-pass').value='';$('service-pass2').value='';setError(error.message,error.field,error.details);}).finally(function(){setBusy(button,false);});
  }
  function scheduleInit(delay,recipient){
    recipient=recipient || initRecipient;
    if(!currentInitRecipient(recipient)){return;}
    var previous=model.initTimer;model.initTimer=0;
    if(previous){window.clearTimeout(previous);}
    if(!currentInitRecipient(recipient)){return;}
    var timer=window.setTimeout(function(){
      if(!currentInitRecipient(recipient)){return;}
      model.initTimer=0;pollInit(recipient);
    },clampPoll(delay,1000));
    if(!currentInitRecipient(recipient)){window.clearTimeout(timer);return;}
    model.initTimer=timer;
  }
  function setCancellationTruth(message,state,recipient,sequence){
    if(recipient!==undefined && (!currentInitRecipient(recipient) || (sequence!==undefined && sequence!==recipient.owner.statusSequence))){return;}
    var status=recipient===undefined?$('cancellation-status'):recipient.status;
    if(recipient!==undefined && (!currentInitRecipient(recipient) || (sequence!==undefined && sequence!==recipient.owner.statusSequence))){return;}
    status.textContent=message;
    if(recipient!==undefined && (!currentInitRecipient(recipient) || (sequence!==undefined && sequence!==recipient.owner.statusSequence))){return;}
    status.dataset.state=state || 'unknown';
  }
  function renderInitCancellation(job,recipient,sequence){
    if(!currentInitRecipient(recipient) || job.id!==recipient.owner.jobId || sequence!==recipient.owner.statusSequence){return;}
    var state=job.state,active=state==='queued' || state==='running';
    var cancellation=initCancellation(job);
    retainObservedInitCancellation(recipient,cancellation);
    var attempt=initAttempt(recipient);
    recipient.snapshot={sequence:sequence,active:active,cancellation:cancellation};
    var button=recipient.button;
    if(!initEffect(recipient,function(){button.hidden=!active;},sequence)){return;}
    if(!initEffect(recipient,function(){button.disabled=true;},sequence)){return;}
    if(!initEffect(recipient,function(){button.textContent='Cancellation unavailable';},sequence)){return;}
    if(!holdInitRetry(recipient,sequence)){return;}
    if(attempt && (attempt.state==='unknown' || attempt.observedUnknown===true || !cancellation.requested)){
      setCancellationTruth('The cancellation outcome is unconfirmed. No repeat request or new init is enabled.','unknown',recipient,sequence);return;
    }
    if(!cancellation.valid){
      setCancellationTruth('Cancellation status is unavailable or inconsistent. No request or new init is enabled.','unknown',recipient,sequence);return;
    }
    if(cancellation.delivery==='not_requested'){
      if(!active){setCancellationTruth('No cancellation intent was reported. The job state does not establish resource closure.','not_requested',recipient,sequence);return;}
      if(initAttemptHistory.size>=INIT_ATTEMPT_LIMIT){
        setCancellationTruth('Cancellation is unavailable while retained local attempts remain.','unknown',recipient,sequence);return;
      }
      if(!initEffect(recipient,function(){button.textContent='Request cancellation';},sequence)){return;}
      if(!initEffect(recipient,function(){button.disabled=false;},sequence)){return;}
      setCancellationTruth('Cancellation has not been requested.','not_requested',recipient,sequence);return;
    }
    if(cancellation.delivery==='pending'){
      if(!initEffect(recipient,function(){button.textContent='Cancellation requested';},sequence)){return;}
      setCancellationTruth('Cancellation intent is recorded; a signal call has not been reported. No stop or resource closure is assumed.','pending',recipient,sequence);return;
    }
    if(cancellation.delivery==='sent'){
      if(!initEffect(recipient,function(){button.textContent='Signal call returned';},sequence)){return;}
      setCancellationTruth('The signal API call returned. This does not confirm child delivery, stopping or resource closure.','sent',recipient,sequence);return;
    }
    setCancellationTruth('The cancellation outcome is unconfirmed. No repeat request or new init is enabled.','unknown',recipient,sequence);
  }
  function requestInitCancellation(){
    var recipient=initRecipient,attempt=beginInitAttempt(recipient);
    if(!attempt){return;}
    var button=recipient.button,jobId=recipient.owner.jobId;
    if(!initEffect(recipient,function(){button.disabled=true;})){return;}
    if(!initEffect(recipient,function(){button.setAttribute('aria-busy','true');})){return;}
    if(!initEffect(recipient,function(){ownedInitError(recipient,'');})){return;}
    if(!holdInitRetry(recipient)){return;}
    setCancellationTruth('Requesting cancellation. The outcome is not yet confirmed.','unknown',recipient);
    Promise.resolve().then(function(){
      if(!currentInitRecipient(recipient)){return null;}
      return postJson(API.initCancel,{id:jobId},true);
    }).then(function(data){
      if(!currentInitRecipient(recipient)){return;}
      var c=data && data.cancellation;
      if(!c || c.job_id!==jobId || c.state!=='requested'){
        throw new Error('Cancellation response did not confirm this init job.');
      }
      attempt.state='acknowledged';
      if(!initEffect(recipient,function(){button.textContent='Cancellation requested';})){return;}
      setCancellationTruth('Cancellation intent was acknowledged. No signal delivery, stop or resource closure is assumed.','pending',recipient);
      scheduleInit(c.poll_after_ms || 250,recipient);
    }).catch(function(){
      // The retained pre-transport duty stays unknown for every error, including409/503.
      if(!currentInitRecipient(recipient)){return;}
      setCancellationTruth('The cancellation outcome is unconfirmed. No repeat request or new init is enabled.','unknown',recipient);
      scheduleInit(0,recipient);
    }).finally(function(){
      initEffect(recipient,function(){button.removeAttribute('aria-busy');});
    });
  }
  function pollInit(recipient){
    recipient=recipient || initRecipient;
    if(!currentInitRecipient(recipient)){return;}
    var jobId=recipient.owner.jobId,sequence=++recipient.owner.statusSequence;
    recipient.snapshot=null;
    function current(){return currentInitRecipient(recipient) && sequence===recipient.owner.statusSequence;}
    if(!initEffect(recipient,function(){recipient.button.disabled=true;},sequence)){return;}
    Promise.resolve().then(function(){
      if(!current()){return null;}
      return getJson(API.initStatus+'?id='+encodeURIComponent(jobId));
    }).then(function(data){
      if(!current()){return;}
      var job=data && data.job;
      if(!job || job.id!==jobId){throw new Error('Init status did not match the requested job.');}
      // Root the accepted negative observation before any progress/native effect.
      retainObservedInitCancellation(recipient,initCancellation(job));
      model.handoffRetried=false;
      if(!initEffect(recipient,function(){ownedInitProgress(recipient,job.progress,sequence);},sequence)){return;}
      if(!current()){return;}
      if(!initEffect(recipient,function(){recipient.nodes['progress-state'].textContent=text(job.state || 'running');},sequence)){return;}
      if(!initEffect(recipient,function(){recipient.nodes['init-as-of'].textContent='AS OF '+new Date().toLocaleString();},sequence)){return;}
      renderInitCancellation(job,recipient,sequence);
      if(!current()){return;}
      if(!initEffect(recipient,function(){ownedInitLog(recipient,job.log_tail,sequence);},sequence)){return;}
      if(!current()){return;}
      if(job.state==='succeeded'){
        if(job.initialized!==true || job.web_setup_complete!==true){throw new Error('Init reported success without both completion markers.');}
        confirmCompletion(recipient,sequence);return;
      }
      if(job.state==='failed'){showInitFailure(job,recipient,sequence);return;}
      scheduleInit(job.poll_after_ms || 2000,recipient);
    }).catch(function(error){
      if(!current()){return;}
      if(!model.handoffRetried){
        model.handoffRetried=true;
        getJson(API.status).then(function(status){
          if(!current()){return;}
          // A global status may invalidate this owner, but never adopt a successor.
          if(status.setup_id!==recipient.owner.setupId ||
            (status.active_init_job_id && status.active_init_job_id!==jobId)){
            retireInitOwner();return;
          }
          if(status.active_init_job_id===jobId){scheduleInit(1000,recipient);}
          else{throw error;}
        }).catch(function(){if(current()){initEffect(recipient,function(){ownedInitError(recipient,'Init status is unconfirmed. No new init or cancellation retry was enabled.',sequence);},sequence);}});
        return;
      }
      initEffect(recipient,function(){ownedInitError(recipient,'Init status is unconfirmed. No new init or cancellation retry was enabled.',sequence);},sequence);
    });
  }
  function refreshLogs(){
    var recipient=initRecipient;if(!currentInitRecipient(recipient)){return;}
    var jobId=recipient.owner.jobId;
    getJson(API.initLogs+'?id='+encodeURIComponent(jobId)).then(function(data){
      if(!currentInitRecipient(recipient)){return;}
      if(!data || !data.job || data.job.id!==jobId){throw new Error('Init logs did not match the requested job.');}
      initEffect(recipient,function(){ownedInitLog(recipient,data.job.log_tail);});
    }).catch(function(){initEffect(recipient,function(){ownedInitError(recipient,'Init logs are unavailable for the current job.');});});
  }
  function confirmCompletion(recipient,sequence){
    function current(){return currentInitRecipient(recipient) && sequence===recipient.owner.statusSequence;}
    if(!current()){return;}
    getJson(API.status).then(function(status){
      if(!current()){return;}
      if(status.setup_id!==recipient.owner.setupId || status.state!=='complete' ||
        status.initialized!==true || status.web_setup_complete!==true){
        throw new Error('Setup status did not confirm both completion markers for this setup.');
      }
      if(!initEffect(recipient,function(){recipient.nodes['progress-state'].textContent='complete';},sequence)){return;}
      if(!initEffect(recipient,function(){recipient.nodes['progress-phase'].textContent='Setup markers';},sequence)){return;}
      if(!initEffect(recipient,function(){recipient.nodes['progress-message'].textContent='Setup reports both durable completion markers. Resource closure is not inferred.';},sequence)){return;}
      if(!initEffect(recipient,function(){recipient.nodes['progress-bar'].style.width='100%';},sequence)){return;}
      if(!holdInitRetry(recipient,sequence)){return;}
      initEffect(recipient,function(){recipient.nodes['completion-card'].hidden=false;},sequence);
    }).catch(function(){if(current()){initEffect(recipient,function(){ownedInitError(recipient,'Setup completion is unconfirmed for the current job.',sequence);},sequence);}});
  }

  function showInitFailure(job,recipient,sequence){
    if(!currentInitRecipient(recipient) || job.id!==recipient.owner.jobId || sequence!==recipient.owner.statusSequence){return;}
    if(!initEffect(recipient,function(){recipient.nodes['completion-card'].hidden=true;},sequence)){return;}
    if(!holdInitRetry(recipient,sequence)){return;}
    if(!initEffect(recipient,function(){recipient.nodes['setup-health'].textContent='blocked';},sequence)){return;}
    if(!initEffect(recipient,function(){recipient.nodes['setup-reason'].textContent='The init job reported failure. A new init requires separately confirmed launch and cancellation settlement.';},sequence)){return;}
    ownedInitError(recipient,'The init job reported failure. No new init was enabled; resource closure has not been confirmed.',sequence);
  }
  function prepareInitRetry(){
    // This revision has no adopted cancellation-aware settlement evidence.
    // error.retryable is only a hint; no terminal label or UI request settles a duty.
    var recipient=initRecipient;
    if(!currentInitRecipient(recipient)){return;}
    if(!holdInitRetry(recipient)){return;}
    initEffect(recipient,function(){ownedInitError(recipient,'A new init is unavailable until original launch and cancellation settlement is confirmed.');});
  }

  function loadDiscovery(id){
    setInitContext('discoveryId',text(id || model.discoveryId));
    if(!model.discoveryId){return Promise.reject(new Error('Setup state did not include an active discovery.'));}
    return getJson(API.discoveryStatus+'?id='+encodeURIComponent(model.discoveryId)).then(function(data){var discovery=data.discovery || {};model.discovery=discovery;if(discovery.state==='succeeded'){renderDiscovery(discovery);}else{progress('discovery',discovery.progress);scheduleDiscovery(discovery.poll_after_ms);}return discovery;});
  }
  function loadContract(){
    return getJson(API.contract).then(function(data){model.contract=data.contract || {};setInitContext('contractId',text(model.contract.id || model.contractId));renderContractSummary();return model.contract;});
  }
  function statusVerifiedComplete(status){
    return status && status.state==='complete' && status.initialized===true && status.web_setup_complete===true;
  }
  function resumeFromStatus(status){
    var state=status.state || 'collecting';
    $('completion-card').hidden=true;
    if(state==='complete'){
      model.unlocked=5;advance('progress');
      if(!statusVerifiedComplete(status)){setError('Setup state claimed complete without both durable completion markers. No completion was assumed.');return;}
      $('completion-card').hidden=false;$('progress-state').textContent='complete';return;
    }
    if(state==='collecting'){advance('connect');return;}
    if(state==='discovering'){setInitContext('discoveryId',text(status.active_discovery_id));advance('discover');scheduleDiscovery(0);return;}
    if(state==='selecting'){setInitContext('discoveryId',text(status.active_discovery_id));advance('discover');loadDiscovery();return;}
    if(state==='credentials' || state==='ready'){
      setInitContext('discoveryId',text(status.active_discovery_id));setInitContext('contractId',text(status.active_contract_id));
      loadDiscovery().then(loadContract).then(function(){renderCredentials();if(state==='ready'){advance('launch');}}).catch(function(error){setError(error.message);});return;
    }
    if(state==='initializing'){setInitContext('initJobId',text(status.active_init_job_id));bindInitOwner();$('retry-init').hidden=true;setLocalTruth('recovering','Recovering the owner-bound init result. No retry has started.');advance('progress');scheduleInit(0);return;}
    if(state==='blocked'){
      if(status.active_init_job_id){setInitContext('initJobId',text(status.active_init_job_id));bindInitOwner();$('retry-init').hidden=true;setLocalTruth('recovering','Recovering the owner-bound init result. No retry has started.');advance('progress');scheduleInit(0);return;}
      else if(status.active_discovery_id){setInitContext('discoveryId',text(status.active_discovery_id));advance('discover');loadDiscovery();}
      else{advance('connect');}
      setError(status.setup_reason || 'The last setup job is blocked. Review the visible state and retry.');return;
    }
    advance('connect');
  }
  function refreshStatus(resume){
    return getJson(API.status).then(function(status){rememberStatus(status);if(resume){resumeFromStatus(status);}return status;}).catch(function(error){$('setup-health').textContent='unreachable';$('setup-reason').textContent=error.message;throw error;});
  }
  function boot(){
    if(!trim('service-account')){$('service-account').value=DEFAULT_SERVICE_ACCOUNT;}
    refreshStatus(false).then(function(status){
      if(status.state==='needs_operator' || (!status.state && status.first_run)){$('session-state').textContent='operator required';showStep('operator');return;}
      return verifySession().then(function(){resumeFromStatus(status);}).catch(function(){model.unlocked=0;showStep('operator');$('operator-form').hidden=true;$('resume-session').hidden=false;$('session-state').textContent='session required';});
    }).catch(function(error){setError(error.message);});
  }

  document.addEventListener('click',function(event){
    var target=event.target.closest('[data-action],[data-step-target],.filter-btn');if(!target){return;}
    if(target.dataset.stepTarget){showStep(target.dataset.stepTarget);return;}
    if(target.classList.contains('filter-btn')){filterRows(target.dataset.filter);return;}
    var action=target.dataset.action;
    if(action==='add-node'){addNode({});}
    if(action==='remove-node'){var rows=document.querySelectorAll('.node-row');if(rows.length>1){target.closest('.node-row').remove();}}
    if(action==='back'){showStep(target.dataset.back);}
    if(action==='rediscover'){showStep('connect');}
  });
  $('resource-rows').addEventListener('change',function(event){if(event.target.matches('input[type="radio"]')){selectionChanged(event.target);}if(event.target.matches('.placement-select')){placementChanged(event.target);}});
  $('operator-form').addEventListener('submit',createOperator);
  $('discovery-form').addEventListener('submit',startDiscovery);
  $('credentials-form').addEventListener('submit',saveCredentials);
  $('launch-form').addEventListener('submit',startInit);
  $('save-contract').addEventListener('click',saveContract);
  $('retry-session').addEventListener('click',checkSession);
  $('retry-init').addEventListener('click',prepareInitRetry);
  $('cancel-init').addEventListener('click',requestInitCancellation);
  $('refresh-logs').addEventListener('click',refreshLogs);
  $('refresh-status').addEventListener('click',function(){refreshStatus(false).catch(function(){});});
  addNode({name:'pve01'});
  boot();
})();
