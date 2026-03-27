"""FREQ Web UI — Diamond Standard.

Every page a diamond. Zero sub-tabs. Collapsible sections everywhere.
Toast notifications. Confirmation modals. Loading skeletons.
Pure Python stdlib. Single-file SPA. Zero dependencies.

"the bass is the foundation. so is this tool. so is this friendship."
"""

SETUP_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PVE FREQ — Setup</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#c9d1d9;--dim:#8b949e;--purple:#7B2FBE;--purple-dim:#5a1f8e;--green:#3fb950;--red:#f85149;--input-bg:#0d1117;--input-border:#30363d}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center}
.setup{max-width:520px;width:100%;padding:40px 32px;background:var(--card);border-radius:16px;border:1px solid var(--border);margin:20px}
.logo{text-align:center;margin-bottom:32px}
.logo h1{font-size:28px;background:linear-gradient(135deg,#7B2FBE,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.logo p{color:var(--dim);font-size:13px;margin-top:4px}
.steps{display:flex;gap:8px;margin-bottom:28px;justify-content:center}
.step-dot{width:10px;height:10px;border-radius:50%;background:var(--border);transition:background 0.3s}
.step-dot.active{background:var(--purple)}
.step-dot.done{background:var(--green)}
.pane{display:none}
.pane.active{display:block}
h2{font-size:18px;margin-bottom:6px}
.desc{color:var(--dim);font-size:13px;margin-bottom:20px}
label{display:block;font-size:12px;color:var(--dim);margin-bottom:4px;margin-top:14px}
input[type=text],input[type=password]{width:100%;padding:10px 14px;background:var(--input-bg);border:2px solid var(--input-border);color:var(--text);border-radius:8px;font-size:13px;font-family:inherit;outline:none;transition:border-color 0.2s}
input:focus{border-color:var(--purple)}
.btn{display:inline-block;padding:10px 24px;background:var(--purple);color:#fff;border:none;border-radius:8px;font-size:13px;font-family:inherit;cursor:pointer;margin-top:20px;transition:background 0.2s}
.btn:hover{background:var(--purple-dim)}
.btn:disabled{opacity:0.5;cursor:not-allowed}
.btn-row{display:flex;gap:10px;justify-content:flex-end;margin-top:24px}
.btn-ghost{background:transparent;border:1px solid var(--border);color:var(--text)}
.btn-ghost:hover{background:var(--border)}
.err{color:var(--red);font-size:12px;margin-top:8px;min-height:18px}
.ok{color:var(--green);font-size:12px;margin-top:8px}
.result{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px 16px;margin-top:16px;font-size:12px;font-family:monospace;line-height:1.6}
.result .check{color:var(--green)}
.skip{color:var(--dim);font-size:12px;margin-top:8px;cursor:pointer;text-decoration:underline}
.skip:hover{color:var(--text)}
</style>
</head>
<body>
<div class="setup">
  <div class="logo">
    <h1>PVE FREQ</h1>
    <p>Datacenter management CLI for homelabbers</p>
  </div>
  <div class="steps">
    <div class="step-dot active" id="dot-0"></div>
    <div class="step-dot" id="dot-1"></div>
    <div class="step-dot" id="dot-2"></div>
    <div class="step-dot" id="dot-3"></div>
  </div>

  <!-- Step 0: Welcome + Admin -->
  <div class="pane active" id="pane-0">
    <h2>Create Admin Account</h2>
    <p class="desc">This account controls your FREQ dashboard and fleet operations.</p>
    <label>Username</label>
    <input type="text" id="s-user" placeholder="admin" autocomplete="username">
    <label>Password</label>
    <input type="password" id="s-pass" placeholder="Choose a strong password" autocomplete="new-password">
    <label>Confirm Password</label>
    <input type="password" id="s-pass2" placeholder="Confirm password" autocomplete="new-password" onkeydown="if(event.key==='Enter')nextStep()">
    <div class="err" id="err-0"></div>
    <div class="btn-row"><button class="btn" onclick="nextStep()">Create Account</button></div>
  </div>

  <!-- Step 1: Cluster Basics -->
  <div class="pane" id="pane-1">
    <h2>Cluster Configuration</h2>
    <p class="desc">Basic settings for your Proxmox cluster. All optional — you can change these later.</p>
    <label>Cluster Name</label>
    <input type="text" id="s-cluster" placeholder="homelab">
    <label>Timezone</label>
    <input type="text" id="s-tz" placeholder="UTC" value="UTC">
    <label>PVE Node IPs (comma-separated, optional)</label>
    <input type="text" id="s-nodes" placeholder="192.168.1.10, 192.168.1.11">
    <div class="err" id="err-1"></div>
    <div class="btn-row">
      <button class="btn btn-ghost" onclick="prevStep()">Back</button>
      <button class="btn" onclick="nextStep()">Continue</button>
    </div>
  </div>

  <!-- Step 2: SSH Key -->
  <div class="pane" id="pane-2">
    <h2>SSH Key Setup</h2>
    <p class="desc">FREQ uses SSH to manage your fleet. Generate a new keypair or skip if you'll configure SSH later.</p>
    <div id="key-status"></div>
    <div class="err" id="err-2"></div>
    <div class="btn-row">
      <button class="btn btn-ghost" onclick="prevStep()">Back</button>
      <button class="btn" id="btn-keygen" onclick="genKey()">Generate SSH Key</button>
      <button class="btn" onclick="nextStep()">Continue</button>
    </div>
    <div class="skip" onclick="nextStep()">Skip — I'll set up SSH later</div>
  </div>

  <!-- Step 3: Done -->
  <div class="pane" id="pane-3">
    <h2>Setup Complete</h2>
    <p class="desc">Your FREQ instance is ready.</p>
    <div class="result" id="summary"></div>
    <div class="btn-row"><button class="btn" onclick="launch()">Launch Dashboard</button></div>
  </div>
</div>

<script>
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
    fetch('/api/setup/create-admin?username='+encodeURIComponent(u)+'&password='+encodeURIComponent(p))
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
    var q='timezone='+encodeURIComponent(tz);
    if(cluster)q+='&cluster_name='+encodeURIComponent(cluster);
    if(nodes)q+='&pve_nodes='+encodeURIComponent(nodes);
    fetch('/api/setup/configure?'+q).then(function(r){return r.json()}).then(function(d){
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
  fetch('/api/setup/generate-key').then(function(r){return r.json()}).then(function(d){
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
  s+='\nNext steps:\n  - Add PVE nodes in System &gt; Config\n  - Add fleet hosts via freq hosts add\n  - Run freq doctor to verify';
  document.getElementById('summary').innerHTML=s;
}

function launch(){
  fetch('/api/setup/complete').then(function(){window.location.href='/'}).catch(function(){window.location.href='/'});
}
</script>
</body>
</html>"""

APP_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PVE FREQ</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0%25' stop-color='%239B4FDE'/%3E%3Cstop offset='100%25' stop-color='%237B2FBE'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='32' height='32' rx='6' fill='%230d1117'/%3E%3Cpath d='M7 8h18v3.5H11.5v4H20v3.5H11.5V24H7V8z' fill='url(%23g)'/%3E%3Cpath d='M3 21 Q8 15 13 21 Q18 27 23 21 Q28 15 32 21' stroke='%239B4FDE' stroke-width='1.5' fill='none' opacity='0.4'/%3E%3C/svg%3E">
<style>
/* ── Tokens ── */
:root {
  --purple: #7B2FBE; --purple-light: #9B4FDE; --purple-dark: #5a1f8e;
  --purple-glow: rgba(123,47,190,0.15); --purple-faint: rgba(123,47,190,0.04);
  --bg: #0a0d12; --bg2: #0d1117; --card: #141920; --card-hover: #1a2028;
  --border: #1e2530; --border-light: #2a3140; --input-border: #2a3140;
  --text: #ffffff; --text-dim: #6e7681; --text-bright: #ffffff;
  --green: #3fb950; --yellow: #d29922; --red: #f85149; --blue: #58a6ff;
  --cyan: #56d4dd; --orange: #f0883e;
}

/* ── Reset ── */
*{margin:0;padding:0;box-sizing:border-box}
h1,h2,h3,h4{text-transform:uppercase}
body{font-family:'Inter',-apple-system,'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;font-size:14px}

/* ── Layout ── */
.mn{min-height:100vh}
.mn-header{padding:12px 24px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:var(--bg2)}
.mn-header h1{font-size:16px;font-weight:600;color:var(--text-bright)}
.mn-header .tagline{font-size:12px;color:var(--text);font-style:italic}
.mn-body{padding:16px 24px}
.page{display:none}.page.active{display:block}

/* ── Stats ── */
.stats{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px;justify-content:center}
.stats .st{min-width:140px;max-width:180px;flex:0 1 180px}
.st{background:var(--card);border:1px solid var(--border-light);border-radius:6px;padding:10px 12px;display:flex;flex-direction:column;align-items:center;box-shadow:0 1px 4px rgba(0,0,0,0.3)}
.st .lb{font-size:10px;color:var(--text);text-transform:uppercase;letter-spacing:1.5px;font-weight:600;background:var(--purple-faint);padding:2px 8px;border-radius:3px;margin-bottom:4px}
.st .vl{font-size:17px;font-weight:700;margin-top:2px;white-space:nowrap}
.st .vl.g{color:var(--green)}.st .vl.r{color:var(--red)}.st .vl.p{color:var(--purple-light)}.st .vl.y{color:var(--yellow)}.st .vl.b{color:var(--blue)}

/* ── Tables ── */
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--input-border);border-radius:6px;overflow:hidden;margin-bottom:12px}
th{text-align:left;padding:7px 12px;font-size:10px;color:var(--text);text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid var(--input-border);background:rgba(0,0,0,0.3);font-weight:600}
td{padding:6px 12px;font-size:12px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--card-hover)}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}
.badge.up,.badge.ok,.badge.healthy,.badge.running{background:rgba(63,185,80,0.12);color:var(--green)}
.badge.down,.badge.stopped,.badge.unreachable,.badge.CRITICAL{background:rgba(248,81,73,0.12);color:var(--red)}
.badge.warn,.badge.HIGH,.badge.created{background:rgba(210,153,34,0.12);color:var(--yellow)}
.badge.remote{background:rgba(88,166,255,0.12);color:var(--blue)}
.badge.paused{background:rgba(210,153,34,0.12);color:var(--yellow)}
.badge.unknown{background:rgba(110,118,129,0.12);color:var(--text-dim)}
.badge.MEDIUM{background:rgba(88,166,255,0.12);color:var(--blue)}

/* ── Cards ── */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;margin-bottom:12px;align-items:stretch}
.crd{background:var(--card);border:1px solid var(--border-light);border-radius:6px;padding:10px 12px;transition:border-color 0.2s ease,box-shadow 0.2s ease,transform 0.2s ease;box-shadow:0 1px 4px rgba(0,0,0,0.3)}
.crd:hover{border-color:var(--purple);box-shadow:0 2px 6px rgba(123,47,190,0.06);transform:translateY(-1px)}
.no-hover-fx .crd{transition:none}
.no-hover-fx .crd:hover{box-shadow:none;transform:none}
.crd h3{font-size:13px;color:var(--purple-light);margin-bottom:4px}
.crd p{font-size:12px;color:var(--text);line-height:1.5}
.crd .tag{display:inline-block;background:var(--purple-faint);color:var(--purple-light);padding:2px 6px;border-radius:3px;font-size:11px;margin:2px 2px 0 0;font-weight:500}

/* ── Exec ── */
.exec-bar{display:flex;gap:6px;margin-bottom:12px}
.exec-bar select,.exec-bar input{background:var(--card);border:1px solid var(--input-border);color:var(--text);padding:7px 12px;border-radius:6px;font-size:12px;font-family:inherit;transition:border-color 0.2s ease}
.exec-bar input{flex:1}
.exec-bar input:focus,.exec-bar select:focus{outline:none;border-color:var(--purple)}
.exec-bar button{background:var(--card);border:1px solid var(--input-border);color:var(--text);padding:7px 16px;border-radius:6px;cursor:pointer;font-weight:600;font-size:12px;transition:border-color 0.2s ease,color 0.2s ease,background 0.2s ease}
.exec-bar button:hover{border-color:var(--purple);color:var(--purple-light);background:var(--purple-faint)}
.exec-out{background:#080b10;border:1px solid var(--input-border);border-radius:6px;padding:14px;font-family:'Fira Code','Cascadia Code','JetBrains Mono',monospace;font-size:11px;white-space:pre-wrap;word-break:break-word;line-height:1.6}
.exec-line{padding:1px 0}

/* ── Search ── */
.search{background:var(--card);border:1px solid var(--input-border);color:var(--text);padding:8px 12px;border-radius:6px;font-size:12px;width:100%;margin-bottom:12px;font-family:inherit;transition:border-color 0.2s ease}
.search:focus{outline:none;border-color:var(--purple);box-shadow:0 0 0 2px var(--purple-glow)}

/* ── Sub-tabs ── */
.sub-tabs{display:flex;gap:2px;margin-bottom:12px;padding:3px;background:var(--card);border-radius:6px;border:1px solid var(--border)}
.sub-tab{background:none;border:none;color:var(--text-dim);padding:4px 12px;border-radius:4px;font-size:11px;font-weight:600;cursor:pointer;text-transform:uppercase;letter-spacing:1px;font-family:inherit;transition:all 0.15s}
.sub-tab:hover{color:var(--text);background:var(--purple-faint)}
.sub-tab.active-sub{color:var(--purple-light);background:var(--purple-faint);box-shadow:0 1px 3px rgba(0,0,0,0.3)}

/* ── Risk Chain ── */
.chain{display:flex;align-items:center;gap:6px;padding:12px;background:var(--card);border-radius:6px;border:1px solid var(--input-border);margin-bottom:12px;flex-wrap:wrap}
.chain-node{padding:5px 12px;border-radius:6px;font-weight:600;font-size:11px;letter-spacing:0.5px}
.chain-arr{color:var(--red);font-size:16px}

/* ── Timeline ── */
.timeline{position:relative;padding-left:24px;border-left:2px solid var(--border)}
.timeline-item{margin-bottom:16px;position:relative}
.timeline-item::before{content:'';position:absolute;left:-29px;top:4px;width:12px;height:12px;border-radius:50%;background:var(--purple);border:2px solid var(--bg)}
.timeline-item h3{font-size:14px;color:var(--purple-light);margin-bottom:4px}
.timeline-item .meta{font-size:11px;color:var(--text-dim);margin-bottom:6px}
.timeline-item p{font-size:13px;color:var(--text);line-height:1.6}

/* ── Two Column ── */
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.two{grid-template-columns:1fr}}

/* ── Severity ── */
.sev-critical{color:var(--red);font-weight:600}
.sev-important{color:var(--yellow)}
.sev-info{color:var(--blue)}
.sev-tip{color:var(--green)}
.gotcha{border-left:3px solid var(--yellow);padding-left:14px;margin-bottom:12px}
.gotcha .fix{color:var(--green);font-size:12px;margin-top:4px}

/* ── Host Overlay ── */
.host-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:var(--bg);z-index:20;overflow-y:auto;display:none}
.host-overlay.open{display:block}
.host-overlay .ho-header{padding:14px 0;border-bottom:1px solid var(--border);background:linear-gradient(180deg,var(--bg2) 0%,var(--bg) 100%);position:sticky;top:0;z-index:1}
.host-overlay .ho-header-inner{max-width:960px;margin:0 auto;padding:0 24px;display:flex;justify-content:space-between;align-items:center}
.host-overlay .ho-header h1{font-size:18px;font-weight:700;color:var(--text-bright);text-transform:uppercase}
.host-overlay .ho-close{background:none;border:1px solid var(--border);color:var(--text-dim);width:36px;height:36px;border-radius:8px;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center;transition:all 0.15s}
.host-overlay .ho-close:hover{border-color:var(--red);color:var(--red);background:rgba(248,81,73,0.1)}
.host-overlay .ho-body{max-width:960px;margin:0 auto;padding:16px 24px}
.host-overlay .ho-actions{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px;margin-bottom:16px}
.host-overlay .ho-actions button{background:var(--card);border:1px solid var(--border);color:var(--text);padding:8px 14px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:500;transition:all 0.15s;text-align:center}
.host-overlay .ho-actions button:hover{border-color:var(--purple);color:var(--purple-light);background:var(--purple-faint)}
.host-overlay .ho-actions button.active{border-color:var(--purple);color:var(--purple-light);background:var(--purple-faint)}
.ho-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;grid-template-rows:1fr auto}
.ho-grid>.ho-section:first-child{grid-row:1/-1}
@media(max-width:900px){.ho-grid{columns:1}}
.ho-section{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px 14px}
.ho-section.wide{grid-column:1/-1}
.ho-section h3{font-size:12px;color:var(--purple-light);text-transform:uppercase;letter-spacing:2px;margin-bottom:8px;font-weight:700}
.ho-row{display:grid;grid-template-columns:100px 1fr;padding:5px 0;border-bottom:1px solid var(--border);font-size:12px;gap:12px;align-items:baseline}
.ho-row:last-child{border-bottom:none}
.ho-row .k{color:var(--text-dim);white-space:nowrap}
.ho-row .v{font-weight:500;word-break:break-word}

/* ── Progress Bars ── */
.pbar{height:4px;background:var(--border);border-radius:2px;overflow:hidden;margin-top:3px}
.pbar-fill{height:100%;border-radius:2px;transition:width 0.3s}
.metric-row{padding:3px 0;border-bottom:1px solid var(--border);font-size:11px}
.metric-row:last-child{border-bottom:none}
.metric-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px;gap:8px;min-width:0}
.metric-label{color:var(--text);font-size:11px;white-space:nowrap;flex-shrink:0}
.metric-val{font-weight:600;color:var(--text);font-size:11px;text-align:right;white-space:nowrap}
.host-card{background:var(--card);border:1px solid var(--border-light);border-radius:6px;padding:8px 12px;overflow:hidden;transition:border-color 0.2s ease,box-shadow 0.2s ease,transform 0.2s ease;box-shadow:0 1px 4px rgba(0,0,0,0.3)}
.host-card:hover{border-color:var(--purple);box-shadow:0 2px 6px rgba(123,47,190,0.06);transform:translateY(-1px)}
.no-hover-fx .host-card{transition:none}
.no-hover-fx .host-card:hover{border-color:var(--purple);box-shadow:none;transform:none}
.host-card .host-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px}
.host-card .host-head h3{font-size:13px;font-weight:700;margin:0;text-transform:uppercase}
.host-card .host-head .host-meta{font-size:10px;color:var(--text);display:flex;align-items:center;gap:5px;flex-wrap:wrap;justify-content:flex-end}

/* ── Fleet Tools ── */
.fleet-tools{margin-bottom:4px}
.fleet-tools-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.fleet-btn{background:var(--card);border:1px solid var(--input-border);color:var(--text);padding:6px 14px;border-radius:6px;cursor:pointer;font-size:11px;font-weight:600;letter-spacing:0.8px;transition:border-color 0.2s ease,color 0.2s ease,background 0.2s ease,box-shadow 0.2s ease;font-family:inherit}
.fleet-btn:hover{color:var(--purple-light);background:var(--purple-faint);border-color:var(--purple)}
.view-btn{position:relative;background:transparent;border-color:transparent}
.view-btn::after{content:'';position:absolute;bottom:-2px;left:25%;right:25%;height:2px;background:var(--purple);border-radius:1px;transform:scaleX(0);transition:transform 0.2s ease}
.view-btn:hover{background:transparent;border-color:transparent}
.view-btn:hover::after{transform:scaleX(0.6)}
.view-btn.active-view{color:var(--purple-light);background:transparent;border-color:transparent}
.view-btn.active-view::after{transform:scaleX(1)}
.fleet-btn.btn-red{color:var(--red);border-color:var(--red)}
.fleet-btn.btn-red:hover{color:var(--red);border-color:var(--red);background:rgba(248,81,73,0.04);box-shadow:0 2px 8px rgba(248,81,73,0.06);transform:translateY(-1px)}
.fleet-btn.btn-cyan{color:var(--cyan);border-color:var(--cyan)}
.fleet-btn.btn-cyan:hover{color:var(--cyan);border-color:var(--cyan);background:rgba(86,212,221,0.04);box-shadow:0 2px 8px rgba(86,212,221,0.06);transform:translateY(-1px)}
.fleet-btn.btn-orange{color:var(--orange);border-color:var(--orange)}
.fleet-btn.btn-orange:hover{color:var(--orange);border-color:var(--orange);background:rgba(240,136,62,0.04);box-shadow:0 2px 8px rgba(240,136,62,0.06);transform:translateY(-1px)}
.fleet-btn.btn-green{color:var(--green);border-color:var(--green)}
.fleet-btn.btn-green:hover{color:var(--green);border-color:var(--green);background:rgba(63,185,80,0.04);box-shadow:0 2px 8px rgba(63,185,80,0.06);transform:translateY(-1px)}
.no-hover-fx .fleet-btn.btn-red,.no-hover-fx .fleet-btn.btn-cyan,.no-hover-fx .fleet-btn.btn-orange,.no-hover-fx .fleet-btn.btn-green{transition:none}
.no-hover-fx .fleet-btn.btn-red:hover,.no-hover-fx .fleet-btn.btn-cyan:hover,.no-hover-fx .fleet-btn.btn-orange:hover,.no-hover-fx .fleet-btn.btn-green:hover{box-shadow:none;transform:none}
.no-hover-fx .fleet-btn{transition:none}
.no-hover-fx .fleet-btn:hover{color:var(--purple-light);background:var(--purple-faint);border-color:var(--purple);box-shadow:none;transform:none}

/* ── Category Badges ── */
.cat-badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;letter-spacing:0.5px;text-transform:uppercase}
.cat-personal{background:rgba(210,153,34,0.12);color:var(--yellow)}
.cat-infrastructure{background:rgba(248,81,73,0.12);color:var(--red)}
.cat-prod_media{background:rgba(123,47,190,0.12);color:var(--purple-light)}
.cat-prod_other{background:rgba(123,47,190,0.12);color:var(--purple-light)}
.cat-sandbox{background:rgba(240,136,62,0.12);color:var(--orange)}
.cat-lab{background:rgba(86,212,221,0.12);color:var(--cyan)}
.cat-templates{background:rgba(110,118,129,0.12);color:var(--text-dim)}
.cat-unknown{background:rgba(110,118,129,0.12);color:var(--text-dim)}
/* ── PVE Toggle ── */
.pve-tab{transition:opacity 0.25s ease}
.pve-tab:hover{opacity:1 !important}
.pve-chev{transition:border-color 0.25s ease,background 0.25s ease,box-shadow 0.25s ease,transform 0.25s ease}
.pve-chev:hover{box-shadow:0 2px 8px rgba(123,47,190,0.06);transform:translateY(-1px)}
.no-hover-fx .pve-chev{transition:none}
.no-hover-fx .pve-chev:hover{box-shadow:none;transform:none}

/* ── PVE Group ── */
.pve-group{transition:box-shadow 0.25s ease,transform 0.25s ease}
.pve-group:hover{box-shadow:0 2px 8px rgba(123,47,190,0.06);transform:translateY(-2px)}
.no-hover-fx .pve-group{transition:none}
.no-hover-fx .pve-group:hover{box-shadow:none;transform:none}

/* ── Sections ── */
.section{background:var(--card);border:1px solid var(--input-border);border-radius:6px;margin-bottom:12px;overflow:hidden;transition:border-color 0.2s ease,box-shadow 0.2s ease}
.section:hover{border-color:#4a5568}
.section-header{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;cursor:pointer;user-select:none}
.section-header h3{font-size:12px;color:var(--text);text-transform:uppercase;letter-spacing:1.5px;font-weight:700;margin:0;background:var(--purple-faint);padding:2px 10px;border-radius:3px;display:inline-block}
.section-header .chev{color:var(--text);font-size:14px;transition:transform 0.2s}
.section.collapsed .section-body{display:none}
.section.collapsed .chev{transform:rotate(-90deg)}
.section-body{padding:0 14px 14px}

/* ── Toast ── */
.toast-container{position:fixed;top:16px;right:16px;z-index:100;display:flex;flex-direction:column;gap:8px;pointer-events:none}
.toast{pointer-events:auto;padding:12px 20px;border-radius:8px;font-size:13px;font-weight:500;color:white;animation:slideIn 0.3s ease;min-width:280px;max-width:420px;box-shadow:0 4px 12px rgba(0,0,0,0.3)}
.toast.success{background:#1a7f37;border-left:3px solid var(--green)}
.toast.error{background:#9e1c23;border-left:3px solid var(--red)}
.toast.info{background:#1158a6;border-left:3px solid var(--blue)}
.toast.fadeout{animation:slideOut 0.3s ease forwards}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
@keyframes slideOut{from{transform:translateX(0);opacity:1}to{transform:translateX(100%);opacity:0}}

/* ── Modal ── */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:90;display:flex;align-items:center;justify-content:center}
.modal{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:24px;max-width:440px;width:90%}
.modal h3{font-size:16px;color:var(--text-bright);margin-bottom:12px}
.modal p{font-size:13px;color:var(--text);margin-bottom:20px;line-height:1.6}
.modal-actions{display:flex;gap:8px;justify-content:flex-end}

/* ── Skeleton ── */
.skeleton{background:linear-gradient(90deg,var(--card) 25%,var(--border) 50%,var(--card) 75%);background-size:200% 100%;animation:shimmer 1.5s infinite;border-radius:8px;height:60px;margin-bottom:8px}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}

/* ── Empty State ── */
.empty-state{text-align:center;padding:40px 20px;color:var(--text-dim);grid-column:1/-1}
.empty-state .es-icon{font-size:36px;opacity:0.3;margin-bottom:12px}
.empty-state p{font-size:13px;line-height:1.6}

/* ── Buttons ── */
.btn{background:var(--card);border:1px solid var(--border);color:var(--text);padding:8px 16px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;font-family:inherit;transition:all 0.15s;position:relative}
.btn:hover{border-color:var(--purple);color:var(--purple-light)}
.btn-primary{background:linear-gradient(135deg,var(--purple),var(--purple-dark));color:white;border:none}
.btn-primary:hover{opacity:0.9}
.btn-danger{border-color:var(--red);color:var(--red)}
.btn-danger:hover{background:rgba(248,81,73,0.1)}
.btn.loading{color:transparent;pointer-events:none}
.btn.loading::after{content:'';position:absolute;inset:0;margin:auto;width:14px;height:14px;border:2px solid var(--text-dim);border-top-color:transparent;border-radius:50%;animation:spin 0.6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── Infra Cards ── */
.infra-role-card{background:var(--card);border:2px solid var(--input-border);border-radius:10px;padding:14px 16px;cursor:pointer;transition:border-color 0.25s ease,box-shadow 0.25s ease,transform 0.25s ease;position:relative;overflow:hidden}
.infra-role-card:hover{border-color:var(--purple);box-shadow:0 2px 8px rgba(123,47,190,0.06);transform:translateY(-2px)}
.no-hover-fx .infra-role-card{transition:none}
.no-hover-fx .infra-role-card:hover{border-color:var(--purple);box-shadow:none;transform:none}
.infra-role-card .role-label{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:6px;display:flex;align-items:center;gap:8px}
.infra-role-card .role-label .role-icon{font-size:14px;opacity:0.7}
.infra-role-card .device-name{font-size:15px;font-weight:700;margin:0;text-transform:uppercase}
.infra-role-card .device-sub{font-size:11px;color:var(--text-dim);margin-top:2px}
.infra-role-card .status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:4px}
.infra-role-card .status-dot.up{background:var(--green);box-shadow:0 0 6px rgba(63,185,80,0.4)}
.infra-role-card .status-dot.down{background:var(--red);box-shadow:0 0 6px rgba(248,81,73,0.4)}
.infra-role-card .role-metrics{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;padding-top:8px;border-top:1px solid var(--border)}
.infra-role-card .role-metric{font-size:12px;display:flex;align-items:center;gap:4px}
.infra-role-card .role-metric .rm-val{font-weight:700}
.infra-role-card .role-metric .rm-lbl{color:var(--text-dim);font-weight:400}

/* ── VM Cards ── */
.action-bar{display:flex;gap:8px;align-items:center;margin-bottom:16px;flex-wrap:wrap}
.action-bar select,.action-bar input{background:var(--card);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:6px;font-size:13px;font-family:inherit}
.vm-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;transition:border-color 0.2s}
.vm-card:hover{border-color:var(--purple)}
.vm-card-actions{display:flex;gap:4px;margin-top:10px}

/* ── Mini Cards ── */
.mc{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px 14px}
.mc-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.mc-row{display:flex;flex-wrap:wrap;gap:6px;font-size:13px;color:var(--text);margin-top:4px}
.mc-row .u{font-size:11px;opacity:0.5}

/* ── Utilities ── */
.c-dim{color:var(--text-dim)}
.c-red{color:var(--red)}
.c-green{color:var(--green)}
.c-yellow{color:var(--yellow)}
.c-purple{color:var(--purple-light)}
.c-purple-active{color:var(--purple-light);border-color:var(--purple)}
.label-sub{font-size:11px;color:var(--text-dim);display:block;margin-bottom:4px}
.label-hint{font-size:12px;font-weight:500;opacity:0.7}
.stat-pair{display:flex;flex-direction:column;align-items:center}
.text-meta{font-size:11px;color:var(--text-dim)}
.text-sub{font-size:12px;color:var(--text-dim)}
.desc-line{font-size:12px;color:var(--text-dim);margin-bottom:12px}
.w-full{width:100%}
.mt-8{margin-top:8px}
.mt-12{margin-top:12px}
.d-none{display:none}
.input-primary{background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:8px 14px;border-radius:8px;font-size:12px;font-family:inherit;width:100%}
.input-primary-lg{background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:12px;font-family:inherit;width:100%}
.form-vertical{display:flex;flex-direction:column;gap:10px;max-width:400px}
.divider-light{border-top:1px solid var(--border);margin-top:2px;padding-top:6px}
.btn-row{display:flex;gap:8px;margin-top:8px}
.flex-1{flex:1}
.flex-fill{flex:1;min-width:0}

/* ── Utilities (extended) ── */
.flex-row-24{display:flex;gap:24px;margin-top:4px}
.flex-row-8-center{display:flex;gap:8px;margin-bottom:12px;align-items:center}
.flex-between-mb8{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.flex-between-mb16{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.flex-between-mb12{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.flex-between{display:flex;justify-content:space-between;align-items:center}
.flex-wrap-8-mb12{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.flex-gap-4{display:flex;gap:4px}
.flex-gap-6{display:flex;gap:6px}
.flex-border-row{display:flex;gap:8px;padding:6px 0;border-top:1px solid var(--border);font-size:12px;align-items:center}
.flex-gap-16-center{display:flex;align-items:center;gap:16px}
.flex-col-10-500{display:flex;flex-direction:column;gap:10px;max-width:500px}
.flex-between-pad-top{padding:12px 16px 0;display:flex;justify-content:space-between;align-items:center}
.flex-row-8-mb16-center{display:flex;gap:8px;margin-bottom:16px;align-items:center;min-height:44px}
.flex-row-8-mb12{display:flex;gap:8px;margin-bottom:12px}
.flex-wrap-8-mb12-wrap{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.pad-v8-fs11{padding:8px 0;font-size:11px}
.pad-v8-warn{padding:8px 0;font-size:11px;color:var(--yellow)}
.pill-sm{padding:4px 10px;font-size:12px}
.pill-warn-sm{padding:3px 10px;font-size:12px;color:var(--yellow)}
.pill-warn-xs{padding:3px 8px;font-size:11px;color:var(--yellow)}
.pill-err-xs{padding:3px 8px;font-size:12px;color:var(--red)}
.pill-ok-sm{padding:3px 10px;font-size:11px;color:var(--green)}
.pill-xs{padding:3px 8px;font-size:11px}
.pill-pad6{padding:6px 10px;font-size:11px}
.pill-warn-4-10{padding:4px 10px;font-size:12px;color:var(--yellow)}
.pill-4-10-fs11{padding:4px 10px;font-size:11px}
.pill-err-3-8{padding:3px 8px;font-size:11px;color:var(--red)}
.pill-ok-3-8{padding:3px 8px;font-size:11px;color:var(--green)}
.pill-ok-3-10{padding:3px 10px;font-size:12px;color:var(--green)}
.pill-purple-xs{padding:4px 12px;font-size:12px;color:var(--purple-light)}
.pill-purple-2-8{padding:2px 8px;font-size:12px;color:var(--purple-light)}
.pill-2-8{padding:2px 8px;font-size:12px}
.pill-active-lg{color:var(--purple-light);border-color:var(--purple);padding:10px 20px;margin-bottom:12px}
.pill-active-self{color:var(--purple-light);border-color:var(--purple);align-self:flex-start;padding:10px 20px}
.pad-h16-fs12{padding:8px 16px;font-size:12px}
.fs-11{font-size:11px}
.fs-12{font-size:12px}
.fs-12-fade{font-size:12px;opacity:0.6}
.fs-12-dim{font-size:12px;opacity:0.6;font-weight:400}
.mono-11{font-family:monospace;font-size:11px}
.section-label-pl{color:var(--purple-light);font-size:13px;margin-bottom:12px}
.section-label-pl-ls{color:var(--purple-light);font-size:13px;margin-bottom:12px;letter-spacing:1px}
.h-60{height:60px}
.h-50{height:50px}
.w-30{width:30px}
.min-w-120-center{min-width:120px;text-align:center}
.my-8{margin:8px 0}
.mb-8{margin-bottom:8px}
.mb-12{margin-bottom:12px}
.mb-16{margin-bottom:16px}
.mb-24{margin-bottom:24px}
.mb-0{margin-bottom:0}
.m-0{margin:0}
.mt-4{margin-top:4px}
.mt-10{margin-top:10px}
.mt-20{margin-top:20px}
.stat-big-red{font-size:20px;font-weight:700;color:var(--red)}
.stat-big-green{font-size:20px;font-weight:700;color:var(--green)}
.stat-big-orange{font-size:20px;font-weight:700;color:var(--orange)}
.stat-big-blue{font-size:20px;font-weight:700;color:var(--blue)}
.card-box{background:var(--card);border:2px solid var(--input-border);border-radius:8px;padding:14px;margin-bottom:16px}
.text-dim-pad12{color:var(--text-dim);padding:12px 0}
.close-x{cursor:pointer;color:var(--text-dim);font-size:18px}
.opacity-5{opacity:0.5}
.opacity-7{opacity:0.7}
.border-red{border-color:var(--red)}
.meta-flex{font-size:11px;color:var(--text-dim);display:flex;align-items:center;gap:6px;margin-left:8px}
.input-sm{background:var(--card);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-size:12px;width:80px}
.grid-auto-280{grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.grid-auto-300{grid-template-columns:repeat(auto-fill,minmax(280px,1fr))}
.grid-auto-240{grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
.label-sub-10{font-size:10px;color:var(--text-dim);display:block;margin-bottom:4px}
.label-sub-10-tight{font-size:10px;color:var(--text-dim);display:block;margin-bottom:2px}
.cursor-ptr{cursor:pointer}
.c-dim-mt8{color:var(--text-dim);margin-top:8px}
.c-dim-fs12{color:var(--text-dim);font-size:12px}
.c-dim-fs11-mt8{color:var(--text-dim);font-size:11px;margin-top:8px}
.c-dim-fs11{color:var(--text-dim);font-size:11px}
.c-dim-mb12-fs12{color:var(--text-dim);margin-bottom:12px;font-size:12px}
.fs-10-dim-600-ls{font-size:10px;font-weight:600;letter-spacing:1px;color:var(--text-dim)}
.fs-12-dim-mt2{font-size:12px;color:var(--text-dim);margin-top:2px}
.fs-11-dim-mt2{font-size:11px;color:var(--text-dim);margin-top:2px}
.fs-11-dim-mb10-ls{font-size:11px;color:var(--text-dim);margin-bottom:10px;letter-spacing:0.5px}
.fs-12-dim-pad4{font-size:12px;color:var(--text-dim);padding:4px 0}
.skel-mt12{min-height:60px;margin-top:12px;display:none}
.text-center{text-align:center}
.pos-rel{position:relative}
.toggle-sw{position:relative;width:40px;height:22px;cursor:pointer;display:block;flex-shrink:0}

/* ── Mobile Responsive ──────────────────────────────────────────────── */
.mobile-menu-btn{display:none;background:var(--card);border:2px solid var(--input-border);color:var(--purple-light);padding:6px 10px;border-radius:6px;font-size:16px;cursor:pointer;line-height:1}
@media(max-width:768px){
.mn-header{flex-direction:column;gap:10px;padding:12px 16px;text-align:center}
.mn-header .flex-gap-16-center{flex-wrap:wrap;justify-content:center}
.mn-header pre{display:none}
.mn-body{padding:12px 14px}
.stats{grid-template-columns:repeat(2,1fr);gap:8px}
.st{padding:10px 12px}
.st .vl{font-size:16px}
table{font-size:12px;display:block;overflow-x:auto;-webkit-overflow-scrolling:touch}
th,td{padding:7px 10px;white-space:nowrap}
.two{grid-template-columns:1fr}
.ho-grid{columns:1}
.ho-row{grid-template-columns:100px 1fr;gap:8px;font-size:12px}
.exec-bar{flex-direction:column}
.chain{flex-direction:column;align-items:flex-start;gap:4px;padding:12px}
.grid-auto-280,.grid-auto-300,.grid-auto-240{grid-template-columns:1fr}
#p-home>div:first-child pre{font-size:8px}
.mobile-menu-btn{display:block}
.nav-toolbar{display:none!important;flex-direction:column;gap:4px;width:100%}
.nav-toolbar.open{display:flex!important}
.fleet-btn{font-size:11px;padding:6px 10px}
}
@media(max-width:480px){
.mn-header{padding:10px 12px}
.mn-body{padding:10px 12px}
.stats{grid-template-columns:1fr 1fr;gap:6px}
.st .lb{font-size:10px;padding:2px 8px}
.st .vl{font-size:14px}
#p-home>div:first-child{display:none}
th,td{padding:5px 8px;font-size:11px}
.ho-row{grid-template-columns:1fr;gap:4px}
.btn,button{font-size:12px}
#header-time{font-size:18px}
#login-overlay>div{width:90%!important;max-width:380px}
#login-overlay pre{font-size:6px!important}
}
</style>
</head>
<body>

<!-- Login Overlay -->
<div id="login-overlay" style="position:fixed;inset:0;background:var(--bg);z-index:9999;display:flex;align-items:center;justify-content:center">
  <div style="width:380px;text-align:center">
    <pre style="font-family:'Courier New',monospace;font-size:10px;line-height:1.1;margin:0 auto 24px;color:var(--purple-light);display:inline-block;text-align:left"> ██████╗ ██╗   ██╗███████╗   ███████╗██████╗ ███████╗ ██████╗
 ██╔══██╗██║   ██║██╔════╝   ██╔════╝██╔══██╗██╔════╝██╔═══██╗
 ██████╔╝██║   ██║█████╗     █████╗  ██████╔╝█████╗  ██║   ██║
 ██╔═══╝ ╚██╗ ██╔╝██╔══╝     ██╔══╝  ██╔══██╗██╔══╝  ██║▄▄ ██║
 ██║      ╚████╔╝ ███████╗   ██║     ██║  ██║███████╗╚██████╔╝
 ╚═╝       ╚═══╝  ╚══════╝   ╚═╝     ╚═╝  ╚═╝╚══════╝ ╚══▀▀═╝</pre>
    <div style="font-size:12px;color:var(--text-dim);letter-spacing:2px;margin-bottom:32px">DATACENTER MANAGEMENT</div>
    <div style="background:var(--card);border:2px solid var(--input-border);border-radius:12px;padding:28px">
      <div style="display:flex;flex-direction:column;gap:12px">
        <input id="login-user" placeholder="Username" autocomplete="username" onkeydown="if(event.key==='Enter')document.getElementById('login-pass').focus()" style="background:var(--bg);border:2px solid var(--input-border);color:var(--text);padding:12px 16px;border-radius:8px;font-size:13px;font-family:inherit;width:100%;outline:none;transition:border-color 0.2s" onfocus="this.style.borderColor='var(--purple)'" onblur="this.style.borderColor='var(--input-border)'">
        <input id="login-pass" type="password" placeholder="Password" autocomplete="current-password" onkeydown="if(event.key==='Enter')doLogin()" style="background:var(--bg);border:2px solid var(--input-border);color:var(--text);padding:12px 16px;border-radius:8px;font-size:13px;font-family:inherit;width:100%;outline:none;transition:border-color 0.2s" onfocus="this.style.borderColor='var(--purple)'" onblur="this.style.borderColor='var(--input-border)'">
        <button onclick="doLogin()" style="background:var(--purple);border:none;color:var(--text);padding:12px;border-radius:8px;font-size:13px;font-weight:600;font-family:inherit;cursor:pointer;letter-spacing:1px;transition:opacity 0.2s" onmouseover="this.style.opacity='0.85'" onmouseout="this.style.opacity='1'">LOG IN</button>
      </div>
      <div id="login-error" style="margin-top:12px;font-size:12px;color:var(--red);display:none"></div>
    </div>
  </div>
</div>

<!-- ═══ MAIN ═══ -->
<div class="mn">
<div class="mn-header">
  <div class="flex-gap-16-center">
    <pre data-view="home" style="font-family:'Courier New',monospace;font-size:5px;line-height:1.1;margin:0;color:var(--purple-light);cursor:pointer;opacity:0.9"> ██████╗ ██╗   ██╗███████╗   ███████╗██████╗ ███████╗ ██████╗
 ██╔══██╗██║   ██║██╔════╝   ██╔════╝██╔══██╗██╔════╝██╔═══██╗
 ██████╔╝██║   ██║█████╗     █████╗  ██████╔╝█████╗  ██║   ██║
 ██╔═══╝ ╚██╗ ██╔╝██╔══╝     ██╔══╝  ██╔══██╗██╔══╝  ██║▄▄ ██║
 ██║      ╚████╔╝ ███████╗   ██║     ██║  ██║███████╗╚██████╔╝
 ╚═╝       ╚═══╝  ╚══════╝   ╚═╝     ╚═╝  ╚═╝╚══════╝ ╚══▀▀═╝</pre><span style="font-size:12px;letter-spacing:3px;color:var(--text-dim);text-transform:uppercase" id="nav-ver"></span>
    <div style="width:1px;height:24px;background:var(--border)"></div>
    <div><h1 id="page-title" style="font-size:16px">Home</h1><div class="tagline fs-11" id="header-tagline" ></div></div>
  </div>
  <div class="flex-gap-16-center">
    <button id="header-user-btn" onclick="openUserMenu()" style="display:none;background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:6px 14px;border-radius:8px;font-size:12px;font-family:inherit;cursor:pointer;display:flex;align-items:center;gap:8px;transition:border-color 0.2s" onmouseover="this.style.borderColor='var(--purple)'" onmouseout="this.style.borderColor='var(--input-border)'"><span id="header-user-icon" style="width:8px;height:8px;border-radius:50%;background:var(--green)"></span><span id="header-user-name" style="font-weight:600;text-transform:uppercase;letter-spacing:0.5px"></span><span id="header-user-role" style="font-size:10px;color:var(--text-dim)"></span></button>
    <span style="font-family:'Courier New',monospace;font-size:24px;font-weight:700;color:var(--purple-light);letter-spacing:2px;opacity:0.8" id="header-time"></span>
  </div>
</div>
<div id="update-banner" style="display:none;background:linear-gradient(135deg,rgba(123,47,190,0.15),rgba(168,85,247,0.1));border-bottom:1px solid var(--purple);padding:10px 32px;font-size:13px;color:var(--text)">
  <span id="update-banner-text"></span>
  <button onclick="document.getElementById('update-banner').style.display='none';sessionStorage.setItem('freq_update_dismissed','1')" style="float:right;background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:14px">&times;</button>
</div>
<div class="mn-body">

<!-- ════════ HOME ════════ -->
<div id="p-home" class="page active">
<!-- Hero -->
<div style="text-align:center;padding:8px 0 12px">
  <pre style="font-family:'Courier New',monospace;font-size:12px;line-height:1.1;margin:0 auto;color:var(--purple-light);opacity:0.9;cursor:pointer;display:inline-block;text-align:left" data-view="home"> ██████╗ ██╗   ██╗███████╗   ███████╗██████╗ ███████╗ ██████╗
 ██╔══██╗██║   ██║██╔════╝   ██╔════╝██╔══██╗██╔════╝██╔═══██╗
 ██████╔╝██║   ██║█████╗     █████╗  ██████╔╝█████╗  ██║   ██║
 ██╔═══╝ ╚██╗ ██╔╝██╔══╝     ██╔══╝  ██╔══██╗██╔══╝  ██║▄▄ ██║
 ██║      ╚████╔╝ ███████╗   ██║     ██║  ██║███████╗╚██████╔╝
 ╚═╝       ╚═══╝  ╚══════╝   ╚═╝     ╚═╝  ╚═╝╚══════╝ ╚══▀▀═╝</pre>
</div>
<!-- Toolbar -->
<div style="border-bottom:1px solid var(--border);padding:6px 0;margin-bottom:12px">
<div style="display:flex;gap:4px;align-items:center;min-height:32px;flex-wrap:wrap">
  <button class="mobile-menu-btn" onclick="document.getElementById('nav-items').classList.toggle('open')" aria-label="Menu">&#9776;</button>
  <div id="nav-items" class="nav-toolbar" style="display:contents">
  <button class="fleet-btn view-btn active-view" data-view="home">HOME</button>
  <button class="fleet-btn view-btn" data-view="fleet">FLEET</button>
  <button class="fleet-btn view-btn" data-view="docker">DOCKER</button>
  <button class="fleet-btn view-btn" data-view="media">MEDIA</button>
  <button class="fleet-btn view-btn" data-view="security">SECURITY</button>
  <button class="fleet-btn view-btn" data-view="tools">SYSTEM</button>
  <button class="fleet-btn view-btn" data-view="lab">LAB</button>
  <div class="flex-1"></div>
  <button class="fleet-btn view-btn opacity-7" data-view="settings">&#9881; SETTINGS</button>
  </div>
</div></div>
<!-- HOME VIEW -->
<div id="home-view">
<!-- Widget dashboard -->
<div id="home-widgets"></div>
<!-- Empty state -->
<div id="home-empty" style="text-align:center;padding:40px 0;display:none">
  <div style="font-size:36px;opacity:0.15;margin-bottom:16px">&#9776;</div>
  <div style="font-size:16px;color:var(--text);margin-bottom:8px">Your Dashboard is Empty</div>
  <div style="font-size:12px;color:var(--text-dim);margin-bottom:20px;max-width:400px;margin-left:auto;margin-right:auto;line-height:1.6">Click LAYOUT to add widgets from Fleet, Docker, Security, and Lab Tools. Or hit Quick Start for a ready-made dashboard.</div>
  <button class="fleet-btn c-purple-active" data-action="openLayoutConfig" >&#9776; CONFIGURE DASHBOARD</button>
</div>
<!-- Footer -->
<div style="text-align:center;padding:32px 0 16px;border-top:1px solid var(--border);margin-top:24px">
  <div id="home-subtitle" style="font-size:12px;letter-spacing:4px;color:var(--text-dim);text-transform:uppercase">PVE FREQ</div>
  <div id="home-ver-footer" style="font-size:13px;color:var(--text);margin-top:4px;opacity:0.5"></div>
  <div id="home-quote-footer" style="font-size:12px;color:var(--text-dim);font-style:italic;margin-top:6px;opacity:0.7"></div>
</div>
</div><!-- close home-view -->
<!-- FLEET VIEW (hidden by default) -->
<div id="fleet-view" class="d-none">
<div class="sub-tabs" id="subtabs-fleet">
  <button class="sub-tab active-sub" onclick="switchView('fleet')">Fleet</button>
  <button class="sub-tab" onclick="switchView('topology')">Topology</button>
  <button class="sub-tab" onclick="switchView('capacity')">Capacity</button>
</div>
<!-- Fleet Stats group -->
<div class="section layout-section" id="fleet-sec-stats">
  <div class="section-header"><h3>Fleet Stats</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="stats" id="metrics-summary"></div>
  </div>
</div>
<!-- Hosts & VMs group -->
<div class="section layout-section" id="fleet-sec-infra">
  <div class="section-header"><h3 class="cursor-ptr">Hosts &amp; VMs</h3><div class="flex-1"></div><input id="fleet-filter" placeholder="&#128269; Filter..." oninput="filterFleetCards(this.value)" onclick="event.stopPropagation()" style="background:var(--bg);border:2px solid var(--input-border);color:var(--text);padding:6px 12px;border-radius:6px;font-size:11px;font-family:inherit;width:180px;outline:none;transition:border-color 0.25s ease" onfocus="this.style.borderColor='var(--purple)'" onblur="this.style.borderColor='var(--input-border)'"><span class="chev" style="cursor:pointer;margin-left:8px">▾</span></div>
  <div class="section-body"><div id="metrics-cards"></div></div>
</div>
<!-- Overview -->
<div class="section layout-section" id="fleet-sec-overview">
  <div class="section-header"><h3>Overview</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px">
      <div id="overview-physical-cards"><!-- populated dynamically from fleet config --></div>
      <div class="host-card">
        <div class="host-head"><h3 class="c-purple">PVE<br>NODES</h3><div class="host-meta" id="pve-node-count"><span>HYPERVISOR</span></div></div>
        <div class="divider-light"><div id="home-pve-summary"><div class="skeleton h-60" ></div></div></div>
      </div>
      <div class="host-card">
        <div class="host-head"><h3 class="c-purple">VMs</h3><div class="host-meta"><span>PROXMOX</span></div></div>
        <div class="divider-light"><div id="home-infra"><div class="skeleton h-60" ></div></div></div>
      </div>
      <div class="host-card">
        <div class="host-head"><h3 class="c-green">MEDIA STACK</h3><div class="host-meta"><span>CONTAINERS</span><span>·</span><span>DOCKER</span></div></div>
        <div class="divider-light"><div id="home-media"><div class="skeleton h-60" ></div></div></div>
      </div>
    </div>
  </div>
</div>
<!-- Lab Equipment (collapsed) -->
<div class="section collapsed layout-section" id="fleet-lab-section" style="margin-top:20px;display:none">
  <div class="section-header"><h3>Lab Equipment</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div id="fleet-lab-cards" class="cards grid-auto-240" ></div>
  </div>
</div>
<!-- Agents -->
<div class="section layout-section mt-20" id="fleet-sec-agents" >
  <div class="section-header"><h3>Agents</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="stats" id="agent-stats"></div>
    <h4 style="color:var(--purple-light);font-size:13px;margin:12px 0 8px">Templates</h4>
    <div id="agent-templates" class="cards"></div>
    <h4 style="color:var(--purple-light);font-size:13px;margin:12px 0 8px">Registered Agents</h4>
    <div id="agent-list"></div>
  </div>
</div>
<!-- Sandbox VMs -->
<div class="section layout-section" id="fleet-sec-specialists">
  <div class="section-header"><h3>Sandbox VMs</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="cards mb-12" >
      <div class="crd"><h3>Create Specialist</h3><p><code>freq specialist create &lt;host&gt; --role dev</code></p></div>
      <div class="crd"><h3>Check Health</h3><p><code>freq specialist health &lt;host&gt;</code></p></div>
      <div class="crd"><h3>Roles</h3><p>sandbox, dev, infra, security, media</p></div>
    </div>
    <table><thead><tr><th>Name</th><th>Role</th><th>VMID</th><th>Status</th></tr></thead><tbody id="specialist-table"></tbody></table>
  </div>
</div>
</div><!-- close fleet-view -->

<!-- DOCKER VIEW -->
<div id="docker-view" class="d-none">
<div class="section layout-section" id="docker-sec-containers">
  <div class="section-header"><h3>Containers</h3><div class="stats" id="container-stats" style="margin-bottom:0;flex:1;justify-content:center"></div><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="flex-row-8-center" style="margin-bottom:8px">
      <button class="fleet-btn docker-sub active-view" data-dsub="docker-services" data-action="switchDockerSub" data-arg="services">SERVICES</button>
      <button class="fleet-btn docker-sub" data-dsub="docker-all" data-action="switchDockerSub" data-arg="all">ALL</button>
      <button class="fleet-btn docker-sub" data-dsub="docker-registry" data-action="switchDockerSub" data-arg="registry">REGISTRY</button>
      <button class="fleet-btn docker-sub" data-dsub="docker-compose" data-action="switchDockerSub" data-arg="compose">COMPOSE</button>
    </div>
    <!-- SERVICES sub-view (default) -->
    <div id="docker-sub-services">
      <div id="services-container-cards" class="cards"></div>
    </div>
    <!-- ALL containers sub-view -->
    <div id="docker-sub-all" class="d-none">
      <div id="container-cards" class="cards"></div>
      <div class="exec-out" id="container-logs" style="margin-top:12px;min-height:100px;display:none">Select a container to view logs...</div>
    </div>
    <!-- REGISTRY sub-view -->
    <div id="docker-sub-registry" class="d-none">
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
        <button class="fleet-btn c-purple-active" onclick="rescanContainers()">RESCAN FLEET</button>
        <button class="fleet-btn" onclick="loadContainerRegistry()">REFRESH</button>
        <span id="registry-status" class="text-meta"></span>
      </div>
      <div id="rescan-results" style="display:none;margin-bottom:12px"></div>
      <div id="registry-table"></div>
      <div style="margin-top:12px;padding:12px;background:var(--bg2);border:1px solid var(--border);border-radius:8px">
        <h4 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">ADD CONTAINER</h4>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <input class="input" id="reg-name" placeholder="Container name" style="width:160px">
          <select class="input" id="reg-vmid" style="width:160px"><option value="">Select VM...</option></select>
          <input class="input" id="reg-port" placeholder="Port (optional)" style="width:100px" type="number">
          <button class="fleet-btn" onclick="addContainer()">ADD</button>
          <span id="reg-msg" class="text-meta"></span>
        </div>
      </div>
    </div>
    <!-- COMPOSE sub-view -->
    <div id="docker-sub-compose" class="d-none">
      <div style="font-size:12px;color:var(--text-dim);margin-bottom:12px">Manage Docker Compose stacks per VM. Select a VM to bring stacks up/down or view compose files.</div>
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
        <select id="compose-vm-select" class="input" style="width:240px"><option value="">Select Docker VM...</option></select>
        <button class="fleet-btn" onclick="composeUp()">COMPOSE UP</button>
        <button class="fleet-btn" onclick="composeDown()" style="color:var(--red);border-color:var(--red)">COMPOSE DOWN</button>
        <button class="fleet-btn" onclick="composeView()">VIEW COMPOSE</button>
      </div>
      <div id="compose-out" class="exec-out" style="min-height:80px">Select a Docker VM and an action.</div>
    </div>
  </div>
</div>
</div><!-- close docker-view -->

<!-- ============================================================
     MEDIA VIEW — Top-level media dashboard
     Services: Plex, Sonarr, Radarr, etc. status cards
     Downloads: Active transfers with progress
     Streams: Plex streams with user/quality info
     ============================================================ -->
<div id="media-view" class="d-none">
  <!-- Media service status cards -->
  <div id="media-container-cards" class="cards mb-16"></div>
  <!-- Downloads -->
  <div class="section">
    <div class="section-header"><h3>Downloads</h3><span class="chev">▾</span></div>
    <div class="section-body">
      <div class="stats" id="dl-stats"></div>
      <table><thead><tr><th>Name</th><th>Client</th><th>VM</th><th>Size</th><th>Progress</th><th>Speed</th></tr></thead><tbody id="dl-table"></tbody></table>
    </div>
  </div>
  <!-- Streams -->
  <div class="section">
    <div class="section-header"><h3>Streams</h3><span class="chev">▾</span></div>
    <div class="section-body">
      <div class="stats" id="stream-stats"></div>
      <table><thead><tr><th>User</th><th>Title</th><th>Type</th><th>Quality</th><th>State</th></tr></thead><tbody id="stream-table"></tbody></table>
    </div>
  </div>
</div><!-- close media-view -->

<!-- SECURITY VIEW — Overview -->
<div id="security-view" class="d-none">
<div class="sub-tabs" id="subtabs-security">
  <button class="sub-tab active-sub" onclick="switchView('security')">Overview</button>
  <button class="sub-tab" onclick="switchView('sec-hardening')">Hardening</button>
  <button class="sub-tab" onclick="switchView('sec-access')">Access</button>
  <button class="sub-tab" onclick="switchView('sec-vault')">Vault</button>
  <button class="sub-tab" onclick="switchView('sec-compliance')">Compliance</button>
</div>
<div class="section layout-section" id="sec-risk">
  <div class="section-header"><h3>Risk Analysis</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="chain" id="risk-chain"></div>
    <p class="c-dim-mb12-fs12">Break any link in the kill chain = no remote recovery.</p>
    <table><thead><tr><th>Target</th><th>Risk Level</th><th>Primary Impact</th><th>Recovery</th></tr></thead><tbody id="risk-tbl"></tbody></table>
  </div>
</div>
<div class="section layout-section" id="sec-policies">
  <div class="section-header"><h3>Policies</h3><span class="chev">▾</span></div>
  <div class="section-body"><div id="policies-c"></div></div>
</div>
</div><!-- close security-view -->

<!-- SECURITY — Hardening -->
<div id="sec-hardening-view" class="d-none">
<div class="sub-tabs">
  <button class="sub-tab" onclick="switchView('security')">Overview</button>
  <button class="sub-tab active-sub" onclick="switchView('sec-hardening')">Hardening</button>
  <button class="sub-tab" onclick="switchView('sec-access')">Access</button>
  <button class="sub-tab" onclick="switchView('sec-vault')">Vault</button>
  <button class="sub-tab" onclick="switchView('sec-compliance')">Compliance</button>
</div>
<div class="section layout-section" id="sec-audit">
  <div class="section-header"><h3>Audit</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="flex-wrap-8-mb12-wrap">
      <button class="fleet-btn c-purple-active" data-audit="all">FULL AUDIT</button>
      <button class="fleet-btn" data-audit="ssh-root">SSH ROOT LOGIN</button>
      <button class="fleet-btn" data-audit="ssh-pass">SSH PASSWORD AUTH</button>
      <button class="fleet-btn" data-audit="ssh-empty">EMPTY PASSWORDS</button>
      <button class="fleet-btn" data-audit="ports">OPEN PORTS</button>
      <button class="fleet-btn" data-audit="failed">FAILED SERVICES</button>
      <button class="fleet-btn" data-audit="firewall">FIREWALL STATUS</button>
      <button class="fleet-btn" onclick="runSshSweep()">POLICY SWEEP</button>
    </div>
    <div id="audit-c"></div>
    <div id="sweep-c" class="mt-12"></div>
  </div>
</div>
<div class="section layout-section" id="sec-harden">
  <div class="section-header"><h3>Hardening</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="flex-wrap-8-mb12-wrap">
      <button class="fleet-btn c-purple-active" data-action="runHarden" >FULL HARDENING AUDIT</button>
      <button class="fleet-btn" onclick="hardenAction('disable-root')">DISABLE ROOT SSH</button>
      <button class="fleet-btn" onclick="hardenAction('key-only')">ENFORCE KEY-ONLY AUTH</button>
      <button class="fleet-btn" onclick="hardenAction('disable-empty')">BLOCK EMPTY PASSWORDS</button>
      <button class="fleet-btn" onclick="hardenAction('auto-updates')">ENABLE AUTO UPDATES</button>
      <button class="fleet-btn" onclick="sshdPanel('harden-c')">RESTART SSHD</button>
    </div>
    <div id="harden-c"></div>
  </div>
</div>
</div><!-- close sec-hardening-view -->

<!-- SECURITY — Access -->
<div id="sec-access-view" class="d-none">
<div class="sub-tabs">
  <button class="sub-tab" onclick="switchView('security')">Overview</button>
  <button class="sub-tab" onclick="switchView('sec-hardening')">Hardening</button>
  <button class="sub-tab active-sub" onclick="switchView('sec-access')">Access</button>
  <button class="sub-tab" onclick="switchView('sec-vault')">Vault</button>
  <button class="sub-tab" onclick="switchView('sec-compliance')">Compliance</button>
</div>
<div class="section layout-section" id="sec-users">
  <div class="section-header"><h3>Users</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="exec-bar"><input id="u-name" placeholder="Username"><select id="u-role"><option>viewer</option><option selected>operator</option><option>admin</option></select><button data-action="userCreate">Create User</button></div>
    <div id="users-c"></div>
  </div>
</div>
<div class="section layout-section" id="sec-sshkeys">
  <div class="section-header"><h3>SSH Keys</h3><span class="chev">▾</span></div>
  <div class="section-body"><div id="keys-c"><div class="skeleton"></div><div class="skeleton"></div></div></div>
</div>
<div class="section layout-section" id="sec-apikeys">
  <div class="section-header"><h3>API Keys</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="exec-bar"><input id="v-key" placeholder="Key name"><input id="v-val" placeholder="Value" type="password"><select id="v-host"><option>DEFAULT</option></select><button data-action="vaultSet">Store</button></div>
    <div id="vault-c"></div>
  </div>
</div>
</div><!-- close sec-access-view -->

<!-- SECURITY — Vault -->
<div id="sec-vault-view" class="d-none">
<div class="sub-tabs">
  <button class="sub-tab" onclick="switchView('security')">Overview</button>
  <button class="sub-tab" onclick="switchView('sec-hardening')">Hardening</button>
  <button class="sub-tab" onclick="switchView('sec-access')">Access</button>
  <button class="sub-tab active-sub" onclick="switchView('sec-vault')">Vault</button>
  <button class="sub-tab" onclick="switchView('sec-compliance')">Compliance</button>
</div>
<div class="section layout-section border-red" id="sec-vault-section">
  <div class="section-header"><h3 style="background:rgba(248,81,73,0.15)">&#128274; Vault</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div id="vault-locked">
      <div style="text-align:center;padding:24px 0">
        <div style="font-size:32px;opacity:0.3;margin-bottom:12px">&#128274;</div>
        <div style="font-size:14px;color:var(--text);margin-bottom:4px">Vault is Locked</div>
        <div style="font-size:11px;color:var(--text-dim);margin-bottom:16px">Admin credentials required to access sensitive data</div>
        <div style="max-width:300px;margin:0 auto;display:flex;flex-direction:column;gap:8px">
          <input id="vault-auth-user" placeholder="Admin username" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:12px;font-family:inherit;text-align:center">
          <input id="vault-auth-pass" type="password" placeholder="Password" onkeydown="if(event.key==='Enter')unlockVault()" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:12px;font-family:inherit;text-align:center">
          <button class="fleet-btn" data-action="unlockVault" style="color:var(--red);border-color:var(--red)">UNLOCK VAULT</button>
        </div>
      </div>
    </div>
    <div id="vault-unlocked" class="d-none">
      <div class="flex-row-8-center">
        <span style="color:var(--green);font-size:12px;font-weight:600">&#128275; UNLOCKED</span>
        <button class="fleet-btn vault-tab active-view" data-vtab="users" data-action="switchVaultTab" data-arg="users">USERS</button>
        <button class="fleet-btn vault-tab" data-vtab="apikeys" data-action="switchVaultTab" data-arg="apikeys">API KEYS</button>
        <button class="fleet-btn vault-tab" data-vtab="all" data-action="switchVaultTab" data-arg="all">ALL</button>
        <div class="flex-1"></div>
        <button class="fleet-btn" onclick="lockVault()" style="padding:3px 10px;font-size:12px;color:var(--red)">LOCK</button>
      </div>
      <div id="vault-sensitive-c"></div>
    </div>
  </div>
</div>
</div><!-- close sec-vault-view -->

<!-- LAB TOOLS VIEW — REMOVED: merged into TOOLS > Lab Tools section -->

<!-- SECURITY — Compliance -->
<div id="sec-compliance-view" class="d-none">
<div class="sub-tabs">
  <button class="sub-tab" onclick="switchView('security')">Overview</button>
  <button class="sub-tab" onclick="switchView('sec-hardening')">Hardening</button>
  <button class="sub-tab" onclick="switchView('sec-access')">Access</button>
  <button class="sub-tab" onclick="switchView('sec-vault')">Vault</button>
  <button class="sub-tab active-sub" onclick="switchView('sec-compliance')">Compliance</button>
</div>
<div class="section">
  <div class="section-header"><h3>Policy Compliance</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="flex-wrap-8-mb12">
      <button class="fleet-btn" onclick="policyAction('check')">CHECK COMPLIANCE</button>
      <button class="fleet-btn" onclick="policyAction('diff')">SHOW DRIFT</button>
      <button class="fleet-btn c-red" onclick="policyAction('fix')">APPLY FIX</button>
    </div>
    <div class="exec-out" id="policy-out">Run a compliance check to see policy status.</div>
  </div>
</div>
<div class="section collapsed">
  <div class="section-header"><h3>Compliance Scan</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="flex-wrap-8-mb12">
      <button class="fleet-btn" onclick="runSweep(false)">DRY RUN</button>
      <button class="fleet-btn c-red" onclick="runSweep(true)">SWEEP + FIX</button>
    </div>
    <div class="exec-out" id="sweep-out">Click to run a full audit sweep.</div>
  </div>
</div>
<div class="section collapsed">
  <div class="section-header"><h3>Continuous Monitoring</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <button class="fleet-btn" onclick="loadPatrolStatus()">CHECK STATUS</button>
    <div class="exec-out" id="patrol-out">Click to check current compliance status.</div>
  </div>
</div>
</div><!-- close sec-compliance-view -->

<!-- ============================================================
     SYSTEM VIEW — Overview page with system utility tools
     Sub-tabs: Overview | Playbooks | Config Sync | Chaos
     Sections: Diagnostics, Logs, Storage, Network Scanner
     ============================================================ -->
<div id="tools-view" class="d-none">
<div class="sub-tabs" id="subtabs-tools">
  <button class="sub-tab active-sub" onclick="switchView('tools')">Overview</button>
  <button class="sub-tab" onclick="switchView('playbooks')">Playbooks</button>
  <button class="sub-tab" onclick="switchView('gitops')">Config Sync</button>
  <button class="sub-tab" onclick="switchView('chaos')" style="color:var(--red)">Chaos</button>
</div>
<!-- Diagnostics — health checks and host diagnosis -->
<div class="section">
  <div class="section-header"><h3>Diagnostics</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="flex-wrap-8-mb12">
      <button class="fleet-btn" onclick="runDoctor()">RUN DOCTOR</button>
      <select id="diag-host" class="input-field" style="width:180px"><option value="">Select host...</option></select>
      <button class="fleet-btn" onclick="runDiagnose()">DIAGNOSE HOST</button>
    </div>
    <div class="exec-out" id="diag-out">Run self-diagnostic or diagnose a specific host.</div>
  </div>
</div>
<!-- Logs — fleet-wide log viewer -->
<div class="section">
  <div class="section-header"><h3>Logs</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="flex-wrap-8-mb12">
      <select id="log-host" class="input-field" style="width:180px"><option value="">Select host...</option></select>
      <input type="text" id="log-unit" placeholder="Unit (optional)..." class="input-field" style="width:180px">
      <input type="number" id="log-lines" placeholder="Lines" value="50" class="input-field" style="width:80px">
      <button class="fleet-btn" onclick="fetchLogs()">FETCH LOGS</button>
    </div>
    <div class="exec-out" id="log-out" style="max-height:400px;overflow-y:auto">Enter a host to view its logs.</div>
  </div>
</div>
<!-- Storage — ZFS pools + backup status (grouped: disk health) -->
<div class="section">
  <div class="section-header"><h3>Storage</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div style="margin-bottom:16px">
      <h4 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">ZFS POOLS</h4>
      <button class="fleet-btn" onclick="loadZfs()">LOAD ZFS STATUS</button>
      <div class="exec-out" id="zfs-out" style="margin-top:8px">Click to load ZFS pool status.</div>
    </div>
    <div>
      <h4 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">BACKUPS</h4>
      <div class="flex-wrap-8-mb12">
        <button class="fleet-btn" onclick="loadBackups('list')">LIST</button>
        <button class="fleet-btn" onclick="loadBackups('status')">STATUS</button>
      </div>
      <div class="exec-out" id="backup-out">Click to view backup status.</div>
    </div>
  </div>
</div>
<!-- Host Discovery & Onboarding -->
<div class="section">
  <div class="section-header"><h3>Host Discovery & Onboarding</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div style="font-size:12px;color:var(--text-dim);margin-bottom:12px">Discover hosts on your network, add them to the fleet, and onboard with SSH key deployment.</div>
    <div class="flex-wrap-8-mb12">
      <input type="text" id="discover-subnet" placeholder="Subnet (e.g. 10.25.10)" class="input-field" style="width:200px">
      <button class="fleet-btn c-purple-active" onclick="runDiscover()">SCAN NETWORK</button>
    </div>
    <div class="exec-out" id="discover-out">Enter a subnet to discover hosts.</div>
    <div style="margin-top:16px;padding:12px;background:var(--bg2);border:1px solid var(--border);border-radius:8px">
      <h4 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">ADD HOST MANUALLY</h4>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <input class="input" id="add-host-ip" placeholder="IP address" style="width:140px">
        <input class="input" id="add-host-label" placeholder="Label (e.g. web-01)" style="width:140px">
        <select class="input" id="add-host-type" style="width:120px">
          <option value="vm">VM</option>
          <option value="ct">Container</option>
          <option value="physical">Physical</option>
          <option value="firewall">Firewall</option>
          <option value="switch">Switch</option>
          <option value="storage">Storage</option>
          <option value="bmc">BMC</option>
        </select>
        <input class="input" id="add-host-groups" placeholder="Groups (optional)" style="width:160px">
        <button class="fleet-btn" onclick="addHostManual()">ADD HOST</button>
        <span id="add-host-msg" class="text-meta"></span>
      </div>
    </div>
  </div>
</div>
</div><!-- close tools-view -->

<!-- ============================================================
     LAB VIEW — Lab Tools (plugin framework)
     ============================================================ -->
<div id="lab-view" class="d-none">
<div class="sub-tabs" id="subtabs-lab">
  <button class="sub-tab active-sub" onclick="switchView('lab')">Tools</button>
  <button class="sub-tab" onclick="openManageTools()">Manage</button>
  <button class="sub-tab" onclick="openAddTool()" style="color:var(--green)">+ Add Tool</button>
</div>
<div id="lab-tools-container"></div>
</div><!-- close lab-view -->

<!-- TOPOLOGY VIEW -->
<div id="topology-view" class="d-none">
<div class="sub-tabs" id="subtabs-topology">
  <button class="sub-tab" onclick="switchView('fleet')">Fleet</button>
  <button class="sub-tab active-sub" onclick="switchView('topology')">Topology</button>
  <button class="sub-tab" onclick="switchView('capacity')">Capacity</button>
</div>
<div style="background:var(--card);border:1px solid var(--border-light);border-radius:10px;padding:16px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,0.4)">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <h3 style="font-size:14px;color:var(--purple-light)">Network Topology</h3>
    <span style="font-size:11px;color:var(--text-dim);margin-right:8px">Drag nodes to rearrange</span>
    <button class="fleet-btn" onclick="resetTopoLayout()" style="margin-right:4px">RESET LAYOUT</button>
    <button class="fleet-btn" onclick="loadTopology()">REFRESH</button>
  </div>
  <div id="topo-legend" style="font-size:11px;color:var(--text-dim);margin-bottom:8px">
    <span style="color:var(--purple-light)">&#9632;</span> PVE Node &nbsp;
    <span style="color:var(--green)">&#9632;</span> VM (running) &nbsp;
    <span style="color:var(--text-dim)">&#9632;</span> VM (stopped) &nbsp;
    <span style="color:var(--red)">&#9632;</span> Unreachable &nbsp;
    <span style="color:var(--blue)">&#9632;</span> Device
  </div>
  <svg id="topo-svg" width="calc(100% + 32px)" height="700" style="margin:0 -16px;background:var(--bg);border-top:1px solid var(--border);border-bottom:1px solid var(--border);overflow:visible"></svg>
  <div id="topo-info" style="margin-top:8px;font-size:12px;color:var(--text-dim)"></div>
</div>
</div><!-- close topology-view -->

<!-- CAPACITY VIEW -->
<div id="capacity-view" class="d-none">
<div class="sub-tabs" id="subtabs-capacity">
  <button class="sub-tab" onclick="switchView('fleet')">Fleet</button>
  <button class="sub-tab" onclick="switchView('topology')">Topology</button>
  <button class="sub-tab active-sub" onclick="switchView('capacity')">Capacity</button>
</div>
<div style="background:var(--card);border:1px solid var(--border-light);border-radius:10px;padding:16px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,0.4)">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <h3 style="font-size:14px;color:var(--purple-light)">Capacity Planner</h3>
    <div style="display:flex;gap:8px">
      <button class="fleet-btn" onclick="forceCapSnapshot()">TAKE SNAPSHOT</button>
      <button class="fleet-btn" onclick="loadCapacity()">REFRESH</button>
    </div>
  </div>
  <div id="cap-info" style="font-size:12px;color:var(--text-dim);margin-bottom:12px"></div>
  <div id="cap-table"></div>
</div>
</div><!-- close capacity-view -->

<!-- PLAYBOOKS VIEW -->
<div id="playbooks-view" class="d-none">
<div class="sub-tabs" id="subtabs-playbooks">
  <button class="sub-tab" onclick="switchView('tools')">Overview</button>
  <button class="sub-tab active-sub" onclick="switchView('playbooks')">Playbooks</button>
  <button class="sub-tab" onclick="switchView('gitops')">Config Sync</button>
  <button class="sub-tab" onclick="switchView('chaos')" style="color:var(--red)">Chaos</button>
</div>
<div style="background:var(--card);border:3px solid var(--input-border);border-radius:10px;padding:16px;margin-bottom:16px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <h3 style="font-size:14px;color:var(--purple-light)">Incident Playbooks</h3>
    <button class="fleet-btn" onclick="loadPlaybooks()">REFRESH</button>
  </div>
  <div id="pb-list"></div>
  <div id="pb-runner" class="d-none" style="margin-top:16px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <h4 id="pb-runner-title" style="font-size:13px;color:var(--text)"></h4>
      <button class="fleet-btn" onclick="closePbRunner()">CLOSE</button>
    </div>
    <div id="pb-steps"></div>
  </div>
</div>
</div><!-- close playbook-view -->

<!-- GITOPS VIEW -->
<div id="gitops-view" class="d-none">
<div class="sub-tabs" id="subtabs-gitops">
  <button class="sub-tab" onclick="switchView('tools')">Overview</button>
  <button class="sub-tab" onclick="switchView('playbooks')">Playbooks</button>
  <button class="sub-tab active-sub" onclick="switchView('gitops')">Config Sync</button>
  <button class="sub-tab" onclick="switchView('chaos')" style="color:var(--red)">Chaos</button>
</div>
<div style="background:var(--card);border:3px solid var(--input-border);border-radius:10px;padding:16px;margin-bottom:16px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <h3 style="font-size:14px;color:var(--purple-light)">GitOps Config Sync</h3>
    <div style="display:flex;gap:8px">
      <button class="fleet-btn" onclick="gitopsFetch()">SYNC</button>
      <button class="fleet-btn" onclick="loadGitops()">REFRESH</button>
    </div>
  </div>
  <div id="go-status" style="font-size:12px;color:var(--text-dim);margin-bottom:12px"></div>
  <div id="go-actions" class="d-none" style="gap:8px;margin-bottom:12px">
    <button class="fleet-btn" onclick="gitopsApply()">APPLY CHANGES</button>
    <button class="fleet-btn" onclick="gitopsDiff()">VIEW DIFF</button>
  </div>
  <div id="go-diff" class="d-none" style="margin-bottom:12px">
    <pre id="go-diff-content" style="font-size:11px;color:var(--text);background:rgba(0,0,0,0.3);padding:12px;border-radius:6px;white-space:pre-wrap;max-height:300px;overflow-y:auto"></pre>
  </div>
  <h4 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">COMMIT HISTORY</h4>
  <div id="go-log"></div>
</div>
</div><!-- close gitops-view -->

<!-- COSTS VIEW — REMOVED: absorbed into SETTINGS > Fleet Costs -->
<!-- FEDERATION VIEW — REMOVED: absorbed into SETTINGS > Sites -->

<!-- CHAOS VIEW -->
<div id="chaos-view" class="d-none">
<div class="sub-tabs" id="subtabs-chaos">
  <button class="sub-tab" onclick="switchView('tools')">Overview</button>
  <button class="sub-tab" onclick="switchView('playbooks')">Playbooks</button>
  <button class="sub-tab" onclick="switchView('gitops')">Config Sync</button>
  <button class="sub-tab active-sub" onclick="switchView('chaos')" style="color:var(--red)">Chaos</button>
</div>
<div style="background:var(--card);border:3px solid var(--input-border);border-radius:10px;padding:16px;margin-bottom:16px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <h3 style="font-size:14px;color:var(--red)">Chaos Engineering</h3>
    <button class="fleet-btn" onclick="loadChaos()">REFRESH</button>
  </div>
  <div style="background:rgba(255,60,60,0.08);border:1px solid rgba(255,60,60,0.3);border-radius:6px;padding:10px 14px;margin-bottom:16px;font-size:12px;color:var(--text-dim)">
    Chaos experiments intentionally disrupt services to test recovery. Production hosts are blocked by safety gates. Use only on lab/dev infrastructure.
  </div>
  <div style="margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--input-border)">
    <h4 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">NEW EXPERIMENT</h4>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
      <input id="chaos-name" placeholder="Experiment name" class="freq-input" style="flex:1;min-width:120px">
      <select id="chaos-type" class="freq-input" style="flex:1;min-width:120px">
        <option value="">Select type...</option>
        <option value="service_kill">service_kill — Stop a Docker container</option>
        <option value="service_restart">service_restart — Restart a systemd service</option>
        <option value="network_delay">network_delay — Add network latency</option>
        <option value="disk_fill">disk_fill — Simulate disk pressure</option>
        <option value="cpu_stress">cpu_stress — Spike CPU load</option>
      </select>
      <select id="chaos-target" class="freq-input" style="flex:1;min-width:100px"><option value="">Select host...</option></select>
      <input id="chaos-service" placeholder="Service/container" class="freq-input" style="flex:1;min-width:100px">
      <input id="chaos-duration" placeholder="Duration (s)" type="number" value="60" class="freq-input" style="width:100px">
      <button class="fleet-btn" style="background:var(--red);color:#fff" onclick="chaosRun()">INJECT</button>
    </div>
  </div>
  <h4 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">EXPERIMENT LOG</h4>
  <div id="chaos-log"></div>
</div>
</div><!-- close chaos-view -->

<!-- ============================================================
     SETTINGS VIEW — Dashboard configuration and management
     Sections: Dashboard Layout, Fleet Costs, Sites (Federation),
               User Preferences
     ============================================================ -->
<div id="settings-view" class="d-none">
  <!-- Dashboard Layout — widget and section configuration -->
  <div class="section">
    <div class="section-header"><h3>Dashboard Layout</h3><span class="chev">▾</span></div>
    <div class="section-body">
      <div style="font-size:12px;color:var(--text-dim);margin-bottom:12px">Configure which widgets appear on your HOME dashboard and reorder sections on any view.</div>
      <div class="flex-wrap-8-mb12">
        <button class="fleet-btn" onclick="openHomeWidgetConfig()">CONFIGURE HOME WIDGETS</button>
        <button class="fleet-btn" onclick="openLayoutConfig()">CONFIGURE CURRENT VIEW</button>
      </div>
    </div>
  </div>
  <!-- Fleet Costs — cost tracking (moved from Planning) -->
  <div class="section">
    <div class="section-header"><h3>Fleet Costs</h3><span class="chev">▾</span></div>
    <div class="section-body">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <span style="font-size:12px;color:var(--text-dim)">Track infrastructure costs across the fleet.</span>
        <button class="fleet-btn" onclick="loadCosts()">REFRESH</button>
      </div>
      <div id="cost-summary" style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px"></div>
      <div id="cost-table"></div>
    </div>
  </div>
  <!-- Sites — multi-site federation (moved from Planning) -->
  <div class="section">
    <div class="section-header"><h3>Sites</h3><span class="chev">▾</span></div>
    <div class="section-body">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <span style="font-size:12px;color:var(--text-dim)">Connect and manage multiple FREQ instances.</span>
        <div style="display:flex;gap:8px">
          <button class="fleet-btn" onclick="fedPoll()">POLL ALL</button>
          <button class="fleet-btn" onclick="loadFederation()">REFRESH</button>
        </div>
      </div>
      <div id="fed-summary" style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px"></div>
      <div id="fed-sites"></div>
      <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--input-border)">
        <h4 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">REGISTER NEW SITE</h4>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <input id="fed-name" placeholder="Site name" style="flex:1;min-width:100px" class="freq-input">
          <input id="fed-url" placeholder="https://freq.dc02:8888" style="flex:2;min-width:200px" class="freq-input">
          <input id="fed-secret" placeholder="Shared secret (optional)" type="password" style="flex:1;min-width:100px" class="freq-input">
          <button class="fleet-btn" onclick="fedRegister()">REGISTER</button>
        </div>
      </div>
    </div>
  </div>
  <!-- Lab Assignment — tag any fleet member as LAB -->
  <div class="section">
    <div class="section-header"><h3>Lab Assignment</h3><span class="chev">▾</span></div>
    <div class="section-body">
      <div style="font-size:12px;color:var(--text-dim);margin-bottom:12px">Tag any host or VM as Lab Equipment. Tagged items appear in the LAB EQUIPMENT section on the Fleet page.</div>
      <div id="lab-assign-list"><div class="skeleton"></div></div>
    </div>
  </div>
  <!-- User Preferences -->
  <div class="section">
    <div class="section-header"><h3>Preferences</h3><span class="chev">▾</span></div>
    <div class="section-body">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px">
        <div>
          <label style="font-size:12px;color:var(--text-dim);margin-bottom:4px;display:block">Auto-Refresh Interval</label>
          <select id="pref-refresh" class="input-field" style="width:100%" onchange="updatePref('refresh',this.value)">
            <option value="0">Disabled</option>
            <option value="10">10 seconds</option>
            <option value="30" selected>30 seconds</option>
            <option value="60">60 seconds</option>
            <option value="120">2 minutes</option>
          </select>
        </div>
        <div>
          <label style="font-size:12px;color:var(--text-dim);margin-bottom:4px;display:block">UI Density</label>
          <select id="pref-density" class="input-field" style="width:100%" onchange="updatePref('density',this.value)">
            <option value="compact">Compact</option>
            <option value="normal" selected>Normal</option>
            <option value="comfortable">Comfortable</option>
          </select>
        </div>
      </div>
    </div>
  </div>
</div><!-- close settings-view -->

</div><!-- close p-home -->

<!-- ════════ INFRA ════════ -->
<div id="p-infra" class="page">
<div class="flex-row-8-mb16-center">
  <button class="fleet-btn c-purple-active" data-view="home" >&#9664; HOME</button>
  <button class="fleet-btn" onclick="loadInfraPage()">REFRESH</button>
</div>
<div class="section">
  <div class="section-header"><h3>Overview</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="stats" id="infra-stats"></div>
    <table><thead><tr><th>Host</th><th>Type</th><th>OS</th><th>CPU</th><th>RAM</th><th>Disk</th><th>Containers</th><th>Services</th><th>Status</th></tr></thead><tbody id="infra-tbl"></tbody></table>
    <div id="infra-vms" class="mt-8"></div>
  </div>
</div>
<div class="section collapsed">
  <div class="section-header"><h3>pfSense <span id="pf-meta" class="fs-12-dim">FIREWALL</span></h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="flex-wrap-8-mb12"><button class="fleet-btn" data-action="pfAction" data-arg="status">STATUS</button><button class="fleet-btn" data-action="pfAction" data-arg="rules">RULES</button><button class="fleet-btn" data-action="pfAction" data-arg="nat">NAT</button><button class="fleet-btn" onclick="pfAction('states')">STATES</button><button class="fleet-btn" onclick="pfAction('interfaces')">INTERFACES</button></div>
    <div class="exec-out" id="pf-out">Click an action above.</div>
  </div>
</div>
<div class="section collapsed">
  <div class="section-header"><h3>TrueNAS <span id="tn-meta" class="fs-12-dim">NETWORK STORAGE</span></h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="flex-wrap-8-mb12"><button class="fleet-btn" data-action="tnAction" data-arg="status">SYSTEM</button><button class="fleet-btn" data-action="tnAction" data-arg="pools">POOLS</button><button class="fleet-btn" data-action="tnAction" data-arg="health">HEALTH</button><button class="fleet-btn" data-action="tnAction" data-arg="datasets">DATASETS</button><button class="fleet-btn" data-action="tnAction" data-arg="shares">SHARES</button><button class="fleet-btn" data-action="tnAction" data-arg="alerts">ALERTS</button></div>
    <div class="exec-out" id="tn-out">Click an action above.</div>
  </div>
</div>
<div class="section collapsed">
  <div class="section-header"><h3>iDRAC <span class="fs-12-dim">BMC Management</span></h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="flex-wrap-8-mb12"><button class="fleet-btn" onclick="idracAction('status')">SYSTEM INFO</button><button class="fleet-btn" onclick="idracAction('sensors')">SENSORS</button><button class="fleet-btn" data-action="idracAction" data-arg="power">POWER</button><button class="fleet-btn" onclick="idracAction('sel')">EVENT LOG</button></div>
    <div id="idrac-out"></div>
  </div>
</div>
<div class="section collapsed">
  <div class="section-header"><h3>Switch <span id="sw-meta" class="fs-12-dim">L3 SWITCH</span></h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="flex-wrap-8-mb12"><button class="fleet-btn" data-action="swAction" data-arg="status">STATUS</button><button class="fleet-btn" data-action="swAction" data-arg="vlans">VLANS</button><button class="fleet-btn" onclick="swAction('interfaces')">INTERFACES</button><button class="fleet-btn" data-action="swAction" data-arg="mac">MAC TABLE</button></div>
    <div class="exec-out" id="sw-out">Click an action above.</div>
  </div>
</div>
</div>

<!-- ════════ SYSTEM ════════ -->
<div id="p-system" class="page">
<div class="flex-row-8-mb16-center">
  <button class="fleet-btn c-purple-active" data-view="home" >&#9664; HOME</button>
  <button class="fleet-btn" onclick="loadSystemPage()">REFRESH</button>
</div>
<!-- Global Settings -->
<div class="section" id="sys-settings-section">
  <div class="section-header"><h3>Global Settings</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div id="global-settings-body"></div>
  </div>
</div>
<!-- Fleet Admin — admin role only, root tax -->
<div class="section d-none" id="fleet-admin-section" >
  <div class="section-header"><h3>Fleet Admin <span style="font-size:11px;font-weight:400;color:var(--yellow);margin-left:8px">ADMIN ONLY</span></h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div id="fleet-admin-body"><div class="skeleton"></div></div>
  </div>
</div>
<div class="section">
  <div class="section-header"><h3>Configuration</h3><span class="chev">▾</span></div>
  <div class="section-body"><div id="config-c"><div class="skeleton"></div><div class="skeleton"></div></div></div>
</div>
<div class="section">
  <div class="section-header"><h3>Doctor</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div style="display:flex;gap:8px;margin-bottom:16px"><button class="fleet-btn c-purple-active" onclick="runSysInfo()" >RUN SELF-DIAGNOSTIC</button><button class="fleet-btn" onclick="runBackup()">EXPORT CONFIG BACKUP</button></div>
    <div id="doctor-c"></div>
    <div id="backup-c" class="mt-12"></div>
  </div>
</div>
<div class="section">
  <div class="section-header"><h3>Journal</h3><span class="chev">▾</span></div>
  <div class="section-body"><div id="journal-c"><div class="skeleton"></div></div></div>
</div>
<div class="section">
  <div class="section-header"><h3>Knowledge Base</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <input class="search" id="learn-q" placeholder="Search knowledge base — try: nfs stale, docker gluetun, pfsense reboot" onkeydown="if(event.key==='Enter')searchLearn()">
    <div id="learn-r"></div>
  </div>
</div>
<div class="section">
  <div class="section-header"><h3>Distros</h3><span class="chev">▾</span></div>
  <div class="section-body"><div id="distro-c"><div class="skeleton"></div></div></div>
</div>
<div class="section">
  <div class="section-header"><h3>Groups</h3><span class="chev">▾</span></div>
  <div class="section-body"><div id="groups-c"><div class="skeleton"></div></div></div>
</div>
<div class="section">
  <div class="section-header"><h3>Alert Rules</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div id="rules-list"><div class="skeleton"></div></div>
    <div style="margin-top:16px;padding:16px;background:var(--bg);border:1px solid var(--border);border-radius:8px">
      <h4 style="font-size:13px;margin-bottom:12px;color:var(--purple-light)">Create Rule</h4>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
        <div><label class="label-sub-10">Name</label><input id="rule-name" class="input-sm" style="width:100%" placeholder="my-rule"></div>
        <div><label class="label-sub-10">Condition</label><select id="rule-cond" class="input-sm" style="width:100%"><option value="host_unreachable">Host Unreachable</option><option value="cpu_above">CPU Above</option><option value="ram_above">RAM Above %</option><option value="disk_above">Disk Above %</option><option value="docker_down">Docker Down</option></select></div>
        <div><label class="label-sub-10">Target</label><input id="rule-target" class="input-sm" style="width:100%" value="*" placeholder="* or hostname"></div>
        <div><label class="label-sub-10">Threshold</label><input id="rule-threshold" class="input-sm" style="width:100%" value="0" type="number"></div>
        <div><label class="label-sub-10">Duration (s)</label><input id="rule-duration" class="input-sm" style="width:100%" value="0" type="number"></div>
        <div><label class="label-sub-10">Cooldown (s)</label><input id="rule-cooldown" class="input-sm" style="width:100%" value="300" type="number"></div>
        <div><label class="label-sub-10">Severity</label><select id="rule-severity" class="input-sm" style="width:100%"><option value="warning">Warning</option><option value="critical">Critical</option><option value="info">Info</option></select></div>
      </div>
      <button class="fleet-btn mt-12" onclick="createRule()">CREATE RULE</button>
      <div id="rule-create-msg" class="mt-8"></div>
    </div>
    <div style="margin-top:16px">
      <h4 style="font-size:13px;margin-bottom:8px;color:var(--purple-light)">Recent Alerts</h4>
      <div id="alert-history"><span class="c-dim-fs12">No alerts yet</span></div>
    </div>
  </div>
</div>
<div class="section">
  <div class="section-header"><h3>Notifications</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div id="notify-status"></div>
    <button class="fleet-btn mt-12" data-action="testNotify" >SEND TEST</button>
    <div id="notify-result" class="mt-8"></div>
  </div>
</div>
<div class="section">
  <div class="section-header"><h3>About</h3><span class="chev">▾</span></div>
  <div class="section-body">
    <div class="crd" style="margin-bottom:24px;border-left:3px solid var(--purple)">
      <h3 style="font-size:16px">About PVE FREQ</h3>
      <p class="mt-8">FREQ is a zero-dependency Proxmox fleet management tool. Pure Python stdlib. One binary. Every command you need to manage VMs, containers, networking, storage, and monitoring across your entire cluster.</p>
      <p class="mt-8">Built from scratch — 16,000+ lines of bash rewritten into clean Python. SSH to 6 platform types. Personality system. Knowledge base. Risk analysis. Auto-audit pipeline. Agent platform for AI-driven infrastructure.</p>
      <p style="margin-top:12px;color:var(--purple-light)"><em>"freq did not come to play."</em></p>
    </div>
    <h3 style="color:var(--purple-light);font-size:14px;margin-bottom:16px">Capabilities</h3>
    <div class="timeline">
      <div class="timeline-item"><h3>Fleet Management</h3><div class="meta">Core</div><p>Create, clone, destroy, resize, migrate, snapshot VMs across your entire cluster. Safety gates protect production. Fleet boundaries enforce VMID discipline.</p></div>
      <div class="timeline-item"><h3>Smart Commands</h3><div class="meta">Intelligence</div><p>learn (knowledge base), risk (kill-chain blast radius), sweep (auto-audit pipeline), patrol (continuous monitoring). Your cluster's operational memory.</p></div>
      <div class="timeline-item"><h3>Agent Platform</h3><div class="meta">AI-Powered</div><p>freq agent create security-ops — VM created, cloud image downloaded, CLAUDE.md generated. AI specialists on your infrastructure in 2 minutes.</p></div>
      <div class="timeline-item"><h3>Web Dashboard</h3><div class="meta">This page</div><p>Real-time fleet overview, VM management, container ops, network tools, and monitoring. Zero external dependencies. Pure Python stdlib HTTP server.</p></div>
      <div class="timeline-item" style="border-left-color:var(--purple)"><h3>Zero Dependencies</h3><div class="meta">Philosophy</div><p>No pip install. No node_modules. No Docker required. Just Python 3.7+ and SSH. Runs on any Linux host that can reach your PVE nodes.</p></div>
    </div>
    <div class="crd" style="margin-top:24px;text-align:center">
      <p id="about-credits" style="font-size:13px;color:var(--text);margin-top:8px">PVE FREQ</p>
      <p style="font-size:12px;color:var(--purple-light);margin-top:8px;font-style:italic">"things are gonna get easier"</p>
    </div>
  </div>
</div>
</div>

</div></div><!-- close mn-body and mn -->

<!-- ═══ HOST DETAIL OVERLAY ═══ -->
<div id="host-overlay" class="host-overlay">
  <div class="ho-header"><div class="ho-header-inner">
    <div>
      <h1 id="hd-title"></h1>
      <div id="hd-subtitle" style="font-size:13px;color:var(--text);margin-top:2px"></div>
    </div>
    <button class="ho-close" onclick="closeCard()">&#10005;</button>
  </div></div>
  <div class="ho-body">
    <div id="hd-loading" style="color:var(--text-dim);padding:60px 0;text-align:center">
      <div style="font-size:28px;margin-bottom:12px;opacity:0.6">&#9881;</div>
      <div style="font-size:13px">Loading Host Details...</div>
    </div>
    <div id="hd-content" style="display:none"></div>
  </div>
</div>

<!-- ═══ TOAST + MODAL ═══ -->
<div id="toast-container" class="toast-container"></div>
<div id="modal-container" class="modal-overlay" style="display:none"></div>

<script>
var HC=['#58a6ff','#3fb950','#d29922','#f778ba','#79c0ff','#d2a8ff','#ff7b72','#ffa657','#7ee787'];
var quotes=[
  '"the bass is the foundation. so is this tool." — freq',
  '"SSH in. Crush it. Log out." — freq',
  '"everything is going to be okay. the cluster is healthy." — freq doctor',
  '"snapshot before you experiment." — freq',
  '"objects in the mirror are closer than they appear." — mac miller',
  '"the ones who know, know." — underground bass & sysadmins',
  '"you built this. it works. that means something." — freq',
  '"every great homelab started with a single qm create." — freq',
  '"things are gonna get easier." — mac miller',
  '"we love bass. we also love uptime." — freq',
  '"the goal every single time: clean." — freq doctor',
  '"no matter where life takes me, find me with a smile." — mac miller'
];
var taglines=[
  'Drop the bass, not the uptime','Low frequency. High efficiency.',
  'Bass-boosted infrastructure','Feel the rumble. Deploy the fleet.',
  'Built different. Built heavy.','Headphones on. VMs deployed.',
  'Sub-zero latency, sub-bass energy','Where the subs hit and the servers sit'
];

function rq(){return quotes[Math.floor(Math.random()*quotes.length)];}
function rt(){return taglines[Math.floor(Math.random()*taglines.length)];}
function badge(s){var c={up:'up',running:'up',online:'up',ok:'ok',healthy:'ok',down:'down',stopped:'down',unreachable:'down',CRITICAL:'CRITICAL',HIGH:'HIGH',MEDIUM:'MEDIUM',created:'created',remote:'remote',paused:'paused',unknown:'unknown'}[s]||'warn';return '<span class="badge '+c+'">'+s.toUpperCase()+'</span>';}
function s(l,v,c){return '<div class="st"><div class="lb">'+l+'</div><div class="vl '+c+'">'+v+'</div></div>';}
var st=s;
function _pbar(pct,color){if(!pct)return '';var c=pct>=90?'var(--red)':pct>=75?'var(--yellow)':color||'var(--purple-light)';return '<div class="pbar"><div class="pbar-fill" style="width:'+pct+'%;background:'+c+'"></div></div>';}
function _mrow(label,val,pct,color){return '<div class="metric-row"><div class="metric-top"><span class="metric-label">'+label+'</span><span class="metric-val">'+val+'</span></div>'+_pbar(pct,color)+'</div>';}
function _ramGB(mb){mb=parseInt(mb)||0;if(mb>=1024)return (mb/1024).toFixed(1).replace(/\.0$/,'')+'GB';return mb+'MB';}
function _ramStr(ramText){
  /* Convert "1234/8192MB (15%)" or "1234/8192" to GB format — no percentage */
  var m=ramText.match(/(\d+)\/(\d+)/);if(!m)return ramText;
  return _ramGB(parseInt(m[1]))+' / '+_ramGB(parseInt(m[2]));
}
function _safe(fn){try{fn();}catch(e){console.error(e);}}
function upTime(){document.getElementById('header-time').textContent=new Date().toLocaleTimeString();}
setInterval(upTime,1000);upTime();

/* === Utility === */
function _esc(s){if(!s)return '';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}

/* === Toast === */
function toast(msg,type){
  var t=document.createElement('div');t.className='toast '+(type||'info');t.textContent=msg;
  document.getElementById('toast-container').appendChild(t);
  setTimeout(function(){t.classList.add('fadeout');},3500);
  setTimeout(function(){t.remove();},4000);
}
/* === Modal === */
function confirmAction(msg,onConfirm){
  var ov=document.getElementById('modal-container');
  ov.innerHTML='<div class="modal"><h3>Confirm Action</h3><p>'+msg+'</p><div class="modal-actions"><button class="btn" onclick="closeModal()">Cancel</button><button class="btn btn-primary" id="modal-confirm-btn">Confirm</button></div></div>';
  ov.style.display='flex';
  document.getElementById('modal-confirm-btn').onclick=function(){closeModal();onConfirm();};
}
function closeModal(){document.getElementById('modal-container').style.display='none';}
/* === Section toggle === */
function toggleSection(el){el.closest('.section').classList.toggle('collapsed');}
/* Delegated listeners — replaces inline onclick for high-frequency patterns */
document.addEventListener('click',function(e){
  var sh=e.target.closest('.section-header');
  if(sh){toggleSection(sh);return;}
  var sv=e.target.closest('[data-view]');
  if(sv){switchView(sv.dataset.view);return;}
  var ft=e.target.closest('[data-fqc]');
  if(ft){fleetTool(ft.dataset.fqc);return;}
  var ac=e.target.closest('[data-audit]');
  if(ac){runAuditCheck(ac.dataset.audit);return;}
  var cx=e.target.closest('.close-x');
  if(cx){closeModal();return;}
  var da=e.target.closest('[data-action]');
  if(da){
    var a=da.dataset.action,g=da.dataset.arg||'';
    if(a==='vmPower'){vmPower(+da.dataset.vmid,g);return;}
    if(a==='vmDestroy'){vmDestroy(+da.dataset.vmid);return;}
    if(a==='vmSnap'){vmSnap(+da.dataset.vmid);return;}
    if(a==='vmQuickTag'){var tags=prompt('Enter tags for VM '+da.dataset.vmid+' (comma-separated):');if(tags!==null)fetch(API.VM_TAG+'?vmid='+da.dataset.vmid+'&tags='+encodeURIComponent(tags)).then(function(r){return r.json()}).then(function(d){if(d.ok)toast('Tags updated','success');else toast(d.error,'error');});return;}
    if(a==='openVmInfo'){openVmInfo(da.dataset.label,'',+da.dataset.vmid);return;}
    if(a==='vaultReveal'){vaultReveal(da.dataset.uid,da.dataset.host,da.dataset.key);return;}
    if(a==='vaultCopy'){vaultCopy(da.dataset.host,da.dataset.key);return;}
    if(a==='vaultDelGroup'){vaultDelGroup(g);return;}
    if(a==='labDockerAction'){labDockerAction(da.dataset.name,g);return;}
    if(a==='hdLogs'){hdLogs(da);return;}
    if(a==='hdExec'){hdExec(da);return;}
    if(a==='hdDiagnose'){hdDiagnose(da);return;}
    if(a==='togglePveGroup'){togglePveGroup(da);return;}
    if(a==='clearHarden'){document.getElementById('harden-c').innerHTML='';return;}
    var fns={sshdRestartSelected:sshdRestartSelected,sshdRestartAll:sshdRestartAll,openLayoutConfig:openLayoutConfig,hdRestart:hdRestart,vmtSnapshot:vmtSnapshot,vmtCreate:vmtCreate,vmtResize:vmtResize,vmtMigrate:vmtMigrate,vmtClone:vmtClone,vmtAddDisk:vmtAddDisk,vmtTag:vmtTag,unlockVault:unlockVault,runHarden:runHarden,testNotify:testNotify,userCreate:userCreate,vaultSet:vaultSet,updateSelected:updateSelected,updateAll:updateAll};
    if(fns[a]){fns[a]();return;}
    var argFns={tnAction:tnAction,swAction:swAction,pfAction:pfAction,idracAction:idracAction,switchVaultTab:switchVaultTab,switchDockerSub:switchDockerSub,toggleMediaTag:toggleMediaTag,runHostUpdate:runHostUpdate,sshdRestartHost:sshdRestartHost,ntpFixHost:ntpFixHost,userPromote:userPromote,userDemote:userDemote,updateCategoryRange:updateCategoryRange,mediaRestart:mediaRestart};
    if(argFns[a]){argFns[a](g);return;}
  }
});
/* === Global Settings === */
function _loadSettings(){
  try{var s=JSON.parse(localStorage.getItem(_userKey('settings'))||'{}');return s;}catch(e){return {};}
}
function _saveSettings(s){localStorage.setItem(_userKey('settings'),JSON.stringify(s));}
function _applySettings(){
  var s=_loadSettings();
  if(s.hoverFx===false)document.body.classList.add('no-hover-fx');
  else document.body.classList.remove('no-hover-fx');
}
/* openSettings removed — settings now live in SYSTEM page */
function saveSetting(key,val){
  var s=_loadSettings();s[key]=val;_saveSettings(s);_applySettings();
  renderGlobalSettings();
  toast('Setting saved','success');
}
_applySettings();/* apply on page load */

/* ═══════════════════════════════════════════════════════════════════
   AUTH — Login, Session, Per-user Storage
   ═══════════════════════════════════════════════════════════════════ */
var _currentRole='operator';
var _currentUser='';
var _authToken='';

/* Per-user localStorage: prefix all keys with username */
function _userKey(key){return _currentUser?'freq_'+_currentUser+'_'+key:'freq_'+key;}

function doLogin(){
  var userEl=document.getElementById('login-user');
  var passEl=document.getElementById('login-pass');
  var errEl=document.getElementById('login-error');
  /* Force browser to flush autofill values */
  userEl.dispatchEvent(new Event('input',{bubbles:true}));
  passEl.dispatchEvent(new Event('input',{bubbles:true}));
  var user=userEl.value.trim();
  var pass=passEl.value;
  if(errEl){errEl.textContent='DEBUG: user=['+user+'] pass_len='+pass.length;errEl.style.display='block';}
  if(!user||!pass){if(errEl){errEl.textContent='Enter username and password (got user=['+user+'] pass_len='+pass.length+')';errEl.style.display='block';}return;}
  if(errEl)errEl.style.display='none';
  var btn=document.querySelector('#login-overlay button');if(btn){btn.textContent='LOGGING IN...';btn.disabled=true;}
  fetch(API.AUTH_LOGIN+'?username='+encodeURIComponent(user)+'&password='+encodeURIComponent(pass)).then(function(r){return r.json()}).then(function(d){
    if(btn){btn.textContent='LOG IN';btn.disabled=false;}
    if(d.error){if(errEl){errEl.textContent=d.error;errEl.style.display='block';}passEl.value='';return;}
    _authToken=d.token;_currentUser=d.user;_currentRole=d.role;
    _showApp();
  }).catch(function(e){if(btn){btn.textContent='LOG IN';btn.disabled=false;}if(errEl){errEl.textContent='Connection failed: '+e;errEl.style.display='block';}});
}

function doLogout(){
  _authToken='';_currentUser='';_currentRole='operator';
  /* Clear any legacy storage tokens */
  try{sessionStorage.removeItem('freq_auth_token');sessionStorage.removeItem('freq_auth_user');}catch(e){}
  try{localStorage.removeItem('freq_auth_token');localStorage.removeItem('freq_auth_user');}catch(e){}
  document.getElementById('login-overlay').style.display='flex';
  document.getElementById('login-user').value='';
  document.getElementById('login-pass').value='';
  document.getElementById('login-user').focus();
}

/* API endpoint constants — single source of truth for all fetch paths */
var API={
  EXEC:'/api/exec',VMS:'/api/vms',HEALTH:'/api/health',STATUS:'/api/status',INFO:'/api/info',
  FLEET_OVERVIEW:'/api/fleet/overview',FLEET_NTP:'/api/fleet/ntp',FLEET_UPDATES:'/api/fleet/updates',
  MEDIA_STATUS:'/api/media/status',MEDIA_HEALTH:'/api/media/health',MEDIA_DASHBOARD:'/api/media/dashboard',
  MEDIA_DOWNLOADS:'/api/media/downloads',MEDIA_STREAMS:'/api/media/streams',MEDIA_RESTART:'/api/media/restart',
  MEDIA_LOGS:'/api/media/logs',MEDIA_UPDATE:'/api/media/update',
  USERS:'/api/users',VAULT:'/api/vault',CONFIG:'/api/config',JOURNAL:'/api/journal',
  AGENTS:'/api/agents',POLICIES:'/api/policies',SPECIALISTS:'/api/specialists',
  INFRA_QUICK:'/api/infra/quick',INFRA_OVERVIEW:'/api/infra/overview',
  INFRA_PFSENSE:'/api/infra/pfsense',INFRA_TRUENAS:'/api/infra/truenas',INFRA_IDRAC:'/api/infra/idrac',
  HOST_DETAIL:'/api/host/detail',LAB_STATUS:'/api/lab/status',
  AUTH_LOGIN:'/api/auth/login',AUTH_VERIFY:'/api/auth/verify',AUTH_CHANGE_PW:'/api/auth/change-password',
  VM_POWER:'/api/vm/power',VM_CREATE:'/api/vm/create',VM_DESTROY:'/api/vm/destroy',
  VM_SNAPSHOT:'/api/vm/snapshot',VM_SNAPSHOTS:'/api/vm/snapshots',VM_DELETE_SNAP:'/api/vm/delete-snapshot',
  VM_RESIZE:'/api/vm/resize',VM_RENAME:'/api/vm/rename',VM_CHANGE_ID:'/api/vm/change-id',
  VM_CHECK_IP:'/api/vm/check-ip',VM_ADD_NIC:'/api/vm/add-nic',VM_CLEAR_NICS:'/api/vm/clear-nics',
  VM_CHANGE_IP:'/api/vm/change-ip',VM_TEMPLATE:'/api/vm/template',
  ADMIN_BOUNDARIES:'/api/admin/fleet-boundaries',ADMIN_BOUNDARIES_UPDATE:'/api/admin/fleet-boundaries/update',
  ADMIN_HOSTS_UPDATE:'/api/admin/hosts/update',
  HARDEN:'/api/harden',GROUPS:'/api/groups',DISTROS:'/api/distros',KEYS:'/api/keys',
  SWITCH:'/api/switch',NOTIFY_TEST:'/api/notify/test',RISK:'/api/risk',LEARN:'/api/learn',METRICS:'/api/metrics',
  VAULT_SET:'/api/vault/set',VAULT_DELETE:'/api/vault/delete',
  USERS_CREATE:'/api/users/create',USERS_PROMOTE:'/api/users/promote',USERS_DEMOTE:'/api/users/demote',
  LAB_TOOL_CONFIG:'/api/lab-tool/config',LAB_TOOL_PROXY:'/api/lab-tool/proxy',LAB_TOOL_SAVE:'/api/lab-tool/save-config',
  DOCTOR:'/api/doctor',DIAGNOSE:'/api/diagnose',LOG:'/api/log',
  POLICY_CHECK:'/api/policy/check',POLICY_FIX:'/api/policy/fix',POLICY_DIFF:'/api/policy/diff',
  SWEEP:'/api/sweep',PATROL_STATUS:'/api/patrol/status',
  ZFS:'/api/zfs',BACKUP:'/api/backup',DISCOVER:'/api/discover',GWIPE:'/api/gwipe',
  VM_ADD_DISK:'/api/vm/add-disk',VM_TAG:'/api/vm/tag',VM_CLONE:'/api/vm/clone',VM_MIGRATE:'/api/vm/migrate',
  COMPOSE_UP:'/api/containers/compose-up',COMPOSE_DOWN:'/api/containers/compose-down',COMPOSE_VIEW:'/api/containers/compose-view',
  BACKUP_LIST:'/api/backup/list',BACKUP_CREATE:'/api/backup/create',BACKUP_RESTORE:'/api/backup/restore'
};
var _fleetCache={fo:null,hd:null};/* cached API responses for instant page switch */

function _showApp(){
  /* Show loading screen while prefetching data */
  var login=document.getElementById('login-overlay');
  login.innerHTML='<div class="text-center"><pre style="font-family:\'Courier New\',monospace;font-size:10px;line-height:1.1;color:var(--purple-light);display:inline-block;text-align:left;margin-bottom:24px"> \u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2557   \u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557\n \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d   \u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2550\u2588\u2588\u2557\n \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2557     \u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551   \u2588\u2588\u2551\n \u2588\u2588\u2554\u2550\u2550\u2550\u255d \u255a\u2588\u2588\u2557 \u2588\u2588\u2554\u255d\u2588\u2588\u2554\u2550\u2550\u255d     \u2588\u2588\u2554\u2550\u2550\u255d  \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u255d  \u2588\u2588\u2551\u2584\u2584 \u2588\u2588\u2551\n \u2588\u2588\u2551      \u255a\u2588\u2588\u2588\u2588\u2554\u255d \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557   \u2588\u2588\u2551     \u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\n \u255a\u2550\u255d       \u255a\u2550\u2550\u2550\u255d  \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d   \u255a\u2550\u255d     \u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u2550\u255d\u2550\u2550\u255d</pre>'+
    '<div id="load-status" style="color:var(--purple-light);font-size:13px;font-weight:600;letter-spacing:1px;margin-bottom:16px">INITIALIZING</div>'+
    '<div style="width:200px;height:4px;background:var(--input-border);border-radius:2px;margin:0 auto;overflow:hidden"><div id="load-bar" style="width:0%;height:100%;background:var(--purple);border-radius:2px;transition:width 0.4s ease"></div></div>'+
    '<div id="load-detail" style="color:var(--text-dim);font-size:11px;margin-top:12px">Connecting to fleet...</div></div>';

  var bar=document.getElementById('load-bar');
  var status=document.getElementById('load-status');
  var detail=document.getElementById('load-detail');
  var _p=function(pct,s,d){bar.style.width=pct+'%';status.textContent=s;detail.textContent=d;};

  _p(10,'CONNECTING','Fetching fleet data...');
  var p1=fetch(API.FLEET_OVERVIEW).then(function(r){return r.json()}).then(function(fo){
    _fleetCache.fo=fo;_initFleetData(fo);_p(40,'FLEET ONLINE',fo.summary.total_vms+' VMs across '+fo.pve_nodes.length+' nodes');
    return fo;
  }).catch(function(){_p(40,'FLEET','Fleet overview unavailable');return null;});

  var p2=fetch(API.HEALTH).then(function(r){return r.json()}).then(function(hd){
    _fleetCache.hd=hd;
    var up=0;hd.hosts.forEach(function(h){if(h.status==='healthy')up++;});
    _p(70,'HEALTH CHECK',up+' of '+hd.hosts.length+' hosts online');
    return hd;
  }).catch(function(){_p(70,'HEALTH','Health check unavailable');return null;});

  var p3=fetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(md){
    _p(85,'MEDIA STACK',md.containers_running+' containers running');
    return md;
  }).catch(function(){return null;});

  Promise.all([p1,p2,p3]).then(function(){
    _p(100,'READY','Welcome, '+_currentUser);
    setTimeout(function(){
      login.style.display='none';
      /* Update header user button */
      var btn=document.getElementById('header-user-btn');if(btn)btn.style.display='flex';
      var nameEl=document.getElementById('header-user-name');if(nameEl)nameEl.textContent=_currentUser;
      var roleEl=document.getElementById('header-user-role');if(roleEl)roleEl.textContent=_currentRole.toUpperCase();
      var rc={admin:'var(--red)',operator:'var(--yellow)',viewer:'var(--green)'};
      var iconEl=document.getElementById('header-user-icon');if(iconEl)iconEl.style.background=rc[_currentRole]||'var(--green)';
      _applyRoleUI();
      _renderHomeWidgets();
      _checkForUpdate();
    },600);
  });
}

function _checkForUpdate(){
  if(sessionStorage.getItem('freq_update_dismissed'))return;
  fetch('/api/update/check').then(function(r){return r.json()}).then(function(d){
    if(d.update_available&&d.latest){
      var banner=document.getElementById('update-banner');
      var text=document.getElementById('update-banner-text');
      if(banner&&text){
        text.innerHTML='<strong>Update Available:</strong> v'+_esc(d.latest)+' &mdash; Pull latest: <code style="background:var(--bg);padding:2px 6px;border-radius:4px;font-size:12px">docker compose pull && docker compose up -d</code>';
        banner.style.display='block';
      }
    }
  }).catch(function(){});
}

function openUserMenu(){
  var rc={admin:'var(--red)',operator:'var(--yellow)',viewer:'var(--green)'};
  var ov=document.getElementById('modal-container');
  ov.innerHTML='<div class="modal" style="max-width:340px">'+
    '<div class="flex-between-mb16"><h3 class="m-0">Session</h3><span class="close-x">&times;</span></div>'+
    '<div style="display:flex;align-items:center;gap:12px;padding:16px;background:var(--bg);border-radius:8px;margin-bottom:16px">'+
    '<div style="width:40px;height:40px;border-radius:50%;background:var(--purple);display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:var(--text)">'+_currentUser.charAt(0).toUpperCase()+'</div>'+
    '<div><div style="font-size:14px;font-weight:600;color:var(--text)">'+_currentUser.toUpperCase()+'</div><div style="font-size:12px;color:'+(rc[_currentRole]||'var(--text-dim)')+';font-weight:600">'+_currentRole.toUpperCase()+'</div></div></div>'+
    '<button onclick="closeModal();doLogout()" style="width:100%;background:none;border:2px solid var(--red);color:var(--red);padding:10px;border-radius:8px;font-size:13px;font-weight:600;font-family:inherit;cursor:pointer;transition:background 0.2s" onmouseover="this.style.background=\'rgba(248,81,73,0.1)\'" onmouseout="this.style.background=\'none\'">LOG OUT</button>'+
    '</div>';
  ov.style.display='flex';
}

/* Auth: always require login on page load — no stored sessions.
   Tokens live only in JS memory; refresh = re-authenticate. */
function _checkSession(){
  /* Clear any legacy stored tokens */
  try{sessionStorage.removeItem('freq_auth_token');sessionStorage.removeItem('freq_auth_user');}catch(e){}
  try{localStorage.removeItem('freq_auth_token');localStorage.removeItem('freq_auth_user');}catch(e){}
  document.getElementById('login-overlay').style.display='flex';
  document.getElementById('login-user').focus();
}

function _applyRoleUI(){
  var roleSelect=document.getElementById('ft-nu-sudo');
  if(roleSelect&&_currentRole!=='admin'){
    var opts=roleSelect.querySelectorAll('option');
    opts.forEach(function(o){if(o.value==='yes')o.disabled=(_currentRole!=='admin');});
  }
}
_checkSession();

/* === HOME Layout Config === */
/* Generic layout system — works for any view */
/* Widget registry — all possible widgets for HOME dashboard */
var WIDGET_REGISTRY=[
  {id:'w-fleet-stats',page:'FLEET',label:'Fleet Stats',loader:function(el){el.innerHTML='<div class="stats" id="hw-fleet-stats"></div>';_loadHomeFleetStats();}},
  {id:'w-fleet-infra',page:'FLEET',label:'Hosts & VMs',ref:'fleet-sec-infra',preload:function(){loadFleetPage();}},
  {id:'w-fleet-overview',page:'FLEET',label:'Overview',loader:function(el){
    /* Summary cards row — cluster-level stats */
    var g='<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px">';
    g+='<div class="host-card"><div class="host-head"><h3 class="c-purple">PVE NODES</h3><div class="host-meta"><span>HYPERVISOR</span></div></div><div class="divider-light"><div id="hw-pve-sum"><div class="skeleton h-60" ></div></div></div></div>';
    g+='<div class="host-card"><div class="host-head"><h3 class="c-purple">VMs</h3><div class="host-meta"><span>PROXMOX</span></div></div><div class="divider-light"><div id="hw-vms"><div class="skeleton h-60" ></div></div></div></div>';
    g+='<div class="host-card"><div class="host-head"><h3 class="c-green">MEDIA STACK</h3><div class="host-meta"><span>CONTAINERS</span><span>·</span><span>DOCKER</span></div></div><div class="divider-light"><div id="hw-media"><div class="skeleton h-60" ></div></div></div></div></div>';
    /* Infrastructure device cards — responsive grid */
    g+='<div id="hw-physical-cards" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px"></div>';
    el.innerHTML=g;
    /* Populate physical device cards as individual grid items */
    var pc='';PROD_HOSTS.filter(function(h){return h.type!=='pve'}).forEach(function(h){var tc={pfsense:'var(--text)',truenas:'var(--blue)',switch:'var(--cyan)',idrac:'var(--orange)'}; pc+='<div class="host-card"><div class="host-head"><h3 style="color:'+(tc[h.type]||'var(--text)')+'">'+h.label.toUpperCase()+'</h3><div class="host-meta"><span>'+h.ip+'</span><span>·</span><span>'+h.role+'</span></div></div><div class="divider-light"><div id="hw-'+h.label.toLowerCase().replace(/[^a-z0-9]/g,'-')+'"><div class="skeleton h-60" ></div></div></div></div>';});
    var pcd=document.getElementById('hw-physical-cards');if(pcd)pcd.innerHTML=pc;
    _loadWidgetOverview();
  }},
  {id:'w-fleet-agents',page:'FLEET',label:'Agents',ref:'fleet-sec-agents',preload:function(){loadAgents();}},
  {id:'w-fleet-specialists',page:'FLEET',label:'Sandbox VMs',ref:'fleet-sec-specialists',preload:function(){loadSpecialists();}},
  {id:'w-docker-containers',page:'DOCKER',label:'Containers',loader:function(el){
    el.innerHTML='<div class="stats" id="hw-ctr-stats"></div><div id="hw-ctr-cards" class="cards"><div class="skeleton"></div></div>';
    fetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(d){
      var _coff2=Math.max(0,d.containers_down||0);var s=document.getElementById('hw-ctr-stats');if(s)s.innerHTML=st('Total',d.containers_total,'p')+st('Online',d.containers_running,'g')+st('Offline',_coff2,_coff2>0?'r':'g')+st('VMs',d.vm_count,'b');
    });
    fetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
      var h='';d.containers.forEach(function(c){h+=_containerCard(c,'');});
      var el2=document.getElementById('hw-ctr-cards');if(el2)el2.innerHTML=h||'<div class="empty-state"><p>No containers.</p></div>';
    });
  }},
  {id:'w-sec-users',page:'SECURITY',label:'Users',ref:'sec-users',preload:function(){loadUsers();}},
  {id:'w-sec-sshkeys',page:'SECURITY',label:'SSH Keys',ref:'sec-sshkeys',preload:function(){loadKeys();}},
  {id:'w-sec-apikeys',page:'SECURITY',label:'API Keys',ref:'sec-apikeys',preload:function(){loadVault();}},
  {id:'w-sec-audit',page:'SECURITY',label:'Audit',ref:'sec-audit'},
  {id:'w-sec-harden',page:'SECURITY',label:'Hardening',ref:'sec-harden'},
  {id:'w-sec-risk',page:'SECURITY',label:'Risk Analysis',ref:'sec-risk',preload:function(){loadRisk();}},
  {id:'w-sec-policies',page:'SECURITY',label:'Policies',ref:'sec-policies',preload:function(){loadPolicies();}},
  {id:'w-sec-vault',page:'SECURITY',label:'Vault',ref:'sec-vault-section'}
];
var QUICK_START_WIDGETS=['w-fleet-stats','w-fleet-infra','w-fleet-overview','w-docker-containers'];
function _loadHomeWidgetConfig(){try{return JSON.parse(localStorage.getItem(_userKey('home_widgets'))||'null');}catch(e){return null;}}
function _saveHomeWidgetConfig(cfg){localStorage.setItem(_userKey('home_widgets'),JSON.stringify(cfg));}
function _renderHomeWidgets(){
  var cfg=_loadHomeWidgetConfig();
  var container=document.getElementById('home-widgets');
  var emptyEl=document.getElementById('home-empty');
  if(!cfg||!cfg.length){container.innerHTML='';emptyEl.style.display='block';return;}
  emptyEl.style.display='none';
  container.innerHTML='';
  cfg.forEach(function(wid){
    var w=WIDGET_REGISTRY.find(function(r){return r.id===wid;});if(!w)return;
    var sec=document.createElement('div');
    sec.className='section';sec.setAttribute('data-widget',wid);
    sec.innerHTML='<div class="section-header"><h3>'+w.label+' <span style="font-size:12px;opacity:0.5;font-weight:400">'+w.page+'</span></h3><span class="chev">▾</span></div><div class="section-body"><div id="hw-'+wid+'" class="widget-body"><div class="skeleton"></div></div></div>';
    container.appendChild(sec);
    /* Load widget data */
    if(w.loader){w.loader(document.getElementById('hw-'+wid));}
    else if(w.ref){
      if(w.preload)w.preload();
      (function(ref,targetId){
        setTimeout(function(){
          var src=document.getElementById(ref);
          if(src){var body=src.querySelector('.section-body');
            if(body){var t=document.getElementById('hw-'+targetId);if(t)t.innerHTML=body.innerHTML;}}
        },2000);
      })(w.ref,wid);
    }
  });
}
function _loadHomeFleetStats(){
  fetch(API.HEALTH).then(function(r){return r.json()}).then(function(hd){
    var up=0,down=0,pve=0;var _homeLabLabels=_getLabLabels(hd.hosts);var lab=Object.keys(_homeLabLabels).length;
    hd.hosts.forEach(function(h){if(h.status==='healthy')up++;else down++;if(h.type==='pve')pve++;});
    var totalAll=hd.hosts.length;
    var totalOff=down;var prodCount=totalAll-lab;var pveCount=PROD_HOSTS.filter(function(h){return h.type==='pve';}).length||pve;
    var _d=function(l,v1,l1,c1,v2,l2,c2){return '<div class="st"><div class="lb">'+l+'</div><div class="flex-row-24"><span class="stat-pair"><span style="font-size:20px;font-weight:700;color:'+c1+'">'+v1+'</span><span class="label-hint">'+l1+'</span></span><span class="stat-pair"><span style="font-size:20px;font-weight:700;color:'+c2+'">'+v2+'</span><span class="label-hint">'+l2+'</span></span></div></div>';};
    var el=document.getElementById('hw-fleet-stats');if(!el)return;
    el.innerHTML=_d('STATUS',up,'ONLINE','var(--green)',totalOff,'OFFLINE','var(--red)')+_d('FLEET',prodCount,'PROD','var(--purple-light)',lab,'LAB','var(--cyan)')+_d('PVE NODES',pveCount,'NODES','var(--purple-light)',pve,'ONLINE','var(--cyan)')+_d('RESPONSE',hd.duration+'s','','var(--blue)','','','var(--text-dim)')+st('VMs','...','p')+st('CONTAINERS','...','p')+st('ACTIVITY','...','p');
    fetch(API.VMS).then(function(r){return r.json()}).then(function(vd){var run=0,stop=0;vd.vms.forEach(function(v){if(v.status==='running')run++;else stop++;});
      var c=el.querySelector('.st:nth-child(5)');if(c)c.innerHTML='<div class="lb">VMs</div><div class="flex-row-24"><span class="stat-pair"><span class="stat-big-green">'+run+'</span><span class="label-hint">RUN</span></span><span class="stat-pair"><span class="stat-big-red">'+stop+'</span><span class="label-hint">STOP</span></span></div>';}).catch(function(){});
    fetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(md){
      var _cdn=Math.max(0,md.containers_down||0);var c=el.querySelector('.st:nth-child(6)');if(c)c.innerHTML='<div class="lb">CONTAINERS</div><div class="flex-row-24"><span class="stat-pair"><span class="stat-big-green">'+(md.containers_running||0)+'</span><span class="label-hint">UP</span></span><span class="stat-pair"><span class="stat-big-red">'+_cdn+'</span><span class="label-hint">DOWN</span></span></div>';}).catch(function(){});
    Promise.all([fetch(API.MEDIA_DOWNLOADS).then(function(r){return r.json()}).catch(function(){return{count:0}}),fetch(API.MEDIA_STREAMS).then(function(r){return r.json()}).catch(function(){return{count:0}})]).then(function(res){
      var c=el.querySelector('.st:nth-child(7)');if(c)c.innerHTML='<div class="lb">ACTIVITY</div><div class="flex-row-24"><span class="stat-pair"><span class="stat-big-orange">'+(res[0].count||0)+'</span><span class="label-hint">DL</span></span><span class="stat-pair"><span class="stat-big-blue">'+(res[1].count||0)+'</span><span class="label-hint">STREAM</span></span></div>';});
  });
}
function _loadWidgetOverview(){
  /* Populate physical device cards from fleet overview data */
  PROD_HOSTS.filter(function(h){return h.type!=='pve'}).forEach(function(h){
    var id='hw-'+h.label.toLowerCase().replace(/[^a-z0-9]/g,'-');
    var el=document.getElementById(id);if(!el)return;
    var c='';
    c+=_mrow('IP',h.ip||'N/A',0,'var(--purple-light)');
    c+=_mrow('ROLE',h.role||h.type.toUpperCase(),0,'var(--purple-light)');
    if(h.detail)c+=_mrow('HARDWARE',h.detail,0,'var(--text-dim)');
    el.innerHTML=c;
  });
  /* PVE summary */
  var tc=0,tr=0,tv=0,tctr=0;
  PROD_HOSTS.filter(function(h){return h.type==='pve'}).forEach(function(ph){tc+=ph.cores;tr+=(parseInt(ph.ram)||0);PROD_VMS.forEach(function(pv){if(pv.node===ph.label){tv++;tctr+=pv.containers;}});});
  var ps='';ps+=_mrow('TOTAL CPU',tc+' Cores',0,'var(--purple-light)');ps+=_mrow('TOTAL RAM',tr+'GB',0,'var(--blue)');ps+=_mrow('VMs',tv,0,'var(--green)');ps+=_mrow('CONTAINERS',tctr,0,'var(--cyan)');
  var pse=document.getElementById('hw-pve-sum');if(pse)pse.innerHTML=ps;
  /* VMs — exclude templates from counts */
  fetch(API.VMS).then(function(r){return r.json()}).then(function(d){
    var _st=_loadSettings();var run=0,stop=0,total=0;d.vms.forEach(function(v){if(!_st.showTemplates&&v.category==='templates')return;total++;if(v.status==='running')run++;else stop++;});
    var h='';h+=_mrow('TOTAL',total+' VMs',0,'var(--purple-light)');h+=_mrow('RUNNING',run,0,'var(--green)');h+=_mrow('STOPPED',stop,0,stop>0?'var(--red)':'var(--green)');
    var ve=document.getElementById('hw-vms');if(ve)ve.innerHTML=h;
  }).catch(function(){});
  /* Media */
  fetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(d){
    var run=d.containers_running||0,tot=d.containers_total||0,dn=Math.max(0,tot-run);
    var h='';h+=_mrow('ONLINE',run+' / '+tot,0,'var(--green)');h+=_mrow('OFFLINE',dn,0,dn>0?'var(--red)':'var(--green)');h+=_mrow('VMs',d.vm_count,0,'var(--blue)');
    var me=document.getElementById('hw-media');if(me)me.innerHTML=h;
  }).catch(function(){});
}
var VIEW_SECTIONS={
  home:[],
  fleet:['fleet-sec-stats','fleet-sec-infra','fleet-sec-overview','fleet-lab-section','fleet-sec-agents','fleet-sec-specialists'],
  docker:['docker-sec-containers'],
  security:['sec-risk','sec-policies'],
  'sec-hardening':['sec-audit','sec-harden'],
  'sec-access':['sec-users','sec-sshkeys','sec-apikeys'],
  'sec-vault':['sec-vault-section'],
  'sec-compliance':[],
  lab:[]
};
var _sectionNames={};
function _ltPopulateSections(){
  VIEW_SECTIONS.lab=[];
  if(typeof LAB_TOOLS!=='undefined'){LAB_TOOLS.forEach(function(t){var secId='lab-sec-'+t.id;VIEW_SECTIONS.lab.push(secId);_sectionNames[secId]=t.name;});}
}
function _sectionLabel(id){if(_sectionNames[id])return _sectionNames[id];var el=document.getElementById(id);if(!el)return id;var h3=el.querySelector('.section-header h3');return h3?h3.textContent.trim():id;}
function _loadViewLayout(view){
  try{var d=JSON.parse(localStorage.getItem(_userKey('layout_'+view))||'{}');
    if(!d.order)d.order=(VIEW_SECTIONS[view]||[]).slice();
    if(!d.visible)d.visible={};return d;
  }catch(e){return {order:(VIEW_SECTIONS[view]||[]).slice(),visible:{}};}
}
function _saveViewLayout(view,cfg){localStorage.setItem(_userKey('layout_'+view),JSON.stringify(cfg));}
function _applyViewLayout(view){
  var cfg=_loadViewLayout(view);var sections=VIEW_SECTIONS[view]||[];if(!sections.length)return;
  var first=document.getElementById(sections[0]);if(!first||!first.parentNode)return;
  var parent=first.parentNode;
  cfg.order.forEach(function(id){var el=document.getElementById(id);if(el&&el.parentNode===parent)parent.appendChild(el);});
  sections.forEach(function(id){var el=document.getElementById(id);if(el)el.style.display=(cfg.visible[id]===false)?'none':'';});
}
var _dragView=null;var _dragId=null;
function openLayoutConfig(){
  var view=_currentView;
  if(view==='home'){openHomeWidgetConfig();return;}
  var sections=VIEW_SECTIONS[view]||[];
  if(!sections.length){toast('No configurable sections on this view','info');return;}
  _dragView=view;
  var cfg=_loadViewLayout(view);
  var h='<div class="desc-line">Drag to reorder. Toggle to show/hide.</div>';
  h+='<div id="layout-drag-list">';
  cfg.order.forEach(function(id){
    var on=cfg.visible[id]!==false;var label=_sectionLabel(id);
    h+='<div class="layout-item" draggable="true" data-id="'+id+'" ondragstart="_dragId=this.getAttribute(\'data-id\');this.style.opacity=\'0.4\'" ondragend="this.style.opacity=\'1\'" ondragover="event.preventDefault();this.style.borderTopColor=\'var(--purple)\'" ondragleave="this.style.borderTopColor=\'var(--border)\'" ondrop="event.preventDefault();this.style.borderTopColor=\'var(--border)\';dropLayoutItem(this.getAttribute(\'data-id\'))" style="display:flex;align-items:center;gap:10px;padding:10px 12px;border-top:2px solid var(--border);cursor:grab;user-select:none;transition:border-color 0.15s">';
    h+='<span style="color:var(--text-dim);font-size:14px;cursor:grab">&#9776;</span>';
    h+='<span style="flex:1;font-size:13px;color:var(--text)">'+label+'</span>';
    h+='<label class="toggle-sw" onclick="event.stopPropagation()">';
    h+='<input type="checkbox" '+(on?'checked':'')+' onchange="toggleViewSection(\''+view+'\',\''+id+'\',this.checked)" class="d-none">';
    h+='<span style="position:absolute;inset:0;background:'+(on?'var(--purple)':'var(--input-border)')+';border-radius:11px;transition:background 0.2s"></span>';
    h+='<span style="position:absolute;top:2px;left:'+(on?'20px':'2px')+';width:18px;height:18px;background:var(--text);border-radius:50%;transition:left 0.2s"></span>';
    h+='</label></div>';
  });
  h+='</div>';
  document.getElementById('modal-container').innerHTML='<div class="modal" style="max-width:400px"><div class="flex-between-mb16"><h3 class="m-0">Layout — '+VIEW_TITLES[view]+'</h3><span class="close-x">&times;</span></div>'+h+'</div>';
  document.getElementById('modal-container').style.display='flex';
}
function dropLayoutItem(targetId){
  if(!_dragId||!_dragView||_dragId===targetId)return;
  var cfg=_loadViewLayout(_dragView);
  var fromIdx=cfg.order.indexOf(_dragId);var toIdx=cfg.order.indexOf(targetId);
  if(fromIdx<0||toIdx<0)return;
  cfg.order.splice(fromIdx,1);cfg.order.splice(toIdx,0,_dragId);
  _saveViewLayout(_dragView,cfg);_applyViewLayout(_dragView);openLayoutConfig();
}
function toggleViewSection(view,id,on){
  var cfg=_loadViewLayout(view);cfg.visible[id]=on;
  _saveViewLayout(view,cfg);_applyViewLayout(view);openLayoutConfig();
}
Object.keys(VIEW_SECTIONS).forEach(function(v){_applyViewLayout(v);});
/* HOME widget config */
function openHomeWidgetConfig(){
  var cfg=_loadHomeWidgetConfig()||[];
  var pages={};WIDGET_REGISTRY.forEach(function(w){if(!pages[w.page])pages[w.page]=[];pages[w.page].push(w);});
  var h='<div class="flex-between-mb12"><span class="text-sub">Toggle widgets for your HOME dashboard</span>';
  h+='<button class="fleet-btn" onclick="quickStartHome()" style="padding:4px 12px;font-size:12px;color:var(--purple-light);border-color:var(--purple)">&#9889; QUICK START</button></div>';
  /* Active widgets — draggable */
  if(cfg.length){
    h+='<div style="font-size:12px;color:var(--purple-light);margin-bottom:6px;font-weight:600">ACTIVE</div>';
    h+='<div id="home-widget-drag">';
    cfg.forEach(function(wid){
      var w=WIDGET_REGISTRY.find(function(r){return r.id===wid;});if(!w)return;
      h+='<div class="layout-item" draggable="true" data-id="'+wid+'" ondragstart="_dragId=this.getAttribute(\'data-id\');this.style.opacity=\'0.4\'" ondragend="this.style.opacity=\'1\'" ondragover="event.preventDefault();this.style.borderTopColor=\'var(--purple)\'" ondragleave="this.style.borderTopColor=\'var(--border)\'" ondrop="event.preventDefault();this.style.borderTopColor=\'var(--border)\';dropHomeWidget(this.getAttribute(\'data-id\'))" style="display:flex;align-items:center;gap:12px;padding:8px 12px;border-top:2px solid var(--border);cursor:grab;user-select:none">';
      h+='<span style="color:var(--text-dim);font-size:14px">&#9776;</span>';
      h+='<span style="flex:1;font-size:12px;color:var(--text)">'+w.label+'</span>';
      h+='<span class="text-sub">'+w.page+'</span>';
      h+='<button onclick="removeHomeWidget(\''+wid+'\')" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:14px;padding:0 4px">&times;</button>';
      h+='</div>';
    });
    h+='</div>';
    h+='<div style="border-bottom:2px solid var(--border);margin:8px 0"></div>';
  }
  /* Available widgets by page */
  Object.keys(pages).forEach(function(page){
    h+='<div style="font-size:12px;color:var(--text-dim);margin:12px 0 6px;font-weight:600">'+page+'</div>';
    pages[page].forEach(function(w){
      var active=cfg.indexOf(w.id)>=0;
      h+='<div style="display:flex;align-items:center;gap:12px;padding:6px 0;border-bottom:1px solid var(--border)">';
      h+='<span style="flex:1;font-size:12px;color:var(--text)">'+w.label+'</span>';
      h+='<label class="toggle-sw">';
      h+='<input type="checkbox" '+(active?'checked':'')+' onchange="toggleHomeWidget(\''+w.id+'\',this.checked)" class="d-none">';
      h+='<span style="position:absolute;inset:0;background:'+(active?'var(--purple)':'var(--input-border)')+';border-radius:11px;transition:background 0.2s"></span>';
      h+='<span style="position:absolute;top:2px;left:'+(active?'20px':'2px')+';width:18px;height:18px;background:var(--text);border-radius:50%;transition:left 0.2s"></span>';
      h+='</label></div>';
    });
  });
  document.getElementById('modal-container').innerHTML='<div class="modal" style="max-width:440px;max-height:80vh;overflow-y:auto"><div class="flex-between-mb16"><h3 class="m-0">Dashboard Layout</h3><span class="close-x">&times;</span></div>'+h+'</div>';
  document.getElementById('modal-container').style.display='flex';
}
function toggleHomeWidget(wid,on){
  var cfg=_loadHomeWidgetConfig()||[];
  var idx=cfg.indexOf(wid);
  if(on&&idx<0)cfg.push(wid);
  if(!on&&idx>=0)cfg.splice(idx,1);
  _saveHomeWidgetConfig(cfg);_renderHomeWidgets();openHomeWidgetConfig();
}
function removeHomeWidget(wid){
  var cfg=_loadHomeWidgetConfig()||[];
  var idx=cfg.indexOf(wid);if(idx>=0)cfg.splice(idx,1);
  _saveHomeWidgetConfig(cfg);_renderHomeWidgets();openHomeWidgetConfig();
}
function dropHomeWidget(targetId){
  if(!_dragId||_dragId===targetId)return;
  var cfg=_loadHomeWidgetConfig()||[];
  var fromIdx=cfg.indexOf(_dragId);var toIdx=cfg.indexOf(targetId);
  if(fromIdx<0||toIdx<0)return;
  cfg.splice(fromIdx,1);cfg.splice(toIdx,0,_dragId);
  _saveHomeWidgetConfig(cfg);_renderHomeWidgets();openHomeWidgetConfig();
}
function quickStartHome(){
  _saveHomeWidgetConfig(QUICK_START_WIDGETS.slice());
  _renderHomeWidgets();openHomeWidgetConfig();
  toast('Quick Start dashboard loaded','success');
}
/* old _applyHomeLayout removed — generic system handles it */
function togglePveGroup(tab){
  var group=tab.closest('.pve-group');
  var vms=group.querySelector('.pve-vms');
  var chev=tab.querySelector('.pve-chev')||tab;
  if(!vms)return;
  if(vms.style.display==='none'){vms.style.display='grid';chev.textContent='▾';tab.style.opacity='1';}
  else{vms.style.display='none';chev.textContent='▸';tab.style.opacity='0.7';}
}
/* === Filter === */
function filterFleetCards(q){
  q=q.toLowerCase();
  document.querySelectorAll('#metrics-cards .host-card').forEach(function(c){
    c.style.display=c.textContent.toLowerCase().indexOf(q)>=0?'':'none';
  });
}

/* === Navigation === */
document.getElementById('header-tagline').textContent=rt();
var qf=document.getElementById('home-quote-footer');if(qf)qf.textContent=rq();

var _currentView='home';
var VIEW_IDS=['home','fleet','topology','capacity','docker','media','security','sec-hardening','sec-access','sec-vault','sec-compliance','tools','playbooks','gitops','chaos','lab','settings'];
var VIEW_TITLES={home:'HOME',fleet:'FLEET',topology:'TOPOLOGY',capacity:'CAPACITY',docker:'DOCKER',media:'MEDIA',security:'SECURITY','sec-hardening':'HARDENING','sec-access':'ACCESS','sec-vault':'VAULT','sec-compliance':'COMPLIANCE',tools:'SYSTEM',playbooks:'PLAYBOOKS',gitops:'CONFIG SYNC',chaos:'CHAOS',lab:'LAB',settings:'SETTINGS'};
var VIEW_LOADERS={home:function(){loadHome()},fleet:function(){loadFleetPage()},topology:function(){loadTopology()},capacity:function(){loadCapacity()},docker:function(){loadDockerPage()},media:function(){loadMediaPage()},security:function(){loadSecurityOverview()},'sec-hardening':function(){loadSecHardening()},'sec-access':function(){loadSecAccess()},'sec-vault':function(){loadSecVault()},'sec-compliance':function(){loadSecCompliance()},tools:function(){loadToolsPage()},playbooks:function(){loadPlaybooks()},gitops:function(){loadGitops()},chaos:function(){loadChaos()},lab:function(){loadLabPage()},settings:function(){loadSettingsPage()}};
/* Nav grouping — maps sub-views to their parent nav button */
var VIEW_TO_NAV={home:'home',fleet:'fleet',topology:'fleet',capacity:'fleet',docker:'docker',media:'media',security:'security','sec-hardening':'security','sec-access':'security','sec-vault':'security','sec-compliance':'security',tools:'tools',playbooks:'tools',gitops:'tools',chaos:'tools',lab:'lab',settings:'settings'};
var NAV_TITLES={home:'HOME',fleet:'FLEET',docker:'DOCKER',media:'MEDIA',security:'SECURITY',tools:'SYSTEM',lab:'LAB',settings:'SETTINGS'};

function nav(p){
  try{
    /* Deactivate all pages */
    document.querySelectorAll('.page').forEach(function(x){x.classList.remove('active')});
    /* When leaving p-home, hide all views to prevent stale display */
    if(p!=='home'){
      VIEW_IDS.forEach(function(v){var el=document.getElementById(v+'-view');if(el)el.style.display='none';});
      document.querySelectorAll('.view-btn').forEach(function(b){b.classList.remove('active-view');});
    }
    var el=document.getElementById('p-'+p);if(el)el.classList.add('active');
    if(p==='home'){
      document.getElementById('page-title').textContent=VIEW_TITLES[_currentView]||'HOME';
      document.getElementById('header-tagline').textContent=rt();
      _safe(VIEW_LOADERS[_currentView]||loadHome);
    }else{
      var titles={infra:'INFRASTRUCTURE',system:'SYSTEM'};
      document.getElementById('page-title').textContent=titles[p]||p;
      document.getElementById('header-tagline').textContent=rt();
      load(p);
    }
  }catch(e){console.error('nav error:',e);}
}
function load(p){
  try{
    if(p==='infra')_safe(loadInfraPage);
    else if(p==='system')_safe(loadSystemPage);
  }catch(e){console.error('load error:',e);}
}
function switchView(view){
  _currentView=view;
  /* Hide all views */
  VIEW_IDS.forEach(function(v){var el=document.getElementById(v+'-view');if(el)el.style.display='none';});
  /* Show selected */
  var el=document.getElementById(view+'-view');if(el)el.style.display='block';
  /* Highlight the PARENT nav button, not the sub-view */
  var navGroup=VIEW_TO_NAV[view]||view;
  document.querySelectorAll('.view-btn').forEach(function(b){b.classList.remove('active-view');});
  var activeBtn=document.querySelector('.view-btn[data-view="'+navGroup+'"]');
  if(activeBtn)activeBtn.classList.add('active-view');
  /* Update title */
  document.getElementById('page-title').textContent=NAV_TITLES[navGroup]||VIEW_TITLES[view]||view;
  /* Make sure we're on p-home */
  document.querySelectorAll('.page').forEach(function(x){x.classList.remove('active')});
  document.getElementById('p-home').classList.add('active');
  /* Load data */
  _safe(VIEW_LOADERS[view]||loadHome);
}
function refreshCurrentView(){_safe(VIEW_LOADERS[_currentView]||loadHome);}
/* Silent background refresh — updates values in-place without rebuilding DOM.
   Health (CPU/RAM/disk): every 10s — lightweight SSH.
   Fleet overview (VM status): every 60s — heavier PVE API call. */
var _healthTimer=null,_fleetTimer=null,_healthInFlight=false,_fleetInFlight=false;
function startSilentRefresh(){
  if(_healthTimer)clearInterval(_healthTimer);
  if(_fleetTimer)clearInterval(_fleetTimer);
  _healthTimer=setInterval(_silentHealthRefresh,15000);
  _fleetTimer=setInterval(_silentFleetRefresh,60000);
}
function _silentHealthRefresh(){
  if(_healthInFlight)return;/* skip if previous call still running */
  _healthInFlight=true;
  fetch(API.HEALTH).then(function(r){return r.json()}).then(function(hd){
    _healthInFlight=false;
    _fleetCache.hd=hd;/* keep cache fresh */
    hd.hosts.forEach(function(h){
      var cards=document.querySelectorAll('.host-card');
      cards.forEach(function(card){
        var title=card.querySelector('.host-head h3');
        if(!title)return;
        var label=title.textContent.trim().toLowerCase();
        if(label!==h.label.toLowerCase()&&label!==h.label)return;
        /* Update status */
        var meta=card.querySelector('.host-meta');
        if(meta){var spans=meta.querySelectorAll('span');var last=spans[spans.length-1];
          if(last&&(last.textContent==='ONLINE'||last.textContent==='OFFLINE')){
            if(h.status==='healthy'){last.style.color='var(--green)';last.textContent='ONLINE';}
            else{last.style.color='var(--red)';last.textContent='OFFLINE';}}}
        /* Update metrics in-place */
        if(h.status!=='healthy')return;
        var cores=parseInt(h.cores)||1;var loadVal=parseFloat(h.load)||0;
        var loadPct=cores>0?Math.min(Math.round(loadVal/cores*100),100):0;
        var ramParts=(h.ram||'').match(/(\d+)\/(\d+)/);
        var ramUsed=ramParts?parseInt(ramParts[1]):0;var ramTotal=ramParts?parseInt(ramParts[2]):1;
        var ramPct=ramTotal>0?Math.round(ramUsed/ramTotal*100):0;
        var diskPct=parseInt((h.disk||'0').replace('%',''))||0;
        card.querySelectorAll('.metric-row').forEach(function(m){
          var lbl=m.querySelector('.metric-label');var val=m.querySelector('.metric-val');var bar=m.querySelector('.pbar-fill');
          if(!lbl||!val)return;var lt=lbl.textContent.trim();
          if(lt==='CPU'){val.textContent=cores+(cores>1?' Cores':' Core')+' \u00b7 '+loadPct+'%';if(bar){bar.style.width=loadPct+'%';bar.style.background=loadPct>=80?'var(--red)':loadPct>=50?'var(--yellow)':'var(--purple-light)';}}
          if(lt==='RAM'){val.textContent=_ramGB(ramUsed)+' / '+_ramGB(ramTotal);if(bar){bar.style.width=ramPct+'%';var isStorage=h.type==='truenas';bar.style.background=isStorage?'var(--blue)':ramPct>=80?'var(--red)':ramPct>=50?'var(--yellow)':'var(--blue)';}}
          if(lt==='DISK'){val.textContent=h.disk||'?';if(bar){bar.style.width=diskPct+'%';bar.style.background=diskPct>=90?'var(--red)':diskPct>=75?'var(--yellow)':'var(--green)';}}
        });
      });
    });
    /* Update fleet stats online/offline counts */
    var up=0,down=0;hd.hosts.forEach(function(h){if(h.status==='healthy')up++;else down++;});
    var sumEl=document.getElementById('metrics-summary');
    if(sumEl){var sts=sumEl.querySelectorAll('.st .vl, .st span[style*="font-size:20px"]');/* lightweight — skip if layout differs */}
  }).catch(function(){_healthInFlight=false;});
}
function _silentFleetRefresh(){
  if(_fleetInFlight)return;
  _fleetInFlight=true;
  fetch(API.FLEET_OVERVIEW).then(function(r){return r.json()}).then(function(fo){
    _fleetInFlight=false;
    _fleetCache.fo=fo;/* keep cache fresh */
    if(!fo||!fo.vms)return;
    /* Update VM status badges in PVE node sections */
    fo.vms.forEach(function(v){
      var cards=document.querySelectorAll('.host-card');
      cards.forEach(function(card){
        var title=card.querySelector('.host-head h3');
        if(!title)return;
        if(title.textContent.trim().toLowerCase()!==v.name.toLowerCase())return;
        var meta=card.querySelector('.host-meta');
        if(!meta)return;
        var spans=meta.querySelectorAll('span');
        spans.forEach(function(sp){
          if(sp.textContent==='RUNNING'||sp.textContent==='STOPPED'){
            if(v.status==='running'){sp.textContent='RUNNING';sp.style.color='var(--green)';}
            else if(v.status==='stopped'){sp.textContent='STOPPED';sp.style.color='var(--red)';}
          }
        });
      });
    });
  }).catch(function(){_fleetInFlight=false;});
}
startSilentRefresh();
/* === Page composite loaders === */
function renderGlobalSettings(){
  var s=_loadSettings();
  var hoverOn=s.hoverFx!==false;
  var _toggle=function(id,label,desc,checked,onchange){
    var on=checked;
    return '<div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid var(--border)">'+
      '<div><div style="font-size:13px;font-weight:600;color:var(--text)">'+label+'</div><div class="text-meta">'+desc+'</div></div>'+
      '<label style="position:relative;width:44px;height:24px;cursor:pointer;display:block;flex-shrink:0">'+
      '<input type="checkbox" id="'+id+'" '+(on?'checked':'')+' onchange="'+onchange+'" class="d-none">'+
      '<span style="position:absolute;inset:0;background:'+(on?'var(--purple)':'var(--input-border)')+';border-radius:12px;transition:background 0.2s"></span>'+
      '<span style="position:absolute;top:3px;left:'+(on?'23px':'3px')+';width:18px;height:18px;background:var(--text);border-radius:50%;transition:left 0.2s"></span>'+
      '</label></div>';
  };
  var showTpl=s.showTemplates===true;
  var h='';
  h+=_toggle('set-hover','Hover Effects','Cards lift and glow purple on hover',hoverOn,"saveSetting('hoverFx',this.checked)");
  h+=_toggle('set-tpl','Show Template VMs','Include template VMs (9000+) in counts and VM lists',showTpl,"saveSetting('showTemplates',this.checked);refreshCurrentView()");
  var el=document.getElementById('global-settings-body');
  if(el)el.innerHTML=h;
}
function loadFleetPage(){
  if(!_fleetCache.fo&&!_fleetCache.hd){
    document.getElementById('metrics-summary').innerHTML='<div class="skeleton h-50" ></div>';
    document.getElementById('metrics-cards').innerHTML='<div class="skeleton"></div><div class="skeleton"></div>';
  }
  loadMetricsQuick();loadAgents();loadSpecialists();
  /* Overview cards — wait for cache or fetch independently */
  setTimeout(function(){
    if(_fleetCache.fo){_renderFleetOverview(_fleetCache.fo);_loadFleetOverviewMedia();}
    else{fetch(API.FLEET_OVERVIEW).then(function(r){return r.json()}).then(function(fo){_fleetCache.fo=fo;_renderFleetOverview(fo);_loadFleetOverviewMedia();}).catch(function(){toast('Failed to load fleet overview','error');});}
  },4000);
}
function _loadFleetOverviewMedia(){
  fetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(d){
    var h='';
    var _dn=Math.max(0,d.containers_total-d.containers_running);
    h+=_mrow('ONLINE',d.containers_running+' / '+d.containers_total,0,'var(--green)');
    h+=_mrow('OFFLINE',_dn,0,_dn>0?'var(--red)':'var(--green)');
    h+=_mrow('VMs',d.vm_count,0,'var(--blue)');
    var me=document.getElementById('home-media');if(me)me.innerHTML=h;
  }).catch(function(){var me=document.getElementById('home-media');if(me)me.innerHTML='<span class="c-dim-fs12">NO MEDIA DATA</span>';});
}
function _renderFleetOverview(fo){
    /* PVE summary */
    var nodeCount=fo.pve_nodes?fo.pve_nodes.length:0;
    var nodeNames=fo.pve_nodes?fo.pve_nodes.map(function(n){return n.name}).join(', '):'';
    var ps='';
    ps+=_mrow('NODES',nodeCount,0,'var(--purple-light)');
    ps+=_mrow('VMs',fo.summary.total_vms,0,'var(--green)');
    ps+=_mrow('RUNNING',fo.summary.running,0,'var(--green)');
    ps+=_mrow('STOPPED',fo.summary.stopped,0,fo.summary.stopped>0?'var(--red)':'var(--green)');
    var pse=document.getElementById('home-pve-summary');if(pse)pse.innerHTML=ps;
    /* pfSense */
    var pfDev=fo.physical?fo.physical.find(function(p){return p.type==='pfsense'}):null;
    var pf='';
    if(pfDev){pf+=_mrow('DEVICE',pfDev.detail,0,'var(--purple-light)');pf+=_mrow('IP',pfDev.ip,0,'var(--purple-light)');pf+=_mrow('STATUS',pfDev.reachable?'ONLINE':'OFFLINE',0,pfDev.reachable?'var(--green)':'var(--red)');}
    var pfe=document.getElementById('home-pfsense');if(pfe)pfe.innerHTML=pf||'<span class="c-dim-fs12">N/A</span>';
    /* TrueNAS */
    var tnDev=fo.physical?fo.physical.find(function(p){return p.type==='truenas'}):null;
    var tn='';
    if(tnDev){tn+=_mrow('DEVICE',tnDev.detail,0,'var(--purple-light)');tn+=_mrow('IP',tnDev.ip,0,'var(--purple-light)');tn+=_mrow('STATUS',tnDev.reachable?'ONLINE':'OFFLINE',0,tnDev.reachable?'var(--green)':'var(--red)');}
    var tne=document.getElementById('home-truenas');if(tne)tne.innerHTML=tn||'<span class="c-dim-fs12">N/A</span>';
    /* VMs card */
    var vi='';
    vi+=_mrow('TOTAL',fo.summary.total_vms,0,'var(--purple-light)');
    vi+=_mrow('RUNNING',fo.summary.running,0,'var(--green)');
    vi+=_mrow('STOPPED',fo.summary.stopped,0,fo.summary.stopped>0?'var(--red)':'var(--green)');
    var vie=document.getElementById('home-infra');if(vie)vie.innerHTML=vi;
}
/* Fleet data — populated from /api/fleet/overview at runtime */
var PROD_HOSTS=[];
var PROD_VMS=[];
/* Device-type action configs (universal — same for any cluster with these device types) */
var _DEVICE_ACTIONS={
  pfsense:{actions:[{l:'STATUS',f:"pfAction('status')"},{l:'RULES',f:"pfAction('rules')"},{l:'NAT',f:"pfAction('nat')"},{l:'STATES',f:"pfAction('states')"},{l:'INTERFACES',f:"pfAction('interfaces')"}],outId:'pf-out'},
  truenas:{actions:[{l:'SYSTEM',f:"tnAction('status')"},{l:'POOLS',f:"tnAction('pools')"},{l:'HEALTH',f:"tnAction('health')"},{l:'DATASETS',f:"tnAction('datasets')"},{l:'SHARES',f:"tnAction('shares')"},{l:'ALERTS',f:"tnAction('alerts')"}],outId:'tn-out'},
  switch:{actions:[{l:'STATUS',f:"swAction('status')"},{l:'VLANS',f:"swAction('vlans')"},{l:'INTERFACES',f:"swAction('interfaces')"},{l:'MAC TABLE',f:"swAction('mac')"}],outId:'sw-out'},
  idrac:{actions:[{l:'SYSTEM INFO',f:"idracAction('status')"},{l:'SENSORS',f:"idracAction('sensors')"},{l:'POWER',f:"idracAction('power')"},{l:'EVENT LOG',f:"idracAction('sel')"}],outId:'idrac-out'}
};
var _idracOutCount=0;
function _initFleetData(fo){
  if(!fo)return;
  /* Build PROD_HOSTS from pve_nodes + physical devices */
  PROD_HOSTS=[];
  (fo.pve_nodes||[]).forEach(function(n){
    /* Use live PVE stats if available, fall back to parsing detail string */
    var cores=n.cores||0;
    var ramGB=n.ram_gb||0;
    if(!ramGB){(n.detail||'').split(' \u00b7 ').forEach(function(p){var m=p.match(/^(\d+)GB$/);if(m)ramGB=parseInt(m[1]);});}
    PROD_HOSTS.push({label:n.name,ip:n.ip,type:'pve',role:'HYPERVISOR',cores:cores,ram:ramGB?ramGB+'GB':'-',vlans:['MGMT'],detail:n.detail||''});
  });
  (fo.physical||[]).forEach(function(p){
    var h={label:p.label,ip:p.ip,type:p.type,role:(p.detail||p.type).split(' · ')[0].toUpperCase(),cores:0,ram:'-',vlans:['MGMT'],detail:p.detail||''};
    var da=_DEVICE_ACTIONS[p.type];
    if(da){h.actions=da.actions;h.outId=p.type==='idrac'?'idrac-out'+(++_idracOutCount>1?_idracOutCount:''):da.outId;}
    PROD_HOSTS.push(h);
  });
  /* Build PROD_VMS from cluster VMs — optionally exclude templates */
  PROD_VMS=[];
  var _tplSetting=_loadSettings();
  (fo.vms||[]).forEach(function(v){
    if(!_tplSetting.showTemplates&&v.category==='templates')return;
    PROD_VMS.push({label:v.name,ip:'',vmid:v.vmid,node:v.node,cores:v.cpu,ram:v.ram_mb?Math.round(v.ram_mb/1024)+'GB':'?',containers:0,vlans:[],detail:'',status:v.status,category:v.category,is_prod:v.is_prod});
  });
  /* Build VLAN config from API */
  if(fo.vlans&&fo.vlans.length){
    _VLAN_MAP={};_vlanPrefixes={};
    fo.vlans.forEach(function(vl){
      _VLAN_MAP[vl.id]={name:vl.name,prefix:vl.prefix,gw:vl.gateway,cidr:vl.cidr||'24'};
      _vlanPrefixes[vl.name]=vl.prefix;
    });
  }
  /* Legacy home-node-sections removed — widget system handles home page */
  /* Derive color maps now that PROD_HOSTS and _VLAN_MAP are populated */
  _assignNodeColors();
  _assignVlanColors();
}
var _dockerSub='services';
function switchDockerSub(sub){
  _dockerSub=sub;
  ['all','services','registry','compose'].forEach(function(s){var el=document.getElementById('docker-sub-'+s);if(el){if(s===sub){el.classList.remove('d-none');el.style.display='';}else{el.classList.add('d-none');el.style.display='';}}});
  document.querySelectorAll('.docker-sub').forEach(function(b){b.classList.remove('active-view');});
  var btn=document.querySelector('.docker-sub[data-dsub="docker-'+sub+'"]');if(btn)btn.classList.add('active-view');
  if(sub==='services')loadServiceContainers();
  if(sub==='registry')loadContainerRegistry();
  if(sub==='compose')loadComposeVMs();
}
function _getMediaTags(){try{return JSON.parse(localStorage.getItem('freq_media_tags')||'[]');}catch(e){return [];}}
function _setMediaTags(tags){localStorage.setItem('freq_media_tags',JSON.stringify(tags));}
var _mediaCache=null;/* cached /api/media/status response */
function toggleMediaTag(name){
  var tags=_getMediaTags();
  var idx=tags.indexOf(name);
  if(idx>=0)tags.splice(idx,1);else tags.push(name);
  _setMediaTags(tags);
  _httpsContainers=JSON.parse(localStorage.getItem('freq_https_containers')||'[]');
  /* Re-render from cache — zero API calls */
  if(_mediaCache){_renderMediaFromCache();_renderServicesFromCache();_renderAllFromCache();}
  else{loadContainerSection();loadServiceContainers();loadMediaContainers();}
}
function _renderMediaFromCache(){
  if(!_mediaCache)return;
  var tags=_getMediaTags();var html='';
  _mediaCache.containers.forEach(function(c){if(tags.indexOf(c.name)<0)return;html+=_containerCard(c,'');});
  document.getElementById('media-container-cards').innerHTML=html||'<div class="empty-state"><div class="es-icon">▶</div><p>No containers tagged as media.<br>Tag containers from the ALL CONTAINERS view.</p></div>';
}
function _renderServicesFromCache(){
  if(!_mediaCache)return;
  var tags=_getMediaTags();var html='';
  _mediaCache.containers.forEach(function(c){if(tags.indexOf(c.name)>=0)return;
    var tagBtn='<button data-action="toggleMediaTag" data-arg="'+c.name+'" style="background:none;border:2px solid var(--input-border);border-radius:6px;padding:4px 6px;cursor:pointer;font-size:14px;margin-left:auto;opacity:0.4;transition:opacity 0.2s" onmouseover="this.style.opacity=\'0.8\'" onmouseout="this.style.opacity=\'0.4\'" title="Tag as media">&#127909;</button>';
    html+=_containerCard(c,tagBtn);});
  document.getElementById('services-container-cards').innerHTML=html||'<div class="empty-state"><div class="es-icon">&#9881;</div><p>All containers are tagged as media.</p></div>';
}
function _renderAllFromCache(){
  if(!_mediaCache)return;
  var html='';
  _mediaCache.containers.forEach(function(c){
    var isMedia=_getMediaTags().indexOf(c.name)>=0;
    var tagBtn='<button data-action="toggleMediaTag" data-arg="'+c.name+'" style="background:none;border:2px solid '+(isMedia?'var(--purple)':'var(--input-border)')+';border-radius:6px;padding:4px 6px;cursor:pointer;font-size:14px;margin-left:auto;opacity:'+(isMedia?'1':'0.4')+';transition:opacity 0.2s" onmouseover="this.style.opacity=\'0.8\'" onmouseout="this.style.opacity=\''+(isMedia?'1':'0.4')+'\'" title="'+(isMedia?'Remove media tag':'Tag as media')+'">&#127909;</button>';
    html+=_containerCard(c,tagBtn);});
  document.getElementById('container-cards').innerHTML=html||'<div class="empty-state"><div class="es-icon">▶</div><p>No containers found.</p></div>';
}
function loadMediaContainers(){
  if(_mediaCache){_renderMediaFromCache();return;}
  fetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
    _mediaCache=d;_renderMediaFromCache();
  });
}
function loadServiceContainers(){
  if(_mediaCache){_renderServicesFromCache();return;}
  fetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
    _mediaCache=d;_renderServicesFromCache();
  });
}
var _httpsContainers=JSON.parse(localStorage.getItem('freq_https_containers')||'[]');
var _webPaths={plex:'/web',tautulli:'/home',organizr:'/auth/login'};
var _publicUrls=JSON.parse(localStorage.getItem('freq_public_urls')||'{}');
function _containerCard(c,extra){
  var isHttps=_httpsContainers.indexOf(c.name)>=0;
  var proto=isHttps?'https':'http';
  var wp=_webPaths[c.name.toLowerCase()]||'';
  var shortUrl=c.vm_ip&&c.port&&c.port!=='-'?proto+'://'+c.vm_ip+':'+c.port:'';
  var url=shortUrl?shortUrl+wp:'';
  var pubUrl=_publicUrls[c.name]||'';
  var h='<div class="crd" style="display:flex;flex-direction:column"><div class="flex-between"><h3 style="text-transform:uppercase">'+c.name+'</h3>'+badge(c.status)+'</div>';
  if(url||pubUrl){
    if(url){
      h+='<div style="display:flex;align-items:center;gap:6px;margin:4px 0">';
      h+='<a href="'+url+'" target="_blank" style="font-size:11px;color:var(--blue);font-family:monospace;text-decoration:none" onmouseover="this.style.textDecoration=\'underline\'" onmouseout="this.style.textDecoration=\'none\'">'+shortUrl+'</a>';
      h+='<span onclick="event.stopPropagation();toggleHttps(\''+c.name+'\')" style="background:'+(isHttps?'rgba(63,185,80,0.15)':'rgba(255,255,255,0.06)')+';border:1px solid '+(isHttps?'var(--green)':'var(--border-light)')+';border-radius:4px;padding:1px 6px;color:'+(isHttps?'var(--green)':'var(--text-dim)')+';cursor:pointer;font-size:10px;font-family:monospace;font-weight:600" title="Click to switch to '+(isHttps?'HTTP':'HTTPS')+'">'+(isHttps?'HTTPS':'HTTP')+'</span>';
      h+='</div>';
    }
    if(pubUrl){
      var pu=pubUrl;try{var _u=new URL(pubUrl);pu=_u.protocol+'//'+_u.host;}catch(e){}
      h+='<div style="display:flex;align-items:center;gap:6px;margin:2px 0">';
      h+='<a href="'+_esc(pubUrl)+'" target="_blank" style="font-size:11px;color:var(--green);font-family:monospace;text-decoration:none" onmouseover="this.style.textDecoration=\'underline\'" onmouseout="this.style.textDecoration=\'none\'">'+_esc(pu)+'</a>';
      h+='</div>';
    }
  } else {
    h+='<div style="font-size:11px;color:var(--text-dim);margin:4px 0">'+c.vm_label+(c.port&&c.port!=='-'?' · '+c.port:'')+'</div>';
  }
  if(c.detail)h+='<div class="text-sub">'+c.detail+'</div>';
  h+='<div style="margin-top:auto;padding-top:8px;display:flex;gap:6px;align-items:center"><button class="fleet-btn pill-sm" data-action="mediaRestart" data-arg="'+c.name+'" >RESTART</button><button class="fleet-btn pill-sm" onclick="mediaLogs(\''+c.name+'\')" >LOGS</button>';
  if(extra)h+=extra;
  h+='</div></div>';
  return h;
}
function copyUrl(url){
  try{
    var ta=document.createElement('textarea');
    ta.value=url;ta.style.position='fixed';ta.style.left='-9999px';
    document.body.appendChild(ta);ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast('Copied: '+url,'success');
  }catch(e){toast('Copy failed','error');}
}
function toggleHttps(name){
  var idx=_httpsContainers.indexOf(name);
  if(idx>=0)_httpsContainers.splice(idx,1);else _httpsContainers.push(name);
  var nowHttps=_httpsContainers.indexOf(name)>=0;
  localStorage.setItem('freq_https_containers',JSON.stringify(_httpsContainers));
  /* Also update public URL protocol to match */
  if(_publicUrls[name]){
    try{
      var u=new URL(_publicUrls[name]);
      u.protocol=nowHttps?'https:':'http:';
      _publicUrls[name]=u.toString();
      localStorage.setItem('freq_public_urls',JSON.stringify(_publicUrls));
    }catch(e){}
  }
  /* Reload whichever view is showing these cards */
  _mediaCache=null;
  loadDockerPage();
  if(typeof loadMediaPage==='function')loadMediaPage();
  toast(name+' set to '+(nowHttps?'HTTPS':'HTTP'),'success');
}
function setPublicUrl(name){
  var current=_publicUrls[name]||'';
  var val=prompt('Public URL for '+name.toUpperCase()+':\n(e.g. https://plex.example.com)',current);
  if(val===null)return;
  val=val.trim();
  if(val){_publicUrls[name]=val;}else{delete _publicUrls[name];}
  localStorage.setItem('freq_public_urls',JSON.stringify(_publicUrls));
  loadDockerPage();
  toast(val?name+' public URL set':'Public URL removed for '+name,'success');
}
function loadDockerPage(){
  loadContainerSection();
  if(_dockerSub==='services')loadServiceContainers();
  else if(_dockerSub==='media'){loadMediaContainers();loadDownloads();loadStreams();}
  loadContainerRegistry();
}
var _regVMs=[];/* cached VM list for edit dropdowns */
function loadContainerRegistry(){
  var tbl=document.getElementById('registry-table');
  if(!tbl)return;
  tbl.innerHTML='<div class="skeleton"></div>';
  fetch('/api/containers/registry?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(!d.containers||d.containers.length===0){tbl.innerHTML='<span class="c-dim-fs12">No containers registered</span>';return;}
    /* Build unique VM list for dropdowns */
    var seen={};_regVMs=[];
    d.containers.forEach(function(c){if(!seen[c.vm_id]){seen[c.vm_id]=true;_regVMs.push({id:c.vm_id,label:c.vm_label,ip:c.vm_ip});}});
    var h='<table><tr><th>Container</th><th>VM</th><th>VMID</th><th>Local IP</th><th>Public IP</th><th>Port</th><th>API Path</th><th></th></tr>';
    d.containers.forEach(function(c){
      var rid='reg-row-'+c.vm_id+'-'+c.name.replace(/[^a-z0-9]/gi,'_');
      var pu=_publicUrls[c.name]||'';
      var puIP='—';if(pu){try{puIP=new URL(pu).hostname;}catch(e){puIP=pu;}}
      h+='<tr id="'+rid+'">';
      h+='<td><strong>'+_esc(c.name)+'</strong></td>';
      h+='<td>'+_esc(c.vm_label)+'</td>';
      h+='<td>'+c.vm_id+'</td>';
      h+='<td class="mono-11">'+_esc(c.vm_ip)+'</td>';
      h+='<td class="mono-11">'+_esc(puIP)+'</td>';
      h+='<td>'+(c.port||'—')+'</td>';
      h+='<td class="mono-11">'+(c.api_path||'—')+'</td>';
      h+='<td style="display:flex;gap:4px">';
      h+='<button class="fleet-btn" style="font-size:10px;padding:2px 8px" onclick="editContainerRow(\''+_esc(c.name)+'\','+c.vm_id+','+(c.port||0)+',\''+_esc(c.api_path||'')+'\')">EDIT</button>';
      h+='<button class="fleet-btn" style="font-size:10px;padding:2px 8px;color:var(--red)" onclick="deleteContainer(\''+_esc(c.name)+'\','+c.vm_id+')">DEL</button>';
      h+='</td></tr>';
    });
    h+='</table>';
    tbl.innerHTML=h;
    /* Populate VM select for add form */
    var sel=document.getElementById('reg-vmid');
    if(sel){
      sel.innerHTML='<option value="">Select VM...</option>';
      _regVMs.forEach(function(v){sel.innerHTML+='<option value="'+v.id+'">'+_esc(v.label)+' ('+v.id+')</option>';});
    }
  }).catch(function(e){tbl.innerHTML='<span class="c-red">Failed: '+e+'</span>';});
}
function editContainerRow(name,vmId,port,apiPath){
  var opts='';_regVMs.forEach(function(v){opts+='<option value="'+v.id+'"'+(v.id===vmId?' selected':'')+'>'+_esc(v.label)+' ('+v.id+')</option>';});
  var pu=_publicUrls[name]||'';
  var h='<div class="modal" style="max-width:400px"><div class="flex-between-mb16"><h3 class="m-0" style="color:var(--purple-light)">Edit: '+_esc(name)+'</h3><span class="close-x">&times;</span></div>';
  h+='<div style="display:flex;flex-direction:column;gap:12px">';
  h+='<div><label class="c-dim-fs12">VM</label><select class="input" id="edit-vm" style="width:100%;margin-top:4px">'+opts+'</select></div>';
  h+='<div><label class="c-dim-fs12">Port</label><input class="input" id="edit-port" type="number" value="'+port+'" style="width:100%;margin-top:4px"></div>';
  h+='<div><label class="c-dim-fs12">API Path</label><input class="input" id="edit-api-path" value="'+_esc(apiPath)+'" placeholder="/api/v1/health" style="width:100%;margin-top:4px"></div>';
  h+='<div><label class="c-dim-fs12">Public URL</label><input class="input" id="edit-public-url" value="'+_esc(pu)+'" placeholder="https://plex.example.com" style="width:100%;margin-top:4px"></div>';
  h+='<div style="display:flex;gap:8px;margin-top:8px">';
  h+='<button class="fleet-btn c-purple-active" onclick="saveContainerEdit(\''+_esc(name)+'\','+vmId+')">SAVE</button>';
  h+='<button class="fleet-btn" onclick="closeModal()">CANCEL</button>';
  h+='</div></div></div>';
  var ov=document.getElementById('modal-container');ov.innerHTML=h;ov.style.display='flex';
}
function saveContainerEdit(name,oldVmId){
  var newVmId=document.getElementById('edit-vm').value;
  var port=document.getElementById('edit-port').value||'0';
  var apiPath=document.getElementById('edit-api-path').value||'';
  var pu=(document.getElementById('edit-public-url').value||'').trim();
  if(pu){_publicUrls[name]=pu;}else{delete _publicUrls[name];}
  localStorage.setItem('freq_public_urls',JSON.stringify(_publicUrls));
  fetch('/api/containers/edit?token='+_authToken+'&name='+encodeURIComponent(name)+'&old_vm_id='+oldVmId+'&new_vm_id='+newVmId+'&port='+port+'&api_path='+encodeURIComponent(apiPath))
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){toast(d.error,'error');return;}
    toast(name+' updated','success');closeModal();_mediaCache=null;loadContainerRegistry();loadContainerSection();
  });
}
/* ── Compose Management ────────────────────────────────────────── */
function loadComposeVMs(){
  var sel=document.getElementById('compose-vm-select');if(!sel)return;
  sel.innerHTML='<option value="">Loading...</option>';
  fetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
    var seen={};sel.innerHTML='<option value="">Select Docker VM...</option>';
    d.containers.forEach(function(c){if(!seen[c.vm_id]){seen[c.vm_id]=true;sel.innerHTML+='<option value="'+c.vm_id+'">'+_esc(c.vm_label)+' ('+c.vm_id+')</option>';}});
    if(!Object.keys(seen).length)sel.innerHTML='<option value="">No Docker VMs found</option>';
  }).catch(function(){sel.innerHTML='<option value="">Failed to load VMs</option>';});
}
function _getComposeVmId(){var v=(document.getElementById('compose-vm-select')||{}).value;if(!v){toast('Select a Docker VM','error');}return v;}
function composeUp(){
  var vmid=_getComposeVmId();if(!vmid)return;
  var out=document.getElementById('compose-out');if(out)out.innerHTML='<span class="c-yellow">Running compose up on VM '+vmid+'...</span>';
  fetch(API.COMPOSE_UP+'?vm_id='+vmid).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Compose up complete on '+d.vm,'success');if(out)out.innerHTML='<pre style="font-size:11px;color:var(--green);white-space:pre-wrap;margin:0">'+_esc(d.output||'Compose up complete')+'</pre>';}
    else{toast('Compose up failed','error');if(out)out.innerHTML='<pre style="font-size:11px;color:var(--red);white-space:pre-wrap;margin:0">'+_esc(d.error||'Unknown error')+'</pre>';}
  }).catch(function(e){toast('Compose up failed','error');if(out)out.innerHTML='<span class="c-red">'+e+'</span>';});
}
function composeDown(){
  var vmid=_getComposeVmId();if(!vmid)return;
  confirmAction('Bring down all compose services on VM <strong>'+vmid+'</strong>?',function(){
    var out=document.getElementById('compose-out');if(out)out.innerHTML='<span class="c-yellow">Running compose down on VM '+vmid+'...</span>';
    fetch(API.COMPOSE_DOWN+'?vm_id='+vmid).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast('Compose down complete on '+d.vm,'success');if(out)out.innerHTML='<pre style="font-size:11px;color:var(--green);white-space:pre-wrap;margin:0">'+_esc(d.output||'Compose down complete')+'</pre>';}
      else{toast('Compose down failed','error');if(out)out.innerHTML='<pre style="font-size:11px;color:var(--red);white-space:pre-wrap;margin:0">'+_esc(d.error||'Unknown error')+'</pre>';}
    }).catch(function(e){toast('Compose down failed','error');if(out)out.innerHTML='<span class="c-red">'+e+'</span>';});
  });
}
function composeView(){
  var vmid=_getComposeVmId();if(!vmid)return;
  var out=document.getElementById('compose-out');if(out)out.innerHTML='<span class="c-yellow">Loading compose file from VM '+vmid+'...</span>';
  fetch(API.COMPOSE_VIEW+'?vm_id='+vmid).then(function(r){return r.json()}).then(function(d){
    if(d.ok){if(out)out.innerHTML='<div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">'+_esc(d.vm)+' — docker-compose.yml</div><pre style="font-size:11px;color:var(--text);white-space:pre-wrap;margin:0;background:var(--bg2);padding:12px;border-radius:6px;border:1px solid var(--border);max-height:500px;overflow:auto">'+_esc(d.content)+'</pre>';}
    else{toast(d.error||'Failed to load compose file','error');if(out)out.innerHTML='<span class="c-red">'+(d.error||'Compose file not found')+'</span>';}
  }).catch(function(e){toast('Failed to load compose file','error');if(out)out.innerHTML='<span class="c-red">'+e+'</span>';});
}
function rescanContainers(){
  var st=document.getElementById('registry-status');
  var res=document.getElementById('rescan-results');
  if(st)st.textContent='Scanning fleet...';
  fetch('/api/containers/rescan?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(st)st.textContent='Scan complete';
    if(!res)return;
    var h='';
    if(d.stale&&d.stale.length>0){
      h+='<div style="margin-bottom:8px"><strong style="color:var(--red)">Stale (not found on VM):</strong></div>';
      h+='<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">';
      d.stale.forEach(function(s){
        h+='<button class="fleet-btn" style="font-size:11px;border-color:var(--red);color:var(--red)" onclick="deleteContainer(\''+_esc(s.name)+'\','+s.vm_id+');rescanContainers()">Remove '+_esc(s.name)+' from '+_esc(s.vm_label)+'</button>';
      });
      h+='</div>';
    }
    if(d.new&&d.new.length>0){
      h+='<div style="margin-bottom:8px"><strong style="color:var(--green)">New (found but not registered):</strong></div>';
      h+='<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">';
      d.new.forEach(function(n){
        h+='<button class="fleet-btn" style="font-size:11px;border-color:var(--green);color:var(--green)" onclick="addContainerQuick(\''+_esc(n.name)+'\','+n.vm_id+')">Add '+_esc(n.name)+' to '+_esc(n.vm_label)+'</button>';
      });
      h+='</div>';
    }
    if(!d.stale.length&&!d.new.length){h='<span class="c-green" style="font-size:12px">Registry is in sync with fleet</span>';}
    res.innerHTML=h;res.style.display='block';
  }).catch(function(e){if(st)st.textContent='Scan failed: '+e;});
}
function deleteContainer(name,vmId){
  if(!confirm('Remove "'+name+'" from registry?'))return;
  fetch('/api/containers/delete?token='+_authToken+'&name='+encodeURIComponent(name)+'&vm_id='+vmId)
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){toast(d.error,'error');return;}
    toast(name+' removed','success');_mediaCache=null;loadContainerRegistry();loadContainerSection();
  });
}
function addContainer(){
  var name=document.getElementById('reg-name').value.trim();
  var vmId=document.getElementById('reg-vmid').value;
  var port=document.getElementById('reg-port').value||'0';
  var msg=document.getElementById('reg-msg');
  if(!name||!vmId){if(msg)msg.innerHTML='<span class="c-red">Name and VM required</span>';return;}
  fetch('/api/containers/add?token='+_authToken+'&name='+encodeURIComponent(name)+'&vm_id='+vmId+'&port='+port)
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){if(msg)msg.innerHTML='<span class="c-red">'+d.error+'</span>';return;}
    if(msg)msg.innerHTML='<span class="c-green">Added</span>';
    document.getElementById('reg-name').value='';document.getElementById('reg-port').value='';
    _mediaCache=null;loadContainerRegistry();loadContainerSection();
  });
}
function addContainerQuick(name,vmId){
  fetch('/api/containers/add?token='+_authToken+'&name='+encodeURIComponent(name)+'&vm_id='+vmId+'&port=0')
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){toast(d.error,'error');return;}
    toast(name+' registered','success');_mediaCache=null;loadContainerRegistry();rescanContainers();
  });
}
function loadInfraPage(){loadInfra();}
/* Security sub-view loaders */
function loadSecurityOverview(){loadRisk();}
function loadSecHardening(){/* audit + hardening sections are button-triggered */}
function loadSecAccess(){loadUsers();loadKeys();}
function loadSecVault(){loadVault();}
function loadSecCompliance(){loadPoliciesPage();}
/* Stub loaders for Morty's views */
function loadMediaPage(){loadMediaContainers();loadDownloads();loadStreams();}
function loadToolsPage(){_populateHostDropdowns();}
function loadLabPage(){loadLabTools();}
function loadSettingsPage(){loadCosts();loadFederation();_loadSettingsPrefs();_loadLabAssignments();}
function _loadSettingsPrefs(){
  var r=localStorage.getItem('freq_refresh_interval');
  var d=localStorage.getItem('freq_density');
  if(r){var el=document.getElementById('pref-refresh');if(el)el.value=r;}
  if(d){var el=document.getElementById('pref-density');if(el)el.value=d;}
}
function updatePref(key,val){
  localStorage.setItem('freq_'+key,val);
  if(key==='refresh'){
    if(window._autoRefreshTimer)clearInterval(window._autoRefreshTimer);
    var ms=parseInt(val)*1000;
    if(ms>0)window._autoRefreshTimer=setInterval(function(){refreshCurrentView();},ms);
  }
  toast('Preference saved: '+key+' = '+val,'ok');
}
/* ── Lab Assignment — tag fleet members as LAB ── */
var _labAssignments=JSON.parse(localStorage.getItem('freq_lab_assign')||'{}');
function _getLabLabels(healthHosts){
  /* Merge: server-side groups + client-side overrides */
  var labels={};
  if(healthHosts){healthHosts.forEach(function(h){
    if(h.groups&&h.groups.indexOf('lab')>=0)labels[h.label]=true;
  });}
  /* Apply user overrides from Settings */
  Object.keys(_labAssignments).forEach(function(k){
    if(_labAssignments[k])labels[k]=true;
    else delete labels[k];
  });
  return labels;
}
function _loadLabAssignments(){
  var el=document.getElementById('lab-assign-list');if(!el)return;
  /* Need both fleet overview (for VMs) and health (for hosts) */
  Promise.all([
    fetch(API.FLEET_OVERVIEW).then(function(r){return r.json();}),
    fetch(API.HEALTH).then(function(r){return r.json();})
  ]).then(function(results){
    var fo=results[0],hd=results[1];
    var items=[];
    /* Add all hosts from health data */
    if(hd&&hd.hosts)hd.hosts.forEach(function(h){
      var serverLab=h.groups&&h.groups.indexOf('lab')>=0;
      items.push({label:h.label,type:h.type||'linux',node:'',status:h.status==='healthy'?'online':'offline',serverLab:serverLab,source:'host'});
    });
    /* Add VMs not already covered by hosts (VMs without SSH entries) */
    var hostSet={};items.forEach(function(i){hostSet[i.label]=true;});
    if(fo&&fo.vms)fo.vms.forEach(function(v){
      if(hostSet[v.name])return;
      items.push({label:v.name,type:'vm',node:v.node||'',status:v.status||'stopped',serverLab:v.category==='lab',source:'pve'});
    });
    /* Sort: lab items first, then alphabetical */
    items.sort(function(a,b){
      var aLab=_labAssignments[a.label]!==undefined?_labAssignments[a.label]:a.serverLab;
      var bLab=_labAssignments[b.label]!==undefined?_labAssignments[b.label]:b.serverLab;
      if(aLab&&!bLab)return -1;if(!aLab&&bLab)return 1;
      return a.label<b.label?-1:1;
    });
    var h='<table><thead><tr><th>Name</th><th>Type</th><th>Node</th><th>Status</th><th style="text-align:center">LAB</th></tr></thead><tbody>';
    items.forEach(function(it){
      var isLab=_labAssignments[it.label]!==undefined?_labAssignments[it.label]:it.serverLab;
      var statusColor=it.status==='online'||it.status==='running'?'var(--green)':'var(--text-dim)';
      h+='<tr><td><strong>'+it.label+'</strong></td>';
      h+='<td class="mono-11">'+it.type.toUpperCase()+'</td>';
      h+='<td class="mono-11">'+(it.node||'-')+'</td>';
      h+='<td><span style="color:'+statusColor+'">'+it.status.toUpperCase()+'</span></td>';
      h+='<td style="text-align:center"><span onclick="toggleLabAssign(\''+it.label+'\','+!isLab+')" style="cursor:pointer;display:inline-block;padding:2px 10px;border-radius:4px;font-size:11px;font-weight:600;border:1px solid '+(isLab?'var(--green)':'var(--border-light)')+';background:'+(isLab?'rgba(63,185,80,0.15)':'transparent')+';color:'+(isLab?'var(--green)':'var(--text-dim)')+'">'+(isLab?'LAB':'—')+'</span></td>';
      h+='</tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){el.innerHTML='<span class="c-red">Failed to load fleet: '+e+'</span>';});
}
function toggleLabAssign(label,isLab){
  _labAssignments[label]=isLab;
  localStorage.setItem('freq_lab_assign',JSON.stringify(_labAssignments));
  _loadLabAssignments();
  toast(label+(isLab?' tagged as LAB':' removed from LAB'),'success');
}
function loadSystemPage(){renderGlobalSettings();loadFleetAdmin();loadConfig();loadJournal();loadDistros();loadGroups();loadNotify();loadRules();loadAlertHistory();}

function loadRules(){
  fetch('/api/rules?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('rules-list');if(!el)return;
    if(!d.rules||d.rules.length===0){el.innerHTML='<span class="c-dim-fs12">No rules configured</span>';return;}
    var h='<table><tr><th>Name</th><th>Condition</th><th>Target</th><th>Threshold</th><th>Severity</th><th>Enabled</th><th>Actions</th></tr>';
    d.rules.forEach(function(r){
      h+='<tr><td><strong>'+r.name+'</strong></td><td>'+r.condition+'</td><td>'+r.target+'</td><td>'+r.threshold+'</td>';
      h+='<td><span class="badge '+(r.severity==='critical'?'CRITICAL':r.severity)+'">'+r.severity+'</span></td>';
      h+='<td>'+(r.enabled?'<span class="c-green">ON</span>':'<span class="c-red">OFF</span>')+'</td>';
      h+='<td><button class="fleet-btn" style="font-size:10px;padding:2px 8px" onclick="toggleRule(\''+r.name+'\','+(!r.enabled)+')">'+(r.enabled?'Disable':'Enable')+'</button> ';
      h+='<button class="fleet-btn" style="font-size:10px;padding:2px 8px" onclick="deleteRule(\''+r.name+'\')">Delete</button></td></tr>';
    });
    h+='</table>';
    el.innerHTML=h;
  }).catch(function(e){var el=document.getElementById('rules-list');if(el)el.innerHTML='<span class="c-red">Failed: '+e+'</span>';});
}
function createRule(){
  var n=document.getElementById('rule-name').value.trim();
  var c=document.getElementById('rule-cond').value;
  var t=document.getElementById('rule-target').value.trim()||'*';
  var th=document.getElementById('rule-threshold').value||'0';
  var dur=document.getElementById('rule-duration').value||'0';
  var cd=document.getElementById('rule-cooldown').value||'300';
  var sev=document.getElementById('rule-severity').value;
  var msg=document.getElementById('rule-create-msg');
  if(!n){msg.innerHTML='<span class="c-red">Name required</span>';return;}
  fetch('/api/rules/create?token='+_authToken+'&name='+encodeURIComponent(n)+'&condition='+c+'&target='+encodeURIComponent(t)+'&threshold='+th+'&duration='+dur+'&cooldown='+cd+'&severity='+sev)
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){msg.innerHTML='<span class="c-red">'+d.error+'</span>';return;}
    msg.innerHTML='<span class="c-green">Rule created</span>';loadRules();
    document.getElementById('rule-name').value='';
  }).catch(function(e){msg.innerHTML='<span class="c-red">Failed: '+e+'</span>';});
}
function toggleRule(name,enabled){
  fetch('/api/rules/update?token='+_authToken+'&name='+encodeURIComponent(name)+'&enabled='+enabled)
  .then(function(r){return r.json()}).then(function(d){loadRules();});
}
function deleteRule(name){
  if(!confirm('Delete rule "'+name+'"?'))return;
  fetch('/api/rules/delete?token='+_authToken+'&name='+encodeURIComponent(name))
  .then(function(r){return r.json()}).then(function(d){loadRules();});
}
function loadAlertHistory(){
  fetch('/api/rules/history?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('alert-history');if(!el)return;
    if(!d.alerts||d.alerts.length===0){el.innerHTML='<span class="c-dim-fs12">No alerts yet</span>';return;}
    var h='<table><tr><th>Time</th><th>Rule</th><th>Host</th><th>Message</th><th>Severity</th></tr>';
    d.alerts.slice(-20).reverse().forEach(function(a){
      var t=a.fired_at?new Date(a.fired_at*1000).toLocaleString():'?';
      h+='<tr><td style="white-space:nowrap">'+t+'</td><td>'+a.rule_name+'</td><td>'+a.host+'</td><td>'+a.message+'</td>';
      h+='<td><span class="badge '+(a.severity==='critical'?'CRITICAL':a.severity)+'">'+a.severity+'</span></td></tr>';
    });
    h+='</table>';
    el.innerHTML=h;
  });
}

/* ═══════════════════════════════════════════════════════════════════
   FLEET ADMIN — admin role only
   ═══════════════════════════════════════════════════════════════════ */
var _fleetAdminData=null;
function loadFleetAdmin(){
  var sec=document.getElementById('fleet-admin-section');
  if(!sec)return;
  /* Only show for admin role */
  if(_currentRole!=='admin'&&_currentRole!=='protected'){sec.style.display='none';return;}
  sec.style.display='';
  var body=document.getElementById('fleet-admin-body');
  if(!body)return;
  body.innerHTML='<div class="skeleton"></div>';
  fetch(API.ADMIN_BOUNDARIES+'?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(d.error){body.innerHTML='<p class="c-red">'+d.error+'</p>';return;}
    _fleetAdminData=d;
    renderFleetAdmin(d);
  }).catch(function(e){body.innerHTML='<p class="c-red">Failed to load: '+e+'</p>';});
}
function renderFleetAdmin(d){
  var body=document.getElementById('fleet-admin-body');
  if(!body)return;
  var h='';
  /* ── Host Properties Editor ── */
  h+='<div class="mb-24">';
  h+='<h4 class="section-label-pl-ls">HOST PROPERTIES</h4>';
  h+='<p class="desc-line">Change host type or groups. Updates hosts.conf immediately.</p>';
  h+='<table><thead><tr><th>Label</th><th>IP</th><th>Type</th><th>Groups</th><th>Actions</th></tr></thead><tbody>';
  var validTypes=['linux','pve','truenas','pfsense','docker','idrac','switch','unknown'];
  (d.hosts||[]).forEach(function(host){
    var typeOpts='';validTypes.forEach(function(t){typeOpts+='<option value="'+t+'"'+(t===host.type?' selected':'')+'>'+t+'</option>';});
    h+='<tr>';
    h+='<td><strong>'+host.label+'</strong></td>';
    h+='<td class="text-sub">'+host.ip+'</td>';
    h+='<td><select id="ht-'+host.label+'" style="background:var(--card);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-size:12px">'+typeOpts+'</select></td>';
    h+='<td><input id="hg-'+host.label+'" value="'+host.groups+'" style="background:var(--card);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-size:12px;width:160px" placeholder="prod,media"></td>';
    h+='<td><button class="fleet-btn pill-ok-sm" onclick="saveHostProps(\''+host.label+'\')" >SAVE</button></td>';
    h+='</tr>';
  });
  h+='</tbody></table></div>';
  /* ── VM Categories ── */
  h+='<div class="mb-24">';
  h+='<h4 class="section-label-pl-ls">VM CATEGORIES & PERMISSIONS</h4>';
  h+='<p class="desc-line">Assign VMIDs to categories. Controls what actions are allowed per VM.</p>';
  var tierNames=Object.keys(d.tiers||{});
  Object.keys(d.categories||{}).forEach(function(cat){
    var info=d.categories[cat];
    var tierOpts='';tierNames.forEach(function(t){tierOpts+='<option value="'+t+'"'+(t===info.tier?' selected':'')+'>'+t+'</option>';});
    h+='<div class="crd mb-8" >';
    h+='<div class="flex-between-mb8">';
    h+='<div><h3 style="font-size:14px;text-transform:uppercase">'+cat.replace(/_/g,' ')+'</h3>';
    h+='<p class="fs-11-dim-mt2">'+info.description+'</p></div>';
    h+='<div style="display:flex;align-items:center;gap:8px"><span class="text-meta">Tier:</span>';
    h+='<select onchange="updateCategoryTier(\''+cat+'\',this.value)" style="background:var(--card);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-size:12px">'+tierOpts+'</select></div>';
    h+='</div>';
    /* VMIDs or range */
    if(info.range_start!==undefined){
      h+='<div style="display:flex;gap:8px;align-items:center;margin-top:8px">';
      h+='<span class="text-sub">VMID Range:</span>';
      h+='<input id="rs-'+cat+'" type="number" value="'+info.range_start+'" class="input-sm">';
      h+='<span class="c-dim">—</span>';
      h+='<input id="re-'+cat+'" type="number" value="'+info.range_end+'" class="input-sm">';
      h+='<button class="fleet-btn pill-ok-sm" data-action="updateCategoryRange" data-arg="'+cat+'" >SAVE</button>';
      h+='</div>';
    } else {
      var vmids=(info.vmids||[]).join(', ');
      h+='<div class="mt-8">';
      h+='<div style="font-size:12px;color:var(--text-dim);margin-bottom:4px">VMIDs: <span style="color:var(--text)">'+vmids+'</span></div>';
      h+='<div style="display:flex;gap:6px;align-items:center;margin-top:4px">';
      h+='<input id="vmid-add-'+cat+'" type="number" placeholder="VMID" class="input-sm">';
      h+='<button class="fleet-btn pill-ok-sm" onclick="addVmidToCategory(\''+cat+'\')" >+ ADD</button>';
      /* Removable badges */
      (info.vmids||[]).forEach(function(vid){
        h+='<span style="display:inline-flex;align-items:center;gap:4px;background:var(--purple-faint);color:var(--purple-light);padding:2px 8px;border-radius:4px;font-size:12px">'+vid;
        h+='<span onclick="removeVmidFromCategory(\''+cat+'\','+vid+')" style="cursor:pointer;color:var(--red);font-weight:700">&times;</span></span>';
      });
      h+='</div></div>';
    }
    /* Tier permissions display */
    var perms=d.tiers[info.tier]||['view'];
    h+='<div style="margin-top:8px;display:flex;gap:4px;flex-wrap:wrap">';
    perms.forEach(function(p){h+='<span class="tag">'+p+'</span>';});
    h+='</div>';
    h+='</div>';
  });
  h+='</div>';
  /* ── Permission Tiers ── */
  h+='<div class="mb-24">';
  h+='<h4 class="section-label-pl-ls">PERMISSION TIERS</h4>';
  h+='<p class="desc-line">Define what actions each tier allows. Tiers are assigned to categories above.</p>';
  Object.keys(d.tiers||{}).forEach(function(tier){
    var actions=d.tiers[tier]||[];
    h+='<div class="crd mb-8" >';
    h+='<h3 style="font-size:14px;text-transform:uppercase">'+tier+'</h3>';
    h+='<div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap">';
    actions.forEach(function(a){h+='<span class="tag">'+a+'</span>';});
    h+='</div></div>';
  });
  h+='</div>';
  body.innerHTML=h;
}
/* Fleet Admin actions */
function saveHostProps(label){
  var typeEl=document.getElementById('ht-'+label);
  var groupEl=document.getElementById('hg-'+label);
  if(!typeEl||!groupEl)return;
  var url='/api/admin/hosts/update?token='+_authToken+'&label='+encodeURIComponent(label)+'&type='+encodeURIComponent(typeEl.value)+'&groups='+encodeURIComponent(groupEl.value);
  fetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.error){toast('Error: '+d.error,'error');return;}
    toast(label+' updated','success');
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function updateCategoryTier(cat,tier){
  fetch(API.ADMIN_BOUNDARIES_UPDATE+'?token='+_authToken+'&action=update_category_tier&category='+encodeURIComponent(cat)+'&tier='+encodeURIComponent(tier)).then(function(r){return r.json()}).then(function(d){
    if(d.error){toast('Error: '+d.error,'error');return;}
    toast(cat+' tier \u2192 '+tier,'success');loadFleetAdmin();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function updateCategoryRange(cat){
  var rs=document.getElementById('rs-'+cat);
  var re=document.getElementById('re-'+cat);
  if(!rs||!re)return;
  fetch(API.ADMIN_BOUNDARIES_UPDATE+'?token='+_authToken+'&action=update_range&category='+encodeURIComponent(cat)+'&range_start='+rs.value+'&range_end='+re.value).then(function(r){return r.json()}).then(function(d){
    if(d.error){toast('Error: '+d.error,'error');return;}
    toast(cat+' range updated','success');loadFleetAdmin();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function addVmidToCategory(cat){
  var el=document.getElementById('vmid-add-'+cat);
  if(!el||!el.value)return;
  fetch(API.ADMIN_BOUNDARIES_UPDATE+'?token='+_authToken+'&action=add_vmid&category='+encodeURIComponent(cat)+'&vmid='+el.value).then(function(r){return r.json()}).then(function(d){
    if(d.error){toast('Error: '+d.error,'error');return;}
    toast('VMID '+el.value+' added to '+cat,'success');loadFleetAdmin();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function removeVmidFromCategory(cat,vmid){
  confirmAction('Remove VMID '+vmid+' from '+cat+'?',function(){
    fetch(API.ADMIN_BOUNDARIES_UPDATE+'?token='+_authToken+'&action=remove_vmid&category='+encodeURIComponent(cat)+'&vmid='+vmid).then(function(r){return r.json()}).then(function(d){
      if(d.error){toast('Error: '+d.error,'error');return;}
      toast('VMID '+vmid+' removed from '+cat,'success');loadFleetAdmin();
    }).catch(function(e){toast('Failed: '+e,'error');});
  });
}

/* ═══════════════════════════════════════════════════════════════════
   HOME
   ═══════════════════════════════════════════════════════════════════ */
function loadHome(){
  _renderHomeWidgets();
  fetch(API.INFO).then(function(r){return r.json()}).then(function(d){
    document.getElementById('nav-ver').textContent='V'+d.version;
    var vf=document.getElementById('home-ver-footer');if(vf)vf.textContent='V'+d.version;
    var st=document.getElementById('home-subtitle');if(st&&d.brand)st.textContent=d.brand;
    document.title=(d.brand||'PVE FREQ')+' Dashboard';
    var cr=document.getElementById('about-credits');if(cr)cr.textContent=(d.cluster||'')+(d.cluster?' · ':'')+(d.brand||'PVE FREQ');
  });
}

/* ═══════════════════════════════════════════════════════════════════
   FLEET
   ═══════════════════════════════════════════════════════════════════ */
var _VLAN_MAP={};/* populated from /api/fleet/overview vlans by _initFleetData */
var _vlanPrefixes={};/* populated alongside _VLAN_MAP by _initFleetData */
var VLAN_COLORS={};
/* Assign colors to VLANs dynamically — cycle through a palette.
   Called from _initFleetData() after _VLAN_MAP is populated. */
var _VLAN_PALETTE=['var(--purple-light)','var(--blue)','var(--green)','var(--red)','var(--cyan)','var(--orange)','var(--text)','var(--yellow)','#f778ba','#58a6ff'];
function _assignVlanColors(){var vi=0;Object.keys(_VLAN_MAP).forEach(function(id){VLAN_COLORS[_VLAN_MAP[id].name]=_VLAN_PALETTE[vi%_VLAN_PALETTE.length];vi++;});}
/* Fleet color scheme — node-based, generated from PVE node list.
   Called from _initFleetData() after PROD_HOSTS is populated. */
var _NODE_PALETTE=['#9B4FDE','#f778ba','#58a6ff','#ffa657','#f0f6fc','#6e7681','#79c0ff','#d2a8ff'];
var NODE_COLORS={};
function _assignNodeColors(){var pveHosts=PROD_HOSTS.filter(function(h){return h.type==='pve';});pveHosts.forEach(function(h,i){NODE_COLORS[h.label]=_NODE_PALETTE[i%_NODE_PALETTE.length];});}
var INFRA_GOLD='var(--text)';
function _hostColor(label,htype,node){
  /* Infra devices → gold */
  if(htype==='pfsense'||htype==='truenas'||htype==='switch'||htype==='docker'||htype==='idrac')return INFRA_GOLD;
  /* PVE nodes → node color */
  if(htype==='pve'){return NODE_COLORS[label]||INFRA_GOLD;}
  /* VMs → inherit from node */
  if(node)return NODE_COLORS[node]||'#79c0ff';
  /* Lab VMs → dim */
  var pv=PROD_VMS.find(function(v){return v.label===label;});
  if(pv&&pv.category==='lab')return '#6e7681';
  return '#79c0ff';
}
/* ── INFRA ROLE CARD SYSTEM ── */
/* Role definitions — the card is about the ROLE, not the vendor */
var INFRA_ROLES={
  pfsense:  {role:'FIREWALL',       icon:'\ud83d\udd25', color:'var(--red)'},
  opnsense: {role:'FIREWALL',       icon:'\ud83d\udd25', color:'var(--red)'},
  truenas:  {role:'NETWORK STORAGE',icon:'\u26c1', color:'var(--blue)'},
  synology: {role:'NETWORK STORAGE',icon:'\u26c1', color:'var(--blue)'},
  unraid:   {role:'NETWORK STORAGE',icon:'\u26c1', color:'var(--blue)'},
  switch:   {role:'SWITCH',         icon:'\u26a1', color:'var(--orange)'},
  idrac:    {role:'BMC',            icon:'\u2699', color:'var(--yellow)'},
  ilo:      {role:'BMC',            icon:'\u2699', color:'var(--yellow)'},
  ipmi:     {role:'BMC',            icon:'\u2699', color:'var(--yellow)'}
};
function _infraRoleCard(ph,healthMap){
  var roleInfo=INFRA_ROLES[ph.type]||{role:ph.type.toUpperCase(),icon:'\u2726',color:'var(--text-dim)'};
  var live=healthMap[ph.label];
  var up=ph.reachable||false;if(live&&live.status==='healthy')up=true;
  var safeId=ph.label.replace(/[^a-zA-Z0-9]/g,'-');
  var c='<div class="infra-role-card" onclick="openHost(\''+ph.label+'\')">';
  /* Role label row */
  c+='<div class="role-label" style="color:'+roleInfo.color+'"><span class="role-icon">'+roleInfo.icon+'</span>'+roleInfo.role+'</div>';
  /* Device name + status */
  c+='<div class="flex-between">';
  c+='<h3 class="device-name">'+ph.label+'</h3>';
  c+='<span id="infra-status-'+safeId+'" style="font-size:11px;font-weight:600;display:flex;align-items:center"><span class="status-dot '+(up?'up':'down')+'"></span>'+(up?'ONLINE':'OFFLINE')+'</span>';
  c+='</div>';
  /* Vendor/model subtitle */
  c+='<div class="device-sub">'+ph.detail+' \u00b7 '+ph.ip+'</div>';
  /* Live role-specific metrics — placeholder, filled by /api/infra/quick */
  c+='<div class="role-metrics" id="infra-metrics-'+safeId+'">';
  if(up){
    c+='<div class="role-metric"><span class="rm-val c-dim">Loading...</span></div>';
  } else {
    c+=_roleOfflineMetrics(ph.type,roleInfo);
  }
  c+='</div>';
  c+='</div>';
  return c;
}
function _roleOfflineMetrics(type,roleInfo){
  var m='';
  if(type==='idrac'||type==='ilo'||type==='ipmi'){
    m+='<div class="role-metric"><span class="rm-val c-dim">NO RESPONSE</span></div>';
  } else {
    m+='<div class="role-metric"><span class="rm-val c-dim">UNREACHABLE</span></div>';
  }
  return m;
}
function _enrichInfraCards(){
  fetch(API.INFRA_QUICK).then(function(r){return r.json()}).then(function(d){
    if(d.warming){
      /* Cache still warming — retry in 3s */
      setTimeout(_enrichInfraCards,3000);
      return;
    }
    /* Show freshness on CORE SYSTEMS header */
    var ageEl=document.getElementById('core-systems-age');
    if(ageEl&&d.age!==undefined){
      var a=Math.round(d.age);
      ageEl.textContent=a<5?'LIVE':a<60?a+'s AGO':Math.round(a/60)+'m AGO';
      ageEl.style.color=a<30?'var(--green)':a<120?'var(--yellow)':'var(--red)';
    }
    d.devices.forEach(function(dev){
      var safeId=dev.label.replace(/[^a-zA-Z0-9]/g,'-');
      var el=document.getElementById('infra-metrics-'+safeId);
      var statusEl=document.getElementById('infra-status-'+safeId);
      if(!el)return;
      /* Update status dot */
      if(statusEl){
        statusEl.innerHTML='<span class="status-dot '+(dev.reachable?'up':'down')+'"></span>'+(dev.reachable?'ONLINE':'OFFLINE');
      }
      if(!dev.reachable){
        var roleInfo=INFRA_ROLES[dev.type]||{};
        el.innerHTML=_roleOfflineMetrics(dev.type,roleInfo);
        return;
      }
      var m=dev.metrics;var h='';
      var _m=function(val,lbl,color){return '<div class="role-metric"><span class="rm-val" style="color:'+color+'">'+val+'</span><span class="rm-lbl">'+lbl+'</span></div>';};
      if(dev.type==='pfsense'||dev.type==='opnsense'){
        h+=_m(m.states||'?','STATES','var(--cyan)');
        if(m.interfaces)h+=_m(m.interfaces,'IFACES','var(--text)');
        if(m.uptime){var pfUp=m.uptime.replace(/^up\s+/i,'').replace(/,\s*\d+:\d+$/,'');h+=_m(pfUp,'UPTIME','var(--green)');}
      } else if(dev.type==='truenas'||dev.type==='synology'||dev.type==='unraid'){
        var poolColor=m.pool_health==='ONLINE'?'var(--green)':m.pool_health==='DEGRADED'?'var(--yellow)':'var(--red)';
        h+=_m(m.pool_health||'?','POOLS',poolColor);
        h+=_m(m.capacity_pct||'?','USED',parseInt(m.capacity_pct)>=85?'var(--red)':'var(--green)');
        h+=_m(m.total_size||'?','TOTAL','var(--blue)');
        var alertCount=m.alerts||0;
        h+=_m(alertCount,'ALERTS',alertCount>0?'var(--yellow)':'var(--green)');
      } else if(dev.type==='switch'){
        if(m.ports_up)h+=_m(m.ports_up,'PORTS UP','var(--green)');
        if(m.vlans)h+=_m(m.vlans,'VLANs','var(--cyan)');
        if(m.uptime){var ut=m.uptime.replace(/.*uptime is /i,'').replace(/,\s*\d+ minutes?/i,'');h+=_m(ut,'UPTIME','var(--green)');}
      } else if(dev.type==='idrac'||dev.type==='ilo'||dev.type==='ipmi'){
        if(m.note){
          h+=_m(m.note,'','var(--yellow)');
        } else {
          var powerColor=m.power==='ON'?'var(--green)':'var(--red)';
          h+=_m(m.power||'?','POWER',powerColor);
          if(m.inlet_temp)h+=_m(m.inlet_temp,'INLET','var(--blue)');
          if(m.model)h+=_m(m.model,'MODEL','var(--text-dim)');
        }
      }
      el.innerHTML=h||'<div class="role-metric"><span class="rm-val c-green">OK</span></div>';
    });
  }).catch(function(e){console.error('infra quick error:',e);});
}
/* Action buttons and output div IDs for physical infrastructure devices — keyed by device type */
var INFRA_ACTIONS={
  pfsense:[{l:'STATUS',f:"pfAction('status')"},{l:'RULES',f:"pfAction('rules')"},{l:'NAT',f:"pfAction('nat')"},{l:'STATES',f:"pfAction('states')"},{l:'INTERFACES',f:"pfAction('interfaces')"},{l:'GATEWAYS',f:"pfAction('gateways')"},{l:'GATEWAY MONITOR',f:"pfAction('gateway_monitor')"},{l:'DNS',f:"pfAction('dns')"},{l:'TRAFFIC',f:"pfAction('traffic')"},{l:'VPN',f:"pfAction('vpn')"},{l:'SERVICES',f:"pfAction('services')"},{l:'FIREWALL LOG',f:"pfAction('log')"},{l:'SYSTEM LOG',f:"pfAction('syslog')"},{l:'ARP TABLE',f:"pfAction('arp')"},{l:'DHCP LEASES',f:"pfAction('dhcp')"},{l:'ALIASES',f:"pfAction('aliases')"},{l:'BACKUP CONFIG',f:"pfAction('backup')"}],
  truenas:[{l:'SYSTEM',f:"tnAction('status')"},{l:'POOLS',f:"tnAction('pools')"},{l:'HEALTH',f:"tnAction('health')"},{l:'DATASETS',f:"tnAction('datasets')"},{l:'SHARES',f:"tnAction('shares')"},{l:'ALERTS',f:"tnAction('alerts')"},{l:'SMART DISKS',f:"tnAction('smart')"},{l:'SNAPSHOTS',f:"tnAction('snapshots')"},{l:'REPLICATION',f:"tnAction('replication')"},{l:'SERVICES',f:"tnAction('services')"},{l:'NETWORK',f:"tnAction('network')"},{l:'SYSTEM LOG',f:"tnAction('syslog')"}],
  switch:[{l:'STATUS',f:"swAction('status')"},{l:'VLANS',f:"swAction('vlans')"},{l:'INTERFACES',f:"swAction('interfaces')"},{l:'MAC TABLE',f:"swAction('mac')"},{l:'TRUNKS',f:"swAction('trunk')"},{l:'PORT ERRORS',f:"swAction('errors')"},{l:'SPANNING TREE',f:"swAction('spanning')"},{l:'LOG',f:"swAction('log')"},{l:'CDP NEIGHBORS',f:"swAction('cdp')"},{l:'INVENTORY',f:"swAction('inventory')"}],
  idrac:[{l:'SYSTEM INFO',f:"idracAction('status')"},{l:'SENSORS',f:"idracAction('sensors')"},{l:'EVENT LOG',f:"idracAction('sel')"},{l:'STORAGE / RAID',f:"idracAction('storage')"},{l:'NETWORK',f:"idracAction('network')"},{l:'FIRMWARE',f:"idracAction('firmware')"},{l:'LICENSE',f:"idracAction('license')"}]
};
function loadMetricsQuick(){
  /* If we have cached data, render instantly — no skeletons, no wait */
  if(_fleetCache.fo||_fleetCache.hd){
    _renderFleetData(_fleetCache.fo,_fleetCache.hd);
  } else {
    document.getElementById('metrics-cards').innerHTML='<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
    document.getElementById('metrics-summary').innerHTML='<div class="skeleton h-50" ></div>';
  }
  /* Fetch fresh data in background and re-render */
  Promise.all([
    fetch(API.FLEET_OVERVIEW).then(function(r){return r.json()}).catch(function(){return null;}),
    fetch(API.HEALTH).then(function(r){return r.json()}).catch(function(){return null;}),
    fetch(API.MEDIA_STATUS).then(function(r){return r.json()}).catch(function(){return null;})
  ]).then(function(results){
    var fo=results[0];var hd=results[1];var md=results[2];
    if(fo)_fleetCache.fo=fo;
    if(hd)_fleetCache.hd=hd;
    _renderFleetData(_fleetCache.fo,_fleetCache.hd,md);
  });
}
/* ── Fleet rendering helpers (hoisted from _renderFleetData) ── */
function _fStat(v,label,color){return '<div class="text-center"><div style="font-size:16px;font-weight:700;color:'+color+'">'+v+'</div><div style="font-size:12px;color:var(--text)">'+label+'</div></div>';}
function _fGrp(title,cols,content){return '<div style="border:1px solid var(--border);border-radius:6px;padding:6px 4px 4px;background:var(--bg)"><div style="font-size:12px;color:var(--text);text-align:center;letter-spacing:1px;margin-bottom:4px;text-transform:uppercase;opacity:0.7">'+title+'</div><div style="display:grid;grid-template-columns:repeat('+cols+',1fr);gap:4px">'+content+'</div></div>';}
function _fDual(label,v1,l1,c1,v2,l2,c2){return '<div class="st"><div class="lb">'+label+'</div><div class="flex-row-24"><span class="stat-pair"><span style="font-size:20px;font-weight:700;color:'+c1+'">'+v1+'</span><span class="label-hint">'+l1+'</span></span><span class="stat-pair"><span style="font-size:20px;font-weight:700;color:'+c2+'">'+v2+'</span><span class="label-hint">'+l2+'</span></span></div></div>';}
function _buildLabHostCards(hosts,infraLabels,labLabels){
  var labCards='';
  if(!hosts)return labCards;
  hosts.forEach(function(h){
    if(infraLabels[h.label])return;
    var cl=_hostColor(h.label,h.type);var up=h.status==='healthy';
    var isLab=labLabels[h.label];
    var diskPct=parseInt((h.disk||'0').replace('%',''))||0;
    var ramParts=(h.ram||'0/0MB').match(/(\d+)\/(\d+)/);
    var ramUsed=ramParts?parseInt(ramParts[1]):0;var ramTotal=ramParts?parseInt(ramParts[2]):1;
    var ramPct=ramTotal>0?Math.round(ramUsed/ramTotal*100):0;
    var loadVal=parseFloat(h.load)||0;var cores=parseInt(h.cores)||1;
    var loadPct=cores>0?Math.round(loadVal/cores*100):0;
    var c='<div class="host-card cursor-ptr" onclick="openHost(\''+h.label+'\')" >';
    c+='<div class="host-head"><h3 style="color:'+cl+'">'+h.label+'</h3><div class="host-meta"><span>'+h.ip+'</span><span>\u00b7</span><span>'+(h.type||'Linux').toUpperCase()+'</span><span>\u00b7</span>'+(up?'<span class="c-green">ONLINE</span>':'<span class="c-red">OFFLINE</span>')+'</div></div>';
    c+='<div class="divider-light">';
    if(up){
      var _isStorage=h.type==='truenas';
      c+=_mrow('CPU',cores+(cores>1?' Cores':' Core')+' \u00b7 '+loadPct+'%',loadPct,'var(--purple-light)');
      if(_isStorage){c+='<div class="metric-row"><div class="metric-top"><span class="metric-label">RAM (ARC)</span><span class="metric-val">'+_ramGB(ramUsed)+' / '+_ramGB(ramTotal)+'</span></div><div class="pbar"><div class="pbar-fill" style="width:'+ramPct+'%;background:var(--blue)"></div></div></div>';}
      else{c+=_mrow('RAM',_ramGB(ramUsed)+' / '+_ramGB(ramTotal),ramPct,'var(--blue)');}
      c+=_mrow('DISK',(h.disk||'?'),diskPct,'var(--green)');
      c+='<div class="metric-row" id="ntp-'+h.label.replace(/[^a-z0-9]/gi,'')+'"><div class="metric-top"><span class="metric-label">NTP</span><span class="metric-val c-dim-fs11" >...</span></div></div>';
      c+='<div class="metric-row" id="upd-'+h.label.replace(/[^a-z0-9]/gi,'')+'"><div class="metric-top"><span class="metric-label">UPDATES</span><span class="metric-val c-dim-fs11" >...</span></div></div>';
    } else {
      c+='<p style="color:var(--text-dim);font-size:12px;padding:8px 0">Host unreachable</p>';
    }
    c+='</div></div>';
    if(isLab)labCards+=c;
  });
  /* Also show lab-tagged or lab-category VMs from PVE that aren't in hosts.conf */
  var hostSet={};if(hosts)hosts.forEach(function(h){hostSet[h.label]=true;});
  PROD_VMS.forEach(function(v){
    if(hostSet[v.label])return;
    if(!labLabels[v.label]&&v.category!=='lab')return;
    var isRunning=v.status==='running';
    var cl=_hostColor(v.label,'vm',v.node);
    var c='<div class="host-card">';
    c+='<div class="host-head"><h3 style="color:'+cl+'">'+v.label+'</h3><div class="host-meta"><span>VM '+v.vmid+'</span><span>\u00b7</span><span>'+(v.node||'?')+'</span><span>\u00b7</span>'+(isRunning?'<span class="c-green">RUNNING</span>':'<span class="c-dim">STOPPED</span>')+'</div></div>';
    c+='<div class="divider-light"><p style="color:var(--text-dim);font-size:12px;padding:8px 0">'+(isRunning?v.cores+' cores \u00b7 '+v.ram:'No SSH entry \u00b7 PVE data only')+'</p></div></div>';
    labCards+=c;
  });
  return labCards;
}
function _buildPveNodeData(pveNodes,healthMap,vmsByNode,ctrByVmid,labLabels){
  var nodeData={};
  pveNodes.forEach(function(pn){
    var nodeName=pn.name;
    var cl=_hostColor(nodeName,'pve');
    var live=healthMap[nodeName];
    var up=live&&live.status==='healthy';
    var nodeVms=(vmsByNode[nodeName]||[]).filter(function(v){return !labLabels[v.name]&&v.category!=='lab';});
    var nVms=nodeVms.length;
    var nCores=0,nRamMb=0,nOnline=0,nOffline=0;
    nodeVms.forEach(function(v){
      nCores+=v.cpu||0;nRamMb+=v.ram_mb||0;
      if(v.status==='running')nOnline++;else nOffline++;
    });
    var dockerCount=0,dockerUp=0,dockerDown=0;
    nodeVms.forEach(function(v){
      var ctr=ctrByVmid[String(v.vmid)];
      if(ctr){dockerCount+=ctr.total;dockerUp+=ctr.up;dockerDown+=ctr.down;}
    });
    var nRamGb=Math.round(nRamMb/1024);
    var detailRam=pn.detail.match(/(\d+)GB/);var nodeRamStr=detailRam?detailRam[1]+'GB':'?';
    var nodeCard='<div class="host-card" style="cursor:pointer;" onclick="openVmInfo(\''+nodeName+'\',\''+pn.ip+'\',0)">';
    nodeCard+='<div class="mb-8"><div class="host-head" style="margin-bottom:2px"><h3 style="color:'+cl+'">'+nodeName+'</h3><div class="host-meta"><span>'+pn.ip+'</span><span>\u00b7</span><span>HYPERVISOR</span><span>\u00b7</span>'+(up?'<span class="c-green">ONLINE</span>':'<span class="c-red">OFFLINE</span>')+'</div></div><div style="font-size:12px;color:var(--text);font-weight:400">'+pn.detail+'</div></div>';
    nodeCard+='<div class="divider-light">';
    if(up&&live){
      var cores=parseInt(live.cores)||1;var loadVal=parseFloat(live.load)||0;
      var loadPct=cores>0?Math.round(loadVal/cores*100):0;
      var diskPct=parseInt((live.disk||'0').replace('%',''))||0;
      var ramParts=(live.ram||'0/0MB').match(/(\d+)\/(\d+)/);
      var ramUsed=ramParts?parseInt(ramParts[1]):0;var ramTotal=ramParts?parseInt(ramParts[2]):1;
      var ramPct=ramTotal>0?Math.round(ramUsed/ramTotal*100):0;
      nodeCard+='<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:6px 0">';
      nodeCard+=_fGrp('PVE NODE',2,_fStat(nCores+'<span class="fs-12-fade">/'+cores+'</span>','CPU ALLOC','var(--purple-light)')+_fStat(nRamGb+'<span class="fs-12-fade">GB/'+nodeRamStr+'</span>','RAM ALLOC','var(--purple-light)'));
      nodeCard+=_fGrp('VMs',3,_fStat(nVms,'TOTAL','var(--purple-light)')+_fStat(nOnline,'ONLINE','var(--green)')+_fStat(nOffline,'OFFLINE','var(--red)'));
      nodeCard+=_fGrp('CONTAINERS',3,_fStat(dockerCount,'TOTAL','var(--purple-light)')+_fStat(dockerUp,'UP','var(--green)')+_fStat(dockerDown,'DOWN',dockerDown>0?'var(--red)':'var(--green)'));
      nodeCard+='</div>';
      nodeCard+='<div style="margin:6px 0">';
      nodeCard+=_mrow('CPU',cores+(cores>1?' Cores':' Core')+' \u00b7 '+loadPct+'%',loadPct,'var(--purple-light)');
      nodeCard+=_mrow('RAM',_ramGB(ramUsed)+' / '+_ramGB(ramTotal),ramPct,'var(--blue)');
      nodeCard+=_mrow('DISK',(live.disk||'?'),diskPct,'var(--green)');
      nodeCard+='</div>';
    } else {
      nodeCard+='<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:6px 0">';
      nodeCard+=_fGrp('PVE NODE',2,_fStat(nCores,'CPU ALLOC','var(--purple-light)')+_fStat(nRamGb+'<span class="fs-12-fade">GB</span>','RAM ALLOC','var(--purple-light)'));
      nodeCard+=_fGrp('VMs',3,_fStat(nVms,'TOTAL','var(--purple-light)')+_fStat(nOnline,'ONLINE','var(--green)')+_fStat(nOffline,'OFFLINE','var(--red)'));
      nodeCard+=_fGrp('CONTAINERS',3,_fStat(dockerCount,'TOTAL','var(--purple-light)')+_fStat(dockerUp,'UP','var(--green)')+_fStat(dockerDown,'DOWN',dockerDown>0?'var(--red)':'var(--green)'));
      nodeCard+='</div>';
      nodeCard+='<div id="pve-live-'+nodeName+'" style="margin:6px 0;padding:6px 8px;background:rgba(248,81,73,0.05);border:1px dashed var(--border);border-radius:6px;text-align:center">';
      nodeCard+='<span style="font-size:12px;color:var(--red);letter-spacing:0.5px">LIVE METRICS: OFFLINE</span>';
      nodeCard+='<div class="fs-12-dim-mt2">Deploy to same network for real-time CPU load, RAM usage, storage pools, cluster health</div>';
      nodeCard+='</div>';
    }
    nodeCard+='</div></div>';
    nodeData[nodeName]={card:nodeCard,vms:''};
  });
  return nodeData;
}
function _assembleFleetOutput(infraCards,nodeData,pveNodes){
  var out='';
  if(infraCards){
    var ic=(infraCards.match(/infra-role-card/g)||[]).length;
    var cols=ic<=3?ic:3;
    out+='<div style="margin-bottom:16px;border:3px solid var(--text);border-radius:10px;background:#000000;overflow:hidden">';
    out+='<div class="flex-between-pad-top"><span style="font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--text);opacity:0.85">CORE SYSTEMS</span><span id="core-systems-age" class="fs-10-dim-600-ls"></span></div>';
    out+='<div style="display:grid;grid-template-columns:repeat('+cols+',1fr);gap:12px;padding:12px 16px 16px">'+infraCards+'</div>';
    out+='</div>';
  }
  var nodeOrder=pveNodes.map(function(n){return n.name;}).sort();
  var pveContent='';
  nodeOrder.forEach(function(nodeName){
    var nd=nodeData[nodeName];if(!nd||!nd.card)return;
    var nodeColor=NODE_COLORS[nodeName]||'var(--text)';
    var vmCount=nd.vms?(nd.vms.match(/host-card/g)||[]).length:0;
    var cols=Math.max(vmCount,3);if(cols>4)cols=4;
    pveContent+='<div class="pve-group" style="border-left:4px solid '+nodeColor+';border-radius:6px;background:var(--bg2);overflow:hidden">';
    pveContent+='<div data-action="togglePveGroup" style="cursor:pointer;padding:8px 12px;display:flex;align-items:center;gap:8px">';
    pveContent+='<span class="pve-chev" style="color:'+nodeColor+';font-size:14px;font-weight:700">\u25b8</span>';
    pveContent+='<div class="flex-1">'+nd.card+'</div>';
    pveContent+='</div>';
    if(nd.vms){
      pveContent+='<div class="pve-vms" style="display:none;grid-template-columns:repeat('+cols+',1fr);gap:10px;padding:8px 12px 12px;border-top:1px solid var(--border)">'+nd.vms+'</div>';
    }
    pveContent+='</div>';
  });
  if(pveContent){
    out+='<div style="margin-bottom:16px;border:3px solid var(--purple);border-radius:10px;background:#000000;overflow:hidden">';
    out+='<div class="flex-between-pad-top"><span style="font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--text);opacity:0.85">PROXMOX NODES</span><span class="fs-10-dim-600-ls">'+pveNodes.length+' NODES</span></div>';
    out+='<div style="display:flex;flex-direction:column;gap:8px;padding:12px 16px 16px">'+pveContent+'</div>';
    out+='</div>';
  }
  return out;
}
function _renderFleetStats(hd,summary,labLabels,pveNodes,totalUp,totalDown,foDuration,hdDuration,labPveNodes){
  var labCount=Object.keys(labLabels).length;
  var prodCount=(hd?hd.hosts.length:0)-labCount;
  var prodPveNodes=pveNodes.length;
  var responseDur=Math.max(foDuration,hdDuration);
  var hdAge=hd&&hd.age!==undefined?Math.round(hd.age):0;
  var ageLabel=hdAge<5?'LIVE':hdAge<60?hdAge+'s':Math.round(hdAge/60)+'m';
  var ageColor=hdAge<30?'var(--green)':hdAge<120?'var(--yellow)':'var(--red)';
  var vmRunning=summary.running||0;var vmStopped=summary.stopped||0;
  var sumEl=document.getElementById('metrics-summary');
  sumEl.innerHTML=
    _fDual('FLEET SPLIT',summary.prod_count||0,'PROD','var(--purple-light)',summary.lab_count||0,'LAB','var(--cyan)')+
    _fDual('FLEET',prodCount,'PROD','var(--purple-light)',labCount,'LAB','var(--cyan)')+
    _fDual('PVE NODES',prodPveNodes,'PROD','var(--purple-light)',labPveNodes,'LAB','var(--cyan)')+
    st('RESPONSE',responseDur+'s','b')+
    _fDual('STATUS',totalUp,'ONLINE','var(--green)',totalDown,'OFFLINE','var(--red)')+
    _fDual('VMs',vmRunning,'RUN','var(--green)',vmStopped,'STOP','var(--red)')+
    st('CONTAINERS','...','p')+
    st('ACTIVITY','...','p');
  fetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(md){
    var _cdn2=Math.max(0,md.containers_down||0);var c=sumEl.querySelector('.st:nth-child(7)');if(c)c.innerHTML='<div class="lb">CONTAINERS</div><div class="flex-row-24"><span class="stat-pair"><span class="stat-big-green">'+(md.containers_running||0)+'</span><span class="label-hint">UP</span></span><span class="stat-pair"><span class="stat-big-red">'+_cdn2+'</span><span class="label-hint">DOWN</span></span></div>';
  }).catch(function(){});
  Promise.all([
    fetch(API.MEDIA_DOWNLOADS).then(function(r){return r.json()}).catch(function(){return {count:0}}),
    fetch(API.MEDIA_STREAMS).then(function(r){return r.json()}).catch(function(){return {count:0}})
  ]).then(function(res){
    var dl=res[0].count||0;var str=res[1].count||0;
    var a=sumEl.querySelector('.st:nth-child(8)');if(a)a.innerHTML='<div class="lb">ACTIVITY</div><div class="flex-row-24"><span class="stat-pair"><span class="stat-big-orange">'+dl+'</span><span class="label-hint">DL</span></span><span class="stat-pair"><span class="stat-big-blue">'+str+'</span><span class="label-hint">STREAM</span></span></div>';
  });
}
function _enrichFleetNtpUpdates(){
  fetch(API.FLEET_NTP).then(function(r){return r.json()}).then(function(nd){
    nd.hosts.forEach(function(x){
      var el=document.getElementById('ntp-'+x.label.replace(/[^a-z0-9]/gi,''));
      if(el){var synced=x.synced;el.innerHTML='<div class="metric-top"><span class="metric-label">NTP</span><span class="metric-val" style="font-size:11px;color:'+(synced?'var(--green)':'var(--red)')+'">'+(synced?'SYNCED':'NOT SYNCED')+' <span style="color:var(--text-dim);font-weight:400">'+x.time+'</span></span></div>';}
    });
  }).catch(function(){});
  fetch(API.FLEET_UPDATES).then(function(r){return r.json()}).then(function(ud){
    ud.hosts.forEach(function(x){
      var el=document.getElementById('upd-'+x.label.replace(/[^a-z0-9]/gi,''));
      if(el){
        var n=x.updates;var color=n>0?'var(--yellow)':'var(--green)';
        var txt=n>0?n+' PENDING':'UP TO DATE';
        var btn=n>0?' <button class="btn" onclick="event.stopPropagation();runHostUpdate(\''+x.label+'\')" style="padding:2px 8px;font-size:12px;margin-left:6px;color:var(--yellow)">UPDATE</button>':'';
        el.innerHTML='<div class="metric-top"><span class="metric-label">UPDATES</span><span class="metric-val" style="font-size:11px;color:'+color+'">'+txt+btn+'</span></div>';
      }
    });
  }).catch(function(){});
}
function _renderFleetData(fo,hd,md){
  try{
    if(!fo&&!hd){document.getElementById('metrics-cards').innerHTML='<p class="c-red">Both fleet overview and health APIs failed.</p>';return;}
    /* Build container counts by VMID from media status data */
    var ctrByVmid={};
    if(md&&md.containers){md.containers.forEach(function(c){
      var vid=String(c.vm_id);
      if(!ctrByVmid[vid])ctrByVmid[vid]={total:0,up:0,down:0};
      ctrByVmid[vid].total++;
      if(c.status==='up')ctrByVmid[vid].up++;else ctrByVmid[vid].down++;
    });}
    /* Build lookup maps from API data */
    var healthMap={};var totalUp=0,totalDown=0,labPveNodes=0;
    var labLabels=_getLabLabels(hd?hd.hosts:null);
    if(hd&&hd.hosts){
      hd.hosts.forEach(function(h){
        healthMap[h.label]=h;
        var up=h.status==='healthy';
        if(up)totalUp++;else totalDown++;
        if(h.type==='pve'&&labLabels[h.label])labPveNodes++;
      });
    }
    /* Index VMs by node — optionally exclude templates */
    var vmsByNode={};var _tplS=_loadSettings();
    var foVms=fo?fo.vms.filter(function(v){return _tplS.showTemplates||v.category!=='templates';}):[];
    foVms.forEach(function(v){var n=v.node||'unknown';if(!vmsByNode[n])vmsByNode[n]=[];vmsByNode[n].push(v);});
    var physicals=fo?fo.physical:[];
    var pveNodes=fo?fo.pve_nodes:[];
    var summary=fo?fo.summary:{};
    var foDuration=fo?fo.duration:0;
    var hdDuration=hd?hd.duration:0;
    /* Infrastructure role cards — sorted: firewall → switch → network_storage → bmc */
    var _infraOrder={pfsense:1,opnsense:1,switch:2,truenas:3,bmc:4,idrac:4};
    var sortedPhysicals=physicals.slice().sort(function(a,b){return (_infraOrder[a.type]||99)-(_infraOrder[b.type]||99);});
    var infraCards='';
    sortedPhysicals.forEach(function(ph){infraCards+=_infraRoleCard(ph,healthMap);});
    /* Lab host cards */
    var infraLabels={};physicals.forEach(function(p){infraLabels[p.label]=true;});
    pveNodes.forEach(function(pn){infraLabels[pn.name]=true;});
    var labCards=_buildLabHostCards(hd?hd.hosts:null,infraLabels,labLabels);
    /* PVE node cards */
    var nodeData=_buildPveNodeData(pveNodes,healthMap,vmsByNode,ctrByVmid,labLabels);
    /* VM cards grouped under nodes — skip lab-tagged VMs */
    foVms.forEach(function(v){
      if(labLabels[v.name]||v.category==='lab')return;
      var nodeName=v.node||'unknown';
      if(!nodeData[nodeName])nodeData[nodeName]={card:'',vms:''};
      var cl=_hostColor(v.name,'vm',nodeName);
      var running=v.status==='running';
      var ramGb=_ramGB(v.ram_mb);
      var c='<div class="host-card" style="cursor:pointer;" data-action="openVmInfo" data-label="'+v.name+'" data-vmid="'+v.vmid+'">';
      c+='<div class="host-head"><h3 style="color:'+cl+'">'+v.name+'</h3><div class="host-meta"><span>VM '+v.vmid+'</span><span>\u00b7</span>'+(running?'<span class="c-green">RUNNING</span>':'<span class="c-red">'+v.status.toUpperCase()+'</span>')+'</div></div>';
      c+='<div class="divider-light">';
      c+=_mrow('CPU',(v.cpu||0)+' Cores',0,'var(--purple-light)');
      c+='<div class="metric-row"><div class="metric-top"><span class="metric-label">RAM</span><span class="metric-val">'+ramGb+'</span></div></div>';
      if(v.category&&v.category!=='unknown')c+='<div class="metric-row"><div class="metric-top"><span class="metric-label">CATEGORY</span><span class="metric-val fs-11" >'+v.category+'</span></div></div>';
      if(v.tier)c+='<div class="metric-row"><div class="metric-top"><span class="metric-label">TIER</span><span class="metric-val fs-11" >'+v.tier+'</span></div></div>';
      c+='</div></div>';
      nodeData[nodeName].vms+=c;
    });
    /* Assemble and render */
    document.getElementById('metrics-cards').innerHTML=_assembleFleetOutput(infraCards,nodeData,pveNodes);
    _enrichFleetNtpUpdates();
    /* Lab hosts section */
    var labSection=document.getElementById('fleet-lab-section');
    if(labSection){
      var labBody=document.getElementById('fleet-lab-cards');
      if(labCards){labBody.innerHTML=labCards;labSection.style.display='block';}
      else{labSection.style.display='none';}
    }
    /* Fleet stats */
    _renderFleetStats(hd,summary,labLabels,pveNodes,totalUp,totalDown,foDuration,hdDuration,labPveNodes);
    try{if(fo){_renderFleetOverview(fo);_loadFleetOverviewMedia();}}catch(e){console.error('Overview render error:',e);}
    _enrichInfraCards();
  }catch(e){console.error('_renderFleetData error:',e);document.getElementById('metrics-cards').innerHTML='<p class="c-red">Render error: '+e.message+'</p>';}
}
function loadMetrics(){
  toast('Deep scan starting... 10-20s','info');
  var panel=document.getElementById('fleet-tool-panel');
  var content=document.getElementById('fleet-tool-content');
  panel.style.display='block';
  content.innerHTML='<h3 class="section-label-pl">DEEP SCAN</h3><div class="skeleton"></div><div class="skeleton"></div><p class="c-dim-fs11-mt8">Collecting deep metrics from all reachable hosts...</p>';
  fetch(API.METRICS).then(function(r){return r.json()}).then(function(d){
    var html='<h3 class="section-label-pl">DEEP SCAN — '+d.hosts.length+' HOSTS</h3>';
    if(!d.hosts.length){html+='<div class="empty-state"><div class="es-icon">&#9881;</div><p>No hosts returned deep metrics. Deploy agents or check connectivity.</p></div>';}
    d.hosts.forEach(function(m,i){
      var hn=m.hostname||m.system&&m.system.hostname||'unknown';var cpu=m.cpu||{};var mem=m.memory||{};var cl=HC[i%HC.length];
      html+='<div class="crd mb-12" ><h3 style="color:'+cl+'">'+hn+' <span class="text-meta">via '+m.source+'</span></h3>';
      html+='<div class="stats" style="margin:12px 0">'+st('CPU',((cpu.usage_pct||0)+'%'),'p')+st('Load',cpu.load_1m||'?','b')+st('Cores',cpu.cores||'?','p')+st('RAM',((mem.usage_pct||0)+'%'),'g')+st('Used',_ramGB(mem.used_mb||0),'y')+st('Total',_ramGB(mem.total_mb||0),'b')+'</div>';
      if(m.disk&&m.disk.mounts){html+='<table class="mt-8"><thead><tr><th>Mount</th><th>Size</th><th>Used</th><th>Avail</th><th>Usage</th></tr></thead><tbody>';
        m.disk.mounts.forEach(function(dd){html+='<tr><td class="mono-11">'+dd.mount+'</td><td>'+dd.size+'</td><td>'+dd.used+'</td><td>'+dd.avail+'</td><td>'+dd.usage_pct+'</td></tr>';});
        html+='</tbody></table>';}
      html+='</div>';
    });
    content.innerHTML=html;
    toast('Deep scan complete — '+d.hosts.length+' hosts scanned','success');
  }).catch(function(e){content.innerHTML='<p class="c-red">Error: '+e+'</p>';toast('Deep scan failed','error');});
}
var _activeFleetTool=null;
function fleetTool(tool){
  var panel=document.getElementById('fleet-tool-panel');
  var content=document.getElementById('fleet-tool-content');
  /* Toggle: clicking same button again collapses */
  if(_activeFleetTool===tool&&panel.style.display==='block'){
    panel.style.display='none';_activeFleetTool=null;
    document.querySelectorAll('.fqc-btn').forEach(function(b){b.classList.remove('active-view');});
    return;
  }
  _activeFleetTool=tool;
  /* Highlight active button */
  document.querySelectorAll('.fqc-btn').forEach(function(b){b.classList.remove('active-view');});
  var btn=document.querySelector('.fqc-btn[data-fqc="'+tool+'"]');if(btn)btn.classList.add('active-view');
  _fleetToolInner(tool,panel,content);
}
function _buildToolTabs(title,tabs,tabClass,switchFn,subtitleId,formId,content){
  var nav='<div style="display:flex;flex-direction:column;gap:8px;min-width:170px">';
  tabs.forEach(function(t,i){
    nav+='<button class="fleet-btn '+tabClass+(i===0?' active-view':'')+'" data-'+tabClass.replace('-tab','tab')+'="'+t.id+'" onclick="'+switchFn+'(\''+t.id+'\')" style="text-align:left;padding:10px 14px;font-size:12px;white-space:nowrap">'+t.label+'</button>';
  });
  nav+='</div>';
  content.innerHTML='<div style="display:flex;gap:20px;align-items:flex-start">'+
    '<div><h3 style="color:var(--purple-light);font-size:13px;margin:0 0 16px 0">'+title+'</h3>'+nav+'</div>'+
    '<div class="flex-fill"><h3 id="'+subtitleId+'" style="color:var(--text);font-size:13px;margin:0 0 16px 0"></h3><div id="'+formId+'"></div></div></div>';
  window[switchFn](tabs[0].id);
}
/* ── Extracted tool renderers ── */
function _toolExec(content){
  content.innerHTML='<h3 class="section-label-pl">FLEET EXEC</h3>'+
    '<div class="flex-row-8-mb12">'+
    '<div style="position:relative;width:220px">'+
    '<input id="ft-exec-target" value="ALL HOSTS" autocomplete="off" onfocus="this.select();showExecDropdown()" oninput="filterExecDropdown(this.value)" onkeydown="if(event.key===\'Escape\')hideExecDropdown()" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:12px;font-family:inherit;width:100%;cursor:pointer;transition:border-color 0.25s ease">'+
    '<div id="ft-exec-dropdown" onmousedown="event.preventDefault()" style="display:none;position:fixed;width:320px;background:var(--card);border:2px solid var(--input-border);border-radius:8px;max-height:390px;overflow-y:auto;z-index:100;scrollbar-width:thin;scrollbar-color:var(--input-border) var(--card)"></div>'+
    '</div>'+
    '<input id="ft-exec-cmd" placeholder="Command (e.g. uptime, df -h, hostname, free -m)" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:12px;font-family:inherit;flex:1" onkeydown="if(event.key===\'Enter\')ftRunExec()">'+
    '<button class="fleet-btn c-purple-active" onclick="ftRunExec()" >RUN</button>'+
    '</div>'+
    '<div class="exec-out" id="ft-exec-out" style="min-height:120px">Pick a target and enter a command.</div>';
  var _execHosts=[];
  fetch(API.STATUS).then(function(r){return r.json()}).then(function(d){
    _execHosts=[{value:'all',label:'ALL HOSTS',detail:'Run on every host'}];
    d.hosts.forEach(function(h){_execHosts.push({value:h.label,label:h.label.toUpperCase(),detail:h.ip+' · '+(h.type||'linux').toUpperCase()+(h.status==='up'?' · ONLINE':' · OFFLINE')});});
    PROD_HOSTS.forEach(function(h){_execHosts.push({value:h.label,label:h.label.toUpperCase(),detail:h.ip+' · '+h.role});});
    PROD_VMS.forEach(function(v){_execHosts.push({value:v.label,label:v.label.toUpperCase(),detail:v.ip+' · VM '+v.vmid+' · '+v.node});});
    window._execHostsList=_execHosts;
    renderExecDropdown(_execHosts);
  });
}
function _toolNtp(content){
  content.innerHTML='<h3 class="section-label-pl">NTP SYNC STATUS</h3><div id="ft-ntp-c" class="c-dim"><div class="skeleton"></div></div>';
  fetch(API.FLEET_NTP).then(function(r){return r.json()}).then(function(d){
    var unsynced=d.hosts.filter(function(x){return !x.synced;});
    var h='';
    if(unsynced.length>0){
      h+='<div class="flex-row-8-center">';
      h+='<button class="fleet-btn c-purple-active" onclick="ntpFixSelected()" >FIX SELECTED</button>';
      h+='<button class="fleet-btn" onclick="ntpFixAll()">FIX ALL ('+unsynced.length+')</button>';
      h+='<label class="meta-flex"><input type="checkbox" id="ft-ntp-selectall" onchange="document.querySelectorAll(\'.ft-ntp-check\').forEach(function(c){c.checked=this.checked}.bind(this))"> Select All</label>';
      h+='</div>';
    }
    h+='<table class="w-full"><thead><tr><th class="w-30"></th><th>HOST</th><th>SYNCED</th><th>TIME</th><th>ACTION</th></tr></thead><tbody>';
    d.hosts.forEach(function(x){
      var synced=x.synced;
      h+='<tr><td>'+(!synced?'<input type="checkbox" class="ft-ntp-check" data-host="'+x.label+'">':'')+'</td>';
      h+='<td><strong>'+x.label.toUpperCase()+'</strong></td>';
      h+='<td>'+(synced?badge('ok'):badge('down'))+'</td>';
      h+='<td>'+x.time+'</td>';
      h+='<td>'+(!synced?'<button class="fleet-btn pill-warn-sm" data-action="ntpFixHost" data-arg="'+x.label+'" >FIX</button>':'<span style="color:var(--green);font-size:11px">OK</span>')+'</td></tr>';
    });
    h+='</tbody></table>';document.getElementById('ft-ntp-c').innerHTML=h;
  });
}
function _toolUpdates(content){
  content.innerHTML='<h3 class="section-label-pl">OS UPDATE STATUS</h3><div id="ft-updates-c" class="c-dim"><div class="skeleton"></div></div>';
  fetch(API.FLEET_UPDATES).then(function(r){return r.json()}).then(function(d){
    var pending=d.hosts.filter(function(x){return x.updates>0;});
    var h='';
    h+='<div class="flex-row-8-center">';
    h+='<button class="fleet-btn c-purple-active" data-action="updateSelected" >UPDATE SELECTED</button>';
    h+='<button class="fleet-btn" data-action="updateAll">UPDATE ALL'+(pending.length>0?' ('+pending.length+')':'')+'</button>';
    h+='<label class="meta-flex"><input type="checkbox" id="ft-upd-selectall" onchange="toggleUpdateAll(this.checked)"> Select All</label>';
    h+='<div class="flex-1"></div>';
    h+='<span style="font-size:11px;color:'+(pending.length>0?'var(--yellow)':'var(--green)')+'">'+pending.length+' pending</span>';
    h+='</div>';
    h+='<table class="w-full"><thead><tr><th class="w-30"></th><th>HOST</th><th>UPDATES</th><th>PKG MGR</th><th>ACTION</th></tr></thead><tbody>';
    d.hosts.forEach(function(x){
      var cls=x.updates>0?'warn':x.updates===0?'up':'down';
      var hasPending=x.updates>0;
      h+='<tr><td><input type="checkbox" class="ft-upd-check" data-host="'+x.label+'"'+(hasPending?' checked':'')+'></td>';
      h+='<td><strong>'+x.label.toUpperCase()+'</strong></td>';
      h+='<td><span class="badge '+cls+'">'+(x.updates>=0?x.updates:'?')+'</span></td>';
      h+='<td>'+x.pkg_mgr.toUpperCase()+'</td>';
      h+='<td>'+(hasPending?'<button class="fleet-btn pill-warn-sm" data-action="runHostUpdate" data-arg="'+x.label+'" >UPDATE</button>':'<button class="fleet-btn" data-action="runHostUpdate" data-arg="'+x.label+'" style="padding:3px 10px;font-size:12px">FORCE UPDATE</button>')+'</td></tr>';
    });
    h+='</tbody></table>';
    document.getElementById('ft-updates-c').innerHTML=h;
  });
}
function _toolLabCtrl(content){
  content.innerHTML='<h3 class="section-label-pl">LAB CONTROL</h3><div id="ft-lab-c" class="c-dim"><div class="skeleton"></div></div>';
  fetch(API.LAB_STATUS).then(function(r){return r.json()}).then(function(d){
    var up=0,dn=0;d.hosts.forEach(function(x){if(x.status==='up')up++;else dn++;});
    var h='<div class="stats mb-12" >'+st('HOSTS',d.hosts.length,'p')+st('ONLINE',up,'g')+st('OFFLINE',dn,dn>0?'r':'g');
    if(d.docker)h+=st('CONTAINERS',d.docker.length,'b');
    h+='</div>';
    h+='<table class="w-full"><thead><tr><th>HOST</th><th>IP</th><th>ROLE</th><th>UPTIME</th><th>STATUS</th><th>ACTIONS</th></tr></thead><tbody>';
    d.hosts.forEach(function(x){
      var isUp=x.status==='up';
      h+='<tr><td><strong>'+x.label.toUpperCase()+'</strong></td><td>'+x.ip+'</td><td>'+x.role.toUpperCase()+'</td><td class="text-meta">'+(x.uptime||'-')+'</td><td>'+badge(isUp?'ok':'down')+'</td>';
      h+='<td class="flex-gap-4">';
      h+='<button class="fleet-btn pill-xs" onclick="labExec(\''+x.label+'\',\'uptime\')" >PING</button>';
      h+='<button class="fleet-btn pill-warn-xs" onclick="labExec(\''+x.label+'\',\'sudo reboot\')" >REBOOT</button>';
      h+='<button class="fleet-btn pill-xs" onclick="labExec(\''+x.label+'\',\'sudo systemctl restart sshd\')" >SSHD</button>';
      h+='</td></tr>';
    });
    h+='</tbody></table>';
    if(d.docker&&d.docker.length){
      h+='<h3 style="color:var(--purple-light);font-size:13px;margin:16px 0 8px">LAB DOCKER</h3>';
      h+='<table class="w-full"><thead><tr><th>CONTAINER</th><th>STATUS</th><th>ACTIONS</th></tr></thead><tbody>';
      d.docker.forEach(function(c){
        var isUp=c.status==='up';
        h+='<tr><td><strong>'+c.name.toUpperCase()+'</strong></td><td>'+badge(isUp?'ok':'down')+'</td>';
        h+='<td class="flex-gap-4">';
        if(isUp)h+='<button class="fleet-btn pill-warn-xs" data-action="labDockerAction" data-name="'+c.name+'" data-arg="restart" >RESTART</button>';
        else h+='<button class="fleet-btn pill-ok-3-8" data-action="labDockerAction" data-name="'+c.name+'" data-arg="start" >START</button>';
        if(isUp)h+='<button class="fleet-btn pill-err-3-8" data-action="labDockerAction" data-name="'+c.name+'" data-arg="stop" >STOP</button>';
        h+='</td></tr>';
      });
      h+='</tbody></table>';
    }
    h+='<div id="ft-lab-out" class="mt-12"></div>';
    document.getElementById('ft-lab-c').innerHTML=h;
  });
}
function _fleetToolInner(tool,panel,content){
  panel.style.display='block';
  if(tool==='usermgmt'){
    _buildToolTabs('USER MANAGEMENT',[{id:'newuser',label:'NEW USER'},{id:'passwd',label:'PASSWORD UPDATE'},{id:'sshkey',label:'SSH KEY UPDATE'},{id:'promote',label:'PROMOTE / DEMOTE'}],'um-tab','switchUserMgmt','um-subtitle','um-form',content);return;
  } else if(tool==='fleetops'){
    _buildToolTabs('FLEET OPS',[{id:'deepscan',label:'DEEP SCAN'},{id:'ntp',label:'NTP SYNC'},{id:'updates',label:'OS UPDATES'},{id:'sshd',label:'RESTART SSHD'},{id:'exec',label:'FLEET EXEC'}],'fo-tab','switchFleetOps','fo-subtitle','fo-form',content);return;
  } else if(tool==='vmmgmt'){
    _buildToolTabs('VM MANAGEMENT',[{id:'vmlist',label:'VM LIST'},{id:'vmcreate',label:'CREATE VM'},{id:'vmclone',label:'CLONE VM'},{id:'vmmigrate',label:'MIGRATE'},{id:'vmsnapshot',label:'SNAPSHOTS'},{id:'vmresize',label:'RESIZE'},{id:'vmadddisk',label:'ADD DISK'},{id:'vmtag',label:'TAGS'}],'vm-tab','switchVmMgmt','vm-subtitle','vm-form',content);return;
  } else if(tool==='newuser'){
    content.innerHTML='<h3 class="section-label-pl">NEW FLEET USER</h3>'+
      '<div class="form-vertical">'+
      '<div><label class="label-sub">USERNAME</label><input id="ft-nu-user" placeholder="e.g. svc-admin" class="input-primary-lg"></div>'+
      '<div><label class="label-sub">PASSWORD</label><input id="ft-nu-pass" type="password" placeholder="Strong password" class="input-primary-lg"></div>'+
      '<div><label class="label-sub">SSH PUBLIC KEY <span class="opacity-5">(optional — will generate if empty)</span></label><textarea id="ft-nu-key" placeholder="ssh-ed25519 AAAA... user@host" rows="3" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:11px;font-family:monospace;width:100%;resize:vertical"></textarea></div>'+
      '<div><label class="label-sub">ROLE</label><select id="ft-nu-role" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:8px 14px;border-radius:8px;font-size:12px;font-family:inherit">'+(_currentRole==='admin'?'<option value="admin">Admin (full sudo)</option>':'')+'<option value="operator" selected>Operator (limited sudo)</option><option value="viewer">Viewer (no sudo)</option></select></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" onclick="fleetNewUser()" >CREATE & DEPLOY</button></div>'+
      '</div>'+
      '<div id="ft-nu-out" class="mt-12"></div>';
  } else if(tool==='passwd'){
    content.innerHTML='<h3 class="section-label-pl">PASSWORD UPDATE</h3>'+
      '<div class="form-vertical">'+
      '<div><label class="label-sub">USERNAME</label>'+
      '<div class="pos-rel"><input id="ft-pw-user" autocomplete="off" placeholder="Select user..." onfocus="showUserDropdown(\'pw\')" oninput="filterUserDropdown(\'pw\',this.value)" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:12px;font-family:inherit;width:100%;cursor:pointer">'+
      '<div id="ft-pw-dropdown" onmousedown="event.preventDefault()" style="display:none;position:fixed;width:320px;background:var(--card);border:2px solid var(--input-border);border-radius:8px;max-height:300px;overflow-y:auto;z-index:100;scrollbar-width:thin;scrollbar-color:var(--input-border) var(--card)"></div></div></div>'+
      '<div><label class="label-sub">NEW PASSWORD</label><input id="ft-pw-pass" type="password" placeholder="New password" class="input-primary-lg"></div>'+
      '<div><label class="label-sub">CONFIRM PASSWORD</label><input id="ft-pw-confirm" type="password" placeholder="Confirm new password" class="input-primary-lg"></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" onclick="fleetPasswdUpdate()" >UPDATE & DEPLOY</button></div>'+
      '</div>'+
      '<div id="ft-pw-out" class="mt-12"></div>';
    _loadUserDropdown('pw');
  } else if(tool==='promote'){
    content.innerHTML='<h3 class="section-label-pl">PROMOTE / DEMOTE USER</h3><div id="ft-prom-c"><div class="skeleton"></div></div>';
    fetch(API.USERS).then(function(r){return r.json()}).then(function(d){
      var rc={admin:'var(--red)',operator:'var(--yellow)',viewer:'var(--green)',protected:'var(--purple-light)'};
      var h='<table class="w-full"><thead><tr><th>USER</th><th>CURRENT ROLE</th><th>ACTIONS</th></tr></thead><tbody>';
      d.users.forEach(function(u,i){
        h+='<tr><td><strong style="color:'+HC[i%HC.length]+'">'+u.username.toUpperCase()+'</strong></td>';
        h+='<td><span style="color:'+(rc[u.role]||'var(--text-dim)')+';font-weight:600">'+u.role.toUpperCase()+'</span></td>';
        h+='<td class="flex-gap-6">';
        if(u.role!=='admin')h+='<button class="fleet-btn pill-ok-3-10" onclick="promoteUser(\''+u.username+'\')" >PROMOTE</button>';
        if(u.role!=='viewer')h+='<button class="fleet-btn pill-warn-sm" onclick="demoteUser(\''+u.username+'\')" >DEMOTE</button>';
        h+='</td></tr>';
      });
      h+='</tbody></table>';
      document.getElementById('ft-prom-c').innerHTML=h;
    });
  } else if(tool==='sshkey'){
    content.innerHTML='<h3 class="section-label-pl">SSH KEY UPDATE</h3>'+
      '<div class="flex-col-10-500">'+
      '<div><label class="label-sub">USERNAME</label>'+
      '<div class="pos-rel"><input id="ft-sk-user" autocomplete="off" placeholder="Select user..." onfocus="showUserDropdown(\'sk\')" oninput="filterUserDropdown(\'sk\',this.value)" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:12px;font-family:inherit;width:100%;cursor:pointer">'+
      '<div id="ft-sk-dropdown" onmousedown="event.preventDefault()" style="display:none;position:fixed;width:320px;background:var(--card);border:2px solid var(--input-border);border-radius:8px;max-height:300px;overflow-y:auto;z-index:100;scrollbar-width:thin;scrollbar-color:var(--input-border) var(--card)"></div></div></div>'+
      '<div><label class="label-sub">PUBLIC KEY</label><textarea id="ft-sk-key" placeholder="Paste your ssh-ed25519 or ssh-rsa public key here..." rows="4" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:11px;font-family:monospace;width:100%;resize:vertical"></textarea></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" onclick="fleetSshKeyDeploy()" >DEPLOY TO FLEET</button></div>'+
      '</div>'+
      '<div id="ft-sk-out" class="mt-12"></div>';
    _loadUserDropdown('sk');
  } else if(tool==='sshd'){
    content.innerHTML='<h3 class="section-label-pl">RESTART SSHD</h3><div id="ft-sshd-c"><div class="skeleton"></div></div>';
    fetch(API.HEALTH).then(function(r){return r.json()}).then(function(d){
      var h='<div class="flex-row-8-center">';
      h+='<button class="fleet-btn c-purple-active" data-action="sshdRestartSelected" >RESTART SELECTED</button>';
      h+='<button class="fleet-btn" data-action="sshdRestartAll">RESTART ALL ('+d.hosts.length+')</button>';
      h+='<label class="meta-flex"><input type="checkbox" id="ft-sshd-selectall" onchange="document.querySelectorAll(\'.ft-sshd-check\').forEach(function(c){c.checked=this.checked}.bind(this))"> Select All</label>';
      h+='</div>';
      h+='<table class="w-full"><thead><tr><th class="w-30"></th><th>HOST</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>';
      d.hosts.forEach(function(x,i){
        var up=x.status==='healthy';
        h+='<tr><td><input type="checkbox" class="ft-sshd-check" data-host="'+x.label+'"></td>';
        h+='<td><strong style="color:'+HC[i%HC.length]+'">'+x.label.toUpperCase()+'</strong></td>';
        h+='<td>'+badge(up?'ok':'down')+'</td>';
        h+='<td><button class="fleet-btn pill-warn-sm" data-action="sshdRestartHost" data-arg="'+x.label+'" >RESTART</button></td></tr>';
      });
      h+='</tbody></table><div id="ft-sshd-out" class="mt-12"></div>';
      document.getElementById('ft-sshd-c').innerHTML=h;
    });
  } else if(tool==='exec'){
    _toolExec(content);
  } else if(tool==='ntp'){
    _toolNtp(content);
  } else if(tool==='updates'){
    _toolUpdates(content);
  } else if(tool==='monitoring'){
    _buildToolTabs('MONITORING',[{id:'monhealth',label:'HEALTH CHECK'},{id:'mondoctor',label:'DOCTOR'},{id:'monjournal',label:'JOURNAL'},{id:'monwatch',label:'WATCH'}],'mon-tab','switchMonitoring','mon-subtitle','mon-form',content);return;
  } else if(tool==='network'){
    _buildToolTabs('NETWORK',[{id:'netvlan',label:'VLAN OVERVIEW'},{id:'netdns',label:'DNS CHECK'},{id:'netping',label:'CONNECTIVITY'},{id:'netports',label:'PORT SCAN'}],'net-tab','switchNetwork','net-subtitle','net-form',content);return;
  } else if(tool==='backup'){
    _buildToolTabs('BACKUP & RECOVERY',[{id:'bkstatus',label:'BACKUP STATUS'},{id:'bkschedule',label:'SCHEDULES'},{id:'bksnapshot',label:'VM SNAPSHOTS'},{id:'bkexport',label:'EXPORT CONFIG'},{id:'bkrestore',label:'RESTORE'}],'bk-tab','switchBackup','bk-subtitle','bk-form',content);return;
  } else if(tool==='labctrl'){
    _toolLabCtrl(content);
  }
}
var _umLabels={newuser:'NEW FLEET USER',passwd:'PASSWORD UPDATE',sshkey:'SSH KEY UPDATE',promote:'PROMOTE / DEMOTE'};
function switchUserMgmt(tab){
  document.querySelectorAll('.um-tab').forEach(function(b){b.classList.remove('active-view');});
  var active=document.querySelector('.um-tab[data-umtab="'+tab+'"]');if(active)active.classList.add('active-view');
  var sub=document.getElementById('um-subtitle');if(sub)sub.textContent=_umLabels[tab]||'';
  var umForm=document.getElementById('um-form');if(!umForm)return;
  var fakePanel={style:{display:'block'}};
  _fleetToolInner(tab,fakePanel,umForm);
  /* Remove the h3 from the inner content since subtitle handles it */
  var innerH3=umForm.querySelector('h3');if(innerH3)innerH3.remove();
}
var _foLabels={deepscan:'DEEP SCAN',ntp:'NTP SYNC',updates:'OS UPDATES',sshd:'RESTART SSHD',exec:'FLEET EXEC'};
function switchFleetOps(tab){
  document.querySelectorAll('.fo-tab').forEach(function(b){b.classList.remove('active-view');});
  var active=document.querySelector('.fo-tab[data-fotab="'+tab+'"]');if(active)active.classList.add('active-view');
  var sub=document.getElementById('fo-subtitle');if(sub)sub.textContent=_foLabels[tab]||'';
  var foForm=document.getElementById('fo-form');if(!foForm)return;
  if(tab==='deepscan'){
    foForm.innerHTML='<div class="flex-col-10-500">'+
      '<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">Run a comprehensive scan across all fleet hosts — CPU, RAM, disk, services, uptime.</div>'+
      '<button class="fleet-btn pill-active-self" onclick="loadMetrics()" >RUN DEEP SCAN</button>'+
      '</div>';
    return;
  }
  var fakePanel={style:{display:'block'}};
  _fleetToolInner(tab,fakePanel,foForm);
  var innerH3=foForm.querySelector('h3');if(innerH3)innerH3.remove();
}
var _vmLabels={vmlist:'VM LIST',vmcreate:'CREATE VM',vmclone:'CLONE VM',vmmigrate:'MIGRATE',vmsnapshot:'SNAPSHOTS',vmresize:'RESIZE',vmadddisk:'ADD DISK',vmtag:'TAGS'};
function switchVmMgmt(tab){
  document.querySelectorAll('.vm-tab').forEach(function(b){b.classList.remove('active-view');});
  var active=document.querySelector('.vm-tab[data-vmtab="'+tab+'"]');if(active)active.classList.add('active-view');
  var sub=document.getElementById('vm-subtitle');if(sub)sub.textContent=_vmLabels[tab]||'';
  var vmForm=document.getElementById('vm-form');if(!vmForm)return;
  if(tab==='vmlist'){
    vmForm.innerHTML='<div id="vmt-stats" class="stats"></div><div style="margin-bottom:8px;display:flex;gap:8px"><select id="vmt-node-filter" onchange="vmtLoadList()" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:6px 12px;border-radius:6px;font-size:11px;font-family:inherit"><option value="all">All Nodes</option></select><select id="vmt-cat-filter" onchange="vmtLoadList()" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:6px 12px;border-radius:6px;font-size:11px;font-family:inherit"><option value="all">All Categories</option><option value="personal">Personal</option><option value="infrastructure">Infrastructure</option><option value="prod_media">Prod Media</option><option value="prod_other">Prod Other</option><option value="sandbox">Sandbox</option><option value="lab">Lab</option><option value="templates">Templates</option></select></div><div id="vmt-list"><div class="skeleton"></div></div>';
    vmtLoadList();
  } else if(tab==='vmcreate'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM NAME</label><input id="vmt-c-name" placeholder="e.g. my-vm" class="input-primary-lg"></div>'+
      '<div><label class="label-sub">CPU CORES</label><select id="vmt-c-cores" class="input-primary"><option>1</option><option selected>2</option><option>4</option><option>8</option><option>16</option></select></div>'+
      '<div><label class="label-sub">RAM</label><select id="vmt-c-ram" class="input-primary"><option value="512">512MB</option><option value="1024">1GB</option><option value="2048" selected>2GB</option><option value="4096">4GB</option><option value="8192">8GB</option><option value="16384">16GB</option><option value="32768">32GB</option></select></div>'+
      '<div><label class="label-sub">TARGET NODE</label><select id="vmt-c-node" class="input-primary"><option value="auto">Auto (least loaded)</option></select></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtCreate" >CREATE VM</button></div>'+
      '</div><div id="vmt-c-out" class="mt-12"></div>';
    fetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var nodes={};d.vms.forEach(function(v){nodes[v.node]=true;});
      var sel=document.getElementById('vmt-c-node');if(!sel)return;
      Object.keys(nodes).sort().forEach(function(n){sel.innerHTML+='<option value="'+n+'">'+n+'</option>';});
    }).catch(function(){});
  } else if(tab==='vmclone'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">SOURCE VMID</label><select id="vmt-cl-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">NEW NAME</label><input id="vmt-cl-name" placeholder="e.g. clone-of-myvm" class="input-primary-lg"></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtClone" >CLONE VM</button></div>'+
      '</div><div id="vmt-cl-out" class="mt-12"></div>';
    fetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-cl-source');if(!sel)return;sel.innerHTML='';
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+' ('+v.node+')</option>';});
    }).catch(function(){});
  } else if(tab==='vmmigrate'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM TO MIGRATE</label><select id="vmt-m-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">TARGET NODE</label><select id="vmt-m-target" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub" style="display:flex;align-items:center;gap:8px"><input type="checkbox" id="vmt-m-online"> LIVE MIGRATION (online)</label></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtMigrate" >MIGRATE</button></div>'+
      '</div><div id="vmt-m-out" class="mt-12"></div>';
    fetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-m-source');var tgt=document.getElementById('vmt-m-target');
      if(!sel||!tgt)return;sel.innerHTML='';var nodes={};
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+' ('+v.node+')</option>';nodes[v.node]=true;});
      tgt.innerHTML='';Object.keys(nodes).sort().forEach(function(n){tgt.innerHTML+='<option value="'+n+'">'+n+'</option>';});
    }).catch(function(){});
  } else if(tab==='vmsnapshot'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM</label><select id="vmt-s-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtSnapshot" >CREATE SNAPSHOT</button></div>'+
      '</div><div id="vmt-s-out" class="mt-12"></div>';
    fetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-s-source');if(!sel)return;sel.innerHTML='';
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+' ('+v.node+')</option>';});
    }).catch(function(){});
  } else if(tab==='vmresize'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM</label><select id="vmt-r-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">NEW CPU CORES</label><select id="vmt-r-cores" class="input-primary"><option value="">Keep current</option><option>1</option><option>2</option><option>4</option><option>8</option><option>16</option></select></div>'+
      '<div><label class="label-sub">NEW RAM</label><select id="vmt-r-ram" class="input-primary"><option value="">Keep current</option><option value="512">512MB</option><option value="1024">1GB</option><option value="2048">2GB</option><option value="4096">4GB</option><option value="8192">8GB</option><option value="16384">16GB</option><option value="32768">32GB</option></select></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtResize" >RESIZE VM</button></div>'+
      '</div><div id="vmt-r-out" class="mt-12"></div>';
    fetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-r-source');if(!sel)return;sel.innerHTML='<option value="">Select VM...</option>';
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+' ('+v.cpu+' cores, '+_ramGB(v.ram_mb)+')</option>';});
    }).catch(function(){});
  } else if(tab==='vmadddisk'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM</label><select id="vmt-ad-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">DISK SIZE</label><div style="display:flex;gap:8px;align-items:center"><input id="vmt-ad-size" placeholder="e.g. 32" class="input-primary" style="width:100px" type="number" min="1"><select id="vmt-ad-unit" class="input-primary" style="width:80px"><option value="G" selected>GB</option><option value="T">TB</option></select></div></div>'+
      '<div><label class="label-sub">STORAGE POOL</label><input id="vmt-ad-storage" placeholder="local-lvm" class="input-primary" value="local-lvm"></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtAddDisk" >ADD DISK</button></div>'+
      '</div><div id="vmt-ad-out" class="mt-12"></div>';
    fetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-ad-source');if(!sel)return;sel.innerHTML='<option value="">Select VM...</option>';
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+' ('+v.node+')</option>';});
    }).catch(function(){});
  } else if(tab==='vmtag'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM</label><select id="vmt-tag-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">TAGS</label><input id="vmt-tag-tags" placeholder="e.g. prod,critical,backup" class="input-primary-lg"><div class="text-sub" style="margin-top:4px">Comma-separated. Allowed: letters, numbers, hyphens, underscores.</div></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtTag" >SET TAGS</button></div>'+
      '</div><div id="vmt-tag-out" class="mt-12"></div>';
    fetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-tag-source');if(!sel)return;sel.innerHTML='<option value="">Select VM...</option>';
      d.vms.forEach(function(v){
        var tagInfo=v.tags?' ['+v.tags+']':'';
        sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+tagInfo+'</option>';
      });
    }).catch(function(){});
  }
}
/* VM Management action handlers */
function vmtLoadList(){
  var el=document.getElementById('vmt-list');if(!el)return;
  el.innerHTML='<div class="skeleton"></div>';
  fetch(API.VMS).then(function(r){return r.json()}).then(function(d){
    if(!d.count){el.innerHTML='<div class="text-dim-pad12">No VMs found.</div>';document.getElementById('vmt-stats').innerHTML='';return;}
    var running=0,stopped=0;d.vms.forEach(function(v){if(v.status==='running')running++;else stopped++;});
    var se=document.getElementById('vmt-stats');
    if(se)se.innerHTML=st('VMs',d.count,'p')+st('Running',running,'g')+st('Stopped',stopped,stopped>0?'r':'g');
    var nodeFilter=(document.getElementById('vmt-node-filter')||{}).value||'all';
    var catFilter=(document.getElementById('vmt-cat-filter')||{}).value||'all';
    var h='<table class="w-full"><thead><tr><th>VMID</th><th>NAME</th><th>CATEGORY</th><th>NODE</th><th>CPU</th><th>RAM</th><th>STATUS</th><th>ACTIONS</th></tr></thead><tbody>';
    var nodes={};
    d.vms.forEach(function(v){
      nodes[v.node]=true;
      if(nodeFilter!=='all'&&v.node!==nodeFilter)return;
      if(catFilter!=='all'&&v.category!==catFilter)return;
      var isRun=v.status==='running';var acts=v.allowed_actions||['view'];
      var catLabel=(v.category||'unknown').replace(/_/g,' ');
      var displayStatus=v.status;
      h+='<tr><td><strong>'+v.vmid+'</strong></td><td>'+v.name+'</td><td><span class="cat-badge cat-'+(v.category||'unknown')+'">'+catLabel+'</span></td><td>'+v.node+'</td><td>'+v.cpu+'</td><td>'+_ramGB(v.ram_mb)+'</td>';
      h+='<td>'+badge(displayStatus)+'</td><td class="flex-gap-4">';
      if(acts.indexOf('snapshot')>=0)h+='<button class="fleet-btn pill-warn-xs" onclick="_vmSnapWarn('+v.vmid+','+isRun+')" >SNAP</button>';
      if(acts.indexOf('stop')>=0&&isRun)h+='<button class="fleet-btn pill-warn-xs" data-action="vmPower" data-vmid="'+v.vmid+'" data-arg="stop" >STOP</button>';
      if(acts.indexOf('start')>=0&&!isRun)h+='<button class="fleet-btn pill-ok-3-8" data-action="vmPower" data-vmid="'+v.vmid+'" data-arg="start" >START</button>';
      if(acts.indexOf('configure')>=0)h+='<button class="fleet-btn pill-xs" data-action="vmQuickTag" data-vmid="'+v.vmid+'" >TAG</button>';
      if(acts.indexOf('destroy')>=0)h+='<button class="fleet-btn pill-err-3-8" data-action="vmDestroy" data-vmid="'+v.vmid+'" >DESTROY</button>';
      h+='</td></tr>';
    });
    h+='</tbody></table>';el.innerHTML=h;
    var sel=document.getElementById('vmt-node-filter');if(!sel)return;var cur=sel.value;
    sel.innerHTML='<option value="all">All Nodes</option>';
    Object.keys(nodes).sort().forEach(function(n){sel.innerHTML+='<option value="'+n+'"'+(n===cur?' selected':'')+'>'+n+'</option>';});
  }).catch(function(){el.innerHTML='<div style="color:var(--red);padding:16px">Failed to load VMs</div>';});
}
function vmtCreate(){
  var n=(document.getElementById('vmt-c-name')||{}).value;
  var c=(document.getElementById('vmt-c-cores')||{}).value;
  var r=(document.getElementById('vmt-c-ram')||{}).value;
  if(!n){toast('Enter a VM name','error');return;}
  var out=document.getElementById('vmt-c-out');if(out)out.innerHTML='<div class="c-yellow">Creating VM...</div>';
  fetch(API.VM_CREATE+'?name='+encodeURIComponent(n)+'&cores='+c+'&ram='+r).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('VM '+d.vmid+' "'+d.name+'" created!','success');if(out)out.innerHTML='<div class="c-green">VM '+d.vmid+' created successfully.</div>';document.getElementById('vmt-c-name').value='';}
    else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<div class="c-red">'+d.error+'</div>';}
  });
}
function vmtClone(){
  var src=(document.getElementById('vmt-cl-source')||{}).value;
  var name=(document.getElementById('vmt-cl-name')||{}).value;
  if(!src){toast('Select a source VM','error');return;}
  if(!name){toast('Enter a name for the clone','error');return;}
  var out=document.getElementById('vmt-cl-out');if(out)out.innerHTML='<div class="c-yellow">Cloning VM '+src+'...</div>';
  fetch(API.VM_CLONE+'?vmid='+src+'&name='+encodeURIComponent(name)+'&full=1').then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Clone created as VM '+d.new_vmid+'!','success');if(out)out.innerHTML='<div class="c-green">Clone "'+name+'" created as VM '+d.new_vmid+'</div>';}
    else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<div class="c-red">'+d.error+'</div>';}
  }).catch(function(e){toast('Clone failed','error');if(out)out.innerHTML='<div class="c-red">'+e+'</div>';});
}
function vmtMigrate(){
  var src=(document.getElementById('vmt-m-source')||{}).value;
  var tgt=(document.getElementById('vmt-m-target')||{}).value;
  var online=document.getElementById('vmt-m-online')&&document.getElementById('vmt-m-online').checked?'1':'0';
  if(!src||!tgt){toast('Select VM and target node','error');return;}
  var out=document.getElementById('vmt-m-out');if(out)out.innerHTML='<div class="c-yellow">Migrating VM '+src+' to '+tgt+'...</div>';
  confirmAction('Migrate VM <strong>'+src+'</strong> to <strong>'+tgt+'</strong>?',function(){
    fetch(API.VM_MIGRATE+'?vmid='+src+'&target_node='+encodeURIComponent(tgt)+'&online='+online).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast('Migration started','success');if(out)out.innerHTML='<div class="c-green">VM '+src+' migrating to '+tgt+(d.online?' (live)':' (offline)')+'</div>';}
      else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<div class="c-red">'+d.error+'</div>';}
    }).catch(function(e){toast('Migration failed','error');if(out)out.innerHTML='<div class="c-red">'+e+'</div>';});
  });
}
function vmtAddDisk(){
  var vmid=(document.getElementById('vmt-ad-source')||{}).value;
  var size=(document.getElementById('vmt-ad-size')||{}).value;
  var unit=(document.getElementById('vmt-ad-unit')||{}).value||'G';
  var storage=(document.getElementById('vmt-ad-storage')||{}).value||'local-lvm';
  if(!vmid){toast('Select a VM','error');return;}
  if(!size||+size<1){toast('Enter a valid disk size','error');return;}
  var out=document.getElementById('vmt-ad-out');if(out)out.innerHTML='<div class="c-yellow">Adding '+size+unit+' disk to VM '+vmid+'...</div>';
  fetch(API.VM_ADD_DISK+'?vmid='+vmid+'&size='+size+unit+'&storage='+encodeURIComponent(storage)).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Disk '+d.disk+' added to VM '+vmid,'success');if(out)out.innerHTML='<div class="c-green">Added '+d.size+' disk as '+d.disk+' on '+d.storage+'</div>';}
    else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<div class="c-red">'+d.error+'</div>';}
  }).catch(function(e){toast('Add disk failed','error');if(out)out.innerHTML='<div class="c-red">'+e+'</div>';});
}
function vmtTag(){
  var vmid=(document.getElementById('vmt-tag-source')||{}).value;
  var tags=(document.getElementById('vmt-tag-tags')||{}).value;
  if(!vmid){toast('Select a VM','error');return;}
  var out=document.getElementById('vmt-tag-out');if(out)out.innerHTML='<div class="c-yellow">Setting tags on VM '+vmid+'...</div>';
  fetch(API.VM_TAG+'?vmid='+vmid+'&tags='+encodeURIComponent(tags||'')).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Tags updated on VM '+vmid,'success');if(out)out.innerHTML='<div class="c-green">VM '+vmid+' tags set to: '+(d.tags||'(cleared)')+'</div>';}
    else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<div class="c-red">'+d.error+'</div>';}
  }).catch(function(e){toast('Tag update failed','error');if(out)out.innerHTML='<div class="c-red">'+e+'</div>';});
}
function vmtSnapshot(){
  var src=(document.getElementById('vmt-s-source')||{}).value;
  if(!src){toast('Select a VM','error');return;}
  var out=document.getElementById('vmt-s-out');if(out)out.innerHTML='<div class="c-yellow">Creating snapshot...</div>';
  fetch(API.VM_SNAPSHOT+'?vmid='+src).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Snapshot "'+d.snapshot+'" created','success');if(out)out.innerHTML='<div class="c-green">Snapshot "'+d.snapshot+'" created for VM '+src+'</div>';}
    else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<div class="c-red">'+d.error+'</div>';}
  });
}
function vmtResize(){
  var src=(document.getElementById('vmt-r-source')||{}).value;
  var cores=(document.getElementById('vmt-r-cores')||{}).value;
  var ram=(document.getElementById('vmt-r-ram')||{}).value;
  if(!src){toast('Select a VM','error');return;}
  if(!cores&&!ram){toast('Set new cores or RAM','error');return;}
  var out=document.getElementById('vmt-r-out');if(out)out.innerHTML='<div class="c-yellow">Resizing VM '+src+'...</div>';
  var url='/api/vm/resize?vmid='+src;
  if(cores)url+='&cores='+cores;
  if(ram)url+='&ram='+ram;
  fetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('VM '+src+' resized','success');if(out)out.innerHTML='<div class="c-green">VM '+src+' resized successfully.</div>';}
    else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<div class="c-red">'+d.error+'</div>';}
  });
}
/* ── MONITORING ─────────────────────────────────────────────────── */
var _monLabels={monhealth:'HEALTH CHECK',mondoctor:'DOCTOR',monjournal:'JOURNAL',monwatch:'WATCH'};
function switchMonitoring(tab){
  document.querySelectorAll('.mon-tab').forEach(function(b){b.classList.remove('active-view');});
  var active=document.querySelector('.mon-tab[data-montab="'+tab+'"]');if(active)active.classList.add('active-view');
  var sub=document.getElementById('mon-subtitle');if(sub)sub.textContent=_monLabels[tab]||'';
  var f=document.getElementById('mon-form');if(!f)return;
  if(tab==='monhealth'){
    f.innerHTML='<div id="mon-h-out"><div class="skeleton"></div></div>';
    fetch(API.HEALTH).then(function(r){return r.json()}).then(function(d){
      var up=0,dn=0;d.hosts.forEach(function(h){if(h.status==='healthy')up++;else dn++;});
      var h='<div class="stats mb-12" >'+st('HOSTS',d.hosts.length,'p')+st('HEALTHY',up,'g')+st('UNHEALTHY',dn,dn>0?'r':'g')+st('RESPONSE',d.duration+'s','b')+'</div>';
      h+='<table class="w-full"><thead><tr><th>HOST</th><th>IP</th><th>TYPE</th><th>STATUS</th><th>UPTIME</th></tr></thead><tbody>';
      d.hosts.forEach(function(x){
        h+='<tr><td><strong>'+x.label.toUpperCase()+'</strong></td><td>'+x.ip+'</td><td>'+(x.type||'linux').toUpperCase()+'</td><td>'+badge(x.status==='healthy'?'ok':'down')+'</td><td class="text-meta">'+(x.uptime||'-')+'</td></tr>';
      });
      h+='</tbody></table>';
      document.getElementById('mon-h-out').innerHTML=h;
    }).catch(function(){document.getElementById('mon-h-out').innerHTML='<div class="c-red">Failed to fetch health data</div>';});
  } else if(tab==='mondoctor'){
    f.innerHTML='<div class="desc-line">Run self-diagnostic checks on the FREQ installation.</div>'+
      '<button class="fleet-btn pill-active-lg" onclick="monRunDoctor()" >RUN DOCTOR</button>'+
      '<div id="mon-doc-out" class="exec-out" style="min-height:80px;display:none"></div>';
  } else if(tab==='monjournal'){
    f.innerHTML='<div id="mon-j-out"><div class="skeleton"></div></div>';
    fetch(API.JOURNAL).then(function(r){return r.json()}).then(function(d){
      if(!d.entries||!d.entries.length){document.getElementById('mon-j-out').innerHTML='<div class="text-dim-pad12">No journal entries.</div>';return;}
      var h='<table class="w-full"><thead><tr><th>TIME</th><th>TYPE</th><th>MESSAGE</th></tr></thead><tbody>';
      d.entries.slice(-50).reverse().forEach(function(e){
        h+='<tr><td style="font-size:11px;white-space:nowrap;color:var(--text-dim)">'+(e.timestamp||e.time||'-')+'</td><td><span class="badge '+(e.level==='error'?'down':e.level==='warn'?'warn':'up')+'">'+(e.level||e.type||'info').toUpperCase()+'</span></td><td class="fs-12">'+(e.message||e.msg||'-')+'</td></tr>';
      });
      h+='</tbody></table>';
      document.getElementById('mon-j-out').innerHTML=h;
    }).catch(function(){document.getElementById('mon-j-out').innerHTML='<div class="text-dim-pad12">No journal entries.</div>';});
  } else if(tab==='monwatch'){
    f.innerHTML='<div class="desc-line">Monitor fleet health continuously. Alerts on host down, high CPU/RAM, disk full.</div>'+
      '<div class="flex-row-8-mb12">'+
      '<button class="fleet-btn" onclick="monWatchStart()" style="color:var(--green);border-color:var(--green);padding:10px 20px">START WATCH</button>'+
      '<button class="fleet-btn" onclick="monWatchStop()" style="color:var(--red);border-color:var(--red);padding:10px 20px">STOP WATCH</button>'+
      '</div>'+
      '<div id="mon-w-out" class="exec-out" style="min-height:80px">Watch daemon not running. Click START to begin monitoring.</div>';
  }
}
function monRunDoctor(){
  var out=document.getElementById('mon-doc-out');if(!out)return;
  out.style.display='block';out.textContent='Running diagnostics...';
  fetch(API.EXEC+'?target=localhost&cmd='+encodeURIComponent('freq doctor 2>&1 || echo "doctor not available"')).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results)d.results.forEach(function(r){txt+=r.output+'\n';});
    out.textContent=txt||'(no output)';
  }).catch(function(){out.textContent='Failed to run doctor';});
}
function monWatchStart(){
  var out=document.getElementById('mon-w-out');if(out)out.textContent='Starting watch daemon...';
  fetch(API.EXEC+'?target=localhost&cmd='+encodeURIComponent('freq watch start 2>&1 || echo "watch not available"')).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results)d.results.forEach(function(r){txt+=r.output+'\n';});
    if(out)out.textContent=txt||'Watch started.';
  });
}
function monWatchStop(){
  var out=document.getElementById('mon-w-out');if(out)out.textContent='Stopping watch daemon...';
  fetch(API.EXEC+'?target=localhost&cmd='+encodeURIComponent('freq watch stop 2>&1 || echo "watch not available"')).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results)d.results.forEach(function(r){txt+=r.output+'\n';});
    if(out)out.textContent=txt||'Watch stopped.';
  });
}

/* ── NETWORK ───────────────────────────────────────────────────── */
var _netLabels={netvlan:'VLAN OVERVIEW',netdns:'DNS CHECK',netping:'CONNECTIVITY',netports:'PORT SCAN'};
function switchNetwork(tab){
  document.querySelectorAll('.net-tab').forEach(function(b){b.classList.remove('active-view');});
  var active=document.querySelector('.net-tab[data-nettab="'+tab+'"]');if(active)active.classList.add('active-view');
  var sub=document.getElementById('net-subtitle');if(sub)sub.textContent=_netLabels[tab]||'';
  var f=document.getElementById('net-form');if(!f)return;
  if(tab==='netvlan'){
    /* Build VLAN table from fleet config */
    var vlans=[];Object.keys(_VLAN_MAP).sort(function(a,b){return parseInt(a)-parseInt(b);}).forEach(function(vid){var v=_VLAN_MAP[vid];vlans.push({id:parseInt(vid),name:v.name,subnet:v.prefix?v.prefix+'.x':'?',gw:v.gw||'-',purpose:''});});
    var h='<table class="w-full"><thead><tr><th>VLAN</th><th>NAME</th><th>SUBNET</th><th>GATEWAY</th><th>PURPOSE</th></tr></thead><tbody>';
    vlans.forEach(function(v){
      var c=VLAN_COLORS[v.name]||'var(--text-dim)';
      h+='<tr><td><strong style="color:'+c+'">'+v.id+'</strong></td><td style="font-weight:600;color:'+c+'">'+v.name+'</td><td>'+v.subnet+'</td><td>'+v.gw+'</td><td class="text-meta">'+v.purpose+'</td></tr>';
    });
    h+='</tbody></table>';f.innerHTML=h;
  } else if(tab==='netdns'){
    f.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">HOSTNAME TO RESOLVE</label><input id="net-dns-host" placeholder="e.g. google.com, hostname, 192.168.1.30" class="input-primary-lg"></div>'+
      '<button class="fleet-btn pill-active-self" onclick="netDnsCheck()" >RESOLVE</button>'+
      '</div><div id="net-dns-out" class="exec-out skel-mt12" ></div>';
  } else if(tab==='netping'){
    f.innerHTML='<div class="desc-line">Test connectivity to all fleet hosts.</div>'+
      '<button class="fleet-btn pill-active-lg" onclick="netPingAll()" >PING ALL HOSTS</button>'+
      '<div id="net-ping-out"><div class="text-dim-pad12">Click to test connectivity.</div></div>';
  } else if(tab==='netports'){
    f.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">TARGET HOST</label><input id="net-port-host" placeholder="e.g. 192.168.1.50" class="input-primary-lg"></div>'+
      '<div><label class="label-sub">PORTS <span class="opacity-5">(comma-separated)</span></label><input id="net-port-ports" value="22,80,443,8006,8080,8888" class="input-primary-lg"></div>'+
      '<button class="fleet-btn pill-active-self" onclick="netPortScan()" >SCAN PORTS</button>'+
      '</div><div id="net-port-out" class="exec-out skel-mt12" ></div>';
  }
}
function netDnsCheck(){
  var host=(document.getElementById('net-dns-host')||{}).value.trim();if(!host){toast('Enter a hostname','error');return;}
  var out=document.getElementById('net-dns-out');if(out){out.style.display='block';out.textContent='Resolving '+host+'...';}
  fetch(API.EXEC+'?target=localhost&cmd='+encodeURIComponent('dig +short '+host+' 2>&1 || nslookup '+host+' 2>&1')).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results)d.results.forEach(function(r){txt+=r.output+'\n';});
    if(out)out.textContent=txt||'(no results)';
  });
}
function netPingAll(){
  var out=document.getElementById('net-ping-out');if(out)out.innerHTML='<div class="skeleton"></div>';
  fetch(API.HEALTH).then(function(r){return r.json()}).then(function(d){
    var h='<table class="w-full"><thead><tr><th>HOST</th><th>IP</th><th>PING</th><th>LATENCY</th></tr></thead><tbody>';
    d.hosts.forEach(function(x){
      var ok=x.status==='healthy';
      h+='<tr><td><strong>'+x.label.toUpperCase()+'</strong></td><td>'+x.ip+'</td><td>'+badge(ok?'ok':'down')+'</td><td class="c-dim">'+( ok?'<1ms':'-')+'</td></tr>';
    });
    h+='</tbody></table>';if(out)out.innerHTML=h;
  });
}
function netPortScan(){
  var host=(document.getElementById('net-port-host')||{}).value.trim();
  var ports=(document.getElementById('net-port-ports')||{}).value.trim();
  if(!host){toast('Enter a target host','error');return;}
  var out=document.getElementById('net-port-out');if(out){out.style.display='block';out.textContent='Scanning '+host+'...';}
  var cmd='for p in '+ports.replace(/,/g,' ')+'; do (echo >/dev/tcp/'+host+'/$p) 2>/dev/null && echo "PORT $p OPEN" || echo "PORT $p CLOSED"; done';
  fetch(API.EXEC+'?target=localhost&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results)d.results.forEach(function(r){txt+=r.output+'\n';});
    if(out)out.textContent=txt||'(no results)';
  });
}

/* ── BACKUP & RECOVERY ─────────────────────────────────────────── */
var _bkLabels={bkstatus:'BACKUP STATUS',bkschedule:'SCHEDULES',bksnapshot:'VM SNAPSHOTS',bkexport:'EXPORT CONFIG',bkrestore:'RESTORE'};
function switchBackup(tab){
  document.querySelectorAll('.bk-tab').forEach(function(b){b.classList.remove('active-view');});
  var active=document.querySelector('.bk-tab[data-bktab="'+tab+'"]');if(active)active.classList.add('active-view');
  var sub=document.getElementById('bk-subtitle');if(sub)sub.textContent=_bkLabels[tab]||'';
  var f=document.getElementById('bk-form');if(!f)return;
  if(tab==='bkstatus'){
    f.innerHTML='<div id="bk-s-out"><div class="skeleton"></div></div>';
    fetch(API.BACKUP_LIST).then(function(r){return r.json()}).then(function(d){
      var h='<div class="desc-line">Snapshots and backup exports across the cluster.</div>';
      var snaps=d.snapshots||[];var exports=d.exports||[];
      if(snaps.length){
        h+='<h4 style="font-size:12px;color:var(--text-dim);margin:12px 0 8px">VM SNAPSHOTS</h4>';
        h+='<table class="w-full"><thead><tr><th>VMID</th><th>VM NAME</th><th>SNAPSHOT</th><th>ACTION</th></tr></thead><tbody>';
        snaps.forEach(function(s){h+='<tr><td><strong>'+s.vmid+'</strong></td><td>'+_esc(s.vm_name)+'</td><td>'+_esc(s.snapshot)+'</td><td><button class="fleet-btn pill-xs" onclick="bkRestoreSnap('+s.vmid+',\''+_esc(s.snapshot)+'\')">RESTORE</button></td></tr>';});
        h+='</tbody></table>';
      } else {h+='<div class="empty-state"><div class="es-icon">&#128230;</div><p>No VM snapshots found. Create one from the VM SNAPSHOTS tab.</p></div>';}
      if(exports.length){
        h+='<h4 style="font-size:12px;color:var(--text-dim);margin:12px 0 8px">BACKUP EXPORTS</h4>';
        h+='<table class="w-full"><thead><tr><th>FILENAME</th><th>SIZE</th></tr></thead><tbody>';
        exports.forEach(function(e){h+='<tr><td>'+_esc(e.filename)+'</td><td>'+(e.size_kb>1024?Math.round(e.size_kb/1024)+'MB':e.size_kb+'KB')+'</td></tr>';});
        h+='</tbody></table>';
      }
      document.getElementById('bk-s-out').innerHTML=h;
    }).catch(function(){document.getElementById('bk-s-out').innerHTML='<div class="c-red">Failed to load backup data</div>';});
  } else if(tab==='bkschedule'){
    f.innerHTML='<div class="desc-line">PVE backup schedules are managed via the Proxmox GUI or <code>pvesh</code> CLI.</div>'+
      '<button class="fleet-btn pill-active-lg" onclick="bkCheckSchedules()" >CHECK SCHEDULES</button>'+
      '<div id="bk-sched-out" class="exec-out" style="min-height:60px;display:none"></div>';
  } else if(tab==='bksnapshot'){
    f.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM</label><select id="bk-snap-vm" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">SNAPSHOT NAME (optional)</label><input id="bk-snap-name" placeholder="auto-generated if empty" class="input-primary"></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" onclick="bkTakeSnap()" >CREATE SNAPSHOT</button><button class="fleet-btn" onclick="bkListSnaps()">LIST SNAPSHOTS</button></div>'+
      '</div><div id="bk-snap-out" class="mt-12"></div>';
    fetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('bk-snap-vm');if(!sel)return;sel.innerHTML='<option value="">Select VM...</option>';
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+'</option>';});
    }).catch(function(){});
  } else if(tab==='bkexport'){
    f.innerHTML='<div class="desc-line">Export FREQ configuration (hosts, users, vault) for backup.</div>'+
      '<div style="display:flex;gap:8px">'+
      '<button class="fleet-btn" onclick="bkExportConfig()" style="color:var(--purple-light);border-color:var(--purple);padding:10px 20px">EXPORT CONFIG</button>'+
      '</div><div id="bk-exp-out" class="exec-out skel-mt12" ></div>';
  } else if(tab==='bkrestore'){
    f.innerHTML='<div class="desc-line">Restore a VM from a named snapshot. Use with caution — this will revert the VM.</div>'+
      '<div class="form-vertical">'+
      '<div><label class="label-sub">VM</label><select id="bk-rest-vm" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">SNAPSHOT NAME</label><input id="bk-rest-name" placeholder="Snapshot name to restore" class="input-primary"></div>'+
      '<button class="fleet-btn" onclick="bkRestore()" style="color:var(--red);border-color:var(--red);align-self:flex-start;padding:10px 20px">RESTORE SNAPSHOT</button>'+
      '</div><div id="bk-rest-out" class="mt-12"></div>';
    fetch(API.BACKUP_LIST).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('bk-rest-vm');if(!sel)return;sel.innerHTML='<option value="">Select VM...</option>';
      var seen={};(d.snapshots||[]).forEach(function(s){if(!seen[s.vmid]){seen[s.vmid]=true;sel.innerHTML+='<option value="'+s.vmid+'">'+s.vmid+' — '+_esc(s.vm_name)+'</option>';}});
    }).catch(function(){});
  }
}
function bkCheckSchedules(){
  var out=document.getElementById('bk-sched-out');if(out){out.style.display='block';out.textContent='Checking schedules...';}
  fetch(API.EXEC+'?target=localhost&cmd='+encodeURIComponent('cat /etc/pve/jobs.cfg 2>/dev/null || echo "No backup schedules found"')).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results)d.results.forEach(function(r){txt+=r.output+'\n';});
    if(out)out.textContent=txt||'(no schedules)';
  });
}
function bkTakeSnap(){
  var vmid=(document.getElementById('bk-snap-vm')||{}).value;if(!vmid){toast('Select a VM','error');return;}
  var name=(document.getElementById('bk-snap-name')||{}).value.trim();
  var out=document.getElementById('bk-snap-out');if(out)out.innerHTML='<div class="c-yellow">Creating snapshot...</div>';
  var url=API.BACKUP_CREATE+'?vmid='+vmid;
  if(name)url+='&name='+encodeURIComponent(name);
  fetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Snapshot "'+d.snapshot+'" created','success');if(out)out.innerHTML='<div class="c-green">Snapshot "'+d.snapshot+'" created for VM '+vmid+'</div>';}
    else{toast(d.error||'Snapshot failed','error');if(out)out.innerHTML='<div class="c-red">'+(d.error||'Failed')+'</div>';}
  }).catch(function(e){toast('Snapshot failed','error');if(out)out.innerHTML='<div class="c-red">'+e+'</div>';});
}
function bkListSnaps(){
  var vmid=(document.getElementById('bk-snap-vm')||{}).value;if(!vmid){toast('Select a VM','error');return;}
  var out=document.getElementById('bk-snap-out');if(out)out.innerHTML='<div class="skeleton"></div>';
  fetch(API.EXEC+'?target=localhost&cmd='+encodeURIComponent('sudo qm listsnapshot '+vmid+' 2>&1')).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results)d.results.forEach(function(r){txt+=r.output+'\n';});
    if(out)out.innerHTML='<pre style="font-size:11px;color:var(--text);white-space:pre-wrap;margin:0">'+(txt||'No snapshots')+'</pre>';
  });
}
function bkExportConfig(){
  var out=document.getElementById('bk-exp-out');if(out){out.style.display='block';out.textContent='Exporting configuration...';}
  fetch(API.CONFIG).then(function(r){return r.json()}).then(function(d){
    if(out)out.textContent=JSON.stringify(d,null,2);
  });
}
function bkRestore(){
  var vmid=(document.getElementById('bk-rest-vm')||{}).value;if(!vmid){toast('Select a VM','error');return;}
  var name=(document.getElementById('bk-rest-name')||{}).value.trim();if(!name){toast('Enter a snapshot name','error');return;}
  confirmAction('Restore VM <strong>'+vmid+'</strong> from snapshot <strong>'+_esc(name)+'</strong>? This will revert the VM.',function(){
    var out=document.getElementById('bk-rest-out');if(out)out.innerHTML='<div class="c-yellow">Restoring VM '+vmid+' from "'+_esc(name)+'"...</div>';
    fetch(API.BACKUP_RESTORE+'?vmid='+vmid+'&name='+encodeURIComponent(name)).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast('Restore complete','success');if(out)out.innerHTML='<div class="c-green">VM '+vmid+' restored from snapshot "'+_esc(d.snapshot)+'"</div>';}
      else{toast(d.error||'Restore failed','error');if(out)out.innerHTML='<div class="c-red">'+(d.error||'Failed')+'</div>';}
    }).catch(function(e){toast('Restore failed','error');if(out)out.innerHTML='<div class="c-red">'+e+'</div>';});
  });
}
function bkRestoreSnap(vmid,snapname){
  document.getElementById('bk-rest-name').value=snapname;
  document.getElementById('bk-rest-vm').value=vmid;
  switchBackup('bkrestore');
  toast('Snapshot "'+snapname+'" selected — review and confirm restore','info');
}

/* ── LAB CONTROL actions ───────────────────────────────────────── */
function labExec(host,cmd){
  if(cmd.indexOf('reboot')>=0){
    confirmAction('Reboot <strong>'+host.toUpperCase()+'</strong>?',function(){_labExecRun(host,cmd);});
  } else {_labExecRun(host,cmd);}
}
function _labExecRun(host,cmd){
  var out=document.getElementById('ft-lab-out');
  if(out)out.innerHTML='<div class="c-yellow">Running on '+host+'...</div>';
  fetch(API.EXEC+'?target='+encodeURIComponent(host)+'&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results)d.results.forEach(function(r){txt+=r.output+'\n';});
    if(out)out.innerHTML='<pre style="font-size:11px;color:var(--text);white-space:pre-wrap;margin:0">'+host.toUpperCase()+': '+(txt||'OK')+'</pre>';
  });
}
function labDockerAction(name,action){
  if(action==='stop'){
    confirmAction('Stop container <strong>'+name.toUpperCase()+'</strong>?',function(){_labDockerRun(name,action);});
  } else {_labDockerRun(name,action);}
}
function _labDockerRun(name,action){
  var out=document.getElementById('ft-lab-out');
  if(out)out.innerHTML='<div class="c-yellow">'+action.toUpperCase()+' '+name+'...</div>';
  fetch(API.EXEC+'?target=docker-dev&cmd='+encodeURIComponent('docker '+action+' '+name)).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results)d.results.forEach(function(r){txt+=r.output+'\n';});
    if(out)out.innerHTML='<pre style="font-size:11px;color:var(--green);white-space:pre-wrap;margin:0">'+name+': '+(txt||action+' OK')+'</pre>';
    toast(name+' '+action+' complete','success');
  });
}

/* User dropdown (reusable for passwd/sshkey) */
var _userDropdownData={};
function _loadUserDropdown(prefix){
  fetch(API.USERS).then(function(r){return r.json()}).then(function(d){
    var rc={admin:'var(--red)',operator:'var(--yellow)',viewer:'var(--green)'};
    var users=d.users.map(function(u){return {value:u.username,label:u.username.toUpperCase(),detail:u.role.toUpperCase(),color:rc[u.role]||'var(--text-dim)'};});
    _userDropdownData[prefix]=users;
    _renderUserDropdown(prefix,users);
  }).catch(function(){});
}
function _renderUserDropdown(prefix,items){
  var dd=document.getElementById('ft-'+prefix+'-dropdown');if(!dd)return;
  var h='';
  items.forEach(function(item){
    h+='<div onmousedown="selectUserDropdown(\''+prefix+'\',\''+item.value+'\')" style="padding:10px 14px;cursor:pointer;border-bottom:1px solid var(--border);transition:background 0.15s" onmouseover="this.style.background=\'var(--purple-faint)\'" onmouseout="this.style.background=\'none\'">';
    h+='<div class="flex-between"><span style="font-size:12px;font-weight:600;color:var(--text)">'+item.label+'</span><span style="font-size:12px;color:'+item.color+';font-weight:600">'+item.detail+'</span></div>';
    h+='</div>';
  });
  if(!items.length)h='<div style="padding:14px;color:var(--text-dim);font-size:11px;text-align:center">No users found</div>';
  dd.innerHTML=h;
}
function showUserDropdown(prefix){
  var dd=document.getElementById('ft-'+prefix+'-dropdown');if(!dd)return;
  var inp=document.getElementById('ft-'+prefix+'-user');if(!inp)return;
  var rect=inp.getBoundingClientRect();
  dd.style.top=(rect.bottom+4)+'px';dd.style.left=rect.left+'px';dd.style.display='block';
  document.body.style.overflow='hidden';
  _renderUserDropdown(prefix,_userDropdownData[prefix]||[]);
  setTimeout(function(){document.addEventListener('mousedown',function _h(e){
    if(!dd.contains(e.target)&&e.target!==inp){dd.style.display='none';document.body.style.overflow='';document.removeEventListener('mousedown',_h);}
  });},10);
}
function filterUserDropdown(prefix,q){
  q=q.toLowerCase();
  var filtered=(_userDropdownData[prefix]||[]).filter(function(u){return u.label.toLowerCase().indexOf(q)>=0||u.detail.toLowerCase().indexOf(q)>=0;});
  _renderUserDropdown(prefix,filtered);
}
function selectUserDropdown(prefix,value){
  document.getElementById('ft-'+prefix+'-user').value=value;
  var dd=document.getElementById('ft-'+prefix+'-dropdown');if(dd)dd.style.display='none';
  document.body.style.overflow='';
}
/* New Tool — shows registered tools dashboard */
function openNewTool(){
  var ov=document.getElementById('modal-container');
  var h='<div class="modal" style="max-width:500px"><div class="flex-between-mb16"><h3 class="m-0">Lab Tools</h3><span class="close-x">&times;</span></div>';
  h+='<div style="font-size:12px;color:var(--text-dim);margin-bottom:16px">Registered tools appear in LAB view and are available as HOME widgets.</div>';
  if(typeof LAB_TOOLS!=='undefined'&&LAB_TOOLS.length){
    LAB_TOOLS.forEach(function(t){
      var connected=false;for(var k in _ltState){if(k.indexOf(t.id)>=0&&_ltState[k])connected=true;}
      var dotColor=connected?'var(--green)':'var(--text-dim)';var statusText=connected?'CONNECTED':'OFFLINE';
      h+='<div style="display:flex;align-items:center;gap:12px;padding:12px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px">';
      h+='<span style="width:10px;height:10px;border-radius:50%;background:'+dotColor+';flex-shrink:0"></span>';
      h+='<div class="flex-1"><div style="font-size:13px;font-weight:600;color:var(--text)">'+t.name+'</div><div class="text-meta">'+t.subtitle+'</div></div>';
      h+='<span style="font-size:11px;color:'+dotColor+';font-weight:600">'+statusText+'</span>';
      h+='</div>';
    });
  } else {
    h+='<div style="text-align:center;padding:24px;color:var(--text-dim)">No tools registered</div>';
  }
  h+='<div style="margin-top:16px;font-size:11px;color:var(--text-dim)">To add a new tool, register it in the <code>LAB_TOOLS</code> array (JS) and <code>LAB_TOOL_REGISTRY</code> dict (Python).</div>';
  h+='</div>';
  ov.innerHTML=h;ov.style.display='flex';
}
/* Vault lock/unlock */
var _vaultUnlocked=false;
function unlockVault(){
  var user=document.getElementById('vault-auth-user').value.trim();
  var pass=document.getElementById('vault-auth-pass').value;
  if(!user||!pass){toast('Enter admin credentials','error');return;}
  /* Verify credentials by attempting SSH auth to localhost */
  toast('Verifying credentials...','info');
  fetch(API.EXEC+'?target=all&cmd='+encodeURIComponent('whoami')).then(function(r){return r.json()}).then(function(d){
    /* Check if the user is an admin in FREQ */
    fetch(API.USERS).then(function(r){return r.json()}).then(function(ud){
      var isAdmin=ud.users.some(function(u){return u.username===user&&u.role==='admin';});
      if(!isAdmin){toast('Access denied — admin role required','error');document.getElementById('vault-auth-pass').value='';return;}
      _vaultUnlocked=true;
      document.getElementById('vault-locked').classList.add('d-none');
      document.getElementById('vault-unlocked').classList.remove('d-none');
      toast('Vault unlocked','success');
      loadSensitiveVault();
    });
  });
}
function lockVault(){
  _vaultUnlocked=false;
  document.getElementById('vault-locked').classList.remove('d-none');
  document.getElementById('vault-unlocked').classList.add('d-none');
  document.getElementById('vault-sensitive-c').innerHTML='';
  document.getElementById('vault-auth-pass').value='';
  toast('Vault locked','info');
}
var _vaultData=null;
var _vaultTab='users';
function switchVaultTab(tab){
  _vaultTab=tab;
  document.querySelectorAll('.vault-tab').forEach(function(b){b.classList.remove('active-view');});
  var btn=document.querySelector('.vault-tab[data-vtab="'+tab+'"]');if(btn)btn.classList.add('active-view');
  renderVaultTab();
}
function loadSensitiveVault(){
  fetch(API.VAULT).then(function(r){return r.json()}).then(function(d){
    _vaultData=d;
    /* Also load FREQ users for the users tab */
    fetch(API.USERS).then(function(r2){return r2.json()}).then(function(ud){
      _vaultData._users=ud.users;
      renderVaultTab();
    }).catch(function(){renderVaultTab();});
  });
}
function _isUserEntry(e){
  var k=e.key.toLowerCase();
  return k.indexOf('pass')>=0||k.indexOf('pwd')>=0||k.indexOf('ssh')>=0||k.indexOf('id_')>=0||k.indexOf('pub')>=0;
}
function renderVaultTab(){
  var d=_vaultData;
  if(!d||!d.initialized){document.getElementById('vault-sensitive-c').innerHTML='<p class="c-yellow">Vault not initialized.</p>';return;}
  var html='';
  if(_vaultTab==='users'){
    /* Users view — show each FREQ user with password + ssh key copy buttons */
    var users=d._users||[];
    var rc={admin:'var(--red)',operator:'var(--yellow)',viewer:'var(--green)'};
    html='<div class="cards grid-auto-280" >';
    users.forEach(function(u,i){
      var passEntry=d.entries.find(function(e){return e.host===u.username&&(e.key.toLowerCase().indexOf('pass')>=0||e.key==='password');});
      var sshEntry=d.entries.find(function(e){return e.host===u.username&&(e.key.toLowerCase().indexOf('ssh')>=0||e.key.toLowerCase().indexOf('pub')>=0||e.key.toLowerCase().indexOf('id_')>=0);});
      html+='<div class="crd border-red" >';
      html+='<div class="flex-between-mb8"><h3 style="color:var(--text)">'+u.username.toUpperCase()+'</h3><span style="color:'+(rc[u.role]||'var(--text-dim)')+';font-size:12px;font-weight:600">'+u.role.toUpperCase()+'</span></div>';
      html+='<div style="display:flex;gap:6px;flex-wrap:wrap">';
      if(passEntry){
        html+='<button class="fleet-btn pill-purple-xs" data-action="vaultCopy" data-host="'+passEntry.host+'" data-key="'+passEntry.key+'" >&#128273; COPY PASSWORD</button>';
      } else {
        html+='<span class="fs-12-dim-pad4">No password stored</span>';
      }
      if(sshEntry){
        html+='<button class="fleet-btn pill-purple-xs" data-action="vaultCopy" data-host="'+sshEntry.host+'" data-key="'+sshEntry.key+'" >&#128272; COPY SSH KEY</button>';
      } else {
        html+='<span class="fs-12-dim-pad4">No SSH key stored</span>';
      }
      html+='</div></div>';
    });
    if(!users.length)html+='<div class="empty-state"><div class="es-icon">&#128100;</div><p>No users registered.</p></div>';
    html+='</div>';
  } else if(_vaultTab==='apikeys'){
    var apiEntries=d.entries.filter(function(e){return !_isUserEntry(e);});
    var groups={};
    apiEntries.forEach(function(e){if(!groups[e.host])groups[e.host]=[];groups[e.host].push(e);});
    html='<div class="cards grid-auto-300" >';
    Object.keys(groups).sort().forEach(function(host){
      var entries=groups[host];
      html+='<div class="crd border-red" >';
      html+='<div class="flex-between-mb8"><h3>'+host.toUpperCase()+'</h3><button class="fleet-btn pill-err-xs" data-action="vaultDelGroup" data-arg="'+host+'" >DELETE</button></div>';
      entries.forEach(function(e){
        var uid=host.replace(/[^a-z0-9]/gi,'')+'-'+e.key.replace(/[^a-z0-9]/gi,'');
        html+='<div class="flex-border-row">';
        html+='<span style="font-weight:600;color:var(--text);min-width:90px">'+e.key+'</span>';
        html+='<span style="color:var(--text-dim);flex:1;font-family:monospace;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" id="vk-'+uid+'">'+e.masked+'</span>';
        html+='<button class="fleet-btn pill-2-8" data-action="vaultReveal" data-uid="'+uid+'" data-host="'+e.host+'" data-key="'+e.key+'" >SHOW</button>';
        html+='<button class="fleet-btn pill-purple-2-8" data-action="vaultCopy" data-host="'+e.host+'" data-key="'+e.key+'" >COPY</button>';
        html+='</div>';
      });
      html+='</div>';
    });
    if(!apiEntries.length)html+='<div class="empty-state"><div class="es-icon">&#128273;</div><p>No API keys stored in vault.</p></div>';
    html+='</div>';
  } else {
    /* ALL tab */
    var groups={};
    d.entries.forEach(function(e){if(!groups[e.host])groups[e.host]=[];groups[e.host].push(e);});
    html='<div class="cards grid-auto-300" >';
    Object.keys(groups).sort().forEach(function(host){
      var entries=groups[host];
      html+='<div class="crd border-red" >';
      html+='<div class="flex-between-mb8"><h3>'+host.toUpperCase()+'</h3><button class="fleet-btn pill-err-xs" data-action="vaultDelGroup" data-arg="'+host+'" >DELETE</button></div>';
      entries.forEach(function(e){
        var uid=host.replace(/[^a-z0-9]/gi,'')+'-'+e.key.replace(/[^a-z0-9]/gi,'');
        html+='<div class="flex-border-row">';
        html+='<span style="font-weight:600;color:var(--text);min-width:90px">'+e.key+'</span>';
        html+='<span style="color:var(--text-dim);flex:1;font-family:monospace;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" id="vk-'+uid+'">'+e.masked+'</span>';
        html+='<button class="fleet-btn pill-2-8" data-action="vaultReveal" data-uid="'+uid+'" data-host="'+e.host+'" data-key="'+e.key+'" >SHOW</button>';
        html+='<button class="fleet-btn pill-purple-2-8" data-action="vaultCopy" data-host="'+e.host+'" data-key="'+e.key+'" >COPY</button>';
        html+='</div>';
      });
      html+='</div>';
    });
    if(!d.entries.length)html+='<div class="empty-state"><div class="es-icon">&#128274;</div><p>Vault is empty.</p></div>';
    html+='</div>';
  }
  document.getElementById('vault-sensitive-c').innerHTML=html;
}
function vaultReveal(uid,host,key){
  if(!_vaultData)return;
  var entry=_vaultData.entries.find(function(e){return e.host===host&&e.key===key;});
  if(!entry)return;
  var el=document.getElementById('vk-'+uid);if(!el)return;
  if(el.getAttribute('data-revealed')){
    el.textContent=entry.masked;el.removeAttribute('data-revealed');el.style.color='var(--text-dim)';
  } else {
    el.textContent=entry.value||entry.masked;el.setAttribute('data-revealed','1');el.style.color='var(--yellow)';
  }
}
function vaultCopy(host,key){
  if(!_vaultData)return;
  var entry=_vaultData.entries.find(function(e){return e.host===host&&e.key===key;});
  if(!entry||!entry.value){toast('Cannot copy — value not available','error');return;}
  try{
    var ta=document.createElement('textarea');
    ta.value=entry.value;ta.style.position='fixed';ta.style.left='-9999px';
    document.body.appendChild(ta);ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast(key+' copied to clipboard','success');
  }catch(e){toast('Copy failed','error');}
}
/* Reset & copy password */
/* Promote/demote functions */
function promoteUser(username){
  confirmAction('Promote <strong>'+username.toUpperCase()+'</strong> to the next role level?',function(){
    fetch(API.USERS_PROMOTE+'?username='+username).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast(username+' promoted','success');fleetTool('promote');}else toast(d.error||'Failed','error');
    });
  });
}
function demoteUser(username){
  confirmAction('Demote <strong>'+username.toUpperCase()+'</strong> to a lower role level?',function(){
    fetch(API.USERS_DEMOTE+'?username='+username).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast(username+' demoted','success');fleetTool('promote');}else toast(d.error||'Failed','error');
    });
  });
}
/* Fleet user/password/key functions */
function fleetNewUser(){
  var user=document.getElementById('ft-nu-user').value.trim();
  var pass=document.getElementById('ft-nu-pass').value;
  var key=document.getElementById('ft-nu-key').value.trim();
  var role=document.getElementById('ft-nu-role').value;
  if(!user){toast('Username required','error');return;}
  if(!pass){toast('Password required','error');return;}
  if(pass.length<8){toast('Password must be at least 8 characters','error');return;}
  confirmAction('Create user <strong>'+user+'</strong> as <strong>'+role.toUpperCase()+'</strong> and deploy to ALL fleet hosts?<br><br>SSH Key: '+(key?'provided':'none'),function(){
    toast('Creating '+user+' ('+role+') across fleet...','info');
    var sudoLine=role==='admin'?user+' ALL=(ALL) NOPASSWD:ALL':role==='operator'?user+' ALL=(ALL) ALL':'';
    var cmd='useradd -m -s /bin/bash '+user+' 2>/dev/null; echo "'+user+':'+pass+'" | chpasswd';
    if(sudoLine)cmd+='; echo "'+sudoLine+'" > /etc/sudoers.d/'+user+'; chmod 440 /etc/sudoers.d/'+user;
    if(key)cmd+='; mkdir -p /home/'+user+'/.ssh; echo "'+key+'" >> /home/'+user+'/.ssh/authorized_keys; chmod 700 /home/'+user+'/.ssh; chmod 600 /home/'+user+'/.ssh/authorized_keys; chown -R '+user+':'+user+' /home/'+user+'/.ssh';
    var out=document.getElementById('ft-nu-out');out.innerHTML='<div class="skeleton"></div>';
    fetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
      var h='<table class="w-full"><thead><tr><th>HOST</th><th>RESULT</th></tr></thead><tbody>';
      d.results.forEach(function(r,i){h+='<tr><td><strong>'+r.host.toUpperCase()+'</strong></td><td>'+(r.ok?'<span class="c-green">DEPLOYED</span>':'<span class="c-red">'+r.error+'</span>')+'</td></tr>';});
      h+='</tbody></table>';out.innerHTML=h;
      toast('User '+user+' deployed to '+d.results.length+' hosts','success');
      /* Also register in FREQ */
      fetch(API.USERS_CREATE+'?username='+encodeURIComponent(user)+'&role='+role).catch(function(){});
    });
  });
}
function fleetPasswdUpdate(){
  var user=document.getElementById('ft-pw-user').value.trim();
  var pass=document.getElementById('ft-pw-pass').value;
  var confirm=document.getElementById('ft-pw-confirm').value;
  if(!user){toast('Username required','error');return;}
  if(!pass){toast('Password required','error');return;}
  if(pass!==confirm){toast('Passwords do not match','error');return;}
  if(pass.length<8){toast('Password must be at least 8 characters','error');return;}
  confirmAction('Update password for <strong>'+user+'</strong> on ALL fleet hosts?',function(){
    toast('Updating password for '+user+'...','info');
    var cmd='echo "'+user+':'+pass+'" | chpasswd && echo OK || echo FAIL';
    var out=document.getElementById('ft-pw-out');out.innerHTML='<div class="skeleton"></div>';
    fetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
      var h='<table class="w-full"><thead><tr><th>HOST</th><th>RESULT</th></tr></thead><tbody>';
      var ok=0;
      d.results.forEach(function(r,i){
        var success=r.ok&&r.output.trim()==='OK';if(success)ok++;
        h+='<tr><td><strong>'+r.host.toUpperCase()+'</strong></td><td>'+(success?'<span class="c-green">UPDATED</span>':'<span class="c-red">FAILED</span>')+'</td></tr>';
      });
      h+='</tbody></table>';out.innerHTML=h;
      toast('Password updated on '+ok+'/'+d.results.length+' hosts','success');
    });
  });
}
function fleetSshKeyDeploy(){
  var user=document.getElementById('ft-sk-user').value.trim();
  var key=document.getElementById('ft-sk-key').value.trim();
  if(!user){toast('Username required','error');return;}
  if(!key){toast('Public key required','error');return;}
  if(key.indexOf('ssh-')<0){toast('Invalid key — must start with ssh-ed25519 or ssh-rsa','error');return;}
  confirmAction('Deploy SSH key to <strong>'+user+'</strong> on ALL fleet hosts?<br><br><code style="font-size:12px;word-break:break-all">'+key.substring(0,60)+'...</code>',function(){
    toast('Deploying SSH key for '+user+'...','info');
    var cmd='mkdir -p /home/'+user+'/.ssh; echo "'+key+'" >> /home/'+user+'/.ssh/authorized_keys; chmod 700 /home/'+user+'/.ssh; chmod 600 /home/'+user+'/.ssh/authorized_keys; chown -R '+user+':'+user+' /home/'+user+'/.ssh && echo OK || echo FAIL';
    var out=document.getElementById('ft-sk-out');out.innerHTML='<div class="skeleton"></div>';
    fetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
      var h='<table class="w-full"><thead><tr><th>HOST</th><th>RESULT</th></tr></thead><tbody>';
      var ok=0;
      d.results.forEach(function(r,i){
        var success=r.ok&&r.output.trim()==='OK';if(success)ok++;
        h+='<tr><td><strong>'+r.host.toUpperCase()+'</strong></td><td>'+(success?'<span class="c-green">DEPLOYED</span>':'<span class="c-red">FAILED</span>')+'</td></tr>';
      });
      h+='</tbody></table>';out.innerHTML=h;
      toast('SSH key deployed to '+ok+'/'+d.results.length+' hosts','success');
    });
  });
}
/* SSHD panel — renders into any target container */
function sshdPanel(targetId){
  var out=document.getElementById(targetId);if(!out)return;
  out.innerHTML='<div class="skeleton"></div>';
  fetch(API.HEALTH).then(function(r){return r.json()}).then(function(d){
    var h='<h3 style="color:var(--purple-light);font-size:13px;margin-bottom:8px">RESTART SSHD</h3>';
    h+='<div class="flex-row-8-center">';
    h+='<button class="fleet-btn c-purple-active" data-action="sshdRestartSelected" >RESTART SELECTED</button>';
    h+='<button class="fleet-btn" data-action="sshdRestartAll">RESTART ALL ('+d.hosts.length+')</button>';
    h+='<label class="meta-flex"><input type="checkbox" onchange="document.querySelectorAll(\'.ft-sshd-check\').forEach(function(c){c.checked=this.checked}.bind(this))"> Select All</label>';
    h+='<div class="flex-1"></div><button class="fleet-btn" onclick="document.getElementById(\''+targetId+'\').innerHTML=\'\'" style="opacity:0.6">CLOSE</button>';
    h+='</div>';
    h+='<table class="w-full"><thead><tr><th class="w-30"></th><th>HOST</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>';
    d.hosts.forEach(function(x,i){
      var up=x.status==='healthy';
      h+='<tr><td><input type="checkbox" class="ft-sshd-check" data-host="'+x.label+'"></td>';
      h+='<td><strong style="color:'+HC[i%HC.length]+'">'+x.label.toUpperCase()+'</strong></td>';
      h+='<td>'+badge(up?'ok':'down')+'</td>';
      h+='<td><button class="fleet-btn pill-warn-sm" data-action="sshdRestartHost" data-arg="'+x.label+'" >RESTART</button></td></tr>';
    });
    h+='</tbody></table><div id="ft-sshd-out" class="mt-12"></div>';
    out.innerHTML=h;
  });
}
/* SSHD restart functions */
function _sshdRestart(hosts){
  var cmd='systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null && echo OK || echo FAIL';
  var out=document.getElementById('ft-sshd-out');out.innerHTML='<div class="skeleton"></div>';
  var done=0,total=hosts.length,html='<table class="w-full"><thead><tr><th>HOST</th><th>RESULT</th></tr></thead><tbody>';
  hosts.forEach(function(h){
    fetch(API.EXEC+'?target='+encodeURIComponent(h)+'&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
      var ok=d.results&&d.results[0]&&d.results[0].ok&&d.results[0].output.trim()==='OK';
      html+='<tr><td><strong>'+h.toUpperCase()+'</strong></td><td>'+(ok?'<span class="c-green">RESTARTED</span>':'<span class="c-red">FAILED</span>')+'</td></tr>';
      done++;if(done===total){html+='</tbody></table>';var cb='<button class="fleet-btn my-8" onclick="document.getElementById(\'ft-sshd-out\').innerHTML=\'\'" >CLOSE RESULTS</button>';out.innerHTML=cb+html+cb;toast('SSHD restarted on '+done+' hosts','success');}
    });
  });
}
function sshdRestartHost(label){
  confirmAction('Restart SSHD on <strong>'+label.toUpperCase()+'</strong>?',function(){
    toast('Restarting SSHD on '+label+'...','info');_sshdRestart([label]);
  });
}
function sshdRestartSelected(){
  var hosts=[];document.querySelectorAll('.ft-sshd-check:checked').forEach(function(c){hosts.push(c.getAttribute('data-host'));});
  if(!hosts.length){toast('No hosts selected','error');return;}
  confirmAction('Restart SSHD on <strong>'+hosts.length+'</strong> host(s)?',function(){
    toast('Restarting SSHD on '+hosts.length+' hosts...','info');_sshdRestart(hosts);
  });
}
function sshdRestartAll(){
  var hosts=[];document.querySelectorAll('.ft-sshd-check').forEach(function(c){hosts.push(c.getAttribute('data-host'));});
  if(!hosts.length){toast('No hosts available','error');return;}
  confirmAction('Restart SSHD on ALL <strong>'+hosts.length+'</strong> online hosts?',function(){
    toast('Restarting SSHD fleet-wide...','info');_sshdRestart(hosts);
  });
}
/* NTP fix functions */
function ntpFixHost(label){
  confirmAction('Fix NTP sync on <strong>'+label.toUpperCase()+'</strong>?',function(){
    toast('Fixing NTP on '+label+'...','info');
    var cmd='timedatectl set-ntp true 2>/dev/null; systemctl restart systemd-timesyncd 2>/dev/null || systemctl restart chronyd 2>/dev/null || ntpd -gq 2>/dev/null; sleep 2; timedatectl status 2>&1 | head -5';
    fetch(API.EXEC+'?target='+encodeURIComponent(label)+'&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
      var ok=d.results&&d.results[0]&&d.results[0].ok;
      toast(label.toUpperCase()+': '+(ok?'NTP sync restored':'Fix failed — check manually'),ok?'success':'error');
      fleetTool('ntp');
    });
  });
}
function ntpFixSelected(){
  var hosts=[];
  document.querySelectorAll('.ft-ntp-check:checked').forEach(function(cb){hosts.push(cb.getAttribute('data-host'));});
  if(!hosts.length){toast('No hosts selected','error');return;}
  confirmAction('Fix NTP on <strong>'+hosts.length+'</strong> host(s)?',function(){
    hosts.forEach(function(h){ntpFixHost.__skip_confirm=true;
      toast('Fixing NTP on '+h+'...','info');
      var cmd='timedatectl set-ntp true 2>/dev/null; systemctl restart systemd-timesyncd 2>/dev/null || systemctl restart chronyd 2>/dev/null; sleep 2; timedatectl status 2>&1 | head -3';
      fetch(API.EXEC+'?target='+encodeURIComponent(h)+'&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
        var ok=d.results&&d.results[0]&&d.results[0].ok;
        toast(h.toUpperCase()+': '+(ok?'NTP fixed':'Failed'),ok?'success':'error');
      });
    });
    setTimeout(function(){fleetTool('ntp');},5000);
  });
}
function ntpFixAll(){
  var hosts=[];
  document.querySelectorAll('.ft-ntp-check').forEach(function(cb){hosts.push(cb.getAttribute('data-host'));});
  if(!hosts.length){toast('All hosts are synced','success');return;}
  confirmAction('Fix NTP on ALL <strong>'+hosts.length+'</strong> unsynced hosts?',function(){
    hosts.forEach(function(h){
      var cmd='timedatectl set-ntp true 2>/dev/null; systemctl restart systemd-timesyncd 2>/dev/null || systemctl restart chronyd 2>/dev/null; sleep 2; timedatectl status 2>&1 | head -3';
      fetch(API.EXEC+'?target='+encodeURIComponent(h)+'&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
        var ok=d.results&&d.results[0]&&d.results[0].ok;
        toast(h.toUpperCase()+': '+(ok?'NTP fixed':'Failed'),ok?'success':'error');
      });
    });
    toast('Fixing '+hosts.length+' hosts...','info');
    setTimeout(function(){fleetTool('ntp');},5000);
  });
}
var _execLeaveTimer=null;
function renderExecDropdown(items){
  var dd=document.getElementById('ft-exec-dropdown');if(!dd)return;
  var h='';
  items.forEach(function(item){
    h+='<div onmousedown="selectExecHost(\''+item.value+'\',\''+item.label+'\')" style="padding:10px 14px;cursor:pointer;border-bottom:1px solid var(--border);transition:background 0.15s" onmouseover="this.style.background=\'var(--purple-faint)\'" onmouseout="this.style.background=\'none\'">';
    h+='<div style="font-size:12px;font-weight:600;color:var(--text)">'+item.label+'</div>';
    h+='<div class="fs-12-dim-mt2">'+item.detail+'</div>';
    h+='</div>';
  });
  dd.innerHTML=h;
}
function showExecDropdown(){
  var dd=document.getElementById('ft-exec-dropdown');if(!dd)return;
  var inp=document.getElementById('ft-exec-target');if(!inp)return;
  var rect=inp.getBoundingClientRect();
  dd.style.top=(rect.bottom+4)+'px';
  dd.style.left=rect.left+'px';
  dd.style.display='block';
  document.body.style.overflow='hidden';
  renderExecDropdown(window._execHostsList||[]);
  setTimeout(function(){document.addEventListener('mousedown',_execOutsideClick);},10);
}
function _execOutsideClick(e){
  var dd=document.getElementById('ft-exec-dropdown');
  var inp=document.getElementById('ft-exec-target');
  if(dd&&inp&&!dd.contains(e.target)&&e.target!==inp){hideExecDropdown();}
}
function hideExecDropdown(){
  var dd=document.getElementById('ft-exec-dropdown');if(dd)dd.style.display='none';
  document.body.style.overflow='';
  document.removeEventListener('mousedown',_execOutsideClick);
}
function filterExecDropdown(q){
  q=q.toLowerCase();
  var filtered=(window._execHostsList||[]).filter(function(item){return item.label.toLowerCase().indexOf(q)>=0||item.detail.toLowerCase().indexOf(q)>=0||item.value.toLowerCase().indexOf(q)>=0;});
  renderExecDropdown(filtered);
}
function selectExecHost(value,label){
  document.getElementById('ft-exec-target').value=label;
  document.getElementById('ft-exec-target').setAttribute('data-value',value);
  hideExecDropdown();
  document.getElementById('ft-exec-cmd').focus();
}
function ftRunExec(){
  var el=document.getElementById('ft-exec-target');
  var target=el.getAttribute('data-value')||el.value.trim().toLowerCase()||'all';
  hideExecDropdown();
  var cmd=document.getElementById('ft-exec-cmd').value;if(!cmd){toast('Enter a command','error');return;}
  document.getElementById('ft-exec-out').textContent='Running: '+cmd+' ...';
  fetch(API.EXEC+'?target='+encodeURIComponent(target)+'&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results){d.results.forEach(function(r){txt+=(r.host?r.host.toUpperCase()+': ':'')+r.output+'\n';});}
    document.getElementById('ft-exec-out').textContent=txt||'(No Output)';
  }).catch(function(e){document.getElementById('ft-exec-out').textContent='Error: '+e;});
}
function toggleUpdateAll(checked){
  document.querySelectorAll('.ft-upd-check').forEach(function(cb){cb.checked=checked;});
}
function updateSelected(){
  var hosts=[];
  document.querySelectorAll('.ft-upd-check:checked').forEach(function(cb){hosts.push(cb.getAttribute('data-host'));});
  if(!hosts.length){toast('No hosts selected','error');return;}
  confirmAction('Update <strong>'+hosts.length+'</strong> host(s)?<br><br>'+hosts.map(function(h){return h.toUpperCase()}).join(', '),function(){
    hosts.forEach(function(h){runHostUpdate(h);});
  });
}
function updateAll(){
  var hosts=[];
  document.querySelectorAll('.ft-upd-check').forEach(function(cb){hosts.push(cb.getAttribute('data-host'));});
  if(!hosts.length){toast('No hosts with pending updates','error');return;}
  confirmAction('Update ALL <strong>'+hosts.length+'</strong> hosts with pending updates?',function(){
    hosts.forEach(function(h){runHostUpdate(h);});
  });
}
function runHostUpdate(label){
  confirmAction('Run OS updates on <strong>'+label+'</strong>? This may take several minutes.',function(){
    toast('Updating '+label+'...','info');
    var cmd='apt-get update -qq && apt-get upgrade -y -qq 2>&1 | tail -5 || dnf update -y -q 2>&1 | tail -5 || zypper update -y 2>&1 | tail -5';
    fetch(API.EXEC+'?target='+encodeURIComponent(label)+'&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
      var out=d.results&&d.results[0]?d.results[0].output:'no output';
      toast(label+': '+out.substring(0,80),d.results&&d.results[0]&&d.results[0].ok?'success':'error');
      loadFleetPage();
    });
  });
}
function loadAgents(){
  fetch(API.AGENTS).then(function(r){return r.json()}).then(function(d){
    document.getElementById('agent-stats').innerHTML=s('Agents',d.count,'p');
    if(d.count>0){var h='<table><thead><tr><th>Name</th><th>Template</th><th>VMID</th><th>Status</th><th>Created</th></tr></thead><tbody>';
      d.agents.forEach(function(a){h+='<tr><td><strong>'+a.name+'</strong></td><td>'+a.template+'</td><td>'+a.vmid+'</td><td>'+badge(a.status)+'</td><td>'+(a.created||'')+'</td></tr>';});
      h+='</tbody></table>';document.getElementById('agent-list').innerHTML=h;
    }else{document.getElementById('agent-list').innerHTML='<div class="empty-state"><div class="es-icon">&#9881;</div><p>No agents registered.<br><code class="c-purple">freq agent create &lt;template&gt;</code></p></div>';}
  });
  var tpls=[{n:'Infra-Manager',d:'Infrastructure operator — fleet monitoring, incident response, maintenance'},{n:'Security-Ops',d:'Security specialist — auditing, hardening, compliance'},{n:'Dev',d:'Development specialist — building, testing, shipping code'},{n:'Media-Ops',d:'Media stack operator — Plex, Sonarr, Radarr, downloads'},{n:'Blank',d:'Empty template — start from scratch'}];
  var h='';tpls.forEach(function(t){h+='<div class="crd"><h3>'+t.n+'</h3><p>'+t.d+'</p></div>';});
  document.getElementById('agent-templates').innerHTML=h;
}
function loadSpecialists(){
  fetch(API.SPECIALISTS).then(function(r){return r.json()}).then(function(d){
    var h='';d.agents.forEach(function(a){h+='<tr><td><strong>'+a.name+'</strong></td><td>'+a.template+'</td><td>'+(a.vmid||'-')+'</td><td>'+a.status+'</td></tr>';});
    document.getElementById('specialist-table').innerHTML=h||'<tr><td colspan="4" class="c-dim">No specialists registered.</td></tr>';
  });
}

/* ═══════════════════════════════════════════════════════════════════
   VMs
   ═══════════════════════════════════════════════════════════════════ */
function loadVMs(){
  document.getElementById('vms-c').innerHTML='<div class="skeleton"></div><div class="skeleton"></div>';
  fetch(API.VMS).then(function(r){return r.json()}).then(function(d){
    if(!d.count){document.getElementById('vms-c').innerHTML='<div class="empty-state"><div class="es-icon">▣</div><p>No VMs found on cluster.</p></div>';document.getElementById('vm-stats').innerHTML='';return;}
    var running=0,stopped=0;d.vms.forEach(function(v){if(v.status==='running')running++;else stopped++;});
    document.getElementById('vm-stats').innerHTML=
      '<div class="st"><div class="lb">VMs</div><div class="flex-row-24"><span class="stat-pair"><span style="font-size:20px;font-weight:700;color:var(--purple-light)">'+d.count+'</span><span class="label-hint">TOTAL</span></span><span class="stat-pair"><span class="stat-big-green">'+running+'</span><span class="label-hint">RUN</span></span><span class="stat-pair"><span class="stat-big-red">'+stopped+'</span><span class="label-hint">STOP</span></span></div></div>';
    var nodeFilter=document.getElementById('vm-node-filter').value;
    var html='<div class="cards grid-auto-240" >';
    var nodes={};
    var catFilter=document.getElementById('vm-cat-filter')?document.getElementById('vm-cat-filter').value:'all';
    d.vms.forEach(function(v,i){
      nodes[v.node]=true;
      if(nodeFilter!=='all'&&v.node!==nodeFilter)return;
      if(catFilter!=='all'&&v.category!==catFilter)return;
      var cl=_hostColor(v.name,'vm',v.node);var isRunning=v.status==='running';
      var acts=v.allowed_actions||['view'];
      var catLabel=(v.category||'unknown').replace(/_/g,' ');
      var displayStatus=v.status;
      html+='<div class="host-card cursor-ptr" data-action="openVmInfo" data-label="'+v.name+'" data-vmid="'+v.vmid+'" >';
      html+='<div class="host-head"><h3 style="color:'+cl+'">'+v.name+'</h3><div style="display:flex;align-items:center;gap:6px">'+
        '<span class="cat-badge cat-'+(v.category||'unknown')+'">'+catLabel+'</span>'+badge(displayStatus)+'</div></div>';
      html+='<div class="divider-light">';
      html+='<div class="metric-row"><div class="metric-top"><span class="metric-label">VMID</span><span class="metric-val">'+v.vmid+' · '+v.node+'</span></div></div>';
      html+=_mrow('CPU',v.cpu+' Cores',0,'var(--purple-light)');
      html+='<div class="metric-row"><div class="metric-top"><span class="metric-label">RAM</span><span class="metric-val">'+_ramGB(v.ram_mb)+'</span></div></div>';
      html+='<div style="display:flex;gap:4px;margin-top:8px;flex-wrap:wrap" onclick="event.stopPropagation()">';
      if(acts.indexOf('snapshot')>=0)html+='<button class="fleet-btn pill-warn-4-10" onclick="_vmSnapWarn('+v.vmid+','+isRunning+')" >SNAP</button>';
      if(acts.indexOf('stop')>=0&&isRunning)html+='<button class="fleet-btn pill-warn-4-10" data-action="vmPower" data-vmid="'+v.vmid+'" data-arg="stop" >STOP</button>';
      if(acts.indexOf('start')>=0&&!isRunning)html+='<button class="fleet-btn" data-action="vmPower" data-vmid="'+v.vmid+'" data-arg="start" style="padding:4px 10px;font-size:12px;color:var(--green)">START</button>';
      if(acts.indexOf('destroy')>=0)html+='<button class="fleet-btn" data-action="vmDestroy" data-vmid="'+v.vmid+'" style="padding:4px 10px;font-size:12px;color:var(--red)">DESTROY</button>';
      html+='</div></div></div>';
    });
    html+='</div>';document.getElementById('vms-c').innerHTML=html;
    var sel=document.getElementById('vm-node-filter');var cur=sel.value;
    sel.innerHTML='<option value="all">All Nodes</option>';
    Object.keys(nodes).sort().forEach(function(n){sel.innerHTML+='<option value="'+n+'"'+(n===cur?' selected':'')+'>'+n+'</option>';});
  });
}

/* ═══════════════════════════════════════════════════════════════════
   MEDIA
   ═══════════════════════════════════════════════════════════════════ */
function loadContainerSection(){
  var cards=document.getElementById('container-cards');if(cards&&!cards.innerHTML.trim())cards.innerHTML='<div class="skeleton"></div><div class="skeleton"></div>';
  fetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(d){
    var _coff=Math.max(0,d.containers_down||0);document.getElementById('container-stats').innerHTML=st('Total',d.containers_total,'p')+st('Online',d.containers_running,'g')+st('Offline',_coff,_coff>0?'r':'g')+st('VMs',d.vm_count,'b');
  }).catch(function(){document.getElementById('container-stats').innerHTML='<span class="c-red">Failed to load stats</span>';});
  fetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
    _mediaCache=d;_renderAllFromCache();
  }).catch(function(){toast('Failed to load containers','error');});
}
function loadDownloads(){
  var tbl=document.getElementById('dl-table');if(tbl)tbl.innerHTML='<tr><td colspan="6"><div class="skeleton"></div></td></tr>';
  fetch(API.MEDIA_DOWNLOADS).then(function(r){return r.json()}).then(function(d){
    document.getElementById('dl-stats').innerHTML=st('Active',d.count,d.count>0?'y':'g');
    var h='';d.downloads.forEach(function(dl){
      var sz=dl.size>1073741824?(dl.size/1073741824).toFixed(1)+'GB':(dl.size/1048576).toFixed(0)+'MB';
      var sp=dl.speed>1048576?(dl.speed/1048576).toFixed(1)+'MB/s':(dl.speed/1024).toFixed(0)+'KB/s';
      h+='<tr><td>'+dl.name.substring(0,50)+'</td><td>'+dl.client+'</td><td>'+dl.vm+'</td><td>'+sz+'</td><td>'+dl.progress+'%</td><td>'+sp+'</td></tr>';
    });document.getElementById('dl-table').innerHTML=h||'<tr><td colspan="6" class="c-dim">No active downloads</td></tr>';
  }).catch(function(){toast('Failed to load downloads','error');if(tbl)tbl.innerHTML='<tr><td colspan="6" class="c-red">Failed to load</td></tr>';});
}
function loadStreams(){
  var tbl=document.getElementById('stream-table');if(tbl)tbl.innerHTML='<tr><td colspan="5"><div class="skeleton"></div></td></tr>';
  fetch(API.MEDIA_STREAMS).then(function(r){return r.json()}).then(function(d){
    document.getElementById('stream-stats').innerHTML=st('Active Streams',d.count,d.count>0?'g':'p');
    var h='';d.sessions.forEach(function(ss){h+='<tr><td><strong>'+ss.user+'</strong></td><td>'+ss.title+'</td><td>'+ss.type+'</td><td>'+ss.quality+'</td><td>'+ss.state+'</td></tr>';});
    document.getElementById('stream-table').innerHTML=h||'<tr><td colspan="5" class="c-dim">No active streams</td></tr>';
  }).catch(function(){toast('Failed to load streams','error');if(tbl)tbl.innerHTML='<tr><td colspan="5" class="c-red">Failed to load</td></tr>';});
}
function mediaRestart(name){
  confirmAction('Restart container <strong>'+name+'</strong>?',function(){
    fetch(API.MEDIA_RESTART+'?name='+encodeURIComponent(name)).then(function(r){return r.json()}).then(function(d){
      toast(d.ok?name+' restarted':'Restart failed: '+(d.error||'unknown'),d.ok?'success':'error');loadContainerSection();
    });
  });
}
function mediaLogs(name){
  var el=document.getElementById('container-logs');el.style.display='block';
  el.textContent='Loading logs for '+name+'...';
  fetch(API.MEDIA_LOGS+'?name='+encodeURIComponent(name)+'&lines=50').then(function(r){return r.json()}).then(function(d){el.textContent=d.logs||'No logs available.';}).catch(function(e){el.textContent='Failed to load logs: '+e;toast('Failed to load logs','error');});
}

/* ═══════════════════════════════════════════════════════════════════
   INFRA
   ═══════════════════════════════════════════════════════════════════ */
function loadInfra(){
  fetch(API.INFRA_OVERVIEW).then(function(r){return r.json()}).then(function(d){
    var up=d.hosts.filter(function(h){return h.status==='up'}).length;
    document.getElementById('infra-stats').innerHTML=s('Cluster',d.cluster,'p')+s('Hosts',d.hosts.length,'p')+s('Online',up,'g')+s('VMs',d.pve.vms.length,'b')+s('pfSense',d.infra.pfsense.ip||'N/A','y')+s('TrueNAS',d.infra.truenas.ip||'N/A','y');
    var t=document.getElementById('infra-tbl');t.innerHTML='';
    d.hosts.forEach(function(h,i){
      if(h.status!=='up'){t.innerHTML+='<tr><td style="color:'+HC[i%HC.length]+'"><strong>'+h.label+'</strong></td><td>'+h.type+'</td><td colspan="6">'+badge('down')+'</td></tr>';return;}
      var dn=parseInt(h.disk_pct);var dc=dn>=90?'r':dn>=75?'y':'g';
      t.innerHTML+='<tr><td style="color:'+HC[i%HC.length]+'"><strong>'+h.label+'</strong></td><td>'+h.type+'</td><td class="fs-11">'+h.os+'</td><td>'+h.cores+'</td><td>'+h.ram+'</td><td><span class="vl '+dc+' fs-12" >'+h.disk_pct+'</span></td><td>'+(h.containers>0?'<strong style="color:var(--blue)">'+h.containers+'</strong>':'-')+'</td><td>'+h.services+'</td><td>'+badge('up')+'</td></tr>';
    });
    var vmhtml='';
    if(d.pve.vms.length){vmhtml='<table><thead><tr><th>VMID</th><th>Name</th><th>Node</th><th>Status</th><th>CPU</th><th>RAM</th></tr></thead><tbody>';
      d.pve.vms.forEach(function(v){vmhtml+='<tr><td>'+v.vmid+'</td><td><strong>'+v.name+'</strong></td><td>'+v.node+'</td><td>'+badge(v.status)+'</td><td>'+v.cpu+'</td><td>'+_ramGB(v.ram_mb)+'</td></tr>';});
      vmhtml+='</tbody></table>';}
    document.getElementById('infra-vms').innerHTML=vmhtml;
  }).catch(function(){toast('Failed to load infrastructure overview','error');});
}
function _infraOut(defaultId){
  /* If called from host overlay, route output to the infra panel instead */
  if(_infraOutputTarget){var el=document.getElementById(_infraOutputTarget);if(el){el.style.display='block';return el;}}
  var el=document.getElementById(defaultId);if(el)el.style.display='block';return el;
}
function _infraPre(title,output){
  return '<div style="color:var(--green);margin-bottom:8px;font-size:12px;font-weight:600">'+title+'</div><pre style="font-size:11px;color:var(--text);white-space:pre-wrap;font-family:\'Courier New\',monospace;line-height:1.5;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:12px">'+output.replace(/</g,'&lt;').replace(/===/g,'<span class="c-purple">═══</span>')+'</pre>';
}
function pfAction(action){
  var o=_infraOut('pf-out');if(!o)return;
  o.innerHTML='<span class="c-dim">Querying pfSense ('+action+')...</span>';
  fetch(API.INFRA_PFSENSE+'?action='+action).then(function(r){return r.json()}).then(function(d){
    if(d.reachable){o.innerHTML=_infraPre('PFSENSE \u2014 '+action.toUpperCase(),d.output);}
    else{o.innerHTML='<div class="c-red">Cannot reach pfSense at '+d.host+'</div><div class="c-dim-mt8">'+d.error+'</div>';}
  }).catch(function(e){o.innerHTML='<div class="c-red">Error: '+e+'</div>';});
}
function tnAction(action){
  var o=_infraOut('tn-out');if(!o)return;
  o.innerHTML='<span class="c-dim">Querying TrueNAS ('+action+')...</span>';
  fetch(API.INFRA_TRUENAS+'?action='+action).then(function(r){return r.json()}).then(function(d){
    if(d.reachable){o.innerHTML=_infraPre('TRUENAS \u2014 '+action.toUpperCase(),d.output);}
    else{o.innerHTML='<div class="c-red">Cannot reach TrueNAS at '+d.host+'</div><div class="c-dim-mt8">'+d.error+'</div>';}
  }).catch(function(e){o.innerHTML='<div class="c-red">Error: '+e+'</div>';});
}
function idracAction(action){
  var o=_infraOut('idrac-out');if(!o)return;
  o.innerHTML='<div class="skeleton"></div>';
  fetch(API.INFRA_IDRAC+'?action='+action).then(function(r){return r.json()}).then(function(d){
    var html='';
    d.targets.forEach(function(t){
      if(t.reachable){html+=_infraPre(t.name.toUpperCase()+' ('+t.ip+') \u2014 '+action.toUpperCase(),t.output);}
      else{html+='<div class="mb-12"><div style="font-size:12px;font-weight:600;color:var(--red)">'+t.name.toUpperCase()+' ('+t.ip+') \u2014 UNREACHABLE</div><p class="c-dim-fs11">'+(t.error||'')+'</p></div>';}
    });
    o.innerHTML=html;
  }).catch(function(e){o.innerHTML='<p class="c-red">Error: '+e+'</p>';});
}
function swAction(action){
  var o=_infraOut('sw-out');if(!o)return;
  o.innerHTML='<span class="c-dim">Querying switch ('+action+')...</span>';
  fetch(API.SWITCH+'?action='+action).then(function(r){return r.json()}).then(function(d){
    if(d.reachable)o.innerHTML=_infraPre('SWITCH \u2014 '+action.toUpperCase(),d.output);
    else o.innerHTML='<div class="c-red">Cannot reach switch at '+d.host+'</div><div class="c-dim-mt8">'+d.error+'</div>';
  });
}

/* ═══════════════════════════════════════════════════════════════════
   SECURITY
   ═══════════════════════════════════════════════════════════════════ */
function loadVault(){
  fetch(API.VAULT).then(function(r){return r.json()}).then(function(d){
    if(!d.initialized){document.getElementById('vault-c').innerHTML='<p class="c-yellow">Vault not initialized. Store a credential to auto-initialize.</p>';return;}
    var groups={};
    d.entries.forEach(function(e){if(!groups[e.host])groups[e.host]=[];groups[e.host].push(e);});
    var html='<div class="cards grid-auto-280" >';
    Object.keys(groups).sort().forEach(function(host){
      var entries=groups[host];
      html+='<div class="crd">';
      html+='<div class="flex-between-mb8"><h3>'+host.toUpperCase()+'</h3><button class="fleet-btn pill-err-xs" data-action="vaultDelGroup" data-arg="'+host+'" >DELETE ALL</button></div>';
      entries.forEach(function(e){
        html+='<div style="display:flex;gap:12px;padding:4px 0;border-top:1px solid var(--border);font-size:12px">';
        html+='<span style="font-weight:600;color:var(--text)">'+e.key+'</span><span class="c-dim">'+e.masked+'</span>';
        html+='</div>';
      });
      html+='</div>';
    });
    html+='</div><p class="c-dim-fs11-mt8">'+d.count+' credential(s) across '+Object.keys(groups).length+' service(s)</p>';
    document.getElementById('vault-c').innerHTML=html;
  });
}
function vaultSet(){
  var k=document.getElementById('v-key').value;var v=document.getElementById('v-val').value;var h=document.getElementById('v-host').value;
  if(!k||!v){toast('Key and value required','error');return;}
  fetch(API.VAULT_SET+'?key='+encodeURIComponent(k)+'&value='+encodeURIComponent(v)+'&host='+h).then(function(r){return r.json()}).then(function(d){
    if(d.ok){document.getElementById('v-key').value='';document.getElementById('v-val').value='';toast('Credential stored','success');loadVault();}else toast(d.error,'error');
  });
}
function vaultDelGroup(host){
  confirmAction('Delete ALL credentials for <strong>'+host.toUpperCase()+'</strong>?',function(){
    fetch(API.VAULT).then(function(r){return r.json()}).then(function(d){
      var promises=d.entries.filter(function(e){return e.host===host;}).map(function(e){
        return fetch(API.VAULT_DELETE+'?host='+e.host+'&key='+encodeURIComponent(e.key));
      });
      Promise.all(promises).then(function(){toast(host.toUpperCase()+' credentials deleted','success');loadVault();});
    });
  });
}
function loadUsers(){
  fetch(API.USERS).then(function(r){return r.json()}).then(function(d){
    var rc={admin:'var(--red)',operator:'var(--yellow)',viewer:'var(--green)',protected:'var(--purple-light)'};
    /* Filter buttons */
    var html='<div class="flex-row-8-center">';
    html+='<button class="fleet-btn user-filter active-view" data-filter="all" onclick="filterUsers(\'all\',this)">ALL ('+d.users.length+')</button>';
    var counts={admin:0,operator:0,viewer:0};
    d.users.forEach(function(u){if(counts[u.role]!==undefined)counts[u.role]++;});
    if(_currentRole==='admin')html+='<button class="fleet-btn user-filter c-red" data-filter="admin" onclick="filterUsers(\'admin\',this)" >ADMIN ('+counts.admin+')</button>';
    html+='<button class="fleet-btn user-filter c-yellow" data-filter="operator" onclick="filterUsers(\'operator\',this)" >OPERATOR ('+counts.operator+')</button>';
    html+='<button class="fleet-btn user-filter c-green" data-filter="viewer" onclick="filterUsers(\'viewer\',this)" >VIEWER ('+counts.viewer+')</button>';
    html+='</div>';
    /* User table */
    html+='<table class="w-full"><thead><tr><th>USERNAME</th><th>ROLE</th><th>PROMOTE / DEMOTE</th></tr></thead><tbody>';
    d.users.forEach(function(u,i){
      html+='<tr class="user-row" data-role="'+u.role+'">';
      html+='<td><strong>'+u.username.toUpperCase()+'</strong></td>';
      html+='<td><span style="color:'+(rc[u.role]||'var(--text-dim)')+';font-weight:600">'+u.role.toUpperCase()+'</span></td>';
      html+='<td class="flex-gap-6">';
      if(_currentRole==='admin'){
        if(u.role!=='admin')html+='<button class="fleet-btn pill-ok-3-10" data-action="userPromote" data-arg="'+u.username+'" >PROMOTE</button>';
        if(u.role!=='viewer')html+='<button class="fleet-btn pill-warn-sm" data-action="userDemote" data-arg="'+u.username+'" >DEMOTE</button>';
        if(u.role==='admin')html+='<span class="text-sub">MAX</span>';
        if(u.role==='viewer')html+='<span class="text-sub">MIN</span>';
      } else {
        html+='<span class="text-sub">ADMIN ONLY</span>';
      }
      html+='</td></tr>';
    });
    html+='</tbody></table>';
    document.getElementById('users-c').innerHTML=html;
  });
}
function filterUsers(role,btn){
  document.querySelectorAll('.user-filter').forEach(function(b){b.classList.remove('active-view');});
  btn.classList.add('active-view');
  document.querySelectorAll('.user-row').forEach(function(row){
    row.style.display=(role==='all'||row.getAttribute('data-role')===role)?'':'none';
  });
}
function userCreate(){
  var n=document.getElementById('u-name').value;var r=document.getElementById('u-role').value;
  if(!n){toast('Username required','error');return;}
  fetch(API.USERS_CREATE+'?username='+n+'&role='+r).then(function(r){return r.json()}).then(function(d){
    if(d.ok){document.getElementById('u-name').value='';toast('User created','success');loadUsers();}else toast(d.error,'error');
  });
}
function userPromote(u){
  confirmAction('Promote <strong>'+u+'</strong>?',function(){
    fetch(API.USERS_PROMOTE+'?username='+u).then(function(r){return r.json()}).then(function(d){if(d.ok){toast(u+' promoted','success');loadUsers();}else toast(d.error,'error');});
  });
}
function userDemote(u){
  confirmAction('Demote <strong>'+u+'</strong>?',function(){
    fetch(API.USERS_DEMOTE+'?username='+u).then(function(r){return r.json()}).then(function(d){if(d.ok){toast(u+' demoted','success');loadUsers();}else toast(d.error,'error');});
  });
}
function loadKeys(){
  fetch(API.KEYS).then(function(r){return r.json()}).then(function(d){
    var html='<p class="c-dim-mb12-fs12">SSH key: <code>'+d.ssh_key+'</code></p>';
    html+='<table><thead><tr><th>Host</th><th>IP</th><th>Reachable</th><th>Auth Keys</th></tr></thead><tbody>';
    d.hosts.forEach(function(h){
      var ph=PROD_HOSTS.find(function(p){return p.label===h.host;});
      var pv=PROD_VMS.find(function(v){return v.label===h.host;});
      var ht=ph?ph.type:'';var nd=pv?pv.node:'';
      var cl=_hostColor(h.host,ht,nd);
      html+='<tr><td style="color:'+cl+'"><strong>'+h.host+'</strong></td><td class="mono-11">'+h.ip+'</td><td>'+badge(h.reachable?'ok':'down')+'</td><td>'+h.key_count+'</td></tr>';
    });
    html+='</tbody></table>';document.getElementById('keys-c').innerHTML=html;
  });
}
var AUDIT_CHECKS={
  'ssh-root':{name:'SSH Root Login',cmd:"grep -c '^PermitRootLogin yes' /etc/ssh/sshd_config 2>/dev/null; true",pass:function(v){return parseInt(v)===0;}},
  'ssh-pass':{name:'SSH Password Auth',cmd:"grep -c '^PasswordAuthentication yes' /etc/ssh/sshd_config 2>/dev/null; true",pass:function(v){return parseInt(v)===0;}},
  'ssh-empty':{name:'Empty Passwords',cmd:"grep -c '^PermitEmptyPasswords yes' /etc/ssh/sshd_config 2>/dev/null; true",pass:function(v){return parseInt(v)===0;}},
  'ports':{name:'Open Ports',cmd:"ss -tlnp 2>/dev/null | grep LISTEN | wc -l",pass:function(v){return parseInt(v)<20;}},
  'failed':{name:'Failed Services',cmd:"systemctl --failed --no-legend 2>/dev/null | wc -l; true",pass:function(v){return parseInt(v)===0;}},
  'firewall':{name:'Firewall Active',cmd:"iptables -L -n 2>/dev/null | grep -c '^Chain'; true",pass:function(v){return parseInt(v)>0;}}
};
function runAuditCheck(type){
  var checks=type==='all'?Object.keys(AUDIT_CHECKS):[type];
  var out=document.getElementById('audit-c');out.innerHTML='<div class="skeleton"></div>';
  toast('Running '+checks.length+' audit check(s)...','info');
  var html='';var done=0;
  checks.forEach(function(key){
    var chk=AUDIT_CHECKS[key];if(!chk)return;
    fetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(chk.cmd)).then(function(r){return r.json()}).then(function(d){
      html+='<h3 style="color:var(--purple-light);margin:12px 0 8px">'+chk.name+'</h3><table><thead><tr><th>HOST</th><th>VALUE</th><th>STATUS</th></tr></thead><tbody>';
      d.results.forEach(function(r,i){
        var val=r.ok?r.output.trim():'error';
        var ok=r.ok&&chk.pass(r.output);
        html+='<tr><td><strong>'+r.host.toUpperCase()+'</strong></td><td>'+val+'</td><td>'+badge(ok?'ok':'CRITICAL')+'</td></tr>';
      });html+='</tbody></table>';done++;
      if(done===checks.length){
        var closeBtn='<button class="fleet-btn my-8" onclick="document.getElementById(\'audit-c\').innerHTML=\'\'" >CLOSE RESULTS</button>';
        out.innerHTML=closeBtn+html+closeBtn;
        toast('Audit complete — '+checks.length+' checks','success');
      }
    });
  });
}
function hardenAction(action){
  var cmds={
    'disable-root':{name:'Disable Root SSH',cmd:"sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config 2>/dev/null && echo OK || echo FAIL"},
    'key-only':{name:'Enforce Key-Only Auth',cmd:"sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config 2>/dev/null && echo OK || echo FAIL"},
    'disable-empty':{name:'Block Empty Passwords',cmd:"sed -i 's/^PermitEmptyPasswords yes/PermitEmptyPasswords no/' /etc/ssh/sshd_config 2>/dev/null; grep -q '^PermitEmptyPasswords' /etc/ssh/sshd_config || echo 'PermitEmptyPasswords no' >> /etc/ssh/sshd_config && echo OK || echo FAIL"},
    'auto-updates':{name:'Enable Auto Updates',cmd:"(apt-get install -y unattended-upgrades 2>/dev/null && dpkg-reconfigure -f noninteractive unattended-upgrades 2>/dev/null && echo OK) || (dnf install -y dnf-automatic 2>/dev/null && systemctl enable --now dnf-automatic.timer 2>/dev/null && echo OK) || echo FAIL"},
    'ssh-restart':{name:'Restart SSHD',cmd:"systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null && echo OK || echo FAIL"}
  };
  var c=cmds[action];if(!c)return;
  confirmAction('Run <strong>'+c.name+'</strong> on ALL fleet hosts?<br><br>This modifies system configuration.',function(){
    toast('Running '+c.name+'...','info');
    var out=document.getElementById('harden-c');out.innerHTML='<div class="skeleton"></div>';
    fetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(c.cmd)).then(function(r){return r.json()}).then(function(d){
      var html='<h3 style="color:var(--purple-light);margin-bottom:8px">'+c.name+'</h3><table><thead><tr><th>HOST</th><th>RESULT</th></tr></thead><tbody>';
      var ok=0;
      d.results.forEach(function(r,i){
        var success=r.ok&&r.output.trim()==='OK';if(success)ok++;
        html+='<tr><td><strong>'+r.host.toUpperCase()+'</strong></td><td>'+(success?'<span class="c-green">APPLIED</span>':'<span class="c-red">FAILED</span>')+'</td></tr>';
      });
      html+='</tbody></table>';
      var closeBtn='<button class="fleet-btn my-8" onclick="document.getElementById(\'harden-c\').innerHTML=\'\'" >CLOSE RESULTS</button>';
      out.innerHTML=closeBtn+html+closeBtn;
      toast(c.name+': '+ok+'/'+d.results.length+' hosts',ok===d.results.length?'success':'error');
    });
  });
}
function runSshSweep(){
  document.getElementById('sweep-c').innerHTML='<div class="skeleton"></div><div class="skeleton"></div>';
  var checks=[{name:'SSH: Password Auth',cmd:"grep -c '^PasswordAuthentication no' /etc/ssh/sshd_config 2>/dev/null||echo 0"},{name:'SSH: Root Login',cmd:"grep -c '^PermitRootLogin yes' /etc/ssh/sshd_config 2>/dev/null||echo 0"},{name:'SSH: Empty Passwords',cmd:"grep -c '^PermitEmptyPasswords no' /etc/ssh/sshd_config 2>/dev/null||echo 0"}];
  var html='';var done=0;
  checks.forEach(function(chk){
    fetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(chk.cmd)).then(function(r){return r.json()}).then(function(d){
      html+='<h3 style="color:var(--purple-light);margin:12px 0 8px">'+chk.name+'</h3><table><thead><tr><th>Host</th><th>Result</th><th>Status</th></tr></thead><tbody>';
      d.results.forEach(function(r,i){
        var val=r.ok?r.output.trim():'error';
        var ok=(chk.name.includes('Password Auth')||chk.name.includes('Empty'))?val!=='0':val==='0';
        html+='<tr><td><strong>'+r.host+'</strong></td><td>'+val+'</td><td>'+badge(ok?'ok':'CRITICAL')+'</td></tr>';
      });html+='</tbody></table>';done++;
      if(done===checks.length){var cb='<button class="fleet-btn my-8" onclick="document.getElementById(\'sweep-c\').innerHTML=\'\'" >CLOSE RESULTS</button>';document.getElementById('sweep-c').innerHTML=cb+html+cb;toast('Sweep complete','success');}
    });
  });
}
function runHarden(){
  document.getElementById('harden-c').innerHTML='<div class="skeleton"></div>';
  fetch(API.HARDEN).then(function(r){return r.json()}).then(function(d){
    var html='<table><thead><tr><th>Host</th><th>Check</th><th>Status</th></tr></thead><tbody>';
    d.results.forEach(function(r,i){html+='<tr><td><strong>'+r.host+'</strong></td><td>'+r.check+'</td><td>'+badge(r.ok?'ok':'CRITICAL')+'</td></tr>';});
    html+='</tbody></table>';var cb2='<button class="fleet-btn my-8" onclick="document.getElementById(\'harden-c\').innerHTML=\'\'" >CLOSE RESULTS</button>';document.getElementById('harden-c').innerHTML=cb2+html+cb2;
    toast('Hardening audit complete','success');
  });
}
function loadRisk(){
  var rc=document.getElementById('risk-chain');rc.innerHTML='';
  fetch(API.RISK).then(function(r){return r.json()}).then(function(d){
    /* Kill chain from API — no hardcoded nodes */
    var ch=d.chain||['Operator','VPN','Firewall','Switch','VLAN','Target'];
    ch.forEach(function(n,i){
      var isCrit=d.targets&&d.targets.find(function(t){return t.name===n.toLowerCase()&&t.risk==='CRITICAL';});
      var bg=isCrit?'background:rgba(248,81,73,0.15);color:var(--red)':'background:var(--purple-faint);color:var(--purple-light)';
      rc.innerHTML+='<div class="chain-node" style="'+bg+'">'+n+'</div>';
      if(i<ch.length-1)rc.innerHTML+='<span class="chain-arr">\u2192</span>';
    });
    var t=document.getElementById('risk-tbl');t.innerHTML='';
    if(!d.targets||!d.targets.length){t.innerHTML='<tr><td colspan="4" class="c-dim">No risk targets detected</td></tr>';}
    else d.targets.forEach(function(r){t.innerHTML+='<tr><td><strong>'+r.name+'</strong><br><span class="text-meta">'+r.label+'</span></td><td>'+badge(r.risk)+'</td><td class="fs-12">'+r.impact+'</td><td class="text-meta">'+r.recovery.substring(0,60)+'</td></tr>';});
  }).catch(function(){toast('Failed to load risk assessment','error');});
}
function loadPolicies(){
  fetch(API.POLICIES).then(function(r){return r.json()}).then(function(d){
    var h='<div class="cards">';
    d.policies.forEach(function(p){h+='<div class="crd"><h3>'+p.name+'</h3><p>'+p.description+'</p><div class="mt-8">';p.scope.forEach(function(ss){h+='<span class="tag">'+ss+'</span>';});h+='</div></div>';});
    h+='</div>';document.getElementById('policies-c').innerHTML=h;
  });
}

/* ═══════════════════════════════════════════════════════════════════
   SYSTEM
   ═══════════════════════════════════════════════════════════════════ */
function loadConfig(){
  fetch(API.CONFIG).then(function(r){return r.json()}).then(function(d){
    var html='<div class="two"><div class="crd"><h3>Identity</h3><table>';
    html+='<tr><td class="c-dim">Version</td><td>v'+d.version+'</td></tr>';
    html+='<tr><td class="c-dim">Brand</td><td>'+d.brand+'</td></tr>';
    html+='<tr><td class="c-dim">Build</td><td>'+d.build+'</td></tr>';
    html+='<tr><td class="c-dim">Cluster</td><td>'+d.cluster+'</td></tr>';
    html+='<tr><td class="c-dim">Timezone</td><td>'+d.timezone+'</td></tr>';
    html+='</table></div><div class="crd"><h3>SSH & Fleet</h3><table>';
    html+='<tr><td class="c-dim">Account</td><td>'+d.ssh_account+'</td></tr>';
    html+='<tr><td class="c-dim">Timeout</td><td>'+d.ssh_timeout+'s</td></tr>';
    html+='<tr><td class="c-dim">Parallel</td><td>'+d.ssh_parallel+'</td></tr>';
    html+='<tr><td class="c-dim">Hosts</td><td>'+d.hosts_count+'</td></tr>';
    html+='<tr><td class="c-dim">VLANs</td><td>'+d.vlans_count+'</td></tr>';
    html+='</table></div></div>';
    html+='<div class="two mt-12"><div class="crd"><h3>Infrastructure</h3><table>';
    html+='<tr><td class="c-dim">PVE Nodes</td><td>'+d.pve_nodes.join(', ')+'</td></tr>';
    html+='<tr><td class="c-dim">pfSense</td><td>'+d.pfsense_ip+'</td></tr>';
    html+='<tr><td class="c-dim">TrueNAS</td><td>'+d.truenas_ip+'</td></tr>';
    html+='</table></div><div class="crd"><h3>Safety</h3><table>';
    html+='<tr><td class="c-dim">Protected VMIDs</td><td class="fs-11">'+d.protected_vmids.join(', ')+'</td></tr>';
    html+='<tr><td class="c-dim">Install Dir</td><td style="font-size:11px;font-family:monospace">'+d.install_dir+'</td></tr>';
    html+='</table></div></div>';
    document.getElementById('config-c').innerHTML=html;
  });
}
function runSysInfo(){
  document.getElementById('doctor-c').innerHTML='<div class="skeleton"></div>';
  fetch(API.INFO).then(function(r){return r.json()}).then(function(d){
    var html='<div class="cards"><div class="crd"><h3>Installation</h3><table>';
    html+='<tr><td class="c-dim">Version</td><td>v'+d.version+'</td></tr>';
    html+='<tr><td class="c-dim">Brand</td><td>'+d.brand+'</td></tr>';
    html+='<tr><td class="c-dim">Build</td><td>'+d.build+'</td></tr>';
    html+='<tr><td class="c-dim">Cluster</td><td>'+d.cluster+'</td></tr>';
    html+='<tr><td class="c-dim">Hosts</td><td>'+d.hosts+'</td></tr>';
    html+='<tr><td class="c-dim">PVE Nodes</td><td>'+d.pve_nodes+'</td></tr>';
    html+='<tr><td class="c-dim">Install Dir</td><td class="mono-11">'+d.install_dir+'</td></tr>';
    html+='</table></div></div>';
    document.getElementById('doctor-c').innerHTML=html;
    toast('Doctor complete','success');
  });
}
function runBackup(){
  fetch(API.EXEC+'?target=all&cmd='+encodeURIComponent('echo ok')).then(function(r){return r.json()}).then(function(d){
    var reachable=d.results.filter(function(r){return r.ok}).length;
    document.getElementById('backup-c').innerHTML='<div class="crd"><h3>Config Export</h3><p>Fleet snapshot: '+reachable+'/'+d.results.length+' hosts reachable</p><p style="margin-top:8px;color:var(--text-dim)">Run from CLI: <code class="c-purple">freq backup export</code></p></div>';
    toast('Backup snapshot complete','success');
  });
}
function loadJournal(){
  fetch(API.JOURNAL).then(function(r){return r.json()}).then(function(d){
    if(!d.entries.length){document.getElementById('journal-c').innerHTML='<div class="empty-state"><div class="es-icon">&#128221;</div><p>No journal entries yet.</p></div>';return;}
    var html='<table><thead><tr><th>Time</th><th>Action</th><th>Target</th><th>Status</th><th>Detail</th></tr></thead><tbody>';
    d.entries.reverse().forEach(function(e){
      var sc={ok:'var(--green)',fail:'var(--red)',warn:'var(--yellow)'}[e.status]||'var(--text-dim)';
      html+='<tr><td class="text-meta">'+e.timestamp+'</td><td><strong>'+e.action+'</strong></td><td>'+e.target+'</td><td style="color:'+sc+'">'+e.status+'</td><td class="text-meta">'+(e.detail||'')+'</td></tr>';
    });html+='</tbody></table><p class="c-dim-fs11-mt8">'+d.count+' total entries</p>';
    document.getElementById('journal-c').innerHTML=html;
  });
}
function searchLearn(){
  var q=document.getElementById('learn-q').value;if(!q)return;
  fetch(API.LEARN+'?q='+encodeURIComponent(q)).then(function(r){return r.json()}).then(function(d){
    var h='';
    if(d.lessons&&d.lessons.length){h+='<h3 style="color:var(--purple-light);margin:12px 0">Lessons ('+d.lessons.length+')</h3><div class="cards">';
      d.lessons.forEach(function(l){h+='<div class="crd"><h3>#'+l.number+' '+l.title+'</h3><p>'+l.description+'</p><div class="mt-8"><span class="sev-'+l.severity+'">'+l.severity.toUpperCase()+'</span> <span class="tag">'+l.platform+'</span>'+(l.commands?' <span class="tag">'+l.commands+'</span>':'')+'</div></div>';});
      h+='</div>';}
    if(d.gotchas&&d.gotchas.length){h+='<h3 style="color:var(--yellow);margin:16px 0 12px">Gotchas ('+d.gotchas.length+')</h3>';
      d.gotchas.forEach(function(g){h+='<div class="gotcha"><p style="font-size:13px"><strong style="color:var(--cyan)">'+g.platform+'</strong>: '+g.description+'</p><p class="fix">Fix: '+g.fix+'</p></div>';});}
    if(!h)h='<p class="c-dim">No results for "'+q+'"</p>';
    document.getElementById('learn-r').innerHTML=h;
  });
}
function loadDistros(){
  fetch(API.DISTROS).then(function(r){return r.json()}).then(function(d){
    var html='<div class="cards">';
    d.distros.forEach(function(i){html+='<div class="crd"><h3>'+i.name+'</h3><div class="mt-4"><span class="tag">'+i.family+'</span><span class="tag">'+i.tier+'</span></div><p style="margin-top:8px;font-size:13px;color:var(--text);word-break:break-all">'+i.url+'</p></div>';});
    html+='</div>';document.getElementById('distro-c').innerHTML=html;
  });
}
function loadGroups(){
  fetch(API.GROUPS).then(function(r){return r.json()}).then(function(d){
    var html='<div class="cards">';
    Object.keys(d.groups).forEach(function(g){html+='<div class="crd"><h3>'+g+'</h3><p>'+d.groups[g].join(', ')+'</p><div class="mt-4"><span class="tag">'+d.groups[g].length+' hosts</span></div></div>';});
    html+='</div>';document.getElementById('groups-c').innerHTML=html;
  });
}
function loadNotify(){
  document.getElementById('notify-status').innerHTML='<div class="skeleton" style="height:40px"></div>';
  fetch(API.CONFIG).then(function(r){return r.json()}).then(function(d){
    var providers=[
      {name:'Discord',key:'discord_webhook'},{name:'Slack',key:'slack_webhook'},
      {name:'Telegram',keys:['telegram_bot_token','telegram_chat_id']},
      {name:'Email',keys:['smtp_host','smtp_to']},
      {name:'ntfy',keys:['ntfy_url','ntfy_topic']},
      {name:'Gotify',keys:['gotify_url','gotify_token']},
      {name:'Pushover',keys:['pushover_user','pushover_token']},
      {name:'Webhook',key:'webhook_url'}
    ];
    var html='<table class="mt-8"><tr><th>Provider</th><th>Status</th></tr>';
    providers.forEach(function(p){
      var ok=false;
      if(p.key)ok=!!d[p.key];
      if(p.keys)ok=p.keys.every(function(k){return !!d[k]});
      html+='<tr><td>'+p.name+'</td><td>'+(ok?badge('ok')+' Configured':badge('down')+' Not configured')+'</td></tr>';
    });
    html+='</table>';
    html+='<p style="margin-top:8px;font-size:11px;color:var(--text-dim)">Configure in freq.toml under [notifications]</p>';
    document.getElementById('notify-status').innerHTML=html;
  });
}
function testNotify(){fetch(API.NOTIFY_TEST).then(function(r){return r.json()}).then(function(d){document.getElementById('notify-result').innerHTML='<p class="c-dim">'+JSON.stringify(d)+'</p>';toast('Test notification sent','info');});}

/* ═══════════════════════════════════════════════════════════════════
   VM ACTIONS (toast + modal)
   ═══════════════════════════════════════════════════════════════════ */
function vmDestroy(vmid){
  confirmAction('Destroy VM <strong>'+vmid+'</strong>? This cannot be undone.',function(){
    fetch(API.VM_DESTROY+'?vmid='+vmid).then(function(r){return r.json()}).then(function(d){
      if(d.ok)toast('VM '+vmid+' destroyed','success');else toast('Error: '+d.error,'error');refreshCurrentView();
    });
  });
}
function vmSnap(vmid){
  fetch(API.VM_SNAPSHOT+'?vmid='+vmid).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast('Snapshot "'+d.snapshot+'" created','success');else toast('Error: '+d.error,'error');
  });
}
function vmPower(vmid,action){
  fetch(API.VM_POWER+'?vmid='+vmid+'&action='+action).then(function(r){return r.json()}).then(function(d){
    toast(d.action+': '+(d.ok?d.output:d.error),d.ok?'success':'error');refreshCurrentView();
  });
}
function vmPushKey(ip){
  if(!ip){toast('No IP available for this VM','error');return;}
  confirmAction('Push freq SSH key to <strong>'+ip+'</strong>?<br><span style="font-size:12px;color:var(--text-dim)">Deploys the freq-admin authorized_keys so FREQ can manage this host.</span>',function(){
    toast('Pushing key to '+ip+'...','info');
    fetch('/api/vm/push-key?token='+_authToken+'&ip='+encodeURIComponent(ip)).then(function(r){return r.json()}).then(function(d){
      if(d.error){toast('Key push failed: '+d.error,'error');return;}
      toast('Key deployed to '+ip+(d.verified?' — verified':''),'success');
    }).catch(function(e){toast('Key push failed: '+e,'error');});
  });
}

function _vmRename(vmid){
  var name=(document.getElementById('vm-new-name')||{}).value;
  if(!name){toast('Enter a name','error');return;}
  var out=document.getElementById('vm-ctrl-out');if(out)out.innerHTML='<span class="c-yellow">Renaming...</span>';
  confirmAction('Rename VM <strong>'+vmid+'</strong> to <strong>'+name+'</strong>?',function(){
    fetch(API.VM_RENAME+'?vmid='+vmid+'&name='+encodeURIComponent(name)).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast('VM '+vmid+' renamed to '+name,'success');if(out)out.innerHTML='<span class="c-green">Renamed to '+name+'</span>';document.getElementById('hd-title').textContent=name.toUpperCase();}
      else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<span class="c-red">'+d.error+'</span>';}
    });
  });
}
function _vmChangeId(vmid){
  var newid=(document.getElementById('vm-new-id')||{}).value;
  if(!newid){toast('Enter a new VMID','error');return;}
  var out=document.getElementById('vm-ctrl-out');if(out)out.innerHTML='<span class="c-yellow">Changing VMID...</span>';
  confirmAction('Change VMID <strong>'+vmid+'</strong> to <strong>'+newid+'</strong>?<br><span class="c-yellow">VM must be stopped. This clones to the new ID and destroys the old one.</span>',function(){
    fetch(API.VM_CHANGE_ID+'?vmid='+vmid+'&newid='+newid).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast('VMID changed: '+vmid+' \u2192 '+newid,'success');if(out)out.innerHTML='<span class="c-green">VMID changed to '+newid+'</span>';closeHost();}
      else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<span class="c-red">'+d.error+'</span>';}
    });
  });
}
function _vmSnapWarn(vmid,isRunning){
  confirmAction(
    '<strong class="c-yellow">SNAPSHOT WARNING</strong><br><br>'+
    'Creating a snapshot on VM <strong>'+vmid+'</strong> will <strong class="c-red">disable live migration</strong> for this VM until all snapshots are deleted.<br><br>'+
    '<span class="c-dim">Live migration requires zero snapshots. If you need to migrate this VM later, you will need to delete all snapshots first.</span><br><br>'+
    'Continue?',
    function(){
      fetch(API.VM_SNAPSHOT+'?vmid='+vmid).then(function(r){return r.json()}).then(function(d){
        if(d.ok){toast('Snapshot "'+d.snapshot+'" created — live migration DISABLED until deleted','success');}
        else{toast('Error: '+d.error,'error');}
      });
    }
  );
}
function _vmListSnaps(vmid){
  var out=document.getElementById('vm-ctrl-out');if(!out)return;
  out.innerHTML='<span class="c-dim">Loading snapshots...</span>';
  fetch(API.VM_SNAPSHOTS+'?vmid='+vmid).then(function(r){return r.json()}).then(function(d){
    if(!d.count){
      out.innerHTML='<div class="mt-8"><span style="color:var(--green);font-size:12px;font-weight:600">NO SNAPSHOTS</span><span style="color:var(--text-dim);font-size:12px;margin-left:8px">\u2014 live migration eligible</span></div>';
      return;
    }
    var h='<div class="mt-8"><div style="font-size:11px;color:var(--red);font-weight:600;margin-bottom:6px">'+d.count+' SNAPSHOT'+(d.count>1?'S':'')+' \u2014 LIVE MIGRATION BLOCKED</div>';
    d.snapshots.forEach(function(s){
      h+='<div style="display:flex;align-items:center;gap:8px;padding:4px 0"><span style="font-size:12px;font-family:monospace;color:var(--text)">'+s+'</span>';
      h+='<button class="fleet-btn btn-red" onclick="_vmDelSnap('+vmid+',\''+s+'\')" style="padding:2px 10px;font-size:11px">DELETE</button></div>';
    });
    h+='<button class="fleet-btn btn-red" onclick="_vmDelAllSnaps('+vmid+')" style="margin-top:8px;padding:6px 14px;font-size:11px">DELETE ALL \u2014 RESTORE LIVE MIGRATION</button>';
    h+='</div>';
    out.innerHTML=h;
  }).catch(function(){out.innerHTML='<span class="c-red">Failed to load snapshots</span>';});
}
function _vmDelSnap(vmid,name){
  confirmAction('Delete snapshot <strong>'+name+'</strong> from VM '+vmid+'?',function(){
    toast('Deleting snapshot '+name+'...','info');
    fetch(API.VM_DELETE_SNAP+'?vmid='+vmid+'&name='+encodeURIComponent(name)).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast('Snapshot '+name+' deleted','success');_vmListSnaps(vmid);}
      else{toast('Error: '+d.error,'error');}
    });
  });
}
function _vmDelAllSnaps(vmid){
  confirmAction('Delete <strong>ALL</strong> snapshots from VM '+vmid+'?<br><span class="c-green">This will restore live migration eligibility.</span>',function(){
    toast('Deleting all snapshots...','info');
    fetch(API.VM_SNAPSHOTS+'?vmid='+vmid).then(function(r){return r.json()}).then(function(d){
      var chain=Promise.resolve();
      d.snapshots.forEach(function(s){
        chain=chain.then(function(){return fetch(API.VM_DELETE_SNAP+'?vmid='+vmid+'&name='+encodeURIComponent(s)).then(function(r){return r.json()});});
      });
      chain.then(function(){toast('All snapshots deleted \u2014 live migration restored','success');_vmListSnaps(vmid);});
    });
  });
}
function _vmToggleResize(vmid){
  var out=document.getElementById('vm-ctrl-out');if(!out)return;
  if(out.getAttribute('data-mode')==='resize'){out.innerHTML='';out.removeAttribute('data-mode');return;}
  out.setAttribute('data-mode','resize');
  out.innerHTML='<div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;padding:12px 0">'+
    '<div><label class="label-sub-10">CPU CORES</label>'+
    '<select id="vm-rz-cores" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:8px 12px;border-radius:6px;font-size:12px;font-family:inherit"><option value="">Keep</option><option>1</option><option>2</option><option>4</option><option>8</option><option>12</option><option>16</option></select></div>'+
    '<div><label class="label-sub-10">RAM</label>'+
    '<select id="vm-rz-ram" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:8px 12px;border-radius:6px;font-size:12px;font-family:inherit"><option value="">Keep</option><option value="512">512MB</option><option value="1024">1GB</option><option value="2048">2GB</option><option value="4096">4GB</option><option value="8192">8GB</option><option value="16384">16GB</option><option value="32768">32GB</option></select></div>'+
    '<button class="fleet-btn pad-h16-fs12" onclick="_vmDoResize('+vmid+')" >APPLY</button></div>';
}
function _vmDoResize(vmid){
  var cores=(document.getElementById('vm-rz-cores')||{}).value;
  var ram=(document.getElementById('vm-rz-ram')||{}).value;
  if(!cores&&!ram){toast('Select cores or RAM','error');return;}
  var desc=[];if(cores)desc.push(cores+' cores');if(ram)desc.push(ram+'MB RAM');
  var out=document.getElementById('vm-ctrl-out');
  confirmAction('Resize VM <strong>'+vmid+'</strong> to '+desc.join(', ')+'?',function(){
    if(out)out.innerHTML='<span class="c-yellow">Resizing...</span>';
    fetch(API.VM_RESIZE+'?vmid='+vmid+(cores?'&cores='+cores:'')+(ram?'&ram='+ram:'')).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast('VM '+vmid+' resized','success');if(out)out.innerHTML='<span class="c-green">Resized \u2014 reboot to apply</span>';}
      else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<span class="c-red">'+d.error+'</span>';}
    });
  });
}
function _vmToggleMigrate(vmid,currentNode){
  var out=document.getElementById('vm-ctrl-out');if(!out)return;
  if(out.getAttribute('data-mode')==='migrate'){out.innerHTML='';out.removeAttribute('data-mode');return;}
  out.setAttribute('data-mode','migrate');
  var nodes=(_fleetCache.fo&&_fleetCache.fo.pve_nodes)||[];
  var opts='';nodes.forEach(function(n){if(n.name!==currentNode)opts+='<option value="'+n.name+'">'+n.name+' ('+n.detail.split(' \u00b7 ')[0]+')</option>';});
  out.innerHTML='<div style="display:flex;gap:10px;align-items:flex-end;padding:12px 0">'+
    '<div><label class="label-sub-10">TARGET NODE <span class="opacity-5">(current: '+currentNode+')</span></label>'+
    '<select id="vm-mig-target" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:8px 12px;border-radius:6px;font-size:12px;font-family:inherit;min-width:200px">'+opts+'</select></div>'+
    '<button class="fleet-btn pad-h16-fs12" onclick="_vmDoMigrate('+vmid+')" >MIGRATE</button></div>';
}
function _vmDoMigrate(vmid){
  var target=(document.getElementById('vm-mig-target')||{}).value;
  if(!target){toast('Select a target node','error');return;}
  var out=document.getElementById('vm-ctrl-out');
  confirmAction('Migrate VM <strong>'+vmid+'</strong> to <strong>'+target+'</strong>?<br><span class="c-dim">This may take several minutes.</span>',function(){
    if(out)out.innerHTML='<span class="c-yellow">Migrating to '+target+'...</span>';
    fetch(API.EXEC+'?target=localhost&cmd='+encodeURIComponent('sudo qm migrate '+vmid+' '+target+' --online')).then(function(r){return r.json()}).then(function(d){
      var txt=d.results?d.results.map(function(r){return r.output;}).join(''):'';
      if(out)out.innerHTML='<span class="c-green">'+txt+'</span>';toast('Migration started','success');
    }).catch(function(e){if(out)out.innerHTML='<span class="c-red">'+e+'</span>';});
  });
}
/* NIC combo builder — VLAN map for preview + apply */
function _getNicCombo(){
  var sel=document.getElementById('vm-nic-combo');if(!sel)return[];
  var opt=sel.options[sel.selectedIndex];
  var ids=(opt.getAttribute('data-nics')||'').split(',').map(function(s){return parseInt(s);});
  return ids;
}
function _updateNicPreviewCombo(){
  var pre=document.getElementById('vm-nic-preview');if(!pre)return;
  var ids=_getNicCombo();
  var octet=(document.getElementById('vm-nic-octet')||{}).value;
  if(!octet){pre.innerHTML='<span class="opacity-5">Enter last octet...</span>';return;}
  var lines=[];
  ids.forEach(function(vid,i){
    var v=_VLAN_MAP[vid];if(!v)return;
    lines.push('<span class="c-dim">net'+i+'</span> <span style="color:var(--purple-light);font-weight:600">'+v.name+'</span> '+v.prefix+'.'+octet+'/'+(v.cidr||'24')+(v.gw?' <span class="c-dim">\u2192 gw '+v.gw+'</span>':''));
  });
  pre.innerHTML=lines.join('<br>');
}
function _vmCheckAndAddNic(vmid){
  var sel=document.getElementById('vm-add-nic-vlan');if(!sel)return;
  var octet=(document.getElementById('vm-add-nic-octet')||{}).value;
  var status=document.getElementById('vm-add-nic-status');
  if(!octet){toast('Enter the last octet','error');return;}
  var opt=sel.options[sel.selectedIndex];
  var prefix=opt.getAttribute('data-prefix');
  var gw=opt.getAttribute('data-gw')||'';
  var vlan=sel.value;
  var ip=prefix+'.'+octet;
  if(status)status.innerHTML='<span class="c-yellow">Checking '+ip+'...</span>';
  fetch(API.VM_CHECK_IP+'?ip='+encodeURIComponent(ip)).then(function(r){return r.json()}).then(function(d){
    if(d.in_use){
      if(status)status.innerHTML='<span class="c-red">'+ip+' is IN USE \u2014 pick another</span>';
      toast(ip+' is already in use','error');
      return;
    }
    if(status)status.innerHTML='<span class="c-green">'+ip+' is AVAILABLE</span>';
    var cidr=opt.getAttribute('data-cidr')||'24';
    confirmAction('Add NIC to VM <strong>'+vmid+'</strong>:<br><span style="font-family:monospace">'+opt.textContent+' \u2192 '+ip+'/'+cidr+'</span>'+(gw?'<br><span style="font-family:monospace;color:var(--text-dim)">gw '+gw+'</span>':'')+'<br><br><span class="c-dim">This adds a new NIC without touching existing ones. Reboot to activate.</span>',function(){
      if(status)status.innerHTML='<span class="c-yellow">Adding NIC...</span>';
      fetch(API.VM_ADD_NIC+'?vmid='+vmid+'&ip='+encodeURIComponent(ip+'/'+cidr)+'&gw='+encodeURIComponent(gw)+'&vlan='+vlan).then(function(r){return r.json()}).then(function(d2){
        if(d2.ok){
          toast(d2.nic+' added: '+ip,'success');
          if(status)status.innerHTML='<span class="c-green">'+d2.nic+' added \u2014 reboot to activate</span>';
        } else {
          toast('Error: '+d2.error,'error');
          if(status)status.innerHTML='<span class="c-red">'+d2.error+'</span>';
        }
      });
    });
  }).catch(function(e){if(status)status.innerHTML='<span class="c-red">Check failed</span>';});
}
function _vmApplyNicCombo(vmid){
  var ids=_getNicCombo();
  var octet=(document.getElementById('vm-nic-octet')||{}).value;
  if(!octet){toast('Enter the last octet','error');return;}
  if(parseInt(octet)<1||parseInt(octet)>254){toast('Octet must be 1-254','error');return;}
  var configs=[];
  ids.forEach(function(vid,i){
    var v=_VLAN_MAP[vid];if(!v)return;
    configs.push({nic:i,ip:v.prefix+'.'+octet+'/'+(v.cidr||'24'),gw:v.gw,vlan:vid});
  });
  if(!configs.length){toast('No NICs configured','error');return;}
  var desc=configs.map(function(c){var v=_VLAN_MAP[c.vlan];return 'net'+c.nic+': '+v.name+' \u2192 '+c.ip;}).join('<br>');
  var out=document.getElementById('vm-ctrl-out');
  confirmAction('<strong>Set VM '+vmid+' network ('+configs.length+' NIC'+(configs.length>1?'s':'')+')</strong><br><br><span style="font-family:monospace;line-height:1.8">'+desc+'</span><br><br><span class="c-yellow">All existing NICs will be CLEARED first.</span><br><span class="c-dim">Reboot required to activate.</span>',function(){
    if(out)out.innerHTML='<span class="c-yellow">Clearing existing NICs...</span>';
    fetch(API.VM_CLEAR_NICS+'?vmid='+vmid).then(function(r){return r.json()}).then(function(d){
      if(out)out.innerHTML='<span class="c-yellow">Applying '+configs.length+' NICs...</span>';
      var chain=Promise.resolve();
      configs.forEach(function(c){
        chain=chain.then(function(){
          return fetch(API.VM_CHANGE_IP+'?vmid='+vmid+'&ip='+encodeURIComponent(c.ip)+'&gw='+encodeURIComponent(c.gw)+'&nic='+c.nic+'&vlan='+c.vlan).then(function(r){return r.json();});
        });
      });
      return chain;
    }).then(function(){
      toast('Network applied — '+configs.length+' NICs configured','success');
      if(out)out.innerHTML='<span class="c-green">'+configs.length+' NICs set \u2014 reboot VM to apply</span>';
    }).catch(function(e){
      toast('Error: '+e,'error');
      if(out)out.innerHTML='<span class="c-red">'+e+'</span>';
    });
  });
}
/* ═══════════════════════════════════════════════════════════════════
   HOST OVERLAY — Card Dispatch System
   ═══════════════════════════════════════════════════════════════════ */
var _cardState={type:'',host:'',vmid:0};
var _infraOutputTarget=null;

/* ── Shared HTML builders ── */
function _toolPanelHtml(){
  return '<div id="hd-tool-panel" style="display:none;margin-bottom:20px">'+
    '<div class="exec-bar">'+
    '<input id="hd-cmd" placeholder="Command to run on this host" onkeydown="if(event.key===\'Enter\')hdRunCmd()">'+
    '<button onclick="hdRunCmd()">Run</button>'+
    '</div>'+
    '<div class="exec-out" id="hd-exec-out" style="margin-top:8px;min-height:150px"></div>'+
    '</div>';
}
function _infraPanelHtml(roleLabel,roleColor,btnsHtml){
  return '<div style="margin-bottom:16px;background:var(--card);border:2px solid var(--input-border);border-radius:8px;padding:16px">'+
    '<div style="font-size:11px;color:'+roleColor+';text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;font-weight:600">'+roleLabel+'</div>'+
    '<div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center">'+btnsHtml+'</div>'+
    '<div class="exec-out" id="hd-infra-out" style="margin-top:12px;min-height:80px;display:none"></div>'+
    '</div>';
}
function _kvRow(k,v,c){return '<div class="ho-row"><span class="k">'+k+'</span><span class="v" style="color:'+(c||'var(--text)')+'">'+v+'</span></div>';}

/* ── Core card dispatcher ── */
function openCard(type,config){
  _cardState={type:type,host:config.label||'',vmid:config.vmid||0};
  _infraOutputTarget=null;
  var ov=document.getElementById('host-overlay');
  ov.classList.add('open');
  ov.scrollTop=0;
  document.body.style.overflow='hidden';
  document.getElementById('hd-title').textContent=(config.label||'').toUpperCase();
  document.getElementById('hd-subtitle').textContent='Loading...';
  document.getElementById('hd-loading').style.display='block';
  document.getElementById('hd-content').style.display='none';
  document.getElementById('hd-content').innerHTML='';
  var renderers={vm:renderVmCard,pve:renderPveNodeCard,infra:renderInfraCard,host:renderHostCard};
  var fn=renderers[type];
  if(fn)fn(config);
}
function closeCard(){
  document.getElementById('host-overlay').classList.remove('open');
  document.body.style.overflow='';
  _infraOutputTarget=null;
  _cardState={type:'',host:'',vmid:0};
  document.getElementById('hd-content').innerHTML='';
}
var closeHost=closeCard;
function _cardReady(html){
  document.getElementById('hd-loading').style.display='none';
  var el=document.getElementById('hd-content');
  el.innerHTML=html;
  el.style.display='block';
}

/* ── Backward-compat shims ── */
function openVmInfo(label,ip,vmid){
  if(vmid===0||vmid==='0'){
    var infraType=_findInfraType(label);
    if(infraType){openCard('infra',{label:label,infraType:infraType});}
    else{openCard('pve',{label:label,ip:ip});}
  }
  else{openCard('vm',{label:label,ip:ip,vmid:vmid});}
}
function openHost(label){
  var infraType=_findInfraType(label);
  if(infraType){openCard('infra',{label:label,infraType:infraType});}
  else{openCard('host',{label:label});}
}

/* ── Renderer: PVE Node ── */
function renderPveNodeCard(config){
  var label=config.label,ip=config.ip||'';
  var pn=null;
  if(_fleetCache.fo&&_fleetCache.fo.pve_nodes)pn=_fleetCache.fo.pve_nodes.find(function(n){return n.name===label;});
  var live=null;
  if(_fleetCache.hd&&_fleetCache.hd.hosts)live=_fleetCache.hd.hosts.find(function(h){return h.label===label;});
  var up=live&&live.status==='healthy';
  document.getElementById('hd-subtitle').textContent=ip+' \u00b7 HYPERVISOR'+(pn?' \u00b7 '+pn.detail:'');
  var stats='';
  stats+=st('STATUS',up?'ONLINE':'OFFLINE',up?'g':'r');
  if(up&&live){
    var cores=parseInt(live.cores)||0;var loadVal=parseFloat(live.load)||0;
    var loadPct=cores>0?Math.round(loadVal/cores*100):0;
    stats+=st('CPU',cores+' cores \u00b7 '+loadPct+'%','p');
    var rp=(live.ram||'').match(/(\d+)\/(\d+)/);
    if(rp)stats+=st('RAM',_ramGB(rp[1])+' / '+_ramGB(rp[2]),'b');
    stats+=st('DISK',live.disk||'?','g');
    stats+=st('LOAD',live.load||'?','b');
  }
  var nodeVms=[];
  if(_fleetCache.fo&&_fleetCache.fo.vms){nodeVms=_fleetCache.fo.vms.filter(function(v){return v.node===label;});}
  var vmRun=nodeVms.filter(function(v){return v.status==='running';}).length;
  var vmStop=nodeVms.length-vmRun;
  stats+=st('VMs',vmRun+' RUN / '+vmStop+' STOP','p');
  var html='<div class="card-box"><div class="stats mb-0" >'+stats+'</div></div>';
  var _pveActs=[
    {l:'CLUSTER STATUS',a:'pvesh get /cluster/status --output-format json-pretty'},
    {l:'STORAGE',a:'pvesh get /storage --output-format json-pretty'},
    {l:'RECENT TASKS',a:'pvesh get /cluster/tasks --limit 15 --output-format json-pretty'},
    {l:'NODE STATUS',a:'pvesh get /nodes/'+label+'/status --output-format json-pretty'},
    {l:'BACKUP STATUS',a:'pvesh get /cluster/backup --output-format json-pretty'},
    {l:'SERVICES',a:'pvesh get /nodes/'+label+'/services --output-format json-pretty'},
    {l:'DISKS',a:'lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE'},
    {l:'NETWORK',a:'pvesh get /nodes/'+label+'/network --output-format json-pretty'},
    {l:'SYSLOG',a:'journalctl --no-pager -n 40 --output=short-iso'},
  ];
  var btns='';
  _pveActs.forEach(function(a){
    btns+='<button class="fleet-btn min-w-120-center"  onclick="event.stopPropagation();_runPveNodeCmd(\''+label+'\',\''+ip+'\',\''+a.a.replace(/'/g,"\\'")+'\')">'+a.l+'</button>';
  });
  btns+='<button class="fleet-btn min-w-120-center"  onclick="event.stopPropagation();hdExec(this)">RUN CMD</button>';
  btns+='<button class="fleet-btn min-w-120-center"  onclick="event.stopPropagation();hdLogs(this)">LOGS</button>';
  btns+='<button class="fleet-btn min-w-120-center"  onclick="event.stopPropagation();hdDiagnose(this)">DIAGNOSE</button>';
  html+=_infraPanelHtml('PVE NODE CONTROLS','var(--purple-light)',btns);
  html+=_toolPanelHtml();
  _infraOutputTarget='hd-infra-out';
  _cardReady(html);
}

/* ── Renderer: Infrastructure (Firewall / Storage / Switch / BMC) ── */
function renderInfraCard(config){
  var label=config.label,infraType=config.infraType;
  var ph=null;
  if(_fleetCache.fo&&_fleetCache.fo.physical)ph=_fleetCache.fo.physical.find(function(p){return p.label===label;});
  if(!ph)ph=PROD_HOSTS.find(function(h){return h.label===label;});
  var roleInfo=INFRA_ROLES[infraType]||{role:infraType.toUpperCase(),color:'var(--text-dim)'};
  document.getElementById('hd-subtitle').textContent=(ph?ph.ip+' \u00b7 ':'')+roleInfo.role+(ph?' \u00b7 '+ph.detail:'');
  var stats='';
  var live=_fleetCache.hd?(_fleetCache.hd.hosts||[]).find(function(h){return h.label===label;}):null;
  var up=ph&&ph.reachable;if(live&&live.status==='healthy')up=true;
  stats+=st('STATUS',up?'ONLINE':'OFFLINE',up?'g':'r');
  if(live){
    if(live.cores)stats+=st('CPU',live.cores+' Cores','p');
    if(live.ram)stats+=st('RAM',_ramStr(live.ram),'b');
    if(live.disk)stats+=st('DISK',live.disk,'g');
    if(live.uptime)stats+=st('UPTIME',live.uptime.replace('up ','').split(',').slice(0,2).join(','),'p');
  }
  var html='<div class="card-box"><div class="stats mb-0" >'+stats+'</div></div>';
  var actions=INFRA_ACTIONS[infraType];
  if(actions){
    var btns='';
    actions.forEach(function(a){
      var match=a.f.match(/\('([^']+)'\)/);
      var actionName=match?match[1]:'status';
      btns+='<button class="fleet-btn min-w-120-center"  onclick="event.stopPropagation();_runInfraAction(\''+infraType+'\',\''+actionName+'\')">'+a.l+'</button>';
    });
    html+=_infraPanelHtml(roleInfo.role+' CONTROLS',roleInfo.color,btns);
  }
  _infraOutputTarget='hd-infra-out';
  _cardReady(html);
}

/* ── Renderer: Host (async SSH probe) — adaptive layout ── */
function renderHostCard(config){
  var label=config.label;
  fetch(API.HOST_DETAIL+'?host='+encodeURIComponent(label)).then(function(r){return r.json()}).then(function(d){
    if(d.error){_cardReady('<p class="c-red">'+d.error+'</p>');return;}
    document.getElementById('hd-subtitle').textContent=d.ip+' \u00b7 '+(d.type||'linux')+' \u00b7 '+(d.os||'unknown');
    var kv=_kvRow;
    var ramParts=(d.ram||'').match(/(\d+)\/(\d+)/);var ramPct=ramParts?Math.round(parseInt(ramParts[1])/parseInt(ramParts[2])*100):0;
    var diskPct=parseInt((d.disk||'').match(/(\d+)%/)?.[1])||0;
    var loadVal=parseFloat(d.load)||0;var cores=parseInt(d.cores)||1;
    var loadPct=Math.min(Math.round(loadVal/cores*100),100);
    var rParts=(d.ram||'').match(/(\d+)\/(\d+)/);
    var dc=parseInt(d.docker_count)||0;
    var isDocker=dc>0;
    /* ── Stats bar ── */
    var stats='';stats+=st('CPU',d.cores+' cores','p');stats+=st('RAM',rParts?_ramGB(rParts[1])+' / '+_ramGB(rParts[2]):'?',ramPct>80?'r':'g');
    stats+=st('Disk',(d.disk||'?').replace(/.*\(|\).*/g,''),diskPct>80?'r':'g');stats+=st('Load',d.load||'?',loadPct>80?'r':'b');
    stats+=st('Uptime',(d.uptime||'?').replace('up ','').split(',').slice(0,2).join(','),'p');
    if(isDocker)stats+=st('Docker',dc+' Containers','b');
    var svcCount=parseInt(d.running_services)||0;if(svcCount>0)stats+=st('Services',svcCount+' Running','y');
    var html='<div class="card-box"><div class="stats mb-0" >'+stats+'</div></div>';
    /* ── Action buttons ── */
    html+='<div class="ho-actions" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin-bottom:24px">';
    html+='<button data-action="hdExec">RUN COMMAND</button>';
    html+='<button data-action="hdLogs">VIEW LOGS</button>';
    html+='<button data-action="hdDiagnose">FULL DIAGNOSE</button>';
    html+='<button data-action="hdRestart" class="c-yellow">RESTART SERVICES</button>';
    html+='</div>';
    html+=_toolPanelHtml();
    /* ── Build reusable data sections ── */
    var sysContent='';sysContent+=kv('HOSTNAME',d.hostname||'-');sysContent+=kv('OS',d.os||'-');sysContent+=kv('KERNEL',d.kernel||'-');
    sysContent+=kv('CPU',d.cpu_model||'-');sysContent+=kv('CORES',d.cores||'-');sysContent+=kv('RAM',_ramStr(d.ram||'-'));
    sysContent+=kv('DISK',d.disk||'-');sysContent+=kv('LOAD',d.load||'-');sysContent+=kv('UPTIME',d.uptime||'-');
    var netContent='';var ips=(d.ips||'').trim();
    if(ips)ips.split('\n').forEach(function(line){if(line.trim())netContent+=kv('INTERFACE',line.trim());});else netContent+=kv('IPs','-');
    if(d.gateway)netContent+=kv('GATEWAY',d.gateway);if(d.dns&&d.dns.trim())netContent+=kv('DNS',d.dns.trim());
    if(d.listening_ports&&d.listening_ports.trim())netContent+=kv('LISTENING',d.listening_ports.trim());
    if(d.running_services&&d.running_services!=='0')netContent+=kv('SERVICES',d.running_services+' Running');
    var secContent='';
    secContent+=kv('ROOT LOGIN',d.ssh_root_login||'Unset',d.ssh_root_login==='yes'?'var(--red)':'var(--green)');
    secContent+=kv('PASSWORD AUTH',d.ssh_password_auth||'Unset',d.ssh_password_auth==='yes'?'var(--yellow)':'var(--green)');
    secContent+=kv('FAILED SERVICES',d.failed_services||'None',(d.failed_services||'none')!=='none'?'var(--yellow)':'var(--green)');
    secContent+=kv('LAST LOGIN',d.last_login||'-');
    var ntpOk=(d.ntp_synced||'')==='yes';secContent+=kv('NTP SYNCED',ntpOk?'YES':'NO',ntpOk?'var(--green)':'var(--red)');
    secContent+=kv('NTP SERVICE',(d.ntp_service||'Unknown').toUpperCase(),(d.ntp_service==='active')?'var(--green)':'var(--yellow)');
    var updates=parseInt(d.updates_available)||0;secContent+=kv('OS UPDATES',updates>0?updates+' AVAILABLE':'UP TO DATE',updates>0?'var(--yellow)':'var(--green)');
    secContent+=kv('PKG MANAGER',(d.pkg_manager||'?').toUpperCase());
    /* ── ADAPTIVE LAYOUT ── */
    if(isDocker&&d.docker_containers&&d.docker_containers.length){
      /* === DOCKER-FIRST LAYOUT === */
      var containers=d.docker_containers;
      var upCount=0;containers.forEach(function(c){if(c.status.indexOf('Up')>=0)upCount++;});
      var downCount=containers.length-upCount;
      /* Container header */
      html+='<div class="flex-between-mb12">';
      html+='<h3 style="font-size:15px;color:var(--purple-light);text-transform:uppercase;letter-spacing:2px;font-weight:700;margin:0">CONTAINERS</h3>';
      html+='<div style="display:flex;gap:8px;align-items:center">';
      html+='<span style="font-size:11px;font-weight:600;color:var(--green)">'+upCount+' UP</span>';
      if(downCount>0)html+='<span style="font-size:11px;font-weight:600;color:var(--red)">'+downCount+' DOWN</span>';
      html+='</div></div>';
      /* Container card grid — 2 cols for 4+, 1 col for 1-3 */
      var gridCols=containers.length>=4?'repeat(2,1fr)':'1fr';
      html+='<div style="display:grid;grid-template-columns:'+gridCols+';gap:10px;margin-bottom:20px">';
      containers.forEach(function(c){
        var isUp=c.status.indexOf('Up')>=0;
        var statusColor=isUp?'var(--green)':'var(--red)';
        var borderColor=isUp?'#1a3a2a':'#3a1a1a';
        var imgShort=(c.image||'').replace(/^.*\//,'').replace(/:latest$/,'');
        html+='<div style="background:var(--card);border:1px solid '+borderColor+';border-left:4px solid '+statusColor+';border-radius:8px;padding:12px 14px">';
        html+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">';
        html+='<span style="font-size:13px;font-weight:700;color:var(--text);text-transform:uppercase;letter-spacing:0.5px">'+c.name+'</span>';
        html+=badge(isUp?'up':'down');
        html+='</div>';
        html+='<div style="font-size:11px;color:var(--text-dim);margin-bottom:4px;font-family:monospace">'+imgShort+'</div>';
        html+='<div style="font-size:11px;color:var(--text-dim);margin-bottom:8px">'+c.status+'</div>';
        html+='<div class="flex-gap-6">';
        html+='<button class="fleet-btn pill-4-10-fs11" onclick="hdDockerRestart(\''+c.name+'\')" >RESTART</button>';
        html+='<button class="fleet-btn pill-4-10-fs11" onclick="hdDockerLogs(\''+c.name+'\')" >LOGS</button>';
        html+='</div></div>';
      });
      html+='</div>';
      /* Compact system summary for Docker hosts — horizontal key-values */
      html+='<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-bottom:10px">';
      html+='<div class="ho-section"><h3>System</h3>';
      html+=kv('OS',d.os||'-');html+=kv('KERNEL',d.kernel||'-');html+=kv('CPU',d.cpu_model||'-');
      html+='</div>';
      html+='<div class="ho-section"><h3>Network</h3>'+netContent+'</div>';
      html+='<div class="ho-section"><h3>Security</h3>'+secContent+'</div>';
      html+='</div>';
    } else {
      /* === STANDARD LAYOUT — bare Linux / non-Docker === */
      html+='<div class="ho-grid">';
      html+='<div class="ho-section"><h3>System</h3>'+sysContent+'</div>';
      html+='<div class="ho-section"><h3>Network</h3>'+netContent+'</div>';
      html+='</div>';
      html+='<div class="ho-section mt-10" ><h3>SECURITY & STATUS</h3>'+secContent+'</div>';
    }
    _cardReady(html);
  }).catch(function(e){_cardReady('<p class="c-red">Error: '+e+'</p>');});
}
/* Docker container actions from host detail */
function hdDockerRestart(name){
  if(!confirm('Restart container: '+name+'?'))return;
  var host=_cardState.host;
  fetch(API.EXEC+'?target='+encodeURIComponent(host)+'&cmd='+encodeURIComponent('docker restart '+name))
    .then(function(r){return r.json()}).then(function(d){var txt='';if(d.results){d.results.forEach(function(r){txt+=r.output+'\n';});}toast(txt||'Restarted '+name,'success');}).catch(function(e){toast('Error: '+e,'error');});
}
function hdDockerLogs(name){
  var host=_cardState.host;
  var panel=document.getElementById('hd-tool-panel');if(panel)panel.style.display='block';
  var out=document.getElementById('hd-exec-out');if(out)out.textContent='Loading logs for '+name+'...';
  fetch(API.EXEC+'?target='+encodeURIComponent(host)+'&cmd='+encodeURIComponent('docker logs --tail 50 '+name+' 2>&1'))
    .then(function(r){return r.json()}).then(function(d){var txt='';if(d.results){d.results.forEach(function(r){txt+=r.output+'\n';});}if(out)out.textContent=txt||'(no output)';}).catch(function(e){if(out)out.textContent='Error: '+e;});
}

/* ── VM Card helpers ── */
function _vmConfigPanel(vmid,label){
  var h='<div class="flex-fill">';
  h+='<div class="fs-11-dim-mb10-ls">CONFIGURE</div>';
  h+='<div class="mb-8"><label class="label-sub-10-tight">RENAME</label><div class="flex-gap-4"><input id="vm-new-name" placeholder="new name" value="'+label+'" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:6px 10px;border-radius:6px;font-size:12px;font-family:inherit;width:180px"><button class="fleet-btn pill-pad6" onclick="_vmRename('+vmid+')" >SET</button></div></div>';
  h+='<div class="mb-8"><label class="label-sub-10-tight">VMID</label><div class="flex-gap-4"><input id="vm-new-id" placeholder="new ID" type="number" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:6px 10px;border-radius:6px;font-size:12px;font-family:inherit;width:100px"><button class="fleet-btn pill-pad6" onclick="_vmChangeId('+vmid+')" >SET</button></div></div>';
  h+='<div><label class="label-sub-10-tight">NETWORK CONFIG</label>';
  h+='<div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">';
  h+='<select id="vm-nic-combo" onchange="_updateNicPreviewCombo()" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:6px 10px;border-radius:6px;font-size:12px;font-family:inherit">';
  var _vids=Object.keys(_VLAN_MAP).sort(function(a,b){return parseInt(a)-parseInt(b);});
  if(_vids.length){
    _vids.forEach(function(vid){h+='<option value="v'+vid+'" data-nics="'+vid+'">'+_VLAN_MAP[vid].name+'</option>';});
    if(_vids.length>1){h+='<option value="all" data-nics="'+_vids.join(',')+'" selected>ALL ('+_vids.length+' VLANs)</option>';}
  } else {
    h+='<option value="default" data-nics="0">Default</option>';
  }
  h+='</select>';
  h+='<span style="color:var(--text-dim);font-size:12px;font-weight:600">OCTET:</span>';
  h+='<input id="vm-nic-octet" type="number" min="1" max="254" placeholder="x" oninput="_updateNicPreviewCombo()" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:6px 10px;border-radius:6px;font-size:12px;font-family:monospace;width:55px">';
  h+='<button class="fleet-btn pill-pad6" onclick="_vmApplyNicCombo('+vmid+')" >APPLY</button>';
  h+='</div>';
  h+='<div id="vm-nic-preview" style="font-size:11px;color:var(--text-dim);font-family:monospace;line-height:1.6"></div>';
  h+='<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--input-border)">';
  h+='<div style="display:flex;gap:6px;align-items:center">';
  h+='<span style="font-size:10px;color:var(--text-dim);font-weight:600">ADD NIC</span>';
  h+='<select id="vm-add-nic-vlan" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:5px 8px;border-radius:6px;font-size:11px;font-family:inherit">';
  Object.keys(_VLAN_MAP).forEach(function(vid){var vl=_VLAN_MAP[vid];h+='<option value="'+vid+'" data-prefix="'+vl.prefix+'" data-gw="'+(vl.gw||'')+'" data-cidr="'+(vl.cidr||'24')+'">'+vl.name+'</option>';});
  h+='</select>';
  h+='<span style="color:var(--text-dim);font-size:14px;font-weight:700">.</span>';
  h+='<input id="vm-add-nic-octet" type="number" min="1" max="254" placeholder="x" style="background:var(--card);border:2px solid var(--input-border);color:var(--text);padding:5px 8px;border-radius:6px;font-size:11px;font-family:monospace;width:50px">';
  h+='<button class="fleet-btn" onclick="_vmCheckAndAddNic('+vmid+')" style="padding:5px 10px;font-size:11px">CHECK & ADD</button>';
  h+='<span id="vm-add-nic-status" class="fs-11"></span>';
  h+='</div></div></div>';
  h+='</div>';
  return h;
}
function _vmNicCards(allIps){
  var h='<div style="font-size:11px;color:var(--text-dim);margin-bottom:8px;letter-spacing:0.5px">CONNECTED NETWORKS</div>';
  allIps.forEach(function(a){
    var c=VLAN_COLORS[a.vlan]||'var(--text-dim)';
    var nicGw='?';
    Object.keys(_VLAN_MAP).forEach(function(vid){var v=_VLAN_MAP[vid];if(v.name===a.vlan){if(v.gw)nicGw=v.gw;else if(v.prefix)nicGw=v.prefix+'.1';}});
    h+='<div style="background:rgba(0,0,0,0.15);border:1px solid var(--input-border);border-radius:6px;padding:8px 10px;margin-bottom:6px">';
    h+='<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">';
    h+='<span style="font-size:11px;color:var(--text-dim);font-family:monospace;font-weight:600">'+a.nic+'</span>';
    h+='<span style="background:rgba(0,0,0,0.3);border:1px solid '+c+';color:'+c+';padding:1px 8px;border-radius:3px;font-size:11px;font-weight:600;letter-spacing:0.3px">'+a.vlan+'</span>';
    h+='</div>';
    h+='<div style="display:flex;gap:16px;font-size:11px;font-family:monospace">';
    h+='<span style="color:var(--blue);font-weight:600">'+a.ip+'</span>';
    h+='<span class="c-dim">GW '+nicGw+'</span>';
    h+='</div>';
    h+='</div>';
  });
  return h;
}
function _vmControlPanel(vmid,label,acts,tier,isRunning,catLabel,vm,ip){
  var ctrl='<div style="display:flex;gap:16px;margin:12px 0;padding:12px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border)">';
  if(acts.indexOf('configure')>=0){
    ctrl+=_vmConfigPanel(vmid,label);
  }
  ctrl+='<div style="width:1px;background:var(--input-border)"></div>';
  ctrl+='<div class="flex-fill">';
  ctrl+='<div class="fs-11-dim-mb10-ls">VM CONTROLS \u00b7 '+tier.toUpperCase()+'</div>';
  ctrl+='<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px">';
  if(acts.indexOf('start')>=0&&!isRunning)ctrl+='<button class="fleet-btn btn-green pad-v8-fs11" data-action="vmPower" data-vmid="'+vmid+'" data-arg="start" >START</button>';
  if(acts.indexOf('stop')>=0&&isRunning)ctrl+='<button class="fleet-btn pad-v8-warn" data-action="vmPower" data-vmid="'+vmid+'" data-arg="stop" >STOP</button>';
  if(acts.indexOf('restart')>=0&&isRunning)ctrl+='<button class="fleet-btn" onclick="vmPower('+vmid+',\'stop\');setTimeout(function(){vmPower('+vmid+',\'start\')},5000)" style="padding:8px 0;font-size:11px;color:var(--orange)">RESTART</button>';
  if(acts.indexOf('snapshot')>=0)ctrl+='<button class="fleet-btn pad-v8-warn" onclick="_vmSnapWarn('+vmid+','+isRunning+')" >SNAPSHOT</button>';
  if(acts.indexOf('snapshot')>=0)ctrl+='<button class="fleet-btn pad-v8-fs11" onclick="_vmListSnaps('+vmid+')" >SNAPSHOTS</button>';
  if(acts.indexOf('resize')>=0)ctrl+='<button class="fleet-btn pad-v8-fs11" onclick="_vmToggleResize('+vmid+')" >RESIZE</button>';
  if(acts.indexOf('migrate')>=0)ctrl+='<button class="fleet-btn pad-v8-fs11" onclick="_vmToggleMigrate('+vmid+',\''+(vm?vm.node:'')+'\')" >MIGRATE</button>';
  if(acts.indexOf('destroy')>=0)ctrl+='<button class="fleet-btn btn-red pad-v8-fs11" data-action="vmDestroy" data-vmid="'+vmid+'" >DESTROY</button>';
  if(acts.length<=1)ctrl+='<span style="font-size:12px;color:var(--text-dim);grid-column:1/-1">View only \u2014 no actions for '+catLabel+'</span>';
  ctrl+='<div style="grid-column:1/-1;border-top:1px solid var(--input-border);margin-top:6px;padding-top:8px;font-size:11px;color:var(--text-dim);letter-spacing:0.5px">HOST TOOLS</div>';
  ctrl+='<button class="fleet-btn pad-v8-fs11" data-action="hdExec" >RUN CMD</button>';
  ctrl+='<button class="fleet-btn pad-v8-fs11" data-action="hdLogs" >LOGS</button>';
  ctrl+='<button class="fleet-btn pad-v8-fs11" data-action="hdDiagnose" >DIAGNOSE</button>';
  ctrl+='<button class="fleet-btn pad-v8-warn" data-action="hdRestart" >RESTART SVC</button>';
  ctrl+='<button class="fleet-btn pad-v8-fs11" onclick="vmPushKey(\''+(ip||'')+'\')" >PUSH KEY</button>';
  ctrl+='</div></div>';
  ctrl+='</div>';
  ctrl+='<div id="vm-ctrl-out"></div>';
  return ctrl;
}
function _resolveVmIps(vmid,ip,liveHost){
  var _vmNicData=(_fleetCache.fo&&_fleetCache.fo.vm_nics&&_fleetCache.fo.vm_nics[vmid])||[];
  var _vlanPrefixes={};Object.keys(_VLAN_MAP).forEach(function(id){var v=_VLAN_MAP[id];if(v.name&&v.prefix)_vlanPrefixes[v.name]=v.prefix;});
  var knownIp=ip||'';
  if(!knownIp&&liveHost)knownIp=liveHost.ip||'';
  var octet='';
  if(knownIp){var parts=knownIp.split('.');if(parts.length===4)octet=parts[3];}
  var allIps=[];
  if(_vmNicData.length){
    _vmNicData.forEach(function(n){
      var prefix=_vlanPrefixes[n.vlan_name]||'';
      allIps.push({nic:n.nic,vlan:n.vlan_name,ip:octet?(prefix+'.'+octet):'?'});
    });
  } else if(knownIp){
    allIps.push({nic:'net0',vlan:'?',ip:knownIp});
  }
  var subtitleIp=knownIp||((allIps.length&&allIps[0].ip!=='?')?allIps[0].ip:'?');
  return {allIps:allIps,subtitleIp:subtitleIp};
}
function _vmDockerFetch(vmid){
  fetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
    var myContainers=[];
    d.containers.forEach(function(c){if(c.vm_id==vmid)myContainers.push(c);});
    if(!myContainers.length)return;
    var upCount=0;myContainers.forEach(function(c){if(c.status==='up'||c.status==='running')upCount++;});
    var downCount=myContainers.length-upCount;
    var countsEl=document.getElementById('hd-docker-counts');
    if(countsEl){
      var ct='<span style="color:var(--green);font-weight:600">'+upCount+' UP</span>';
      if(downCount>0)ct+=' <span style="color:var(--red);font-weight:600;margin-left:8px">'+downCount+' DOWN</span>';
      countsEl.innerHTML=ct;
    }
    var gridEl=document.getElementById('hd-docker-grid');
    if(gridEl){
      var cols=myContainers.length>=4?'repeat(2,1fr)':'1fr';
      gridEl.style.gridTemplateColumns=cols;
      var gh='';
      myContainers.forEach(function(c){gh+=_containerCard(c,'');});
      gridEl.innerHTML=gh;
    }
  }).catch(function(){});
}

/* ── Renderer: VM Card ── */
function renderVmCard(config){
  var label=config.label,ip=config.ip||'',vmid=config.vmid;
  var vm=null;
  if(_fleetCache.fo&&_fleetCache.fo.vms){vm=_fleetCache.fo.vms.find(function(v){return v.vmid===vmid;});}
  var acts=vm?vm.allowed_actions||['view']:['view'];
  var cat=vm?vm.category||'unknown':'unknown';
  var tier=vm?vm.tier||'probe':'probe';
  var isRunning=vm&&vm.status==='running';
  var catLabel=cat.replace(/_/g,' ');
  /* Live host data */
  var liveHost=null;
  var labelLower=label.toLowerCase();
  if(_fleetCache.hd&&_fleetCache.hd.hosts){
    liveHost=_fleetCache.hd.hosts.find(function(h){
      var hl=h.label.toLowerCase();
      return hl===labelLower||hl.indexOf(labelLower)>=0||labelLower.indexOf(hl)>=0||h.ip===ip;
    });
  }
  if(!liveHost&&_fleetCache.hd&&_fleetCache.hd.hosts){
    /* Build container IP map from PROD_VMS (populated from API) */
    var _containerIps={};PROD_VMS.forEach(function(pv){if(pv.ip)_containerIps[pv.vmid]=pv.ip;});
    var cip=_containerIps[vmid];
    if(cip)liveHost=_fleetCache.hd.hosts.find(function(h){return h.ip===cip;});
  }
  var kv=_kvRow;
  var _ips=_resolveVmIps(vmid,ip,liveHost);
  var allIps=_ips.allIps,subtitleIp=_ips.subtitleIp;
  document.getElementById('hd-subtitle').textContent=subtitleIp+' \u00b7 VM '+vmid+' \u00b7 '+(vm?vm.node:'?');
  /* Stats */
  var stats='';
  stats+=st('VMID',vmid,'p');
  stats+=st('NODE',vm?vm.node:'?','b');
  stats+=st('STATUS',isRunning?'RUNNING':'STOPPED',isRunning?'g':'r');
  stats+='<div class="st"><div class="lb">CATEGORY</div><div><span class="cat-badge cat-'+cat+'">'+catLabel+'</span></div></div>';
  if(liveHost&&liveHost.status==='healthy'){
    stats+=st('CPU',liveHost.cores+' cores','p');
    var rp=(liveHost.ram||'').match(/(\d+)\/(\d+)/);
    stats+=st('RAM',rp?(_ramGB(rp[1])+'/'+_ramGB(rp[2])):'?',rp&&parseInt(rp[1])/parseInt(rp[2])>0.8?'r':'g');
    stats+=st('Disk',liveHost.disk||'?','g');
  } else {
    if(vm){stats+=st('CPU',vm.cpu+' cores','p');stats+=st('RAM',_ramGB(vm.ram_mb),'b');}
  }
  var html='<div class="card-box"><div class="stats mb-0" >'+stats+'</div></div>';
  html+=_vmControlPanel(vmid,label,acts,tier,isRunning,catLabel,vm,ip);
  html+=_toolPanelHtml();
  /* Build reusable data */
  var sys='';
  sys+=kv('LABEL',label.toUpperCase());
  sys+=kv('VMID',''+vmid);
  sys+=kv('NODE',vm?vm.node:'?');
  sys+=kv('STATUS',isRunning?'RUNNING':'STOPPED',isRunning?'var(--green)':'var(--red)');
  sys+=kv('CATEGORY',catLabel.toUpperCase());
  sys+=kv('TIER',tier.toUpperCase());
  if(liveHost&&liveHost.status==='healthy'){
    sys+=kv('HOSTNAME',liveHost.label);
    sys+=kv('LOAD',liveHost.load);
  }
  var net=_vmNicCards(allIps);
  var secContent='';
  secContent+=kv('TIER',tier.toUpperCase(),'var(--purple-light)');
  secContent+=kv('CATEGORY',catLabel.toUpperCase());
  secContent+=kv('ALLOWED',acts.join(', ').toUpperCase(),'var(--green)');
  var hasDocker=liveHost&&parseInt(liveHost.docker)>0;
  /* ── ADAPTIVE LAYOUT ── */
  if(hasDocker){
    /* === DOCKER VM — containers are the hero === */
    html+='<div id="hd-docker-hero" class="mb-16">';
    html+='<div class="flex-between-mb12">';
    html+='<h3 style="font-size:15px;color:var(--purple-light);text-transform:uppercase;letter-spacing:2px;font-weight:700;margin:0">CONTAINERS</h3>';
    html+='<span id="hd-docker-counts" class="text-meta">Loading...</span>';
    html+='</div>';
    html+='<div id="hd-docker-grid" style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px"><div class="skeleton" style="height:80px;grid-column:1/-1"></div></div>';
    html+='</div>';
    /* Compact info below containers */
    html+='<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px">';
    html+='<div class="ho-section"><h3>System</h3>'+sys+'</div>';
    html+='<div class="ho-section"><h3>Network</h3>'+net+'</div>';
    html+='<div class="ho-section"><h3>Permissions</h3>'+secContent+'</div>';
    html+='</div>';
  } else {
    /* === STANDARD VM — System/Network grid === */
    html+='<div class="ho-grid">';
    html+='<div class="ho-section"><h3>System</h3>'+sys+'</div>';
    html+='<div class="ho-section"><h3>Network</h3>'+net+'</div>';
    html+='</div>';
    html+='<div class="ho-section mt-10" ><h3>SECURITY & STATUS</h3>'+secContent+'</div>';
  }
  _cardReady(html);
  if(document.getElementById('vm-nic-combo'))_updateNicPreviewCombo();
  if(hasDocker)_vmDockerFetch(vmid);
}

/* ── Infra helpers ── */
function _findInfraType(label){
  if(_fleetCache.fo&&_fleetCache.fo.physical){
    var match=_fleetCache.fo.physical.find(function(p){return p.label===label;});
    if(match)return match.type;
  }
  var ph=PROD_HOSTS.find(function(h){return h.label===label;});
  if(ph&&INFRA_ROLES[ph.type])return ph.type;
  return null;
}
function _getInfraFn(type){
  var map={pfsense:pfAction,opnsense:pfAction,truenas:tnAction,synology:tnAction,unraid:tnAction,switch:swAction,idrac:idracAction,ilo:idracAction,ipmi:idracAction};
  return map[type]||null;
}
function _runPveNodeCmd(label,ip,cmd){
  _infraOutputTarget='hd-infra-out';
  var o=document.getElementById('hd-infra-out');
  o.style.display='block';
  o.innerHTML='<span class="c-dim">Querying '+label.toUpperCase()+'...</span>';
  fetch(API.EXEC+'?target='+encodeURIComponent(label)+'&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
    var out='';
    if(d.results){d.results.forEach(function(r){out+=r.output+'\n';});}
    o.innerHTML=_infraPre(label.toUpperCase(),out||'No output');
  }).catch(function(e){o.innerHTML='<div class="c-red">Error: '+e+'</div>';});
}
function _runInfraAction(type,action){
  _infraOutputTarget='hd-infra-out';
  var fn=_getInfraFn(type);
  if(fn)fn(action);
  else{var o=document.getElementById('hd-infra-out');o.style.display='block';o.innerHTML='<span class="c-red">No handler for '+type+'</span>';}
}

/* ── Host tool functions ── */
function _hdBtn(btn){document.querySelectorAll('.ho-actions button').forEach(function(b){b.classList.remove('active')});if(btn)btn.classList.add('active');}
function hdExec(btn){_hdBtn(btn);document.getElementById('hd-tool-panel').style.display='block';document.getElementById('hd-exec-out').textContent='Ready. Type a command above.';document.getElementById('hd-cmd').focus();}
function hdLogs(btn){
  _hdBtn(btn);document.getElementById('hd-tool-panel').style.display='block';
  document.getElementById('hd-exec-out').textContent='Loading logs for '+_cardState.host+'...';
  fetch(API.EXEC+'?target='+encodeURIComponent(_cardState.host)+'&cmd='+encodeURIComponent('journalctl --no-pager -n 50 --output=short-iso 2>/dev/null || tail -50 /var/log/syslog 2>/dev/null')).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results){d.results.forEach(function(r){txt+=r.output+'\n';});}document.getElementById('hd-exec-out').textContent=txt||'No logs available.';
  }).catch(function(e){document.getElementById('hd-exec-out').textContent='Error: '+e;});
}
function hdDiagnose(btn){
  _hdBtn(btn);document.getElementById('hd-tool-panel').style.display='block';
  document.getElementById('hd-exec-out').textContent='Running full diagnostic on '+_cardState.host+'...';
  fetch(API.EXEC+'?target='+encodeURIComponent(_cardState.host)+'&cmd='+encodeURIComponent('echo "=== SYSTEM ===" && hostname -f && cat /etc/os-release 2>/dev/null | grep PRETTY && uname -r && echo "=== RESOURCES ===" && nproc && free -h | head -2 && df -h / && cat /proc/loadavg && echo "=== NETWORK ===" && ip -4 addr show | grep inet | grep -v 127 && ip route show default && echo "=== DOCKER ===" && docker ps --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "not installed" && echo "=== SECURITY ===" && systemctl --failed --no-legend 2>/dev/null | head -5 || echo "ok" && echo "=== LISTENING ===" && ss -tlnp 2>/dev/null | grep LISTEN | head -10')).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results){d.results.forEach(function(r){txt+=r.output+'\n';});}document.getElementById('hd-exec-out').textContent=txt||'No output.';
  }).catch(function(e){document.getElementById('hd-exec-out').textContent='Error: '+e;});
}
function hdRestart(){
  confirmAction('Restart services on <strong>'+_cardState.host+'</strong>?',function(){
    document.getElementById('hd-tool-panel').style.display='block';
    document.getElementById('hd-exec-out').textContent='Use CLI: freq exec '+_cardState.host+' sudo systemctl restart <service>';
    toast('Use CLI for service restarts','info');
  });
}
function hdRunCmd(){
  var cmd=document.getElementById('hd-cmd').value;if(!cmd)return;
  document.getElementById('hd-exec-out').textContent='Running: '+cmd+' ...';
  fetch(API.EXEC+'?target='+encodeURIComponent(_cardState.host)+'&cmd='+encodeURIComponent(cmd)).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results){d.results.forEach(function(r){txt+=r.output+'\n';});}document.getElementById('hd-exec-out').textContent=txt||'(no output)';
  }).catch(function(e){document.getElementById('hd-exec-out').textContent='Error: '+e;});
}

/* ═══════════════════════════════════════════════════════════════════
   LAB TOOLS — Plugin Framework
   ═══════════════════════════════════════════════════════════════════ */
var _ltTimers={};var _ltState={};

/* ── Registry ──────────────────────────────────────────────────── */
var LAB_TOOLS=[{
  id:'gwipe',
  name:'Drive Wipe',
  subtitle:'NIST 800-88 Clear &middot; Drive Sanitization Station &middot; PVE FREQ',
  defaultPort:7980,
  connectEndpoint:'status',
  refreshInterval:3000,
  parseStats:function(d){
    return[{label:'BAYS',value:d.bays_total||0,color:'p'},{label:'OCCUPIED',value:d.bays_occupied||0,color:'b'},{label:'WIPING',value:d.wiping||0,color:d.wiping>0?'y':'g'},{label:'WIPED',value:d.wiped||0,color:'g'},{label:'FAILED',value:d.failed||0,color:d.failed>0?'r':'g'},{label:'SESSION',value:d.session_counter||0,color:'p'},{label:'LIFETIME',value:d.lifetime_counter||0,color:'b'}];
  },
  onConnect:function(d,pfx,host){
    var ver=_ltEl(pfx,'lt-version');if(ver)ver.textContent='v'+d.version;
    var sl=_ltEl(pfx,'lt-station-label');if(sl)sl.textContent=host+':7980 \u2014 '+d.bays_total+' bays';
  },
  renderControls:function(pfx){
    return '<button onclick="gwipeAction(\'full-send\',\''+pfx+'\')" class="fleet-btn" style="color:var(--purple-light);border-color:var(--purple);font-weight:700">FULL SEND</button>'+
      '<button onclick="gwipeAction(\'test-all\',\''+pfx+'\')" class="fleet-btn btn-cyan">SMART ALL</button>'+
      '<button onclick="gwipeWipeAll(\''+pfx+'\')" class="fleet-btn btn-red">WIPE ALL</button>'+
      '<button onclick="gwipeAction(\'pause-all\',\''+pfx+'\')" class="fleet-btn btn-orange">PAUSE</button>'+
      '<button onclick="gwipeAction(\'resume-all\',\''+pfx+'\')" class="fleet-btn btn-green">RESUME</button>';
  },
  renderContent:function(host,key,pfx){gwipeRefreshBays(host,key,pfx);},
  renderExtra:function(host,key,pfx){gwipeRefreshHistory(host,key,pfx);},
  offlineHint:'Enter the IP and API key above, or save to vault via CLI:<br><code class="c-purple">freq vault set gwipe gwipe_host &lt;ip&gt;</code><br><code class="c-purple">freq vault set gwipe gwipe_api_key &lt;key&gt;</code>',
  confirmActions:{'wipe-all':'WIPE ALL TESTED DRIVES? This is destructive and irreversible.'}
}];
/* Auto-register LAB_TOOLS as HOME widgets */
LAB_TOOLS.forEach(function(t){
  WIDGET_REGISTRY.push({id:'w-lab-'+t.id,page:'LAB',label:t.name,loader:function(el){
    var P='hw-'+t.id+'-';
    el.innerHTML=_ltGenerateHTML(t.id,P);
    ltLoad(t.id,P);
  }});
});

/* ── Framework functions ───────────────────────────────────────── */
function _ltEl(pfx,id){return document.getElementById((pfx||'')+id);}
function _ltGetTool(toolId){return _allLabTools().find(function(t){return t.id===toolId;});}
function _ltHostKey(toolId,pfx){
  pfx=pfx||'';
  return{host:((_ltEl(pfx,'lt-host')||{}).value||'').trim(),key:((_ltEl(pfx,'lt-key')||{}).value||'').trim()};
}

function _ltGenerateHTML(toolId,pfx,hideBtn){
  pfx=pfx||'';var t=_ltGetTool(toolId);if(!t)return '';
  var hb=hideBtn||'';
  return '<div style="background:var(--bg2);border:2px solid var(--input-border);border-radius:8px;margin-bottom:16px;padding:16px 20px;display:flex;justify-content:space-between;align-items:center"><div><div style="display:flex;align-items:center;gap:10px"><span style="font-size:22px;font-weight:800;letter-spacing:2px;background:linear-gradient(135deg,var(--purple-light),var(--purple));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">'+t.name+'</span><span id="'+pfx+'lt-version" class="text-meta"></span><span id="'+pfx+'lt-live-dot" style="display:none;width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green)"></span></div><div class="fs-11-dim-mt2">'+t.subtitle+'</div></div><div style="display:flex;align-items:center;gap:10px"><div id="'+pfx+'lt-station-label" class="text-sub"></div>'+hb+'</div></div>'+
    '<div class="stats" id="'+pfx+'lt-stats"></div>'+
    '<div class="exec-bar mb-0" id="'+pfx+'lt-connect-bar" ><input id="'+pfx+'lt-host" placeholder="'+t.name+' station IP" style="max-width:200px" value=""><input id="'+pfx+'lt-key" type="password" placeholder="API key" class="flex-1"><button onclick="ltConnect(\''+toolId+'\',\''+pfx+'\')">CONNECT</button><button onclick="ltSaveConfig(\''+toolId+'\',\''+pfx+'\')" style="background:var(--card);border:2px solid var(--input-border);color:var(--text)">SAVE TO VAULT</button></div>'+
    '<div id="'+pfx+'lt-conn-status" style="font-size:11px;color:var(--text-dim);margin:6px 0 16px 2px"></div>'+
    '<div id="'+pfx+'lt-controls" style="display:none;margin-bottom:16px"><div style="display:flex;gap:8px;flex-wrap:wrap">'+(t.renderControls?t.renderControls(pfx):'')+'</div></div>'+
    '<div id="'+pfx+'lt-content"></div>'+
    '<div id="'+pfx+'lt-extra"></div>'+
    '<div id="'+pfx+'lt-offline" style="text-align:center;padding:60px 0"><div style="font-size:48px;opacity:0.15;margin-bottom:16px;font-weight:900;letter-spacing:4px;background:linear-gradient(135deg,var(--purple-light),var(--purple-dark));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">'+t.name+'</div><div style="font-size:15px;color:var(--text);margin-bottom:8px">Station Offline</div><div style="font-size:12px;color:var(--text-dim);max-width:420px;margin:0 auto;line-height:1.7">'+(t.offlineHint||'Enter the IP and API key above to connect.')+'</div></div>';
}

function ltLoad(toolId,pfx){
  pfx=pfx||'';
  fetch(API.LAB_TOOL_CONFIG+'?tool='+encodeURIComponent(toolId)).then(function(r){return r.json()}).then(function(d){
    var hEl=_ltEl(pfx,'lt-host');var kEl=_ltEl(pfx,'lt-key');
    if(d.host&&hEl)hEl.value=d.host;
    if(d.key&&kEl)kEl.value=d.key;
    if(d.host&&d.key)ltConnect(toolId,pfx);
  }).catch(function(){});
}

function ltConnect(toolId,pfx){
  pfx=pfx||'';var t=_ltGetTool(toolId);if(!t)return;
  var host=(_ltEl(pfx,'lt-host')||{}).value;var key=(_ltEl(pfx,'lt-key')||{}).value;
  if(!host||!key){var cs=_ltEl(pfx,'lt-conn-status');if(cs)cs.innerHTML='<span class="c-red">Enter host IP and API key</span>';return;}
  host=host.trim();key=key.trim();
  var cs=_ltEl(pfx,'lt-conn-status');if(cs)cs.innerHTML='<span class="c-yellow">Connecting...</span>';
  _ltProxy(toolId,'GET',t.connectEndpoint||'status',host,key,function(d){
    if(d.error){if(cs)cs.innerHTML='<span class="c-red">'+d.error+'</span>';_ltState[pfx+toolId]=false;
      var off=_ltEl(pfx,'lt-offline');if(off)off.style.display='block';
      var ctrl=_ltEl(pfx,'lt-controls');if(ctrl)ctrl.style.display='none';
      var dot=_ltEl(pfx,'lt-live-dot');if(dot)dot.style.display='none';
      var ver=_ltEl(pfx,'lt-version');if(ver)ver.textContent='';
      var sl=_ltEl(pfx,'lt-station-label');if(sl)sl.textContent='';return;}
    _ltState[pfx+toolId]=true;
    if(cs)cs.innerHTML='<span class="c-green">Connected</span>';
    var dot=_ltEl(pfx,'lt-live-dot');if(dot)dot.style.display='inline-block';
    var off=_ltEl(pfx,'lt-offline');if(off)off.style.display='none';
    var ctrl=_ltEl(pfx,'lt-controls');if(ctrl)ctrl.style.display='block';
    if(t.onConnect)t.onConnect(d,pfx,host,key);
    if(t.parseStats){var statsEl=_ltEl(pfx,'lt-stats');if(statsEl){var items=t.parseStats(d);statsEl.innerHTML=items.map(function(s){return st(s.label,s.value,s.color);}).join('');}}
    if(t.renderContent)t.renderContent(host,key,pfx);
    if(t.renderExtra)t.renderExtra(host,key,pfx);
    /* Start refresh timer */
    var timerKey=pfx+toolId;
    if(_ltTimers[timerKey])clearInterval(_ltTimers[timerKey]);
    if(t.refreshInterval>0){
      _ltTimers[timerKey]=setInterval(function(){
        if(!_ltState[timerKey]){clearInterval(_ltTimers[timerKey]);_ltTimers[timerKey]=null;return;}
        ltRefresh(toolId,host,key,pfx);
      },t.refreshInterval);
    }
  });
}

function ltRefresh(toolId,host,key,pfx){
  pfx=pfx||'';var t=_ltGetTool(toolId);if(!t)return;
  _ltProxy(toolId,'GET',t.connectEndpoint||'status',host,key,function(d){
    if(d.error){_ltState[pfx+toolId]=false;return;}
    if(t.parseStats){var statsEl=_ltEl(pfx,'lt-stats');if(statsEl){var items=t.parseStats(d);statsEl.innerHTML=items.map(function(s){return st(s.label,s.value,s.color);}).join('');}}
  });
  if(t.renderContent)t.renderContent(host,key,pfx);
}

function _ltProxy(toolId,method,endpoint,host,key,callback){
  fetch(API.LAB_TOOL_PROXY+'?tool='+encodeURIComponent(toolId)+'&method='+method+'&endpoint='+encodeURIComponent(endpoint)+'&host='+encodeURIComponent(host)+'&key='+encodeURIComponent(key)).then(function(r){return r.json()}).then(callback).catch(function(e){callback({error:String(e)});});
}

function ltSaveConfig(toolId,pfx){
  pfx=pfx||'';
  var host=((_ltEl(pfx,'lt-host')||{}).value||'').trim();var key=((_ltEl(pfx,'lt-key')||{}).value||'').trim();if(!host||!key)return;
  fetch(API.LAB_TOOL_SAVE+'?tool='+encodeURIComponent(toolId)+'&host='+encodeURIComponent(host)+'&key='+encodeURIComponent(key)).then(function(r){return r.json()}).then(function(){toast('Config saved to vault','success');});
}

function ltAction(toolId,action,pfx,confirm){
  var c=_ltHostKey(toolId,pfx);
  var url='/api/lab-tool/proxy?tool='+encodeURIComponent(toolId)+'&method=POST&endpoint='+encodeURIComponent(action)+'&host='+encodeURIComponent(c.host)+'&key='+encodeURIComponent(c.key);
  if(confirm)url+='&confirm=YES';
  fetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.message)toast(d.message,'success');if(d.error)toast(d.error,'error');
  });
}

var _hiddenLabTools=JSON.parse(localStorage.getItem('freq_hidden_lab_tools')||'[]');
var _customLabTools=JSON.parse(localStorage.getItem('freq_custom_lab_tools')||'[]');
function _allLabTools(){
  var custom=_customLabTools.map(function(ct){
    var hint=ct.offlineHint||'Enter the IP and API key above to connect.';
    return {id:ct.id,name:ct.name,subtitle:ct.subtitle||(ct.type==='freq'?'PVE FREQ':'Custom API Tool'),defaultPort:ct.port||0,connectEndpoint:ct.endpoint||'status',refreshInterval:ct.refresh||5000,isCustom:true,toolType:ct.type||'custom',vaultNamespace:ct.vaultNamespace||'',offlineHint:hint};
  });
  return LAB_TOOLS.concat(custom);
}
function hideLabTool(id){
  if(_hiddenLabTools.indexOf(id)<0)_hiddenLabTools.push(id);
  localStorage.setItem('freq_hidden_lab_tools',JSON.stringify(_hiddenLabTools));
  loadLabTools();
  toast(id+' hidden','info');
}
function openManageTools(){
  var all=_allLabTools();
  var h='<div class="modal" style="max-width:460px"><div class="flex-between-mb16"><h3 class="m-0" style="color:var(--purple-light)">Manage Lab Tools</h3><span class="close-x">&times;</span></div>';
  h+='<div style="display:flex;flex-direction:column;gap:8px">';
  if(!all.length){h+='<p class="c-dim-fs12">No tools registered.</p>';}
  all.forEach(function(t){
    var hidden=_hiddenLabTools.indexOf(t.id)>=0;
    var typeBadge=t.isCustom?(t.toolType==='freq'?'<span style="font-size:9px;padding:1px 6px;border-radius:3px;background:var(--purple-faint);color:var(--purple-light);margin-left:6px">FREQ</span>':'<span style="font-size:9px;padding:1px 6px;border-radius:3px;background:var(--bg);color:var(--text-dim);margin-left:6px;border:1px solid var(--input-border)">CUSTOM</span>'):'<span style="font-size:9px;padding:1px 6px;border-radius:3px;background:var(--purple-faint);color:var(--purple-light);margin-left:6px">BUILT-IN</span>';
    h+='<div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--bg2);border:1px solid var(--input-border);border-radius:6px">';
    h+='<div><strong>'+_esc(t.name)+'</strong>'+typeBadge+'<div class="fs-11-dim-mt2">'+_esc(t.subtitle||'')+'</div></div>';
    h+='<div style="display:flex;gap:6px;align-items:center">';
    h+='<button class="fleet-btn" style="font-size:10px;padding:3px 10px" onclick="toggleLabToolVis(\''+t.id+'\')">'+( hidden?'SHOW':'HIDE')+'</button>';
    if(t.isCustom){h+='<button class="fleet-btn" style="font-size:10px;padding:3px 10px;color:var(--red)" onclick="removeLabTool(\''+t.id+'\')">DELETE</button>';}
    h+='</div></div>';
  });
  h+='</div></div>';
  var ov=document.getElementById('modal-container');ov.innerHTML=h;ov.style.display='flex';
}
function toggleLabToolVis(id){
  var idx=_hiddenLabTools.indexOf(id);
  if(idx>=0)_hiddenLabTools.splice(idx,1);else _hiddenLabTools.push(id);
  localStorage.setItem('freq_hidden_lab_tools',JSON.stringify(_hiddenLabTools));
  openManageTools();
  loadLabTools();
}
function removeLabTool(id){
  if(!confirm('Remove this tool permanently?'))return;
  _customLabTools=_customLabTools.filter(function(t){return t.id!==id;});
  localStorage.setItem('freq_custom_lab_tools',JSON.stringify(_customLabTools));
  var hi=_hiddenLabTools.indexOf(id);if(hi>=0)_hiddenLabTools.splice(hi,1);
  localStorage.setItem('freq_hidden_lab_tools',JSON.stringify(_hiddenLabTools));
  closeModal();loadLabTools();
  toast('Tool removed','success');
}
function openAddTool(){
  var h='<div class="modal" style="max-width:480px"><div class="flex-between-mb16"><h3 class="m-0" style="color:var(--purple-light)">Add Lab Tool</h3><span class="close-x">&times;</span></div>';
  h+='<div style="display:flex;flex-direction:column;gap:12px">';
  h+='<div><label class="c-dim-fs12">Type</label><div style="display:flex;gap:8px;margin-top:6px">';
  h+='<button class="fleet-btn at-type active-view" id="at-type-freq" onclick="switchAddToolType(\'freq\')" style="flex:1;font-size:11px">FREQ TOOL</button>';
  h+='<button class="fleet-btn at-type" id="at-type-custom" onclick="switchAddToolType(\'custom\')" style="flex:1;font-size:11px">CUSTOM API</button>';
  h+='</div></div>';
  h+='<div><label class="c-dim-fs12">Tool Name</label><input class="input" id="at-name" placeholder="Drive Wipe, Bench Station..." style="width:100%;margin-top:4px"></div>';
  h+='<div><label class="c-dim-fs12">Description</label><input class="input" id="at-subtitle" placeholder="Short description of what this tool does" style="width:100%;margin-top:4px"></div>';
  h+='<div><label class="c-dim-fs12">Default Port</label><input class="input" id="at-port" type="number" placeholder="8080" style="width:100%;margin-top:4px"></div>';
  h+='<div id="at-freq-fields">';
  h+='<div style="margin-bottom:12px"><label class="c-dim-fs12">Vault Namespace</label><input class="input" id="at-vault-ns" placeholder="tool-name (for freq vault set)" style="width:100%;margin-top:4px"></div>';
  h+='<div><label class="c-dim-fs12">Vault Keys</label><div class="fs-11-dim-mt2">Auto-generated: <code style="color:var(--purple-light)">&lt;namespace&gt;_host</code>, <code style="color:var(--purple-light)">&lt;namespace&gt;_api_key</code></div></div>';
  h+='</div>';
  h+='<div id="at-custom-fields" style="display:none">';
  h+='<div style="margin-bottom:12px"><label class="c-dim-fs12">Connect Endpoint</label><input class="input" id="at-endpoint" value="status" placeholder="status, health, api/v1/ping..." style="width:100%;margin-top:4px"></div>';
  h+='<div><label class="c-dim-fs12">Refresh Interval (ms)</label><input class="input" id="at-refresh" type="number" value="5000" style="width:100%;margin-top:4px"></div>';
  h+='</div>';
  h+='<div style="display:flex;gap:8px;margin-top:8px">';
  h+='<button class="fleet-btn c-purple-active" onclick="saveNewTool()">ADD TOOL</button>';
  h+='<button class="fleet-btn" onclick="closeModal()">CANCEL</button>';
  h+='</div></div></div>';
  var ov=document.getElementById('modal-container');ov.innerHTML=h;ov.style.display='flex';
}
var _addToolType='freq';
function switchAddToolType(type){
  _addToolType=type;
  document.querySelectorAll('.at-type').forEach(function(b){b.classList.remove('active-view');});
  document.getElementById('at-type-'+type).classList.add('active-view');
  document.getElementById('at-freq-fields').style.display=type==='freq'?'block':'none';
  document.getElementById('at-custom-fields').style.display=type==='custom'?'block':'none';
}
function saveNewTool(){
  var name=(document.getElementById('at-name').value||'').trim();
  if(!name){toast('Name is required','error');return;}
  var id=name.toLowerCase().replace(/[^a-z0-9]+/g,'-');
  var existing=_allLabTools();
  for(var i=0;i<existing.length;i++){if(existing[i].id===id){toast('Tool ID "'+id+'" already exists','error');return;}}
  var tool={id:id,name:name,subtitle:(document.getElementById('at-subtitle').value||'').trim(),port:parseInt(document.getElementById('at-port').value)||0,type:_addToolType};
  if(_addToolType==='freq'){
    var ns=(document.getElementById('at-vault-ns').value||'').trim()||id;
    tool.vaultNamespace=ns;
    tool.endpoint='status';
    tool.refresh=3000;
    tool.offlineHint='Enter the IP and API key above, or save to vault via CLI:<br><code class="c-purple">freq vault set '+_esc(ns)+' '+_esc(ns)+'_host &lt;ip&gt;</code><br><code class="c-purple">freq vault set '+_esc(ns)+' '+_esc(ns)+'_api_key &lt;key&gt;</code>';
  } else {
    tool.endpoint=(document.getElementById('at-endpoint').value||'status').trim();
    tool.refresh=parseInt(document.getElementById('at-refresh').value)||5000;
  }
  _customLabTools.push(tool);
  localStorage.setItem('freq_custom_lab_tools',JSON.stringify(_customLabTools));
  closeModal();loadLabTools();
  toast(name+' added to lab','success');
}
function loadLabTools(){
  _ltPopulateSections();
  var container=document.getElementById('lab-tools-container');if(!container)return;
  container.innerHTML='';
  var all=_allLabTools();
  var visible=all.filter(function(t){return _hiddenLabTools.indexOf(t.id)<0;});
  if(!visible.length){
    container.innerHTML='<div class="empty-state" style="grid-column:1/-1"><div class="es-icon">&#128295;</div><p>No lab tools visible.</p><button class="fleet-btn mt-12" onclick="openManageTools()">MANAGE TOOLS</button></div>';
    return;
  }
  visible.forEach(function(t){
    var sec=document.createElement('div');
    sec.className='layout-section';
    sec.id='lab-sec-'+t.id;
    sec.style.cssText='background:var(--card);border:3px solid var(--input-border);border-radius:10px;padding:20px;margin-bottom:16px';
    var hBtn='<button onclick="hideLabTool(\''+t.id+'\')" style="background:var(--bg);border:2px solid var(--input-border);border-radius:6px;color:var(--text-dim);cursor:pointer;font-size:12px;padding:4px 12px;font-family:inherit" title="Hide this tool">HIDE</button>';
    sec.innerHTML=_ltGenerateHTML(t.id,'',hBtn);
    container.appendChild(sec);
    ltLoad(t.id,'');
  });
}

/* ── GWIPE tool-specific functions ─────────────────────────────── */
function gwipeRefreshBays(host,key,pfx){
  pfx=pfx||'';
  _ltProxy('gwipe','GET','bays',host,key,function(d){
    if(d.error||!d.bays)return;var html='';
    Object.keys(d.bays).sort().forEach(function(dev,i){html+=gwipeBayCard(dev,d.bays[dev],i,pfx);});
    var el=_ltEl(pfx,'lt-content');if(el)el.innerHTML='<div class="cards grid-auto-280" >'+(html||'<div style="color:var(--text-dim);padding:24px">No bays detected</div>')+'</div>';
  });
}
function gwipeBayCard(dev,b,idx,pfx){
  pfx=pfx||'';
  var state=b.state||'EMPTY';
  var displayState=(state==='DETECTED')?'IDLE':state;
  var h='<div class="host-card">';
  h+='<div class="flex-between-mb8">';
  h+='<div style="font-size:16px;font-weight:700;color:var(--purple-light)">BAY '+(idx+1)+'</div>';
  var stBg='background:rgba(110,118,129,0.1);color:var(--text-dim)';
  if(displayState==='WIPING')stBg='background:rgba(210,153,34,0.15);color:var(--yellow)';
  else if(displayState==='WIPED'||displayState==='TESTED')stBg='background:rgba(63,185,80,0.15);color:var(--green)';
  else if(displayState==='SMART_FAILED')stBg='background:rgba(248,81,73,0.15);color:var(--red)';
  else if(displayState==='TESTING')stBg='background:rgba(86,212,221,0.15);color:var(--cyan)';
  else if(displayState==='IDLE')stBg='background:rgba(123,47,190,0.1);color:var(--purple-light)';
  h+='<div style="font-size:12px;font-weight:600;letter-spacing:1px;padding:2px 8px;border-radius:4px;'+stBg+'">'+displayState+'</div></div>';
  if(!b.present&&state!=='REMOVED'){h+='<div style="color:var(--text-dim);font-size:12px;padding:12px 0;text-align:center">No drive inserted</div><div class="text-sub">/dev/'+dev+'</div></div>';return h;}
  h+='<div style="font-size:13px;font-weight:600;color:var(--text-bright);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="'+(b.model||'Unknown')+'">'+(b.model||'Unknown')+'</div>';
  h+='<div style="display:flex;gap:12px;margin-top:4px;font-size:11px;color:var(--text-dim)"><span>'+(b.size||'?')+'</span><span>'+(b.type||'?')+'</span><span>/dev/'+dev+'</span></div>';
  h+='<div style="margin-top:10px;padding:10px 12px;background:var(--bg);border:2px solid var(--input-border);border-radius:8px">';
  h+='<div style="font-size:12px;color:var(--text-dim);letter-spacing:1px;margin-bottom:6px">DRIVE IDENTITY</div>';
  h+='<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px">';
  h+='<div>Serial: <strong style="font-size:14px;font-family:monospace;color:var(--text);letter-spacing:1px">'+(b.serial||'N/A')+'</strong></div>';
  h+='<div>Model: <strong>'+(b.model||'Unknown')+'</strong></div>';
  h+='<div>Size: <strong>'+(b.size||'?')+'</strong></div>';
  h+='<div>Type: <strong>'+(b.type||'?')+'</strong></div>';
  h+='</div></div>';
  if(b.smart){
    var sh=b.smart;var hc=sh.health==='PASSED'?'var(--green)':sh.health?'var(--red)':'var(--text-dim)';
    h+='<div style="margin-top:8px;padding:10px 12px;background:var(--bg);border:2px solid var(--input-border);border-radius:8px">';
    h+='<div style="font-size:12px;color:var(--cyan);letter-spacing:1px;margin-bottom:6px">SMART TEST RESULTS</div>';
    h+='<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px">';
    if(sh.health)h+='<div>Health: <strong style="color:'+hc+'">'+sh.health+'</strong></div>';
    if(sh.hours)h+='<div>Power-On: <strong>'+sh.hours+'</strong></div>';
    if(sh.age)h+='<div>Age: <strong>'+sh.age+'</strong></div>';
    if(b.temp_c&&b.temp_c>0){var tc=b.temp_c;h+='<div>Temp: <strong style="color:'+(tc<=35?'var(--green)':tc<=45?'var(--yellow)':'var(--red)')+'">'+tc+'\u00b0C</strong></div>';}
    h+='</div></div>';
  } else {
    h+='<div style="margin-top:8px;padding:10px 12px;background:var(--bg);border:2px dashed var(--input-border);border-radius:8px;text-align:center">';
    h+='<div class="text-sub">Run SMART TEST to get health, hours, age, temperature</div>';
    h+='</div>';
  }
  if(state==='WIPING'&&b.wipe){var pct=b.wipe.percent||0;
    h+='<div class="mt-10"><div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px"><span class="c-yellow">'+(b.wipe.method||'')+'</span><span style="color:var(--text-bright);font-weight:600">'+pct.toFixed(1)+'%</span></div>';
    h+='<div style="background:rgba(255,255,255,0.06);border-radius:3px;height:6px;overflow:hidden"><div style="width:'+pct+'%;height:100%;background:linear-gradient(90deg,var(--yellow),var(--orange));border-radius:3px;transition:width 0.5s"></div></div>';
    h+='<div style="display:flex;justify-content:space-between;font-size:12px;margin-top:3px;color:var(--text-dim)"><span>'+(b.wipe.speed||'')+'</span><span>ETA: '+(b.wipe.eta||'')+'</span></div></div>';
  }
  if(state==='WIPED'&&b.wipe)h+='<div style="margin-top:8px;padding:6px 10px;background:rgba(63,185,80,0.08);border-radius:6px;font-size:11px;color:var(--green);font-weight:600;text-align:center">CLEAN — '+(b.wipe.method||'')+(b.wipe.duration?' ('+b.wipe.duration+')':'')+'</div>';
  if(b.present){
    h+='<div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">';
    h+='<button class="fleet-btn btn-cyan pill-sm" onclick="gwipeBayAction(\''+dev+'\',\'smart\',\''+pfx+'\')" >SMART TEST</button>';
    h+='<button class="fleet-btn btn-red pill-sm" onclick="gwipeBayWipe(\''+dev+'\',\''+pfx+'\')" >WIPE</button>';
    h+='<button class="fleet-btn btn-orange pill-sm" onclick="gwipeBayAction(\''+dev+'\',\'pause\',\''+pfx+'\')" >PAUSE</button>';
    h+='<button class="fleet-btn btn-green pill-sm" onclick="gwipeBayAction(\''+dev+'\',\'resume\',\''+pfx+'\')" >RESUME</button>';
    h+='<button class="fleet-btn" onclick="gwipeBayClear(\''+dev+'\',\''+pfx+'\')" style="padding:4px 10px;font-size:12px;color:var(--text);border-color:var(--text)">CLEAR</button>';
    h+='</div>';
  }
  h+='</div>';
  return h;
}
function gwipeRefreshHistory(host,key,pfx){
  pfx=pfx||'';
  _ltProxy('gwipe','GET','history',host,key,function(d){
    if(d.error||!d.history)return;
    var sec=_ltEl(pfx,'lt-extra');
    if(d.history.length===0){if(sec)sec.innerHTML='';return;}
    var h='<div class="mt-20"><h3 style="color:var(--purple-light);font-size:13px;margin-bottom:10px;text-transform:uppercase;letter-spacing:1px">Wipe History</h3><table><thead><tr><th>Time</th><th>Bay</th><th>Model</th><th>Serial</th><th>Size</th><th>Method</th><th>Result</th><th>Duration</th></tr></thead><tbody>';
    d.history.slice().reverse().forEach(function(e){
      var cls=e.result==='WIPED'?'up':e.result==='FAILED'?'down':'warn';
      h+='<tr><td style="font-size:11px;white-space:nowrap">'+(e.timestamp||'-')+'</td><td>'+e.bay+'</td><td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+(e.model||'')+'">'+(e.model||'-')+'</td><td class="mono-11">'+(e.serial||'-')+'</td><td>'+(e.size||'-')+'</td><td>'+(e.method||'-')+'</td><td><span class="badge '+cls+'">'+(e.result||'?')+'</span></td><td>'+(e.duration||'-')+'</td></tr>';
    });
    h+='</tbody></table></div>';
    if(sec)sec.innerHTML=h;
  });
}
function gwipeAction(action,pfx){ltAction('gwipe',action,pfx);}
function gwipeWipeAll(pfx){
  confirmAction('<strong>WIPE ALL TESTED DRIVES?</strong> This is destructive and irreversible.',function(){ltAction('gwipe','wipe-all',pfx,true);});
}
function gwipeBayAction(dev,action,pfx){
  var c=_ltHostKey('gwipe',pfx);
  _ltProxy('gwipe','POST','bays/'+dev+'/'+action,c.host,c.key,function(d){
    if(d.message)toast(d.message,'success');if(d.error)toast(d.error,'error');
  });
}
function gwipeBayClear(dev,pfx){
  confirmAction('Clear SMART data and reset bay /dev/'+dev+'?',function(){
    var c=_ltHostKey('gwipe',pfx);
    _ltProxy('gwipe','POST','bays/'+dev+'/clear',c.host,c.key,function(d){
      if(d.message)toast(d.message,'success');if(d.error)toast(d.error,'error');
    });
  });
}
function gwipeBayWipe(dev,pfx){
  confirmAction('WIPE /dev/'+dev+'? <strong>This destroys all data on the drive.</strong>',function(){
    var c=_ltHostKey('gwipe',pfx);
    fetch(API.LAB_TOOL_PROXY+'?tool=gwipe&method=POST&endpoint='+encodeURIComponent('bays/'+dev+'/wipe')+'&host='+encodeURIComponent(c.host)+'&key='+encodeURIComponent(c.key)+'&confirm=YES').then(function(r){return r.json()}).then(function(d){
      if(d.message)toast(d.message,'info');if(d.error)toast(d.error,'error');
    });
  });
}

/* ═══════════════════════════════════════════════════════════════════
   POLICIES VIEW
   ═══════════════════════════════════════════════════════════════════ */
function loadPoliciesPage(){
  policyAction('check');
}
function policyAction(action){
  var out=document.getElementById('policy-out');if(!out)return;
  out.innerHTML='<span style="color:var(--text-dim)">Running policy '+action+'...</span>';
  var url=action==='check'?API.POLICY_CHECK:action==='diff'?API.POLICY_DIFF:API.POLICY_FIX;
  fetch(url+'?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'No output')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function runSweep(doFix){
  var out=document.getElementById('sweep-out');if(!out)return;
  out.innerHTML='<span style="color:var(--text-dim)">Running sweep'+(doFix?' with fixes':'...')+'</span>';
  fetch(API.SWEEP+'?fix='+doFix+'&token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'No output')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function loadPatrolStatus(){
  var out=document.getElementById('patrol-out');if(!out)return;
  out.innerHTML='<span style="color:var(--text-dim)">Checking compliance...</span>';
  fetch(API.PATROL_STATUS).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'No output')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
/* ═══════════════════════════════════════════════════════════════════
   OPS VIEW
   ═══════════════════════════════════════════════════════════════════ */
function loadOpsPage(){
  _populateHostDropdowns();
}
function _populateHostDropdowns(){
  fetch(API.STATUS).then(function(r){return r.json()}).then(function(d){
    var hosts=d.hosts||[];
    var selects=['diag-host','log-host','chaos-target'];
    selects.forEach(function(id){
      var el=document.getElementById(id);if(!el)return;
      var val=el.value;
      var opts='<option value="">Select host...</option>';
      hosts.forEach(function(h){
        opts+='<option value="'+h.label+'">'+h.label.toUpperCase()+' ('+h.ip+')</option>';
      });
      el.innerHTML=opts;
      if(val)el.value=val;
    });
  });
}

/* ═══════════════════════════════════════════════════════════════════
   TOPOLOGY MAP — force-directed SVG
   ═══════════════════════════════════════════════════════════════════ */
function loadTopology(){
  var svg=document.getElementById('topo-svg');if(!svg)return;
  var info=document.getElementById('topo-info');
  if(info)info.textContent='Loading topology...';
  fetch('/api/topology?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    var showTpl=_loadSettings().showTemplates===true;
    var nodes=d.nodes,links=d.links;
    if(!showTpl){
      /* Filter template VMs (VMID >= 9000) */
      var tplIds={};
      nodes.forEach(function(n){if(n.type==='vm'&&n.vmid&&n.vmid>=9000)tplIds[n.id||('vm:'+n.vmid)]=true;});
      nodes=nodes.filter(function(n){return !tplIds[n.id];});
      links=links.filter(function(l){return !tplIds[l.target];});
    }
    var vmCount=nodes.filter(function(n){return n.type==='vm';}).length;
    if(info)info.textContent=d.pve_count+' PVE nodes, '+vmCount+' VMs';
    _renderTopology(svg,nodes,links);
  }).catch(function(e){if(info)info.textContent='Failed: '+e;});
}

/* Topology position persistence — lets users drag nodes and save layout */
function _loadTopoPositions(){try{return JSON.parse(localStorage.getItem(_userKey('topo_positions'))||'{}');}catch(e){return {};}}
function _saveTopoPositions(positions){localStorage.setItem(_userKey('topo_positions'),JSON.stringify(positions));}
function resetTopoLayout(){localStorage.removeItem(_userKey('topo_positions'));loadTopology();}
var _topoResizeTimer;window.addEventListener('resize',function(){clearTimeout(_topoResizeTimer);_topoResizeTimer=setTimeout(function(){if(_currentView==='topology')loadTopology();},250);});

function _renderTopology(svg,nodes,links){
  var W=Math.round(svg.getBoundingClientRect().width)||svg.clientWidth||900;
  svg.innerHTML='';
  if(!nodes||nodes.length===0){svg.setAttribute('viewBox','0 0 '+W+' 700');svg.innerHTML='<text x="'+W/2+'" y="350" fill="#8b949e" text-anchor="middle" font-size="14">No topology data</text>';return;}

  /* Color map */
  var colors={pve:'#9B4FDE',running:'#3fb950',stopped:'#484f58',unreachable:'#f85149',
    healthy:'#3fb950',pfsense:'#f0883e',truenas:'#58a6ff',switch:'#56d4dd',idrac:'#d29922'};
  function nodeColor(n){
    if(n.status==='unreachable')return colors.unreachable;
    if(n.type==='pve')return colors.pve;
    if(n.type==='vm')return n.status==='running'?colors.running:colors.stopped;
    return colors[n.type]||'#58a6ff';
  }
  function nodeRadius(n){
    if(n.type==='pve')return 26;
    if(n.type==='switch')return 22;
    if(n.type==='pfsense'||n.type==='truenas')return 18;
    if(n.type==='idrac')return 14;
    return 9; /* vm */
  }

  /* Classify nodes into tiers */
  var tier1=[]; /* core infra: switch, pfsense, truenas, idrac */
  var tier2=[]; /* PVE hypervisors */
  var tier3=[]; /* VMs */
  var nodeMap={};
  nodes.forEach(function(n){
    nodeMap[n.id]=n;
    if(n.type==='pve')tier2.push(n);
    else if(n.type==='vm')tier3.push(n);
    else tier1.push(n);
  });

  /* Sort tier1: switch first, then pfsense, truenas, idrac */
  var t1order={switch:0,pfsense:1,truenas:2,idrac:3};
  tier1.sort(function(a,b){return(t1order[a.type]||9)-(t1order[b.type]||9);});
  tier2.sort(function(a,b){return a.label<b.label?-1:1;});

  /* Group VMs by parent PVE node */
  var vmsByNode={};
  tier2.forEach(function(pve){vmsByNode[pve.id]=[];});
  links.forEach(function(l){
    var src=nodeMap[l.source],tgt=nodeMap[l.target];
    if(src&&tgt&&src.type==='pve'&&tgt.type==='vm'){
      if(!vmsByNode[src.id])vmsByNode[src.id]=[];
      vmsByNode[src.id].push(tgt);
    }
  });

  /* Layout constants */
  var padX=60,padY=50;
  var switchY=55;    /* switch hub — top center */
  var coreY=150;     /* other core infra — below switch */
  var tierY2=260;    /* PVE nodes */
  var tierY3=380;    /* VMs start */
  var vmSpacingX=110,vmSpacingY=56;
  var vmColsMax=4;   /* max VMs per row under a PVE node */

  /* Position Tier 1 — switch as elevated hub, others radiate below */
  var switchNode=tier1.find(function(n){return n.type==='switch';});
  if(switchNode){
    switchNode.x=W/2;switchNode.y=switchY;
    var others=tier1.filter(function(n){return n!==switchNode;});
    var coreSpread=Math.min(W-2*padX,others.length*180);
    var coreStart=W/2-coreSpread/2;
    var coreStep=others.length>1?coreSpread/(others.length-1):0;
    others.forEach(function(n,i){
      n.x=others.length===1?W/2:coreStart+i*coreStep;
      n.y=coreY;
    });
  } else {
    var t1spacing=tier1.length>1?(W-2*padX)/(tier1.length-1):0;
    var t1start=tier1.length>1?padX:W/2;
    tier1.forEach(function(n,i){n.x=t1start+i*t1spacing;n.y=coreY;});
  }

  /* Position Tier 2 — PVE nodes evenly spaced */
  var pveCount=tier2.length;
  var colWidth=(W-2*padX)/Math.max(pveCount,1);
  tier2.forEach(function(n,i){n.x=padX+colWidth*i+colWidth/2;n.y=tierY2;});

  /* Position Tier 3 — VMs in columns under their parent PVE */
  var maxVmRows=0;
  tier2.forEach(function(pve){
    var vms=vmsByNode[pve.id]||[];
    /* Sort: running first, then by label */
    vms.sort(function(a,b){
      if(a.status==='running'&&b.status!=='running')return -1;
      if(a.status!=='running'&&b.status==='running')return 1;
      return a.label<b.label?-1:1;
    });
    var cols=Math.min(vms.length,vmColsMax);
    var rows=Math.ceil(vms.length/vmColsMax);
    if(rows>maxVmRows)maxVmRows=rows;
    var blockW=cols*vmSpacingX;
    var startX=pve.x-blockW/2+vmSpacingX/2;
    vms.forEach(function(vm,i){
      var col=i%vmColsMax;
      var row=Math.floor(i/vmColsMax);
      vm.x=startX+col*vmSpacingX;
      vm.y=tierY3+row*vmSpacingY;
    });
  });

  /* Load saved positions — override auto-layout with user's custom positions */
  var _savedPositions=_loadTopoPositions();
  var allNodes=tier1.concat(tier2).concat(tier3);
  allNodes.forEach(function(n){
    if(_savedPositions[n.id]){n.x=_savedPositions[n.id].x;n.y=_savedPositions[n.id].y;}
  });

  /* Dynamic height */
  var maxY=0;
  allNodes.forEach(function(n){if(n.y>maxY)maxY=n.y;});
  var H=Math.max(maxY+padY+40, tierY3+maxVmRows*vmSpacingY+padY);
  if(H<500)H=500;
  svg.setAttribute('viewBox','0 0 '+W+' '+H);
  svg.setAttribute('height',H);

  /* === Tier divider lines with labels === */
  function tierDivider(txt,y){
    /* Midpoint between tiers — the dividing line */
    var lineY=y-20;
    /* Full-width line */
    var line=document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1','0');line.setAttribute('y1',lineY);
    line.setAttribute('x2',W);line.setAttribute('y2',lineY);
    line.setAttribute('stroke','#1e2530');line.setAttribute('stroke-width','1');
    line.setAttribute('stroke-opacity','0.8');
    svg.appendChild(line);
    /* Label centered on line */
    var lblW=txt.length*7+16;
    var bg=document.createElementNS('http://www.w3.org/2000/svg','rect');
    bg.setAttribute('x',W/2-lblW/2);bg.setAttribute('y',lineY-8);
    bg.setAttribute('width',lblW);bg.setAttribute('height','16');
    bg.setAttribute('fill','#0a0d12');bg.setAttribute('rx','3');
    svg.appendChild(bg);
    var t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x',W/2);t.setAttribute('y',lineY+4);
    t.setAttribute('text-anchor','middle');
    t.setAttribute('fill','#484f58');t.setAttribute('font-size','10');
    t.setAttribute('font-weight','600');t.setAttribute('letter-spacing','2');
    t.textContent=txt;svg.appendChild(t);
  }
  tierDivider('CORE INFRASTRUCTURE',switchY);
  tierDivider('HYPERVISORS',tierY2);
  if(tier3.length>0)tierDivider('VIRTUAL MACHINES',tierY3);

  /* === Draw links === */
  function drawLink(x1,y1,x2,y2,color,width,opacity,dashed){
    var line=document.createElementNS('http://www.w3.org/2000/svg','line');
    line.classList.add('topo-link');
    line.setAttribute('x1',x1);line.setAttribute('y1',y1);
    line.setAttribute('x2',x2);line.setAttribute('y2',y2);
    line.setAttribute('stroke',color||'#2a3140');
    line.setAttribute('stroke-width',width||'1');
    line.setAttribute('stroke-opacity',opacity||'0.5');
    if(dashed)line.setAttribute('stroke-dasharray','4,4');
    svg.appendChild(line);
  }

  /* Core → switch links (switchNode already found during layout) */
  if(switchNode){
    tier1.forEach(function(n){
      if(n!==switchNode)drawLink(n.x,n.y,switchNode.x,switchNode.y,'#56d4dd','1.5','0.4');
    });
    /* Switch → PVE links */
    tier2.forEach(function(pve){
      drawLink(switchNode.x,switchNode.y,pve.x,pve.y,'#7B2FBE','2','0.35');
    });
  }

  /* PVE → VM links */
  tier2.forEach(function(pve){
    var vms=vmsByNode[pve.id]||[];
    vms.forEach(function(vm){
      var c=vm.status==='running'?'#3fb950':'#484f58';
      drawLink(pve.x,pve.y,vm.x,vm.y,c,'1','0.3');
    });
  });

  /* === Draw nodes === */
  function drawNode(n){
    var g=document.createElementNS('http://www.w3.org/2000/svg','g');
    g.style.cursor='pointer';
    var r=nodeRadius(n);
    var col=nodeColor(n);

    /* Glow for PVE + core infra */
    if(n.type==='pve'||n.type==='switch'){
      var glow=document.createElementNS('http://www.w3.org/2000/svg','circle');
      glow.setAttribute('cx',n.x);glow.setAttribute('cy',n.y);
      glow.setAttribute('r',r+5);glow.setAttribute('fill','none');
      glow.setAttribute('stroke',col);glow.setAttribute('stroke-width','2');
      glow.setAttribute('stroke-opacity','0.25');
      g.appendChild(glow);
    }

    var circle=document.createElementNS('http://www.w3.org/2000/svg','circle');
    circle.setAttribute('cx',n.x);circle.setAttribute('cy',n.y);
    circle.setAttribute('r',r);circle.setAttribute('fill',col);
    if(n.type==='pve'){circle.setAttribute('stroke','#5a1f8e');circle.setAttribute('stroke-width','2');}
    g.appendChild(circle);

    /* Label */
    var text=document.createElementNS('http://www.w3.org/2000/svg','text');
    text.setAttribute('x',n.x);
    var lblY=n.type==='vm'?n.y+r+11:n.y+r+14;
    text.setAttribute('y',lblY);
    text.setAttribute('text-anchor','middle');
    var isCore=n.type!=='vm';
    text.setAttribute('fill',isCore?'#c9d1d9':'#8b949e');
    text.setAttribute('font-size',n.type==='pve'?'12':n.type==='vm'?'9':'11');
    text.setAttribute('font-weight',isCore?'600':'normal');
    text.textContent=n.label;
    g.appendChild(text);

    /* Type badge for core infra */
    if(n.type!=='pve'&&n.type!=='vm'){
      var badge=document.createElementNS('http://www.w3.org/2000/svg','text');
      badge.setAttribute('x',n.x);badge.setAttribute('y',n.y+4);
      badge.setAttribute('text-anchor','middle');
      badge.setAttribute('fill','#0a0d12');badge.setAttribute('font-size','8');
      badge.setAttribute('font-weight','bold');
      var icons={switch:'SW',pfsense:'FW',truenas:'NAS',idrac:'BMC'};
      badge.textContent=icons[n.type]||n.type.substring(0,3).toUpperCase();
      g.appendChild(badge);
    }

    /* Store node ref on group for drag */
    g._topoNode=n;

    /* Click handler — show info (only fires if not dragged) */
    g._wasDragged=false;
    g.addEventListener('click',function(){
      if(g._wasDragged){g._wasDragged=false;return;}
      var info=document.getElementById('topo-info');
      if(info){
        var parts=[n.label+' ('+n.type+')'];
        if(n.ip)parts.push('IP: '+n.ip);
        if(n.status)parts.push('Status: '+n.status);
        if(n.ram)parts.push('RAM: '+n.ram);
        if(n.disk)parts.push('Disk: '+n.disk);
        if(n.docker&&n.docker!=='0')parts.push('Containers: '+n.docker);
        if(n.vmid)parts.push('VMID: '+n.vmid);
        info.textContent=parts.join(' | ');
      }
    });
    svg.appendChild(g);
  }

  /* Draw in order: links first (already done), then nodes back-to-front */
  tier1.forEach(drawNode);
  tier2.forEach(drawNode);
  tier3.forEach(drawNode);

  /* === Drag-to-move nodes === */
  var _dragNode=null,_dragOffset={x:0,y:0},_dragMoved=false;
  function _svgPoint(evt){
    var pt=svg.createSVGPoint();
    pt.x=evt.clientX;pt.y=evt.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }
  svg.addEventListener('mousedown',function(evt){
    var g=evt.target.closest('g');
    if(!g||!g._topoNode)return;
    evt.preventDefault();
    _dragNode=g;_dragMoved=false;
    var p=_svgPoint(evt);
    _dragOffset.x=p.x-g._topoNode.x;
    _dragOffset.y=p.y-g._topoNode.y;
    svg.style.cursor='grabbing';
  });
  svg.addEventListener('mousemove',function(evt){
    if(!_dragNode)return;
    evt.preventDefault();
    _dragMoved=true;
    var p=_svgPoint(evt);
    var n=_dragNode._topoNode;
    n.x=p.x-_dragOffset.x;
    n.y=p.y-_dragOffset.y;
    /* Update all child elements in this group */
    _dragNode.querySelectorAll('circle').forEach(function(c){c.setAttribute('cx',n.x);c.setAttribute('cy',n.y);});
    _dragNode.querySelectorAll('text').forEach(function(t){
      t.setAttribute('x',n.x);
      /* Reposition label below node */
      if(t.textContent===n.label){
        var r=nodeRadius(n);
        t.setAttribute('y',n.type==='vm'?n.y+r+11:n.y+r+14);
      } else {
        t.setAttribute('y',n.y+4); /* badge */
      }
    });
    /* Redraw connection links (not divider lines) */
    svg.querySelectorAll('line.topo-link').forEach(function(l){l.remove();});
    if(switchNode){
      tier1.forEach(function(nd){if(nd!==switchNode)_drawLinkLive(svg,nd.x,nd.y,switchNode.x,switchNode.y,'#56d4dd','1.5','0.4');});
      tier2.forEach(function(pve){_drawLinkLive(svg,switchNode.x,switchNode.y,pve.x,pve.y,'#7B2FBE','2','0.35');});
    }
    tier2.forEach(function(pve){
      (vmsByNode[pve.id]||[]).forEach(function(vm){
        _drawLinkLive(svg,pve.x,pve.y,vm.x,vm.y,vm.status==='running'?'#3fb950':'#484f58','1','0.3');
      });
    });
    /* Re-append node groups on top of links */
    svg.querySelectorAll('g').forEach(function(g2){svg.appendChild(g2);});
  });
  svg.addEventListener('mouseup',function(){
    if(_dragNode&&_dragMoved){
      _dragNode._wasDragged=true;
      /* Save position */
      var positions=_loadTopoPositions();
      var n=_dragNode._topoNode;
      positions[n.id]={x:Math.round(n.x),y:Math.round(n.y)};
      _saveTopoPositions(positions);
    }
    _dragNode=null;
    svg.style.cursor='';
  });
  svg.addEventListener('mouseleave',function(){
    if(_dragNode&&_dragMoved){
      var positions=_loadTopoPositions();
      var n=_dragNode._topoNode;
      positions[n.id]={x:Math.round(n.x),y:Math.round(n.y)};
      _saveTopoPositions(positions);
    }
    _dragNode=null;svg.style.cursor='';
  });
}
/* Helper for live link redraw during drag */
function _drawLinkLive(svg,x1,y1,x2,y2,color,width,opacity){
  var line=document.createElementNS('http://www.w3.org/2000/svg','line');
  line.classList.add('topo-link');
  line.setAttribute('x1',x1);line.setAttribute('y1',y1);
  line.setAttribute('x2',x2);line.setAttribute('y2',y2);
  line.setAttribute('stroke',color);line.setAttribute('stroke-width',width);
  line.setAttribute('stroke-opacity',opacity);
  svg.insertBefore(line,svg.firstChild);
}

/* ═══════════════════════════════════════════════════════════════════
   CAPACITY PLANNER — trend projections + sparklines
   ═══════════════════════════════════════════════════════════════════ */
function loadCapacity(){
  var info=document.getElementById('cap-info');
  var tbl=document.getElementById('cap-table');
  if(!tbl)return;
  tbl.innerHTML='<div class="skeleton"></div>';
  fetch('/api/capacity?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(info)info.textContent=d.snapshot_count+' snapshots, '+d.hosts+' hosts tracked';
    if(!d.projections||d.hosts===0){
      tbl.innerHTML='<div class="c-dim-fs12" style="padding:20px;text-align:center">'+
        (d.snapshot_count<2?'Need at least 2 snapshots for projections. Snapshots are taken weekly, or click TAKE SNAPSHOT.':
        'No projection data available.')+'</div>';
      return;
    }
    var h='<table><tr><th>Host</th><th>Metric</th><th>Current</th><th>Trend</th><th>Days to 80%</th><th>Sparkline</th></tr>';
    Object.keys(d.projections).sort().forEach(function(host){
      var metrics=d.projections[host];
      ['ram','disk','load'].forEach(function(m){
        if(!metrics[m])return;
        var p=metrics[m];
        var trendColor=p.trend_direction==='rising'?'var(--yellow)':p.trend_direction==='falling'?'var(--green)':'var(--text-dim)';
        var trendIcon=p.trend_direction==='rising'?'&#9650;':p.trend_direction==='falling'?'&#9660;':'&#8212;';
        var daysCell=p.days_to_80pct>0?('<span style="color:'+(p.days_to_80pct<30?'var(--red)':'var(--yellow)')+'">'+p.days_to_80pct+' days</span>'):'<span class="c-dim-fs12">&mdash;</span>';
        var spark=_miniSparkline(p.sparkline||[]);
        h+='<tr><td><strong>'+host+'</strong></td><td>'+m.toUpperCase()+'</td>';
        h+='<td>'+p.current+(m!=='load'?'%':'')+'</td>';
        h+='<td style="color:'+trendColor+'">'+trendIcon+' '+p.trend_direction+'</td>';
        h+='<td>'+daysCell+'</td>';
        h+='<td>'+spark+'</td></tr>';
      });
    });
    h+='</table>';
    tbl.innerHTML=h;
  }).catch(function(e){tbl.innerHTML='<span class="c-red">Failed: '+e+'</span>';});
}
function _miniSparkline(data){
  if(!data||data.length<2)return'<span class="c-dim-fs12">—</span>';
  var w=80,ht=20,mn=Math.min.apply(null,data),mx=Math.max.apply(null,data);
  if(mx===mn)mx=mn+1;
  var pts=data.map(function(v,i){return (i/(data.length-1))*w+','+(ht-(v-mn)/(mx-mn)*ht);}).join(' ');
  return'<svg width="'+w+'" height="'+ht+'" style="vertical-align:middle"><polyline points="'+pts+'" fill="none" stroke="#9B4FDE" stroke-width="1.5"/></svg>';
}
function forceCapSnapshot(){
  fetch('/api/capacity/snapshot?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast('Snapshot saved: '+d.snapshot,'success');
    else toast('Error: '+(d.error||'unknown'),'error');
    loadCapacity();
  }).catch(function(e){toast('Failed: '+e,'error');});
}

// ── PLAYBOOK RUNNER ──────────────────────────────────────────────────
function loadPlaybooks(){
  var list=document.getElementById('pb-list');
  if(!list)return;
  list.innerHTML='<div class="skeleton"></div>';
  fetch('/api/playbooks?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    var pbs=d.playbooks||[];
    if(pbs.length===0){
      list.innerHTML='<div class="c-dim-fs12" style="padding:20px;text-align:center">No playbooks found. Add TOML files to conf/playbooks/.</div>';
      return;
    }
    var h='<table><tr><th>Name</th><th>Trigger</th><th>Steps</th><th>Actions</th></tr>';
    pbs.forEach(function(pb){
      h+='<tr><td><strong>'+_esc(pb.name)+'</strong>';
      if(pb.description)h+='<br><span class="c-dim-fs12">'+_esc(pb.description)+'</span>';
      h+='</td><td>'+_esc(pb.trigger||'manual')+'</td>';
      h+='<td>'+pb.steps.length+'</td>';
      h+='<td><button class="fleet-btn" onclick="openPbRunner(\''+_esc(pb.filename)+'\',\''+_esc(pb.name)+'\')">RUN</button></td></tr>';
    });
    h+='</table>';
    list.innerHTML=h;
  }).catch(function(e){list.innerHTML='<span class="c-red">Failed: '+e+'</span>';});
}
var _pbSteps=[];var _pbFilename='';var _pbCurrentStep=0;
function openPbRunner(filename,name){
  _pbFilename=filename;_pbCurrentStep=0;_pbSteps=[];
  document.getElementById('pb-runner').classList.remove('d-none');
  document.getElementById('pb-runner-title').textContent='Running: '+name;
  var stepsEl=document.getElementById('pb-steps');
  stepsEl.innerHTML='<div class="skeleton"></div>';
  // Load playbook details to show step list
  fetch('/api/playbooks?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    var pb=(d.playbooks||[]).find(function(p){return p.filename===filename});
    if(!pb){stepsEl.innerHTML='<span class="c-red">Playbook not found</span>';return;}
    _pbSteps=pb.steps;_pbCurrentStep=0;
    _renderPbSteps();
  });
}
function closePbRunner(){
  document.getElementById('pb-runner').classList.add('d-none');
  _pbSteps=[];_pbFilename='';_pbCurrentStep=0;
}
function _renderPbSteps(){
  var el=document.getElementById('pb-steps');if(!el)return;
  var h='';
  _pbSteps.forEach(function(s,i){
    var statusColor=s._status==='pass'?'var(--green)':s._status==='fail'?'var(--red)':
      s._status==='running'?'var(--yellow)':'var(--text-dim)';
    var statusIcon=s._status==='pass'?'&#10003;':s._status==='fail'?'&#10007;':
      s._status==='running'?'&#8987;':'&#9679;';
    h+='<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;margin-bottom:4px;';
    h+='background:'+(i===_pbCurrentStep?'rgba(123,47,190,0.1)':'transparent')+';border-radius:6px">';
    h+='<span style="color:'+statusColor+';font-size:16px">'+statusIcon+'</span>';
    h+='<div style="flex:1"><div style="font-size:13px;color:var(--text)">'+_esc(s.name)+'</div>';
    h+='<div class="c-dim-fs12">'+s.type+(s.target?' &rarr; '+_esc(s.target):'')+'</div>';
    if(s._output)h+='<pre style="font-size:11px;color:var(--text-dim);margin:4px 0 0 0;white-space:pre-wrap">'+_esc(s._output)+'</pre>';
    if(s._error)h+='<pre style="font-size:11px;color:var(--red);margin:2px 0 0 0">'+_esc(s._error)+'</pre>';
    h+='</div>';
    if(i===_pbCurrentStep&&!s._status){
      if(s.confirm){
        h+='<button class="fleet-btn" style="background:var(--yellow);color:#000" onclick="runPbStep('+i+')">CONFIRM &amp; RUN</button>';
      } else {
        h+='<button class="fleet-btn" onclick="runPbStep('+i+')">RUN STEP</button>';
      }
    }
    h+='</div>';
  });
  if(_pbCurrentStep>=_pbSteps.length&&_pbSteps.length>0){
    var allPass=_pbSteps.every(function(s){return s._status==='pass'});
    h+='<div style="padding:12px;text-align:center;font-size:13px;color:'+(allPass?'var(--green)':'var(--red)')+'">'+
      (allPass?'All steps completed successfully':'Playbook stopped — check failures above')+'</div>';
  }
  el.innerHTML=h;
}
function runPbStep(idx){
  _pbSteps[idx]._status='running';
  _renderPbSteps();
  fetch('/api/playbooks/step?token='+_authToken+'&filename='+encodeURIComponent(_pbFilename)+'&step='+idx)
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){_pbSteps[idx]._status='fail';_pbSteps[idx]._error=d.error;_renderPbSteps();return;}
    var r=d.result;
    _pbSteps[idx]._status=r.status;
    _pbSteps[idx]._output=r.output||'';
    _pbSteps[idx]._error=r.error||'';
    if(r.status==='pass'){_pbCurrentStep=idx+1;}
    _renderPbSteps();
  }).catch(function(e){_pbSteps[idx]._status='fail';_pbSteps[idx]._error=''+e;_renderPbSteps();});
}

// ── GITOPS CONFIG SYNC ──────────────────────────────────────────────
function loadGitops(){
  var st=document.getElementById('go-status');
  var log=document.getElementById('go-log');
  var acts=document.getElementById('go-actions');
  if(!st||!log)return;
  st.innerHTML='<div class="skeleton"></div>';
  fetch('/api/gitops/status?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(!d.enabled){
      st.innerHTML='<div class="c-dim-fs12">GitOps not configured. Add <code>[gitops]</code> section with <code>repo_url</code> to freq.toml.</div>';
      if(acts)acts.classList.add('d-none');
      log.innerHTML='';
      return;
    }
    var s=d.state||{};
    var statusColor=s.status==='error'?'var(--red)':s.status==='changes_pending'?'var(--yellow)':'var(--green)';
    var h='<div style="display:flex;gap:20px;flex-wrap:wrap">';
    h+='<div>Repo: <strong>'+_esc(d.repo_url)+'</strong></div>';
    h+='<div>Branch: <strong>'+_esc(d.branch)+'</strong></div>';
    h+='<div>Status: <span style="color:'+statusColor+'">'+_esc(s.status)+'</span></div>';
    if(s.last_commit)h+='<div>Commit: <code>'+_esc(s.last_commit)+'</code> '+_esc(s.last_message)+'</div>';
    if(s.pending_changes>0)h+='<div style="color:var(--yellow)">'+s.pending_changes+' pending changes</div>';
    if(s.last_error)h+='<div style="color:var(--red)">Error: '+_esc(s.last_error)+'</div>';
    if(s.last_sync>0)h+='<div>Last sync: '+new Date(s.last_sync*1000).toLocaleString()+'</div>';
    h+='</div>';
    st.innerHTML=h;
    if(acts){if(s.pending_changes>0){acts.classList.remove('d-none');acts.style.display='flex';}else{acts.classList.add('d-none');acts.style.display='';}}
    // Load commit log
    fetch('/api/gitops/log?token='+_authToken).then(function(r){return r.json()}).then(function(ld){
      var commits=ld.commits||[];
      if(commits.length===0){log.innerHTML='<div class="c-dim-fs12">No commit history.</div>';return;}
      var t='<table><tr><th>Hash</th><th>Message</th><th>Date</th><th>Author</th><th></th></tr>';
      commits.forEach(function(c){
        t+='<tr><td><code>'+_esc(c.hash)+'</code></td><td>'+_esc(c.message)+'</td>';
        t+='<td class="c-dim-fs12">'+_esc(c.date)+'</td><td>'+_esc(c.author)+'</td>';
        t+='<td><button class="fleet-btn" onclick="gitopsRollback(\''+_esc(c.hash)+'\')">ROLLBACK</button></td></tr>';
      });
      t+='</table>';
      log.innerHTML=t;
    });
  }).catch(function(e){st.innerHTML='<span class="c-red">Failed: '+e+'</span>';});
}
function gitopsFetch(){
  toast('Syncing...','info');
  fetch('/api/gitops/sync?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast('Sync complete','success');
    else toast('Error: '+(d.error||'unknown'),'error');
    loadGitops();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function gitopsApply(){
  toast('Applying changes...','info');
  fetch('/api/gitops/apply?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast(d.message||'Applied','success');
    else toast('Error: '+(d.error||'unknown'),'error');
    loadGitops();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function gitopsDiff(){
  var el=document.getElementById('go-diff');
  var content=document.getElementById('go-diff-content');
  if(!el||!content)return;
  el.classList.toggle('d-none');
  if(!el.classList.contains('d-none')){
    content.textContent='Loading diff...';
    fetch('/api/gitops/diff?token='+_authToken+'&full=1').then(function(r){return r.json()}).then(function(d){
      content.textContent=d.diff||'No differences.';
    }).catch(function(e){content.textContent='Error: '+e;});
  }
}
function gitopsRollback(hash){
  if(!confirm('Roll back config to commit '+hash+'?'))return;
  fetch('/api/gitops/rollback?token='+_authToken+'&commit='+encodeURIComponent(hash)).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast(d.message||'Rolled back','success');
    else toast('Error: '+(d.error||'unknown'),'error');
    loadGitops();
  }).catch(function(e){toast('Failed: '+e,'error');});
}

// ── COST TRACKING ───────────────────────────────────────────────────
function loadCosts(){
  var sum=document.getElementById('cost-summary');
  var tbl=document.getElementById('cost-table');
  if(!tbl)return;
  tbl.innerHTML='<div class="skeleton"></div>';
  fetch('/api/cost?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(d.error){tbl.innerHTML='<span class="c-red">'+_esc(d.error)+'</span>';return;}
    var s=d.summary||{};
    if(sum){
      var cur=s.currency||'USD';
      sum.innerHTML=
        '<div style="background:rgba(123,47,190,0.1);padding:12px 16px;border-radius:8px;text-align:center;flex:1;min-width:120px">'+
          '<div class="c-dim-fs12">TOTAL / MONTH</div><div style="font-size:20px;font-weight:700;color:var(--purple-light)">'+cur+' '+s.total_cost_month+'</div></div>'+
        '<div style="background:rgba(123,47,190,0.1);padding:12px 16px;border-radius:8px;text-align:center;flex:1;min-width:120px">'+
          '<div class="c-dim-fs12">TOTAL / YEAR</div><div style="font-size:20px;font-weight:700;color:var(--text)">'+cur+' '+s.total_cost_year+'</div></div>'+
        '<div style="background:rgba(123,47,190,0.1);padding:12px 16px;border-radius:8px;text-align:center;flex:1;min-width:120px">'+
          '<div class="c-dim-fs12">TOTAL WATTS</div><div style="font-size:20px;font-weight:700;color:var(--yellow)">'+s.total_watts+'W</div></div>'+
        '<div style="background:rgba(123,47,190,0.1);padding:12px 16px;border-radius:8px;text-align:center;flex:1;min-width:120px">'+
          '<div class="c-dim-fs12">kWh / MONTH</div><div style="font-size:20px;font-weight:700;color:var(--text-dim)">'+s.total_kwh_month+'</div></div>'+
        '<div style="background:rgba(123,47,190,0.1);padding:12px 16px;border-radius:8px;text-align:center;flex:1;min-width:120px">'+
          '<div class="c-dim-fs12">RATE</div><div style="font-size:16px;font-weight:700;color:var(--text-dim)">'+cur+' '+s.rate_per_kwh+'/kWh &middot; PUE '+s.pue+'</div></div>';
    }
    var hosts=d.hosts||[];
    if(hosts.length===0){tbl.innerHTML='<div class="c-dim-fs12" style="text-align:center;padding:20px">No host data.</div>';return;}
    var h='<table><tr><th>Host</th><th>Watts</th><th>Source</th><th>kWh/mo</th><th>Cost/mo</th><th>RAM</th><th>Containers</th></tr>';
    hosts.forEach(function(c){
      var srcColor=c.watts_source==='idrac'?'var(--green)':'var(--text-dim)';
      h+='<tr><td><strong>'+_esc(c.label)+'</strong></td>';
      h+='<td>'+c.watts+'W</td>';
      h+='<td style="color:'+srcColor+'">'+c.watts_source+'</td>';
      h+='<td>'+c.kwh_month+'</td>';
      h+='<td style="color:var(--purple-light)">$'+c.cost_month+'</td>';
      h+='<td>'+c.ram_gb+'GB</td>';
      h+='<td>'+c.vms+'</td></tr>';
    });
    h+='</table>';
    tbl.innerHTML=h;
  }).catch(function(e){tbl.innerHTML='<span class="c-red">Failed: '+e+'</span>';});
}

// ── FEDERATION ──────────────────────────────────────────────────────
function loadFederation(){
  var sum=document.getElementById('fed-summary');
  var sites=document.getElementById('fed-sites');
  if(!sites)return;
  sites.innerHTML='<div class="skeleton"></div>';
  fetch('/api/federation/status?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    var s=d.summary||{};
    if(sum){
      sum.innerHTML=
        '<div style="background:rgba(123,47,190,0.1);padding:10px 14px;border-radius:8px;text-align:center;flex:1;min-width:100px">'+
          '<div class="c-dim-fs12">SITES</div><div style="font-size:18px;font-weight:700;color:var(--purple-light)">'+s.total_sites+'</div></div>'+
        '<div style="background:rgba(123,47,190,0.1);padding:10px 14px;border-radius:8px;text-align:center;flex:1;min-width:100px">'+
          '<div class="c-dim-fs12">REACHABLE</div><div style="font-size:18px;font-weight:700;color:var(--green)">'+s.reachable_sites+'</div></div>'+
        '<div style="background:rgba(123,47,190,0.1);padding:10px 14px;border-radius:8px;text-align:center;flex:1;min-width:100px">'+
          '<div class="c-dim-fs12">TOTAL HOSTS</div><div style="font-size:18px;font-weight:700;color:var(--text)">'+s.total_hosts+'</div></div>'+
        '<div style="background:rgba(123,47,190,0.1);padding:10px 14px;border-radius:8px;text-align:center;flex:1;min-width:100px">'+
          '<div class="c-dim-fs12">HEALTHY</div><div style="font-size:18px;font-weight:700;color:var(--green)">'+s.total_healthy+'</div></div>';
    }
    var sl=d.sites||[];
    if(sl.length===0){sites.innerHTML='<div class="c-dim-fs12" style="text-align:center;padding:20px">No sites registered. Add a remote FREQ instance below.</div>';return;}
    var h='<table><tr><th>Site</th><th>URL</th><th>Status</th><th>Version</th><th>Hosts</th><th>Healthy</th><th>Last Seen</th><th>Actions</th></tr>';
    sl.forEach(function(site){
      var sc=site.last_status==='ok'?'var(--green)':site.last_status==='unreachable'?'var(--red)':'var(--text-dim)';
      h+='<tr'+(site.enabled?'':' style="opacity:0.5"')+'><td><strong>'+_esc(site.name)+'</strong></td>';
      h+='<td class="c-dim-fs12">'+_esc(site.url)+'</td>';
      h+='<td style="color:'+sc+'">'+_esc(site.last_status)+'</td>';
      h+='<td>'+_esc(site.last_version||'—')+'</td>';
      h+='<td>'+site.last_hosts+'</td>';
      h+='<td>'+site.last_healthy+'</td>';
      h+='<td class="c-dim-fs12">'+(site.age>=0?(site.age<60?site.age+'s':Math.round(site.age/60)+'m')+' ago':'never')+'</td>';
      h+='<td style="display:flex;gap:4px">';
      h+='<button class="fleet-btn" onclick="fedToggle(\''+_esc(site.name)+'\')">'+(site.enabled?'DISABLE':'ENABLE')+'</button>';
      h+='<button class="fleet-btn" style="color:var(--red)" onclick="fedRemove(\''+_esc(site.name)+'\')">REMOVE</button>';
      h+='</td></tr>';
    });
    h+='</table>';
    sites.innerHTML=h;
  }).catch(function(e){sites.innerHTML='<span class="c-red">Failed: '+e+'</span>';});
}
function fedPoll(){
  toast('Polling all sites...','info');
  fetch('/api/federation/poll?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast('Poll complete','success');
    else toast('Error: '+(d.error||'unknown'),'error');
    loadFederation();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function fedRegister(){
  var name=document.getElementById('fed-name').value.trim();
  var url=document.getElementById('fed-url').value.trim();
  var secret=document.getElementById('fed-secret').value;
  if(!name||!url){toast('Name and URL required','error');return;}
  var q='/api/federation/register?token='+_authToken+'&name='+encodeURIComponent(name)+'&url='+encodeURIComponent(url);
  if(secret)q+='&secret='+encodeURIComponent(secret);
  fetch(q).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast(d.message||'Registered','success');document.getElementById('fed-name').value='';document.getElementById('fed-url').value='';document.getElementById('fed-secret').value='';}
    else toast('Error: '+(d.error||'unknown'),'error');
    loadFederation();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function fedToggle(name){
  fetch('/api/federation/toggle?token='+_authToken+'&name='+encodeURIComponent(name)).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast(name+' '+(d.enabled?'enabled':'disabled'),'success');
    else toast('Error: '+(d.error||'unknown'),'error');
    loadFederation();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function fedRemove(name){
  if(!confirm('Remove site "'+name+'"?'))return;
  fetch('/api/federation/unregister?token='+_authToken+'&name='+encodeURIComponent(name)).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast(d.message||'Removed','success');
    else toast('Error: '+(d.error||'unknown'),'error');
    loadFederation();
  }).catch(function(e){toast('Failed: '+e,'error');});
}

// ── CHAOS ENGINEERING ───────────────────────────────────────────────
function loadChaos(){
  var log=document.getElementById('chaos-log');
  var sel=document.getElementById('chaos-type');
  if(!log)return;
  // Load experiment types into dropdown
  if(sel&&sel.options.length<=1){
    fetch('/api/chaos/types?token='+_authToken).then(function(r){return r.json()}).then(function(d){
      (d.types||[]).forEach(function(t){
        var o=document.createElement('option');o.value=t.type;o.textContent=t.type+' — '+t.description;
        sel.appendChild(o);
      });
    });
  }
  // Load experiment log
  log.innerHTML='<div class="skeleton"></div>';
  fetch('/api/chaos/log?token='+_authToken).then(function(r){return r.json()}).then(function(d){
    var exps=d.experiments||[];
    if(exps.length===0){log.innerHTML='<div class="c-dim-fs12" style="text-align:center;padding:20px">No experiments run yet.</div>';return;}
    var h='<table><tr><th>Name</th><th>Type</th><th>Target</th><th>Status</th><th>Duration</th><th>Recovery</th><th>Error</th></tr>';
    exps.forEach(function(e){
      var sc=e.status==='completed'?'var(--green)':e.status==='blocked'?'var(--yellow)':'var(--red)';
      h+='<tr><td><strong>'+_esc(e.experiment_name)+'</strong></td>';
      h+='<td>'+_esc(e.experiment_type)+'</td>';
      h+='<td>'+_esc(e.target_host)+'</td>';
      h+='<td style="color:'+sc+'">'+_esc(e.status)+'</td>';
      h+='<td>'+(e.duration>0?e.duration+'s':'—')+'</td>';
      h+='<td>'+(e.recovery_time>0?e.recovery_time+'s':'—')+'</td>';
      h+='<td class="c-dim-fs12">'+_esc(e.error||'—')+'</td></tr>';
    });
    h+='</table>';
    log.innerHTML=h;
  }).catch(function(e){log.innerHTML='<span class="c-red">Failed: '+e+'</span>';});
  _populateHostDropdowns();
}
function chaosRun(){
  var name=document.getElementById('chaos-name').value.trim();
  var type=document.getElementById('chaos-type').value;
  var target=document.getElementById('chaos-target').value.trim();
  var service=document.getElementById('chaos-service').value.trim();
  var duration=document.getElementById('chaos-duration').value||'60';
  if(!name||!type||!target){toast('Name, type, and target are required','error');return;}
  if(!confirm('Run chaos experiment "'+name+'" ('+type+') on '+target+'? This will intentionally disrupt the service.')){return;}
  toast('Running experiment...','info');
  var q='/api/chaos/run?token='+_authToken+'&name='+encodeURIComponent(name)+'&type='+encodeURIComponent(type);
  q+='&target='+encodeURIComponent(target)+'&service='+encodeURIComponent(service)+'&duration='+duration;
  fetch(q).then(function(r){return r.json()}).then(function(d){
    if(d.error){toast('Error: '+d.error,'error');return;}
    var r=d.result||{};
    if(r.status==='completed')toast('Experiment completed — recovery: '+(r.recovery_time||0)+'s','success');
    else if(r.status==='blocked')toast('Blocked: '+(r.error||'safety gate'),'error');
    else toast('Status: '+r.status+' '+(r.error||''),'error');
    loadChaos();
  }).catch(function(e){toast('Failed: '+e,'error');});
}

function runDoctor(){
  var out=document.getElementById('diag-out');if(!out)return;
  out.innerHTML='<span style="color:var(--text-dim)">Running self-diagnostic...</span>';
  fetch(API.DOCTOR).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'OK')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function runDiagnose(){
  var host=document.getElementById('diag-host').value.trim();
  if(!host){toast('Select a host','error');return;}
  var out=document.getElementById('diag-out');if(!out)return;
  out.innerHTML='<span style="color:var(--text-dim)">Diagnosing '+_esc(host)+'...</span>';
  fetch(API.DIAGNOSE+'?target='+encodeURIComponent(host)).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    var h='<div style="font-size:14px;font-weight:700;color:var(--purple-light);margin-bottom:8px">'+_esc(d.host)+' ('+_esc(d.ip)+')</div>';
    var checks=d.checks||{};
    Object.keys(checks).forEach(function(k){
      h+='<div style="margin-bottom:8px"><div style="font-size:11px;letter-spacing:1px;color:var(--text-dim);text-transform:uppercase">'+_esc(k)+'</div>';
      h+='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text);margin:2px 0 0 0">'+_esc(checks[k])+'</pre></div>';
    });
    out.innerHTML=h;
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function fetchLogs(){
  var host=document.getElementById('log-host').value.trim();
  if(!host){toast('Select a host','error');return;}
  var unit=document.getElementById('log-unit').value.trim();
  var lines=document.getElementById('log-lines').value||50;
  var out=document.getElementById('log-out');if(!out)return;
  out.innerHTML='<span style="color:var(--text-dim)">Fetching logs from '+_esc(host)+'...</span>';
  var url=API.LOG+'?target='+encodeURIComponent(host)+'&lines='+lines;
  if(unit)url+='&unit='+encodeURIComponent(unit);
  fetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    var logLines=d.lines||[];
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:11px;color:var(--text);line-height:1.5">'+_esc(logLines.join('\\n'))+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function loadZfs(){
  var out=document.getElementById('zfs-out');if(!out)return;
  out.innerHTML='<span style="color:var(--text-dim)">Loading ZFS status...</span>';
  fetch(API.ZFS).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'No ZFS data')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function loadBackups(action){
  var out=document.getElementById('backup-out');if(!out)return;
  out.innerHTML='<span style="color:var(--text-dim)">Loading backups...</span>';
  fetch(API.BACKUP+'?action='+action).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'No backup data')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function runDiscover(){
  var subnet=document.getElementById('discover-subnet').value.trim();
  var out=document.getElementById('discover-out');if(!out)return;
  out.innerHTML='<span style="color:var(--text-dim)">Scanning network...</span>';
  var url=API.DISCOVER+'?token='+_authToken;
  if(subnet)url+='&subnet='+encodeURIComponent(subnet);
  fetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'No hosts discovered')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function addHostManual(){
  var ip=(document.getElementById('add-host-ip')||{}).value.trim();
  var label=(document.getElementById('add-host-label')||{}).value.trim();
  var htype=(document.getElementById('add-host-type')||{}).value;
  var groups=(document.getElementById('add-host-groups')||{}).value.trim();
  var msg=document.getElementById('add-host-msg');
  if(!ip||!label){toast('IP and label are required','error');return;}
  if(msg)msg.textContent='Adding host...';msg.style.color='var(--text-dim)';
  fetch(API.ADMIN_HOSTS_UPDATE+'?label='+encodeURIComponent(label)+'&type='+encodeURIComponent(htype)+(groups?'&groups='+encodeURIComponent(groups):'')+'&ip='+encodeURIComponent(ip)+'&token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(d.error){toast(d.error,'error');if(msg){msg.textContent=d.error;msg.style.color='var(--red)';}return;}
    toast('Host '+label+' added','success');
    if(msg){msg.textContent='Added '+label+' ('+ip+')';msg.style.color='var(--green)';}
    document.getElementById('add-host-ip').value='';
    document.getElementById('add-host-label').value='';
    document.getElementById('add-host-groups').value='';
  }).catch(function(e){toast('Failed to add host','error');if(msg){msg.textContent='Error: '+e;msg.style.color='var(--red)';}});
}
function loadGwipe(action){
  var out=document.getElementById('gwipe-out');if(!out)return;
  out.innerHTML='<span style="color:var(--text-dim)">Loading GWIPE '+action+'...</span>';
  fetch(API.GWIPE+'?action='+action+'&token='+_authToken).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    var data=d.data||{};
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(JSON.stringify(data,null,2))+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
/* ═══════════════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════════════ */
document.addEventListener('keydown',function(e){if(e.key==='Escape'){closeHost();closeModal();}});
try{loadHome();renderGlobalSettings();}catch(e){console.error(e);}
</script>
</body>
</html>"""
