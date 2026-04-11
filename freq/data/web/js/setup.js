var step=0,adminUser='',adminCreated=false,clusterConfigured=false,keyGenerated=false;
function _esc(s){if(!s)return '';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}

function show(s){
  document.querySelectorAll('.pane').forEach(function(p){p.classList.remove('active')});
  document.getElementById('pane-'+s).classList.add('active');
  for(var i=0;i<4;i++){
    var d=document.getElementById('dot-'+i);
    d.className='step-dot'+(i<s?' done':'')+(i===s?' active':'');
  }
}

function err(s,msg){document.getElementById('err-'+s).textContent=msg}

function nextStep(){
  err(step,'');
  if(step===0){
    var u=document.getElementById('s-user').value.trim();
    var p=document.getElementById('s-pass').value;
    var p2=document.getElementById('s-pass2').value;
    if(!u){err(0,'Username required');return}
    if(u.length<2||!/^[a-z_][a-z0-9_-]*$/.test(u)){err(0,'Lowercase letters, numbers, hyphens only');return}
    if(!p||p.length<8){err(0,'Password must be at least 8 characters');return}
    if(p!==p2){err(0,'Passwords do not match');return}
    var btn=document.querySelector('#pane-0 .btn');btn.disabled=true;btn.textContent='Creating...';
    fetch('/api/setup/create-admin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})})
    .then(function(r){return r.json()}).then(function(d){
      btn.disabled=false;btn.textContent='Create Account';
      if(d.error){err(0,d.error);return}
      adminUser=u;adminCreated=true;step=1;show(1);
    }).catch(function(e){btn.disabled=false;btn.textContent='Create Account';err(0,'Request failed: '+e)});
    return;
  }
  if(step===1){
    var cluster=document.getElementById('s-cluster').value.trim();
    var tz=document.getElementById('s-tz').value.trim()||'UTC';
    var nodes=document.getElementById('s-nodes').value.trim();
    
    fetch('/api/setup/configure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cluster_name:cluster,timezone:tz,pve_nodes:nodes?nodes.split(',').map(function(s){return s.trim()}):[]})}).then(function(r){return r.json()}).then(function(d){
      if(d.error){err(1,d.error);return}
      clusterConfigured=true;step=2;show(2);checkKey();
    }).catch(function(e){err(1,'Request failed: '+e)});
    return;
  }
  if(step===2){step=3;show(3);renderSummary();return}
}

function prevStep(){if(step>0){step--;show(step)}}

function checkKey(){
  fetch('/api/setup/status').then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('key-status');
    if(d.ssh_key_exists){
      el.innerHTML='<div class="ok">SSH key already exists at '+_esc(d.ssh_key_path)+'</div>';
      keyGenerated=true;
      document.getElementById('btn-keygen').textContent='Key Exists';
      document.getElementById('btn-keygen').disabled=true;
    } else {
      el.innerHTML='<div style="color:var(--dim);font-size:12px">No SSH key found. Click "Generate SSH Key" to create one.</div>';
    }
  });
}

function genKey(){
  var btn=document.getElementById('btn-keygen');btn.disabled=true;btn.textContent='Generating...';
  fetch('/api/setup/generate-key',{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.error){err(2,d.error);btn.disabled=false;btn.textContent='Generate SSH Key';return}
    keyGenerated=true;
    document.getElementById('key-status').innerHTML='<div class="ok">SSH keypair generated: '+_esc(d.key_path)+'</div>';
    btn.textContent='Key Generated';
  }).catch(function(e){err(2,'Failed: '+e);btn.disabled=false;btn.textContent='Generate SSH Key'});
}

function renderSummary(){
  var s='<span class="check">&#10003;</span> Admin account: <b>'+adminUser+'</b> (admin role)\n';
  if(clusterConfigured){
    var c=document.getElementById('s-cluster').value.trim();
    var tz=document.getElementById('s-tz').value.trim()||'UTC';
    if(c)s+='<span class="check">&#10003;</span> Cluster: <b>'+c+'</b>\n';
    s+='<span class="check">&#10003;</span> Timezone: <b>'+tz+'</b>\n';
  }
  s+='<span class="check">&#10003;</span> SSH key: '+(keyGenerated?'<b>configured</b>':'<b>skipped</b> (configure later)')+'\n';
  s+='\nNext steps:\n  - Add PVE nodes in System &gt; Config\n  - Add fleet hosts via freq host add\n  - Run freq doctor to verify';
  document.getElementById('summary').innerHTML=s;
}

function launch(){
  fetch('/api/setup/complete',{method:'POST'}).then(function(){window.location.href='/'}).catch(function(){window.location.href='/'});
}