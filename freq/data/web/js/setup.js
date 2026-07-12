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
    initStatus: '/api/setup/init/status',
    initLogs: '/api/setup/init/logs'
  };
  var STEP_ORDER = ['operator','connect','discover','credentials','launch','progress'];
  var model = {
    csrf: '', setupId: '', discoveryId: '', contractId: '', initJobId: '',
    discovery: null, contract: null, selections: {}, unlocked: 0,
    discoveryTimer: 0, initTimer: 0, handoffRetried: false
  };

  function $(id){return document.getElementById(id);}
  function text(value){return value == null ? '' : String(value);}
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
  function setError(message,field){
    var box=$('form-error');
    box.hidden=!message;
    box.textContent=message || '';
    if(message){box.scrollIntoView({behavior:'smooth',block:'nearest'});}
    if(field){
      var target=document.querySelector('[data-api-field="'+CSS.escape(field)+'"]');
      if(target){target.focus();}
    }
  }
  function errorMessage(data,status,url){
    var error=data && data.error;
    if(error && typeof error === 'object'){
      return {message:error.message || error.code || (url+' returned HTTP '+status),field:error.field || '',code:error.code || ''};
    }
    return {message:text(error || (url+' returned HTTP '+status)),field:'',code:''};
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
          failure.status=response.status;failure.code=detail.code;failure.field=detail.field;
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
    model.setupId=text(data.setup_id || model.setupId);
    model.discoveryId=text(data.active_discovery_id || model.discoveryId);
    model.contractId=text(data.active_contract_id || model.contractId);
    model.initJobId=text(data.active_init_job_id || model.initJobId);
    $('setup-health').textContent=text(data.state || data.setup_health || 'unknown').replace(/_/g,' ');
    $('setup-reason').textContent=data.setup_reason || 'Setup state received without additional detail.';
  }
  function setLocalTruth(state,reason){
    $('setup-health').textContent=text(state).replace(/_/g,' ');
    $('setup-reason').textContent=reason;
  }
  function rememberSession(data){
    model.csrf=text(data.csrf_token);
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
    document.querySelectorAll('[data-step]').forEach(function(section){section.hidden=section.dataset.step!==step;});
    document.querySelectorAll('[data-step-target]').forEach(function(button){
      var active=button.dataset.stepTarget===step;
      if(active){button.setAttribute('aria-current','step');}else{button.removeAttribute('aria-current');}
    });
    setError('');
    var current=$('step-'+step);
    if(current){current.focus({preventScroll:true});window.scrollTo({top:0,behavior:'smooth'});}
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
    $(prefix+'-phase').textContent=text(p.phase_name || p.phase || 'Working');
    $(prefix+'-count').textContent=total ? current+' / '+total : 'in progress';
    $(prefix+'-message').textContent=p.message || 'Waiting for the next verified update.';
    $(prefix+'-bar').style.width=total ? Math.min(100,(current/total)*100)+'%' : '12%';
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
    var button=$('create-operator');setBusy(button,true,'Creating secure session…');
    postJson(API.createAdmin,{schema:SCHEMA,username:trim('operator-user').toLowerCase(),password:$('operator-pass').value,client_request_id:uuid()},false)
      .then(function(data){
        if(!data.session_started || !data.csrf_token){throw new Error('The operator was not given an authenticated setup session.');}
        model.setupId=text(data.setup_id);rememberSession(data);
        setLocalTruth(data.state || 'collecting','Operator session established. Cluster access has not been submitted.');
        $('operator-pass').value='';$('operator-pass2').value='';
        advance('connect');
      }).catch(function(error){
        if(error.code==='operator_exists'){$('operator-form').hidden=true;$('resume-session').hidden=false;}
        setError(error.message,error.field);
      }).finally(function(){setBusy(button,false);});
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
      model.discoveryId=text(data.discovery && data.discovery.id);model.contractId='';model.contract=null;model.selections={};
      setLocalTruth('discovering','Bounded discovery is running against the declared PVE nodes.');
      $('bootstrap-pass').value='';advance('discover');
      progress('discovery',{phase:'queued',message:'Discovery accepted and queued.'});
      scheduleDiscovery(data.discovery && data.discovery.poll_after_ms);
    }).catch(function(error){setError(error.message,error.field);}).finally(function(){setBusy(button,false);});
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
    }).catch(function(error){setError(error.message,error.field);});
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
      .then(function(data){model.contract=data.contract || {};model.contractId=text(model.contract.id);setLocalTruth(model.contract.ready?'ready':'credentials',model.contract.ready?'The frozen contract is ready for init.':'The frozen contract still requires owned-device credentials.');renderContractSummary();renderCredentials();})
      .catch(function(error){setError(error.message,error.field);}).finally(function(){setBusy(button,false);});
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
    var device=deviceFor(requirement.resource_id),card=el('fieldset','credential-card');card.dataset.resourceId=requirement.resource_id;
    var legend=document.createElement('legend');legend.append(el('strong','',resourceTitle(device)),el('span','',resourceMeta(device,true)));card.appendChild(legend);
    var alternatives=(requirement.required_any || []).map(function(group){return group.join(' + ');}).join(' or ');
    card.appendChild(el('p','requirement-copy','Required: '+(alternatives || 'server-requested credential')));
    if((requirement.stored_fields || []).length){card.appendChild(el('p','stored-fields','Stored: '+requirement.stored_fields.join(', ')+' (values never returned)'));}
    var fields={};(requirement.required_any || []).forEach(function(group){group.forEach(function(name){fields[name]=true;});});
    (device.credential_fields || []).forEach(function(name){fields[name]=true;});
    var grid=el('div','field-row credential-fields');
    Object.keys(fields).forEach(function(name){
      var label=el('label');label.appendChild(document.createTextNode(name.replace(/_/g,' ')));
      var input=document.createElement(name==='ssh_private_key'?'textarea':'input');input.dataset.credentialField=name;input.autocomplete=name==='username'?'username':'new-password';
      if(input.tagName==='INPUT'){input.type=name==='username'?'text':'password';}
      if(name==='ssh_private_key'){input.rows=4;input.spellcheck=false;}
      label.appendChild(input);grid.appendChild(label);
    });
    card.appendChild(grid);return card;
  }
  function collectCredentials(){
    return Array.prototype.map.call(document.querySelectorAll('.credential-card'),function(card){
      var item={resource_id:card.dataset.resourceId,secrets:{}};
      card.querySelectorAll('[data-credential-field]').forEach(function(input){
        var value=input.value;if(!value){return;}var field=input.dataset.credentialField;
        if(field==='username'){item.username=value.trim();}else{item.secrets[field]=value;}
      });
      return item;
    }).filter(function(item){return item.username || Object.keys(item.secrets).length;});
  }
  function clearCredentialInputs(){document.querySelectorAll('[data-credential-field]').forEach(function(input){input.value='';});}
  function saveCredentials(event){
    event.preventDefault();setError('');
    var requirements=model.contract && model.contract.credential_requirements || [];
    if(!requirements.length){renderContractSummary();advance('launch');return;}
    var button=$('save-credentials');setBusy(button,true,'Storing in vault…');
    postJson(API.credentials,{schema:SCHEMA,setup_id:model.setupId,contract_id:model.contractId,client_request_id:uuid(),credentials:collectCredentials()},true)
      .then(function(data){clearCredentialInputs();if(!data.ready){throw new Error('Required device credentials are still incomplete. Stored values were not returned.');}model.contract.ready=true;setLocalTruth('ready','Contract and required credential presence are complete. Init may start.');renderContractSummary();advance('launch');})
      .catch(function(error){clearCredentialInputs();setError(error.message,error.field);}).finally(function(){setBusy(button,false);});
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
    var button=$('start-init');setBusy(button,true,'Starting init…');
    postJson(API.initStart,{schema:SCHEMA,setup_id:model.setupId,discovery_id:model.discoveryId,contract_id:model.contractId,client_request_id:uuid(),service_account:{username:trim('service-account'),password:$('service-pass').value},options:{ssh_mode:'sudo',pdm:{mode:'skip'},ssl:{mode:'defer'}}},true)
      .then(function(data){$('service-pass').value='';$('service-pass2').value='';model.initJobId=text(data.job && data.job.id);model.handoffRetried=false;setLocalTruth('initializing','Browser-launched init is running. Completion has not been assumed.');advance('progress');progress('progress',{phase:'queued',message:'Init accepted and queued.'});scheduleInit(data.job && data.job.poll_after_ms);})
      .catch(function(error){$('service-pass').value='';$('service-pass2').value='';setError(error.message,error.field);}).finally(function(){setBusy(button,false);});
  }
  function scheduleInit(delay){window.clearTimeout(model.initTimer);model.initTimer=window.setTimeout(pollInit,clampPoll(delay,1000));}
  function pollInit(){
    if(!model.initJobId){setError('No active init job ID was returned.');return;}
    getJson(API.initStatus+'?id='+encodeURIComponent(model.initJobId)).then(function(data){
      model.handoffRetried=false;var job=data.job || {};progress('progress',job.progress);$('progress-state').textContent=text(job.state || 'running');$('init-as-of').textContent='AS OF '+new Date().toLocaleString();
      if(Array.isArray(job.log_tail)){$('phase-log').textContent=job.log_tail.join('\n') || 'No redacted log lines returned.';}
      if(job.state==='succeeded'){
        if(!job.initialized || !job.web_setup_complete){throw new Error('Init reported success without both completion markers. No completion was assumed.');}
        confirmCompletion();return;
      }
      if(job.state==='failed'){setError((job.error && job.error.message) || 'Init failed. Stored selections remain available for a bounded retry.');return;}
      scheduleInit(job.poll_after_ms || 2000);
    }).catch(function(error){
      if(!model.handoffRetried){model.handoffRetried=true;getJson(API.status).then(function(status){rememberStatus(status);if(status.active_init_job_id===model.initJobId || status.state==='initializing'){scheduleInit(1000);}else{throw error;}}).catch(function(){setError(error.message);});return;}
      setError(error.message,error.field);
    });
  }
  function refreshLogs(){
    if(!model.initJobId){return;}
    getJson(API.initLogs+'?id='+encodeURIComponent(model.initJobId)).then(function(data){var lines=data.log_tail || (data.job && data.job.log_tail) || [];if(Array.isArray(lines)){$('phase-log').textContent=lines.join('\n') || 'No redacted log lines returned.';}}).catch(function(error){setError(error.message);});
  }
  function confirmCompletion(){
    getJson(API.status).then(function(status){rememberStatus(status);if(status.state!=='complete' || !status.initialized || !status.web_setup_complete){throw new Error('Init stopped, but setup/status has not verified complete.');}$('progress-state').textContent='complete';$('progress-phase').textContent='Verification';$('progress-message').textContent='Runner exit, initialized marker, and web setup marker all verified.';$('progress-bar').style.width='100%';$('completion-card').hidden=false;}).catch(function(error){setError(error.message);});
  }

  function loadDiscovery(id){
    model.discoveryId=text(id || model.discoveryId);
    if(!model.discoveryId){return Promise.reject(new Error('Setup state did not include an active discovery.'));}
    return getJson(API.discoveryStatus+'?id='+encodeURIComponent(model.discoveryId)).then(function(data){var discovery=data.discovery || {};model.discovery=discovery;if(discovery.state==='succeeded'){renderDiscovery(discovery);}else{progress('discovery',discovery.progress);scheduleDiscovery(discovery.poll_after_ms);}return discovery;});
  }
  function loadContract(){
    return getJson(API.contract).then(function(data){model.contract=data.contract || {};model.contractId=text(model.contract.id || model.contractId);renderContractSummary();return model.contract;});
  }
  function resumeFromStatus(status){
    var state=status.state || 'collecting';
    if(state==='complete'){model.unlocked=5;advance('progress');$('completion-card').hidden=false;$('progress-state').textContent='complete';return;}
    if(state==='collecting'){advance('connect');return;}
    if(state==='discovering'){model.discoveryId=text(status.active_discovery_id);advance('discover');scheduleDiscovery(0);return;}
    if(state==='selecting'){model.discoveryId=text(status.active_discovery_id);advance('discover');loadDiscovery();return;}
    if(state==='credentials' || state==='ready'){
      model.discoveryId=text(status.active_discovery_id);model.contractId=text(status.active_contract_id);
      loadDiscovery().then(loadContract).then(function(){renderCredentials();if(state==='ready'){advance('launch');}}).catch(function(error){setError(error.message);});return;
    }
    if(state==='initializing'){model.initJobId=text(status.active_init_job_id);advance('progress');scheduleInit(0);return;}
    if(state==='blocked'){
      if(status.active_init_job_id){model.initJobId=text(status.active_init_job_id);advance('progress');scheduleInit(0);}
      else if(status.active_discovery_id){model.discoveryId=text(status.active_discovery_id);advance('discover');loadDiscovery();}
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
  $('refresh-logs').addEventListener('click',refreshLogs);
  $('refresh-status').addEventListener('click',function(){refreshStatus(false).catch(function(){});});
  addNode({name:'pve01'});
  boot();
})();
