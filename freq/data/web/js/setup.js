(function(){
  'use strict';

  var API = {
    status: '/api/setup/status',
    createAdmin: '/api/setup/create-admin',
    start: '/api/setup/init/start',
    runStatus: '/api/setup/init/status',
    logs: '/api/setup/init/logs',
    certAdopt: '/api/cert/lifecycle/adopt-existing',
    certBootstrap: '/api/cert/lifecycle/bootstrap',
    certReconcile: '/api/cert/lifecycle/reconcile'
  };

  var nodeList = document.getElementById('pve-node-list');
  var deviceList = document.getElementById('device-list');
  var form = document.getElementById('init-form');
  var errorBox = document.getElementById('form-error');
  var phaseLog = document.getElementById('phase-log');
  var progressState = document.getElementById('progress-state');
  var progressPhase = document.getElementById('progress-phase');

  function $(id){return document.getElementById(id);}
  function val(id){var el=$(id);return el ? el.value.trim() : '';}
  function boolRadio(name,value){
    var el = document.querySelector('input[name="'+name+'"][value="'+value+'"]');
    return !!(el && el.checked);
  }
  function radioValue(name){
    var el = document.querySelector('input[name="'+name+'"]:checked');
    return el ? el.value : '';
  }
  function esc(s){
    return String(s == null ? '' : s).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function splitList(s){
    return String(s || '').split(',').map(function(v){return v.trim();}).filter(Boolean);
  }
  function targetFromHostname(hostname,baseDomain,mode){
    var h = String(hostname || '').trim().toLowerCase();
    var suffix = baseDomain ? '.' + String(baseDomain).toLowerCase() : '';
    var subdomain = suffix && h.endsWith(suffix) ? h.slice(0,-suffix.length) : '';
    return {
      name: subdomain || h,
      hostname: h,
      subdomain: subdomain,
      mode: mode || 'direct',
      enabled: true,
      scope: 'web-init'
    };
  }
  function certTargets(hostnames,baseDomain,mode){
    return (hostnames || []).map(function(hostname){
      return targetFromHostname(hostname,baseDomain,mode);
    });
  }
  function setError(msg){
    errorBox.hidden = !msg;
    errorBox.textContent = msg || '';
  }
  function appendLog(line){
    var current = phaseLog.textContent || '';
    phaseLog.textContent = (current && current !== 'No init run has started in this browser session.' ? current + '\n' : '') + line;
    phaseLog.scrollTop = phaseLog.scrollHeight;
  }

  function addNode(data){
    var row = document.createElement('div');
    row.className = 'list-row node-row';
    row.innerHTML =
      '<label>Node name<input type="text" class="node-name" placeholder="pve01" value="'+esc(data && data.name || '')+'"></label>'+
      '<label>Node IP<input type="text" class="node-ip" placeholder="10.25.255.26" value="'+esc(data && data.ip || '')+'"></label>'+
      '<button class="icon-btn" type="button" data-action="remove-row" aria-label="Remove PVE node">x</button>';
    nodeList.appendChild(row);
  }

  function addDevice(data){
    var row = document.createElement('div');
    row.className = 'list-row device-row';
    row.innerHTML =
      '<label>Type<select class="device-type">'+
      '<option value="pfsense">pfSense</option><option value="truenas">TrueNAS</option>'+
      '<option value="switch">Switch</option><option value="bmc">BMC</option>'+
      '<option value="linux">Linux</option><option value="other">Other</option></select></label>'+
      '<label>Target<input type="text" class="device-target" placeholder="label or IP" value="'+esc(data && data.target || '')+'"></label>'+
      '<label>User<input type="text" class="device-user" placeholder="admin" value="'+esc(data && data.user || '')+'"></label>'+
      '<label>Secret<input type="password" class="device-secret" value="'+esc(data && data.secret || '')+'"></label>'+
      '<button class="icon-btn" type="button" data-action="remove-row" aria-label="Remove device credential">x</button>';
    deviceList.appendChild(row);
    if(data && data.type){row.querySelector('.device-type').value=data.type;}
  }

  function showSslFields(){
    var mode = radioValue('ssl_mode');
    document.querySelectorAll('[data-ssl-fields]').forEach(function(el){
      el.hidden = el.getAttribute('data-ssl-fields') !== mode;
    });
  }

  function collectNodes(){
    return Array.prototype.slice.call(document.querySelectorAll('.node-row')).map(function(row,idx){
      return {
        name: row.querySelector('.node-name').value.trim() || 'pve' + String(idx + 1).padStart(2,'0'),
        ip: row.querySelector('.node-ip').value.trim()
      };
    }).filter(function(n){return n.ip;});
  }

  function collectDevices(){
    var devices = {};
    Array.prototype.slice.call(document.querySelectorAll('.device-row')).forEach(function(row,idx){
      var item = {
        type: row.querySelector('.device-type').value,
        target: row.querySelector('.device-target').value.trim(),
        username: row.querySelector('.device-user').value.trim(),
        secret: row.querySelector('.device-secret').value
      };
      if(item.target || item.username || item.secret){
        var key = item.type + '_' + String(idx + 1);
        devices[key] = item;
      }
    });
    return devices;
  }

  function collectStartPayload(payload){
    var nodes = payload.cluster.pve_nodes;
    var start = {
      contract_version: payload.contract_version,
      bootstrap_user: payload.ssh.bootstrap_user,
      service_account: payload.ssh.service_account,
      dashboard_user: payload.operator.username,
      pve_nodes: nodes.map(function(n){return n.ip;}),
      pve_node_names: nodes.map(function(n){return n.name;}),
      gateway: payload.cluster.gateway,
      nameserver: payload.cluster.nameserver,
      cluster_name: payload.cluster.cluster_name,
      timezone: payload.cluster.timezone,
      ssh_mode: payload.ssh.mode,
      hosts_import: payload.fleet.hosts_import,
      hosts_file: '',
      owned_vmids: payload.fleet.owned_vmids,
      template_vmids: payload.fleet.template_vmids,
      acknowledged_out_of_contract_vmids: payload.fleet.acknowledged_out_of_contract_vmids,
      core_devices: payload.fleet.core_devices,
      lab_devices: payload.fleet.lab_devices,
      install_pdm: payload.pdm.mode === 'install',
      skip_pdm: payload.pdm.mode === 'skip',
      pdm_password: payload.pdm.root_pam_password,
      pdm_remote_name: payload.pdm.remote_name,
      device_credentials: payload.fleet.device_credentials,
      ssl_mode: payload.ssl.mode
    };
    if(payload.ssh.service_password_source === 'path'){
      start.service_account_password_file = payload.ssh.service_password;
    }else{
      start.service_account_password = payload.ssh.service_password;
    }
    if(payload.operator.password_source === 'path'){
      start.dashboard_password_file = payload.operator.password;
    }else{
      start.dashboard_password = payload.operator.password;
    }
    if(payload.ssh.bootstrap_auth === 'password'){
      start.bootstrap_password = payload.ssh.bootstrap_secret;
    }else if(payload.ssh.bootstrap_auth === 'password-path'){
      start.bootstrap_password_file = payload.ssh.bootstrap_secret;
    }else if(payload.ssh.bootstrap_auth === 'key'){
      start.bootstrap_key = payload.ssh.bootstrap_secret;
    }else{
      start.bootstrap_key_path = payload.ssh.bootstrap_secret;
    }
    return start;
  }

  function collectPayload(){
    var sslMode = radioValue('ssl_mode');
    return {
      contract_version: 'zero-state-web-init-v1',
      operator: {
        username: val('operator-user').toLowerCase(),
        password_source: val('operator-pass-source') || 'secret',
        password: $('operator-pass').value
      },
      cluster: {
        cluster_name: val('cluster-name'),
        timezone: val('timezone') || 'UTC',
        gateway: val('gateway'),
        nameserver: val('nameserver') || '1.1.1.1',
        pve_nodes: collectNodes()
      },
      ssh: {
        mode: val('ssh-mode') || 'sudo',
        bootstrap_user: val('bootstrap-user') || 'root',
        bootstrap_auth: val('bootstrap-auth') || 'password',
        bootstrap_secret: $('bootstrap-secret').value,
        service_account: val('service-account') || 'freq-admin',
        service_password_source: val('service-pass-source') || 'secret',
        service_password: $('service-pass').value
      },
      fleet: {
        owned_vmids: val('owned-vmids'),
        template_vmids: val('template-vmids'),
        acknowledged_out_of_contract_vmids: val('ack-vmids'),
        core_devices: val('core-devices'),
        lab_devices: val('lab-devices'),
        hosts_import: $('hosts-import').value,
        device_credentials: collectDevices()
      },
      pdm: {
        mode: radioValue('pdm_mode'),
        root_pam_password: $('pdm-pass').value,
        remote_name: val('pdm-remote')
      },
      ssl: {
        mode: sslMode,
        defer_base_init_ssl: boolRadio('ssl_mode','defer'),
        adopt_existing: {
          base_domain: val('ssl-adopt-domain'),
          cert_source: val('ssl-adopt-source'),
          reverse_proxy_host: val('ssl-proxy-host'),
          cert_fullchain_path: val('ssl-fullchain-path'),
          cert_key_path: val('ssl-key-path'),
          target_hostnames: splitList(val('ssl-targets')),
          renewal_owner: 'external'
        },
        bootstrap_new: {
          base_domain: val('ssl-bootstrap-domain'),
          cloudflare_token_path: val('cloudflare-token-path'),
          target_hostnames: splitList(val('ssl-bootstrap-targets'))
        }
      }
    };
  }

  function validatePayload(payload){
    if(!payload.operator.username){return 'Operator username is required.';}
    if(!/^[a-z_][a-z0-9_-]{0,31}$/.test(payload.operator.username)){
      return 'Operator username must be lowercase with letters, numbers, underscores, or hyphens.';
    }
    if(!payload.operator.password){return 'Operator password or password file path is required.';}
    if(payload.operator.password_source !== 'path' && payload.operator.password.length < 8){return 'Operator password must be at least 8 characters.';}
    if(payload.operator.password_source !== 'path' && payload.operator.password !== $('operator-pass2').value){return 'Operator passwords do not match.';}
    if(!payload.cluster.cluster_name){return 'Cluster name is required for full init.';}
    if(!payload.cluster.pve_nodes.length){return 'At least one PVE node is required.';}
    if(!payload.ssh.bootstrap_secret){return 'Bootstrap secret is required so web init can reach the fleet.';}
    if(!payload.ssh.service_password){return 'Service account password or password file path is required.';}
    if(payload.ssh.service_password_source !== 'path' && payload.ssh.service_password.length < 8){return 'Service account password must be at least 8 characters.';}
    if(payload.ssl.mode === 'adopt-existing'){
      if(!payload.ssl.adopt_existing.base_domain){return 'Existing SSL adoption requires a base domain.';}
      if(payload.ssl.adopt_existing.cert_source === 'managed-paths' &&
        (!payload.ssl.adopt_existing.cert_fullchain_path || !payload.ssl.adopt_existing.cert_key_path)){
        return 'Existing SSL managed paths require both fullchain and key paths.';
      }
      if(payload.ssl.adopt_existing.cert_source === 'reverse-proxy' &&
        !payload.ssl.adopt_existing.reverse_proxy_host){
        return 'Existing SSL reverse-proxy mode requires the proxy host.';
      }
    }
    if(payload.ssl.mode === 'bootstrap-new'){
      if(!payload.ssl.bootstrap_new.base_domain){return 'New SSL bootstrap requires a base domain.';}
      if(!payload.ssl.bootstrap_new.cloudflare_token_path){return 'New SSL bootstrap requires the Cloudflare token path.';}
    }
    return '';
  }

  function postJson(url,payload){
    return fetch(url,{
      method:'POST',
      credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    }).then(function(r){
      return r.text().then(function(text){
        var data = {};
        try{data = text ? JSON.parse(text) : {};}catch(e){data = {raw:text};}
        if(!r.ok){
          var msg = url+' returned HTTP '+r.status;
          if(data && data.error){msg += ': '+data.error;}
          throw new Error(msg);
        }
        return data;
      });
    });
  }

  function ensureAdminSession(payload){
    appendLog('Creating first operator session via '+API.createAdmin+'.');
    return postJson(API.createAdmin,{
      username: payload.operator.username,
      password: payload.operator.password_source === 'path' ? '' : payload.operator.password,
      password_file: payload.operator.password_source === 'path' ? payload.operator.password : ''
    }).then(function(data){
      appendLog('Operator session ready: '+(data.user || payload.operator.username)+'.');
      return data;
    }).catch(function(err){
      appendLog('Operator create-admin did not complete: '+String(err.message || err));
      appendLog('Continuing to init/start; backend admin auth will be final truth.');
      return {warning:String(err.message || err)};
    });
  }

  function applySslChoice(payload){
    if(payload.ssl.mode === 'defer'){
      appendLog('SSL choice: deferred. Base init will not require SSL.');
      return Promise.resolve({ok:true,mode:'defer'});
    }
    if(payload.ssl.mode === 'adopt-existing'){
      appendLog('SSL choice: adopting existing ownership via '+API.certAdopt+'.');
      var adoptMode = payload.ssl.adopt_existing.cert_source === 'reverse-proxy' ? 'behind-proxy' : 'direct';
      var adoptTargets = certTargets(
        payload.ssl.adopt_existing.target_hostnames,
        payload.ssl.adopt_existing.base_domain,
        adoptMode
      );
      return postJson(API.certAdopt,{
        base_domain: payload.ssl.adopt_existing.base_domain,
        cert_fullchain_path: payload.ssl.adopt_existing.cert_source === 'managed-paths' ? payload.ssl.adopt_existing.cert_fullchain_path : '',
        cert_key_path: payload.ssl.adopt_existing.cert_source === 'managed-paths' ? payload.ssl.adopt_existing.cert_key_path : '',
        reverse_proxy_host: payload.ssl.adopt_existing.reverse_proxy_host,
        renewal_owner: payload.ssl.adopt_existing.renewal_owner,
        cert_targets: adoptTargets,
        targets: adoptTargets,
        replace: true,
        dry_run: false,
        infer_targets: true
      }).then(function(data){
        appendLog('Existing SSL target_source: '+(data.target_source || 'not returned')+'.');
        return data;
      });
    }
    appendLog('SSL choice: bootstrapping Cloudflare lifecycle via '+API.certBootstrap+'.');
    var bootstrapTargets = certTargets(
      payload.ssl.bootstrap_new.target_hostnames,
      payload.ssl.bootstrap_new.base_domain,
      'direct'
    );
    return postJson(API.certBootstrap,{
      base_domain: payload.ssl.bootstrap_new.base_domain,
      cloudflare_token_path: payload.ssl.bootstrap_new.cloudflare_token_path,
      cert_targets: bootstrapTargets,
      targets: bootstrapTargets,
      replace: true,
      dry_run: false
    }).then(function(data){
      appendLog('New SSL target_source: '+(data.target_source || 'not returned')+'.');
      return data;
    });
  }

  function refreshCertTruth(){
    return fetch(API.certReconcile,{credentials:'same-origin'}).then(function(r){return r.json();}).then(function(data){
      appendLog('SSL served-cert truth: '+JSON.stringify(data.summary || data));
      return data;
    }).catch(function(err){
      appendLog('SSL reconcile unavailable: '+String(err.message || err));
      return null;
    });
  }

  function refreshStatus(){
    fetch(API.status,{credentials:'same-origin'}).then(function(r){return r.json();}).then(function(data){
      $('setup-health').textContent = data.setup_health || 'unknown';
      $('setup-reason').textContent = data.setup_reason || 'No setup reason returned.';
      if(data.initialized){
        progressState.textContent = 'configured';
        progressPhase.textContent = 'initialized marker present';
      }
    }).catch(function(err){
      $('setup-health').textContent = 'unreachable';
      $('setup-reason').textContent = String(err);
    });
  }

  function handleStart(evt){
    evt.preventDefault();
    setError('');
    var payload = collectPayload();
    var invalid = validatePayload(payload);
    if(invalid){setError(invalid);return;}

    var btn = $('start-init');
    btn.disabled = true;
    btn.textContent = 'Starting...';
    progressState.textContent = 'starting';
    progressPhase.textContent = 'posting init contract';
    phaseLog.textContent = '';
    appendLog('Collected zero-state-web-init-v1 payload in browser.');
    appendLog('Posting to '+API.start+'.');

    ensureAdminSession(payload).then(function(){
      return applySslChoice(payload);
    }).then(function(){
      return refreshCertTruth();
    }).then(function(){
      appendLog('Posting full init start payload to '+API.start+'.');
      return postJson(API.start,collectStartPayload(payload));
    }).then(function(data){
      progressState.textContent = data.state || 'running';
      progressPhase.textContent = data.phase || 'init runner accepted';
      appendLog('Backend accepted init run: '+JSON.stringify(data));
      pollRun();
    }).catch(function(err){
      progressState.textContent = 'blocked';
      progressPhase.textContent = 'backend contract missing';
      var msg = String(err.message || err);
      if(msg.indexOf(API.start) !== -1){
        msg += '. Required: accept the flat zero-state-web-init-v1 payload, stage browser-entered secrets to 0600 temp files/vault, launch freq init --headless, expose '+API.runStatus+' with {running,job:{state,pid,lines,returncode,initialized}}, then mark success only when /api/setup/status reports initialized/configured.';
      }
      setError(msg);
      appendLog('BLOCKER: '+String(err.message || err));
      btn.disabled = false;
      btn.textContent = 'Start Web Init';
    });
  }

  function pollRun(){
    fetch(API.runStatus,{credentials:'same-origin'}).then(function(r){return r.json();}).then(function(data){
      progressState.textContent = data.state || 'running';
      progressPhase.textContent = data.phase || '';
      if(data.log_tail){phaseLog.textContent = data.log_tail.join ? data.log_tail.join('\n') : String(data.log_tail);}
      if(data.state === 'complete'){
        refreshStatus();
        refreshCertTruth();
        $('start-init').textContent = 'Init Complete';
        return;
      }
      if(data.state === 'failed' || data.blocker){
        setError(data.blocker || data.error || 'Init failed. See phase log.');
        $('start-init').disabled = false;
        $('start-init').textContent = 'Start Web Init';
        return;
      }
      window.setTimeout(pollRun, 2000);
    }).catch(function(err){
      progressState.textContent = 'blocked';
      progressPhase.textContent = 'progress endpoint missing';
      setError('Missing progress endpoint '+API.runStatus+': '+String(err));
      $('start-init').disabled = false;
      $('start-init').textContent = 'Start Web Init';
    });
  }

  document.addEventListener('click',function(evt){
    var action = evt.target && evt.target.getAttribute('data-action');
    if(action === 'add-node'){addNode({});}
    if(action === 'add-device'){addDevice({});}
    if(action === 'remove-row'){
      var row = evt.target.closest('.list-row');
      if(row){row.remove();}
    }
  });
  document.querySelectorAll('input[name="ssl_mode"]').forEach(function(el){
    el.addEventListener('change',showSslFields);
  });
  $('refresh-status').addEventListener('click',refreshStatus);
  form.addEventListener('submit',handleStart);

  addNode({name:'pve01',ip:''});
  addDevice({});
  showSslFields();
  refreshStatus();
})();
