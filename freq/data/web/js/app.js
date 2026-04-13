var HC=['#58a6ff','#3fb950','#d29922','#f778ba','#79c0ff','#d2a8ff','#ff7b72','#ffa657','#7ee787'];
/* Deterministic per-view subtitles — no randomization, no comfort copy.
 * Each label names the domain the page covers. State/counts come from
 * the actual probes, not flavor text. */
var _viewLabels={
  home:'fleet',
  fleet:'hosts',
  docker:'containers',
  media:'media stack',
  security:'security',
  tools:'tools',
  lab:'lab',
  settings:'settings'
};
function rt(view){return _viewLabels[view]||_viewLabels.home;}
/* Badge helper — preserve distinct backend states instead of collapsing
 * everything into up/down. Each source state maps to a dedicated CSS class
 * so degraded/stale/auth-failed states don't render as plain green or red. */
function badge(s){var c={
  up:'up',running:'up',online:'up',healthy:'ok',ok:'ok',
  down:'down',stopped:'down',
  unreachable:'unreachable',
  auth_failed:'warn',
  stale:'warn',
  probe_error:'warn',
  pending:'warn',
  warming:'warn',
  CRITICAL:'CRITICAL',HIGH:'HIGH',MEDIUM:'MEDIUM',
  created:'created',remote:'remote',paused:'paused',unknown:'unknown'
}[s]||'warn';var label=String(s).replace(/_/g,' ').toUpperCase();return '<span class="badge '+c+'">'+label+'</span>';}
function s(l,v,c){return '<div class="st"><div class="lb">'+l+'</div><div class="vl '+c+'">'+v+'</div></div>';}
var st=s;
function _pbar(pct,color){var p=pct||0;var c=p>=90?'var(--red)':p>=75?'var(--yellow)':color||'var(--purple-light)';return '<div class="pbar"><div class="pbar-fill" style="width:'+p+'%;background:'+c+'"></div></div>';}
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
/* Authenticated fetch — sends token via Authorization header instead of query string */
function _authFetch(url, opts) {
    opts = opts || {};
    if (!opts.headers) opts.headers = {};
    if (_authToken) opts.headers['Authorization'] = 'Bearer ' + _authToken;
    return fetch(url, opts).then(function(r){
      if(r.status===403||r.status===401){doLogout();return r;}
      if(!r.ok){toast('API error: '+url.replace('/api/','')+ ' ('+r.status+')','error');}
      return r;
    });
}

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
    if(a==='vmQuickTag'){var tags=prompt('Enter tags for VM '+da.dataset.vmid+' (comma-separated):');if(tags!==null)_authFetch(API.VM_TAG+'?vmid='+da.dataset.vmid+'&tags='+encodeURIComponent(tags),{method:'POST'}).then(function(r){return r.json()}).then(function(d){if(d.ok)toast('Tags updated','success');else toast(d.error,'error');});return;}
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
    var fns={sshdRestartSelected:sshdRestartSelected,sshdRestartAll:sshdRestartAll,openLayoutConfig:openLayoutConfig,hdRestart:hdRestart,vmtSnapshot:vmtSnapshot,vmtCreate:vmtCreate,vmtResize:vmtResize,vmtMigrate:vmtMigrate,vmtClone:vmtClone,vmtAddDisk:vmtAddDisk,vmtTag:vmtTag,vmtRollback:vmtRollback,unlockVault:unlockVault,runHarden:runHarden,testNotify:testNotify,userCreate:userCreate,vaultSet:vaultSet,updateSelected:updateSelected,updateAll:updateAll,pfWriteService:pfWriteService,pfWriteDhcp:pfWriteDhcp,pfWriteRule:pfWriteRule,pfWriteNat:pfWriteNat,pfWriteWgPeer:pfWriteWgPeer,pfBackupNow:pfBackupNow,pfCheckUpdates:pfCheckUpdates,pfReboot:pfReboot,tnWriteService:tnWriteService,tnWriteScrub:tnWriteScrub,tnWriteShare:tnWriteShare,tnWriteReplication:tnWriteReplication,tnReboot:tnReboot,swWriteAcl:swWriteAcl,opnWriteService:opnWriteService,opnWriteRule:opnWriteRule,opnDeleteRule:opnDeleteRule,opnWriteDhcp:opnWriteDhcp,opnWriteDns:opnWriteDns,opnWriteWg:opnWriteWg,opnReboot:opnReboot,ipmiClearSel:ipmiClearSel,synWriteService:synWriteService,synReboot:synReboot};
    if(fns[a]){fns[a]();return;}
    var argFns={tnAction:tnAction,swAction:swAction,pfAction:pfAction,idracAction:idracAction,idracWrite:idracWrite,opnAction:opnAction,ipmiAction:ipmiAction,ipmiWrite:ipmiWrite,ipmiWriteBoot:ipmiWriteBoot,redfishAction:redfishAction,redfishWrite:redfishWrite,synAction:synAction,tnWriteSnapshot:tnWriteSnapshot,tnWriteDataset:tnWriteDataset,swWriteVlan:swWriteVlan,switchVaultTab:switchVaultTab,switchDockerSub:switchDockerSub,toggleMediaTag:toggleMediaTag,runHostUpdate:runHostUpdate,sshdRestartHost:sshdRestartHost,ntpFixHost:ntpFixHost,userPromote:userPromote,userDemote:userDemote,updateCategoryRange:updateCategoryRange,mediaRestart:mediaRestart};
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
  if(!user||!pass){if(errEl){errEl.textContent='Enter username and password';errEl.style.display='block';}return;}
  if(errEl)errEl.style.display='none';
  var btn=document.querySelector('#login-overlay button');if(btn){btn.textContent='LOGGING IN...';btn.disabled=true;}
  _authFetch(API.AUTH_LOGIN,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:user,password:pass})}).then(function(r){return r.json()}).then(function(d){
    if(btn){btn.textContent='LOG IN';btn.disabled=false;}
    if(d.error){if(errEl){errEl.textContent=d.error;errEl.style.display='block';}passEl.value='';return;}
    _authToken=d.token;_currentUser=d.user;_currentRole=d.role;
    _showApp();
  }).catch(function(e){if(btn){btn.textContent='LOG IN';btn.disabled=false;}if(errEl){errEl.textContent='Connection failed: '+e;errEl.style.display='block';}});
}

function doLogout(){
  /* Invalidate server-side session + clear cookie */
  _authFetch('/api/auth/logout',{method:'POST'}).catch(function(){});

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
  /* POLICY_CHECK, POLICY_FIX, POLICY_DIFF removed — zero consumers */
  SWEEP:'/api/sweep',PATROL_STATUS:'/api/patrol/status',
  ZFS:'/api/zfs',BACKUP:'/api/backup',DISCOVER:'/api/discover',GWIPE:'/api/gwipe',
  VM_ADD_DISK:'/api/vm/add-disk',VM_TAG:'/api/vm/tag',VM_CLONE:'/api/vm/clone',VM_MIGRATE:'/api/vm/migrate',
  COMPOSE_UP:'/api/containers/compose-up',COMPOSE_DOWN:'/api/containers/compose-down',COMPOSE_VIEW:'/api/containers/compose-view',
  BACKUP_LIST:'/api/backup/list',BACKUP_CREATE:'/api/backup/create',BACKUP_RESTORE:'/api/backup/restore',
  EVENTS:'/api/events',
  /* ── Alerting ── */
  ALERT_RULES:'/api/alert/rules',ALERT_HISTORY:'/api/alert/history',ALERT_CHECK:'/api/alert/check',ALERT_SILENCES:'/api/alert/silences',
  /* ── Observability ── */
  MONITORS:'/api/monitors',MONITORS_CHECK:'/api/monitors/check',
  TREND_DATA:'/api/trend/data',TREND_SNAPSHOT:'/api/trend/snapshot',
  SLA:'/api/sla',SLA_CHECK:'/api/sla/check',
  CAPACITY_RECOMMEND:'/api/capacity/recommend',
  /* ── Security/Compliance ── */
  COMPLY_STATUS:'/api/comply/status',COMPLY_RESULTS:'/api/comply/results',
  CERT_INVENTORY:'/api/cert/inventory',DNS_INVENTORY:'/api/dns/inventory',
  PATCH_STATUS:'/api/patch/status',SECRETS_AUDIT:'/api/secrets/audit',
  SECRETS_LEASES:'/api/secrets/leases',SECRETS_SCAN:'/api/secrets/scan',
  BASELINE_LIST:'/api/baseline/list',
  /* ── Network ── */
  SWITCH_SHOW:'/api/v1/net/switch/show',SWITCH_FACTS:'/api/v1/net/switch/facts',
  SWITCH_INTERFACES:'/api/v1/net/switch/interfaces',SWITCH_VLANS:'/api/v1/net/switch/vlans',
  SWITCH_MAC:'/api/v1/net/switch/mac',SWITCH_ARP:'/api/v1/net/switch/arp',
  SWITCH_NEIGHBORS:'/api/v1/net/switch/neighbors',SWITCH_ENV:'/api/v1/net/switch/environment',
  CONFIG_HISTORY:'/api/v1/net/config/history',CONFIG_SEARCH:'/api/v1/net/config/search',
  MAP_DATA:'/api/map/data',MAP_IMPACT:'/api/map/impact',
  NETMON_DATA:'/api/netmon/data',
  /* ── Docker Fleet ── */
  DOCKER_FLEET:'/api/docker-fleet',
  /* ── Oncall ── */
  ONCALL_WHOAMI:'/api/oncall/whoami',ONCALL_SCHEDULE:'/api/oncall/schedule',ONCALL_INCIDENTS:'/api/oncall/incidents',
  /* ── Schedule/Webhooks ── */
  SCHEDULE_JOBS:'/api/schedule/jobs',SCHEDULE_LOG:'/api/schedule/log',SCHEDULE_TEMPLATES:'/api/schedule/templates',
  WEBHOOK_LIST:'/api/webhook/list',WEBHOOK_LOG:'/api/webhook/log',
  /* ── Inventory ── */
  INVENTORY:'/api/inventory',
  COMPARE:'/api/compare',REPORT:'/api/report',
  /* ── DR ── */
  BACKUP_POLICY_LIST:'/api/backup-policy/list',BACKUP_POLICY_STATUS:'/api/backup-policy/status',
  WATCHDOG_HEALTH:'/api/watchdog/health',
  /* ── Playbook Create ── */
  PLAYBOOKS_CREATE:'/api/playbooks/create',PLAYBOOKS_RUN:'/api/playbooks/run',
  /* ── Cost ── */
  COST_CONFIG:'/api/cost/config',
  /* ── Remaining endpoints ── */
  DB_STATUS:'/api/db/status',LOGS_STATS:'/api/logs/stats',
  PATCH_COMPLIANCE:'/api/patch/compliance',NETMON_INTERFACES:'/api/netmon/interfaces',
  MIGRATE_PLAN:'/api/migrate-plan',DEPLOY_AGENT:'/api/deploy-agent',
  PROXY_STATUS:'/api/proxy/status',PROXY_LIST:'/api/proxy/list',
  AGENT_CREATE:'/api/agent/create',AGENT_DESTROY:'/api/agent/destroy',
  MIGRATE_VMWARE:'/api/migrate-vmware/status',
  POOL:'/api/pool',ROLLBACK:'/api/rollback',
  MEDIA_DOWNLOADS_DETAIL:'/api/media/downloads/detail',
  GITOPS_INIT:'/api/gitops/init',PLUGIN_INFO:'/api/v1/plugin/info',
  API_DOCS:'/api/docs',OPENAPI:'/api/openapi.json',
  METRICS_PROMETHEUS:'/api/metrics/prometheus',
  SETUP_STATUS:'/api/setup/status',
  /* ── LXC Containers ── */
  CT_LIST:'/api/ct/list',CT_CREATE:'/api/ct/create',CT_DESTROY:'/api/ct/destroy',
  CT_POWER:'/api/ct/power',CT_CONFIG:'/api/ct/config',CT_SET:'/api/ct/set',
  CT_SNAPSHOT:'/api/ct/snapshot',CT_ROLLBACK:'/api/ct/rollback',CT_SNAPSHOTS:'/api/ct/snapshots',
  CT_DELETE_SNAP:'/api/ct/delete-snapshot',CT_CLONE:'/api/ct/clone',CT_MIGRATE:'/api/ct/migrate',
  CT_RESIZE:'/api/ct/resize',CT_EXEC:'/api/ct/exec',CT_TEMPLATES:'/api/ct/templates',
  /* ── Device Write Operations ── */
  TRUENAS_SNAPSHOT:'/api/truenas/snapshot',TRUENAS_SERVICE:'/api/truenas/service',
  TRUENAS_SCRUB:'/api/truenas/scrub',TRUENAS_REBOOT:'/api/truenas/reboot',
  TRUENAS_DATASET:'/api/truenas/dataset',TRUENAS_SHARE:'/api/truenas/share',
  TRUENAS_REPLICATION:'/api/truenas/replication',TRUENAS_APP:'/api/truenas/app',
  PFSENSE_SERVICE:'/api/pfsense/service',PFSENSE_DHCP:'/api/pfsense/dhcp/reservation',
  PFSENSE_CONFIG_BACKUP:'/api/pfsense/config/backup',PFSENSE_REBOOT:'/api/pfsense/reboot',
  PFSENSE_RULES:'/api/pfsense/rules',PFSENSE_NAT:'/api/pfsense/nat',
  PFSENSE_WG_PEER:'/api/pfsense/wg/peer',PFSENSE_UPDATES:'/api/pfsense/updates',
  SWITCH_VLAN_CREATE:'/api/v1/net/switch/vlan/create',SWITCH_VLAN_DELETE:'/api/v1/net/switch/vlan/delete',
  SWITCH_ACL:'/api/v1/net/switch/acl',
  /* ── OPNsense ── */
  OPN_STATUS:'/api/opnsense/status',OPN_SERVICES:'/api/opnsense/services',OPN_SVC_ACTION:'/api/opnsense/service/action',
  OPN_RULES:'/api/opnsense/rules',OPN_RULES_ADD:'/api/opnsense/rules/add',OPN_RULES_DEL:'/api/opnsense/rules/delete',
  OPN_DHCP:'/api/opnsense/dhcp',OPN_DHCP_ADD:'/api/opnsense/dhcp/add',OPN_DHCP_DEL:'/api/opnsense/dhcp/delete',
  OPN_DNS:'/api/opnsense/dns',OPN_DNS_ADD:'/api/opnsense/dns/add',OPN_DNS_DEL:'/api/opnsense/dns/delete',
  OPN_WG:'/api/opnsense/wireguard',OPN_WG_ADD:'/api/opnsense/wireguard/add',
  OPN_FW:'/api/opnsense/firmware',OPN_REBOOT:'/api/opnsense/reboot',
  /* ── Generic IPMI ── */
  IPMI_STATUS:'/api/ipmi/status',IPMI_SENSORS:'/api/ipmi/sensors',IPMI_SEL:'/api/ipmi/sel',
  IPMI_POWER:'/api/ipmi/power',IPMI_BOOT:'/api/ipmi/boot',IPMI_SEL_CLEAR:'/api/ipmi/sel/clear',
  /* ── Redfish ── */
  RF_SYSTEM:'/api/redfish/system',RF_THERMAL:'/api/redfish/thermal',RF_POWER_USAGE:'/api/redfish/power-usage',
  RF_EVENTS:'/api/redfish/events',RF_POWER:'/api/redfish/power',
  /* ── Synology ── */
  SYN_STATUS:'/api/synology/status',SYN_STORAGE:'/api/synology/storage',SYN_SHARES:'/api/synology/shares',
  SYN_DOCKER:'/api/synology/docker',SYN_PACKAGES:'/api/synology/packages',
  SYN_SERVICE:'/api/synology/service',SYN_REBOOT:'/api/synology/reboot',
  /* ── WoL + Benchmarks ── */
  WOL:'/api/wol',BENCH_RUN:'/api/bench/run',BENCH_RESULTS:'/api/bench/results',
  BENCH_NETSPEED:'/api/bench/netspeed',BENCH_TOOLS:'/api/bench/tools',
  /* ── Log Aggregation ── */
  LOGS_FLEET:'/api/logs/fleet',LOGS_SEARCH:'/api/logs/search',LOGS_OOM:'/api/logs/oom',LOGS_AUTH:'/api/logs/auth',
  /* ── Backup Verify + Cert Expiry ── */
  BACKUP_VERIFY_RUN:'/api/backup/verify',BACKUP_VERIFY_STATUS:'/api/backup/verify/status',
  CERT_EXPIRY:'/api/cert/expiry'
};
var _fleetCache={fo:null,hd:null};/* cached API responses for instant page switch */

function _showApp(){
  /* Post-login launch sequence: evidence-first, each stage reports
   * what was actually fetched from the API so the operator sees a
   * boot log, not a marketing spinner. */
  var login=document.getElementById('login-overlay');
  login.innerHTML='<div class="text-center"><div style="font-size:32px;font-weight:700;letter-spacing:8px;color:var(--text);margin-bottom:8px">PVE FREQ</div>'+
    '<div style="font-size:11px;color:var(--text-dim);letter-spacing:3px;margin-bottom:24px">operator console</div>'+
    '<div id="load-status" style="color:var(--text);font-size:13px;font-weight:600;letter-spacing:1px;margin-bottom:16px">COLD START</div>'+
    '<div style="width:220px;height:2px;background:var(--input-border);border-radius:1px;margin:0 auto;overflow:hidden"><div id="load-bar" style="width:0%;height:100%;background:var(--text);border-radius:1px;transition:width 0.4s ease"></div></div>'+
    '<div id="load-detail" style="color:var(--text-dim);font-size:11px;margin-top:12px">awaiting fleet overview</div></div>';

  var bar=document.getElementById('load-bar');
  var status=document.getElementById('load-status');
  var detail=document.getElementById('load-detail');
  var _p=function(pct,s,d){bar.style.width=pct+'%';status.textContent=s;detail.textContent=d;};

  _p(10,'CONNECTING','awaiting fleet overview');
  var p1=_authFetch(API.FLEET_OVERVIEW).then(function(r){return r.json()}).then(function(fo){
    _fleetCache.fo=fo;_initFleetData(fo);_p(40,'FLEET',fo.summary.total_vms+' VMs, '+fo.pve_nodes.length+' nodes');
    return fo;
  }).catch(function(){_p(40,'FLEET','fleet overview unavailable');return null;});

  var p2=_authFetch(API.HEALTH).then(function(r){return r.json()}).then(function(hd){
    _fleetCache.hd=hd;
    var up=0;hd.hosts.forEach(function(h){if(h.status==='healthy')up++;});
    _p(70,'HEALTH',up+'/'+hd.hosts.length+' hosts responded');
    return hd;
  }).catch(function(){_p(70,'HEALTH','health probe unavailable');return null;});

  var p3=_authFetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(md){
    _p(85,'MEDIA',md.containers_running+' containers');
    return md;
  }).catch(function(){return null;});

  Promise.all([p1,p2,p3]).then(function(){
    _p(100,'ONLINE','operator console live');
    setTimeout(function(){
      var body=document.getElementById('mn-body');if(body)body.style.display='';
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
  _authFetch('/api/update/check').then(function(r){return r.json()}).then(function(d){
    if(d.update_available&&d.latest){
      var banner=document.getElementById('update-banner');
      var text=document.getElementById('update-banner-text');
      if(banner&&text){
        var method=window._freqInstallMethod||'unknown';
        var cmd='freq update';
        if(method==='git')cmd='cd /opt/pve-freq && git pull';
        else if(method==='docker')cmd='docker compose pull && docker compose up -d';
        else if(method==='dpkg')cmd='sudo apt update && sudo apt upgrade pve-freq';
        else if(method==='rpm')cmd='sudo dnf update pve-freq';
        else cmd='sudo bash install.sh';
        text.innerHTML='<strong>Update Available:</strong> v'+_esc(d.latest)+' &mdash; <code style="background:var(--bg);padding:2px 6px;border-radius:4px;font-size:12px">'+_esc(cmd)+'</code>';
        banner.style.display='block';
      }
    }
  }).catch(function(e){console.error('API error:',e);});
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
  {id:'w-fleet-infra',page:'FLEET',label:'Hosts & VMs & LXC',ref:'fleet-sec-infra',preload:function(){loadFleetPage();}},
  {id:'w-fleet-overview',page:'FLEET',label:'Overview',loader:function(el){
    /* Summary cards row — cluster-level stats */
    var g='<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px">';
    g+='<div class="host-card"><div class="host-head"><h3 class="c-purple">PVE NODES</h3><div class="host-meta"><span>HYPERVISOR</span></div></div><div class="divider-light"><div id="hw-pve-sum"><div class="skeleton h-60" ></div></div></div></div>';
    g+='<div class="host-card"><div class="host-head"><h3 class="c-purple">VMs</h3><div class="host-meta"><span>PROXMOX</span></div></div><div class="divider-light"><div id="hw-vms"><div class="skeleton h-60" ></div></div></div></div>';
    g+='<div class="host-card"><div class="host-head"><h3 class="c-green">MEDIA</h3><div class="host-meta"><span>CONTAINERS</span><span>·</span><span>DOCKER</span></div></div><div class="divider-light"><div id="hw-media"><div class="skeleton h-60" ></div></div></div></div></div>';
    /* Infrastructure device cards — responsive grid */
    g+='<div id="hw-physical-cards" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px"></div>';
    el.innerHTML=g;
    /* Populate physical device cards as individual grid items */
    var pc='';PROD_HOSTS.filter(function(h){return h.type!=='pve'}).forEach(function(h){var tc={pfsense:'var(--text)',truenas:'var(--blue)',switch:'var(--cyan)',idrac:'var(--orange)'}; pc+='<div class="host-card" data-host-id="'+h.label.toLowerCase()+'"><div class="host-head"><h3 style="color:'+(tc[h.type]||'var(--text)')+'">'+h.label.toUpperCase()+'</h3><div class="host-meta"><span>'+h.ip+'</span><span>·</span><span>'+h.role+'</span></div></div><div class="divider-light"><div id="hw-'+h.label.toLowerCase().replace(/[^a-z0-9]/g,'-')+'"><div class="skeleton h-60" ></div></div></div></div>';});
    var pcd=document.getElementById('hw-physical-cards');if(pcd)pcd.innerHTML=pc;
    _loadWidgetOverview();
  }},
  {id:'w-fleet-agents',page:'FLEET',label:'Agents',ref:'fleet-sec-agents',preload:function(){loadAgents();}},
  {id:'w-fleet-specialists',page:'FLEET',label:'Sandbox VMs',ref:'fleet-sec-specialists',preload:function(){loadSpecialists();}},
  {id:'w-docker-containers',page:'DOCKER',label:'Containers',loader:function(el){
    el.innerHTML='<div class="stats" id="hw-ctr-stats"></div><div id="hw-ctr-cards" class="cards"><div class="skeleton"></div></div>';
    _authFetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(d){
      var _coff2=Math.max(0,d.containers_down||0);var s=document.getElementById('hw-ctr-stats');if(s)s.innerHTML=st('Total',d.containers_total,'p')+st('Online',d.containers_running,'g')+st('Offline',_coff2,_coff2>0?'r':'g')+st('VMs',d.vm_count,'b');
    });
    _authFetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
      var h='';d.containers.forEach(function(c){h+=_containerCard(c,'');});
      var el2=document.getElementById('hw-ctr-cards');if(el2)el2.innerHTML=h||'<div class="empty-state"><p>0 containers</p></div>';
    });
  }},
  {id:'w-sec-users',page:'SECURITY',label:'Users',ref:'sec-users',preload:function(){loadUsers();}},
  {id:'w-sec-sshkeys',page:'SECURITY',label:'SSH Keys',ref:'sec-sshkeys',preload:function(){loadKeys();}},
  {id:'w-sec-apikeys',page:'SECURITY',label:'API Keys',ref:'sec-apikeys',preload:function(){loadVault();}},
  {id:'w-sec-audit',page:'SECURITY',label:'Audit',ref:'sec-audit'},
  {id:'w-sec-harden',page:'SECURITY',label:'Hardening',ref:'sec-harden'},
  {id:'w-sec-risk',page:'SECURITY',label:'Risk Analysis',ref:'sec-risk',preload:function(){loadRisk();}},
  {id:'w-sec-policies',page:'SECURITY',label:'Policies',ref:'sec-policies',preload:function(){loadPolicies();}},
  {id:'w-sec-vault',page:'SECURITY',label:'Vault',ref:'sec-vault-section'},
  {id:'w-activity-feed',page:'OPS',label:'Activity Feed',loader:function(el){
    el.innerHTML='<div id="hw-activity-list" class="activity-feed"><div class="skeleton"></div></div>';
    _loadActivityFeed();
  }},
  {id:'w-fleet-health-score',page:'FLEET',label:'Health Score',loader:function(el){
    el.innerHTML='<div id="hw-health-score"><div class="skeleton"></div></div>';
    _authFetch('/api/fleet/health-score').then(function(r){return r.json()}).then(function(d){
      var t=document.getElementById('hw-health-score');if(!t)return;
      var color=d.score>=90?'var(--green)':d.score>=75?'var(--blue)':d.score>=60?'var(--orange)':'var(--red)';
      var h='<div class="text-center" style="padding:12px 0">';
      h+='<div style="font-size:48px;font-weight:700;color:'+color+'">'+d.score+'</div>';
      h+='<div style="font-size:24px;font-weight:600;color:'+color+';margin-top:-4px">'+d.grade+'</div>';
      h+='<div class="text-sm text-dim mt-sm">Fleet Health Score</div>';
      h+='</div>';
      if(d.factors&&d.factors.length>0){
        h+='<div style="border-top:1px solid var(--border);padding-top:8px">';
        d.factors.forEach(function(f){
          h+='<div class="text-sm" style="display:flex;justify-content:space-between;padding:2px 0">';
          h+='<span class="text-dim">'+_esc(f.detail)+'</span>';
          h+='<span style="color:var(--red)">-'+f.penalty+'</span>';
          h+='</div>';
        });
        h+='</div>';
      }
      t.innerHTML=h;
    }).catch(function(e){var t=document.getElementById('hw-health-score');if(t)t.innerHTML='<div class="empty-state"><p>Score unavailable</p></div>';});
  }},
  {id:'w-vlan-topology',page:'NETWORK',label:'VLAN Topology',loader:function(el){
    el.innerHTML='<div id="hw-vlan-topo"><div class="skeleton"></div></div>';
    _authFetch('/api/fleet/topology-enhanced').then(function(r){return r.json()}).then(function(d){
      var t=document.getElementById('hw-vlan-topo');if(!t)return;
      if(!d.vlans||!d.vlans.length){t.innerHTML='<div class="empty-state"><p>0 VLANs configured</p></div>';return;}
      var h='';
      d.vlans.forEach(function(v){
        if(!v.hosts||!v.hosts.length)return;
        var color=v.id===0?'var(--text-dim)':'var(--purple-light)';
        h+='<div class="mb-md">';
        h+='<div style="font-weight:600;font-size:13px;color:'+color+'">'+_esc(v.name)+' <span style="font-size:11px" class="text-dim">VLAN '+v.id+(v.subnet?' \u2022 '+v.subnet:'')+'</span></div>';
        h+='<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px">';
        v.hosts.forEach(function(host){
          var bg=host.status==='healthy'?'rgba(50,255,50,0.1)':'rgba(255,50,50,0.1)';
          var dot=host.status==='healthy'?'\u2022':'!';
          var dotColor=host.status==='healthy'?'var(--green)':'var(--red)';
          h+='<span style="padding:2px 8px;border-radius:4px;background:'+bg+';font-size:11px"><span style="color:'+dotColor+'">'+dot+'</span> '+_esc(host.label)+'</span>';
        });
        h+='</div></div>';
      });
      if(d.nodes&&d.nodes.length){
        h+='<div style="margin-top:12px;border-top:1px solid var(--border);padding-top:8px">';
        h+='<div style="font-weight:600;font-size:13px;margin-bottom:4px">PVE Nodes</div>';
        d.nodes.forEach(function(n){
          h+='<div style="font-size:12px;padding:2px 0">'+_esc(n.name)+': '+n.running+'/'+n.vms+' VMs running</div>';
        });
        h+='</div>';
      }
      t.innerHTML=h;
    }).catch(function(e){var t=document.getElementById('hw-vlan-topo');if(t)t.innerHTML='<div class="empty-state"><p>Topology unavailable</p></div>';});
  }},
  {id:'w-ntp-status',page:'NETWORK',label:'NTP Sync Status',loader:function(el){
    el.innerHTML='<div id="hw-ntp"><div class="skeleton"></div></div>';
    _authFetch('/api/fleet/ntp').then(function(r){return r.json()}).then(function(d){
      var t=document.getElementById('hw-ntp');if(!t)return;
      if(!d.hosts||!d.hosts.length){t.innerHTML='<div class="empty-state"><p>NTP probe returned 0 hosts</p></div>';return;}
      var h='';var synced=0;
      d.hosts.forEach(function(host){
        var ok=host.synced||host.status==='synced';if(ok)synced++;
        var icon=ok?'\u2705':'\u274c';
        h+='<div class="text-sm" style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)">';
        h+='<span>'+icon+' '+_esc(host.label)+'</span>';
        h+='<span class="text-dim">'+(host.offset||host.server||'')+'</span>';
        h+='</div>';
      });
      h='<div class="text-sm text-dim mb-sm">'+synced+'/'+d.hosts.length+' synced</div>'+h;
      t.innerHTML=h;
    }).catch(function(e){var t=document.getElementById('hw-ntp');if(t)t.innerHTML='<div class="empty-state"><p>NTP probe failed \u2014 check /api/fleet/ntp</p></div>';});
  }},
  {id:'w-resource-heatmap',page:'FLEET',label:'Resource Heatmap',loader:function(el){
    el.innerHTML='<div id="hw-heatmap"><div class="skeleton"></div></div>';
    _authFetch('/api/fleet/heatmap').then(function(r){return r.json()}).then(function(d){
      var t=document.getElementById('hw-heatmap');if(!t)return;
      if(!d.hosts||!d.hosts.length){t.innerHTML='<div class="empty-state"><p>0 hosts in heatmap</p></div>';return;}
      var h='<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px">';
      d.hosts.forEach(function(host){
        var maxPct=Math.max(host.ram_pct,host.disk_pct);
        var bg=maxPct>=80?'rgba(255,50,50,0.15)':maxPct>=60?'rgba(255,165,0,0.1)':'rgba(50,255,50,0.08)';
        var border=maxPct>=80?'var(--red)':maxPct>=60?'var(--orange)':'var(--green)';
        h+='<div style="padding:8px;border:1px solid '+border+';border-radius:6px;background:'+bg+';text-align:center">';
        h+='<div style="font-size:11px;font-weight:600;margin-bottom:4px">'+_esc(host.label)+'</div>';
        h+='<div class="text-xs text-dim">RAM '+host.ram_pct+'%</div>';
        h+='<div class="text-xs text-dim">Disk '+host.disk_pct+'%</div>';
        if(host.containers>0)h+='<div class="text-xs text-dim">'+host.containers+' ctr</div>';
        h+='</div>';
      });
      h+='</div>';
      t.innerHTML=h;
    }).catch(function(e){var t=document.getElementById('hw-heatmap');if(t)t.innerHTML='<div class="empty-state"><p>heatmap probe failed \u2014 check /api/fleet/heatmap</p></div>';});
  }},
  {id:'w-stale-snapshots',page:'FLEET',label:'Stale Snapshots',loader:function(el){
    el.innerHTML='<div id="hw-stale-snaps"><div class="skeleton"></div></div>';
    _authFetch('/api/snapshots/stale?days=30').then(function(r){return r.json()}).then(function(d){
      var t=document.getElementById('hw-stale-snaps');if(!t)return;
      if(!d.stale||!d.stale.length){t.innerHTML='<div style="color:var(--text-dim);padding:8px 0;font-size:11px">0 snapshots older than 30d</div>';return;}
      var h='<div class="text-sm text-dim mb-sm">'+d.count+' snapshot(s) found</div>';
      d.stale.slice(0,20).forEach(function(s){
        h+='<div class="text-sm" style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)">';
        h+='<span><span style="font-weight:500">'+_esc(s.vm_name)+'</span> <span class="text-dim">VM '+s.vmid+'</span></span>';
        h+='<span class="text-dim">'+_esc(s.snapshot)+'</span>';
        h+='</div>';
      });
      if(d.count>20)h+='<div style="font-size:11px;color:var(--text-dim);margin-top:4px">+'+(d.count-20)+' more</div>';
      t.innerHTML=h;
    }).catch(function(e){var t=document.getElementById('hw-stale-snaps');if(t)t.innerHTML='<div class="empty-state"><p>snapshot probe failed \u2014 check /api/snapshots/stale</p></div>';});
  }},
  {id:'w-storage-health',page:'STORAGE',label:'Storage Health',loader:function(el){
    el.innerHTML='<div id="hw-storage-pools"><div class="skeleton"></div></div>';
    _authFetch('/api/storage/health').then(function(r){return r.json()}).then(function(d){
      var t=document.getElementById('hw-storage-pools');if(!t)return;
      if(!d.pools||!d.pools.length){t.innerHTML='<div class="empty-state"><p>0 storage pools detected</p></div>';return;}
      var h='<div class="text-sm text-dim mb-sm">'+d.total_tb+'TB total \u2022 '+d.used_tb+'TB used</div>';
      d.pools.forEach(function(p){
        var color=p.used_pct>=80?'var(--red)':p.used_pct>=60?'var(--orange)':'var(--green)';
        h+='<div style="padding:6px 0;border-bottom:1px solid var(--border)">';
        h+='<div style="display:flex;justify-content:space-between"><span style="font-weight:500">'+_esc(p.name)+'</span><span class="text-sm text-dim">'+p.node+'</span></div>';
        h+='<div class="flex-center" style="margin-top:4px">';
        h+='<div style="flex:1;height:6px;background:var(--border);border-radius:3px"><div style="height:100%;width:'+p.used_pct+'%;background:'+color+';border-radius:3px"></div></div>';
        h+='<span style="font-size:12px;color:'+color+'">'+p.used_pct+'%</span>';
        h+='</div>';
        h+='<div style="font-size:11px;color:var(--text-dim);margin-top:2px">'+p.used_gb+'GB / '+p.total_gb+'GB ('+p.type+')</div>';
        h+='</div>';
      });
      t.innerHTML=h;
    }).catch(function(e){var t=document.getElementById('hw-storage-pools');if(t)t.innerHTML='<div class="empty-state"><p>storage probe failed \u2014 check /api/storage/health</p></div>';});
  }},
  {id:'w-tdarr',page:'MEDIA',label:'Tdarr Transcode',loader:function(el){
    el.innerHTML='<div id="hw-tdarr"><div class="skeleton"></div></div>';
    _authFetch('/api/media/tdarr').then(function(r){return r.json()}).then(function(d){
      var t=document.getElementById('hw-tdarr');if(!t)return;
      if(d.status==='not_configured'){t.innerHTML='<div class="empty-state"><p>tdarr not installed</p></div>';return;}
      var h='<div style="display:flex;align-items:center;gap:8px;padding:8px 0">';
      h+='<span style="font-weight:500">tdarr up</span>';
      if(d.host)h+='<span class="text-sm text-dim">on '+_esc(d.host)+'</span>';
      h+='</div>';
      if(d.queue>0)h+='<div>queue: '+d.queue+' files</div>';
      if(d.processed>0)h+='<div>processed: '+d.processed+'</div>';
      t.innerHTML=h;
    }).catch(function(e){var t=document.getElementById('hw-tdarr');if(t)t.innerHTML='<div class="empty-state"><p>tdarr probe failed \u2014 check /api/media/tdarr</p></div>';});
  }},
  {id:'w-deploy-log',page:'OPS',label:'Deploy Log',loader:function(el){
    el.innerHTML='<div id="hw-deploy-log"><div class="skeleton"></div></div>';
    _authFetch('/api/deploy/log').then(function(r){return r.json()}).then(function(d){
      var t=document.getElementById('hw-deploy-log');if(!t)return;
      if(!d.commits||!d.commits.length){t.innerHTML='<div class="empty-state"><p>0 deploys recorded</p></div>';return;}
      var h='';d.commits.forEach(function(c){
        h+='<div style="display:flex;gap:8px;padding:4px 0;border-bottom:1px solid var(--border);font-size:12px">';
        h+='<code style="color:var(--purple-light);flex-shrink:0">'+c.hash+'</code>';
        h+='<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+_esc(c.message)+'</span>';
        h+='<span style="flex-shrink:0;color:var(--text-dim)">'+_esc(c.ago)+'</span>';
        h+='</div>';
      });
      t.innerHTML=h;
    }).catch(function(e){var t=document.getElementById('hw-deploy-log');if(t)t.innerHTML='<div class="empty-state"><p>deploy log probe failed \u2014 check /api/deploy/log</p></div>';});
  }},
  {id:'w-config-viewer',page:'OPS',label:'Config Viewer',loader:function(el){
    el.innerHTML='<div id="hw-config-view"><div class="skeleton"></div></div>';
    _authFetch('/api/config/view').then(function(r){return r.json()}).then(function(d){
      var t=document.getElementById('hw-config-view');if(!t)return;
      if(d.error){t.innerHTML='<div class="empty-state"><p>'+_esc(d.error)+'</p></div>';return;}
      var c=d.config;var h='';
      var kv=function(k,v){return '<div style="display:flex;justify-content:space-between;padding:3px 0" class="text-sm"><span class="text-dim">'+k+'</span><span>'+_esc(String(v))+'</span></div>';};
      h+=kv('Version',c.version);h+=kv('Brand',c.brand);h+=kv('Cluster',c.cluster_name||'(not set)');
      h+=kv('SSH Mode',c.ssh_mode);h+=kv('SSH Account',c.ssh_service_account);
      h+=kv('PVE Nodes',c.pve_nodes?c.pve_nodes.join(', '):'none');
      h+=kv('VM Defaults',c.vm_defaults.cores+' cores / '+(c.vm_defaults.ram/1024)+'GB / '+c.vm_defaults.disk+'GB');
      h+=kv('Hosts',c.hosts_count);h+=kv('VLANs',c.vlans_count);h+=kv('Monitors',c.monitors_count);
      t.innerHTML=h;
    }).catch(function(e){var t=document.getElementById('hw-config-view');if(t)t.innerHTML='<div class="empty-state"><p>config probe failed \u2014 check /api/config/view</p></div>';});
  }},
  {id:'w-vm-wizard',page:'FLEET',label:'VM Wizard',loader:function(el){
    el.innerHTML='<div id="hw-vm-wizard"><div class="skeleton"></div></div>';
    _authFetch('/api/vm/wizard-defaults').then(function(r){return r.json()}).then(function(d){
      var t=document.getElementById('hw-vm-wizard');if(!t)return;
      var h='<div class="text-sm text-dim mb-sm">Quick-create presets</div>';
      if(d.profiles){
        Object.keys(d.profiles).forEach(function(name){
          var p=d.profiles[name];
          h+='<div style="display:flex;justify-content:space-between;padding:6px 8px;border:1px solid var(--border);border-radius:6px;margin-bottom:4px;cursor:pointer" ';
          h+='onclick="document.getElementById(\'hw-vm-wizard-sel\').textContent=\''+name+': '+p.cores+'C/'+Math.round(p.ram/1024)+'G/'+p.disk+'G\'">';
          h+='<span style="font-weight:500;text-transform:capitalize">'+name+'</span>';
          h+='<span class="text-sm text-dim">'+p.cores+' cores \u2022 '+Math.round(p.ram/1024)+'GB \u2022 '+p.disk+'GB</span>';
          h+='</div>';
        });
      }
      h+='<div id="hw-vm-wizard-sel" style="margin-top:8px;font-size:12px;color:var(--purple-light)"></div>';
      h+='<div style="margin-top:8px;font-size:11px;color:var(--text-dim)">Nodes: '+(d.nodes?d.nodes.join(', '):'?')+' \u2022 '+d.distros.length+' images available</div>';
      t.innerHTML=h;
    }).catch(function(e){var t=document.getElementById('hw-vm-wizard');if(t)t.innerHTML='<div class="empty-state"><p>wizard probe failed \u2014 check /api/vm/wizard-defaults</p></div>';});
  }},
  {id:'w-monitors',page:'OPS',label:'HTTP Monitors',loader:function(el){
    el.innerHTML='<div id="hw-monitors-list"><div class="skeleton"></div></div>';
    _loadMonitorsWidget();
  }}
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
  _authFetch(API.HEALTH).then(function(r){return r.json()}).then(function(hd){
    if(!hd||!hd.hosts)hd={hosts:[],duration:0};
    var up=0,down=0,pve=0;var _homeLabLabels=_getLabLabels(hd.hosts);var lab=Object.keys(_homeLabLabels||{}).length;
    hd.hosts.forEach(function(h){if(h.status==='healthy')up++;else down++;if(h.type==='pve')pve++;});
    var totalAll=hd.hosts.length;
    var totalOff=down;var prodCount=totalAll-lab;var pveCount=PROD_HOSTS.filter(function(h){return h.type==='pve';}).length||pve;
    var _d=function(l,v1,l1,c1,v2,l2,c2){return '<div class="st"><div class="lb">'+l+'</div><div class="flex-row-24"><span class="stat-pair"><span style="font-size:20px;font-weight:700;color:'+c1+'">'+v1+'</span><span class="label-hint">'+l1+'</span></span><span class="stat-pair"><span style="font-size:20px;font-weight:700;color:'+c2+'">'+v2+'</span><span class="label-hint">'+l2+'</span></span></div></div>';};
    var el=document.getElementById('hw-fleet-stats');if(!el)return;
    var _age=Math.round(hd.age_seconds||hd.age||0);var _ageLbl=_age<60?_age+'s':Math.round(_age/60)+'m';
    /* Preserve distinct probe states — don't collapse stale/error/disk_cache into "ok" */
    var _ps=hd.probe_status||'ok';
    var _ageClr=_ps==='error'?'var(--red)':_ps==='stale'?'var(--yellow)':_age<30?'var(--green)':_age<120?'var(--yellow)':'var(--red)';
    var _probeLbl=_ps==='error'?'PROBE FAILED':_ps==='stale'?'STALE':_ps==='pending'?'CACHE WARMING':'';
    var _probeClr=_ps==='error'?'var(--red)':_ps==='stale'?'var(--yellow)':'var(--red)';
    var _sseClr=_evtSource&&_evtSource.readyState===1?'var(--green)':'var(--yellow)';var _sseLbl=_evtSource&&_evtSource.readyState===1?'LIVE':'CACHED';
    var _ldStat='<div class="st"><div class="lb">PROBE AGE</div><div class="flex-row-24"><span class="stat-pair"><span style="font-size:20px;font-weight:700;color:'+_ageClr+'">'+_ageLbl+'</span><span class="label-hint"></span></span><span class="stat-pair"><span id="sse-conn-status" style="font-size:20px;font-weight:700;color:'+(_probeLbl?_probeClr:_sseClr)+'">'+(_probeLbl||_sseLbl)+'</span><span class="label-hint"></span></span></div></div>';
    /* When probe state is stale/error, SSH PROBE label also gets dimmed so UP count
     * doesn't read as genuine-good. Operators must consult PROBE AGE for freshness. */
    var _probeCountLbl=_ps==='ok'?'SSH PROBE':'SSH PROBE ('+_ps+')';
    var _upClr=_ps==='ok'?'var(--green)':'var(--yellow)';
    el.innerHTML=_d(_probeCountLbl,up,'UP',_upClr,totalOff,'DOWN','var(--red)')+_d('FLEET',prodCount,'PROD','var(--purple-light)',lab,'LAB','var(--cyan)')+_d('PVE NODES',pveCount,'NODES','var(--purple-light)',pve,'UP','var(--cyan)')+_ldStat+st('VMs','...','p')+st('CONTAINERS','...','p')+st('ACTIVITY','...','p');
    _authFetch(API.VMS).then(function(r){return r.json()}).then(function(vd){var run=0,stop=0;vd.vms.forEach(function(v){if(v.status==='running')run++;else stop++;});
      var c=el.querySelector('.st:nth-child(5)');if(c)c.innerHTML='<div class="lb">VMs</div><div class="flex-row-24"><span class="stat-pair"><span class="stat-big-green">'+run+'</span><span class="label-hint">RUN</span></span><span class="stat-pair"><span class="stat-big-red">'+stop+'</span><span class="label-hint">STOP</span></span></div>';}).catch(function(e){console.error('API error:',e);});
    _authFetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(md){
      var _cdn=Math.max(0,md.containers_down||0);var c=el.querySelector('.st:nth-child(6)');if(c)c.innerHTML='<div class="lb">CONTAINERS</div><div class="flex-row-24"><span class="stat-pair"><span class="stat-big-green">'+(md.containers_running||0)+'</span><span class="label-hint">UP</span></span><span class="stat-pair"><span class="stat-big-red">'+_cdn+'</span><span class="label-hint">DOWN</span></span></div>';}).catch(function(e){console.error('API error:',e);});
    Promise.all([_authFetch(API.MEDIA_DOWNLOADS).then(function(r){return r.json()}).catch(function(){return{count:0}}),_authFetch(API.MEDIA_STREAMS).then(function(r){return r.json()}).catch(function(){return{count:0}})]).then(function(res){
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
  _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
    var _st=_loadSettings();var run=0,stop=0,total=0;d.vms.forEach(function(v){if(!_st.showTemplates&&v.category==='templates')return;total++;if(v.status==='running')run++;else stop++;});
    var h='';h+=_mrow('TOTAL',total+' VMs',0,'var(--purple-light)');h+=_mrow('RUNNING',run,0,'var(--green)');h+=_mrow('STOPPED',stop,0,stop>0?'var(--red)':'var(--green)');
    var ve=document.getElementById('hw-vms');if(ve)ve.innerHTML=h;
  }).catch(function(e){console.error('API error:',e);});
  /* Media */
  _authFetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(d){
    var run=d.containers_running||0,tot=d.containers_total||0,dn=Math.max(0,tot-run);
    var h='';h+=_mrow('UP',run+' / '+tot,0,'var(--green)');h+=_mrow('DOWN',dn,0,dn>0?'var(--red)':'var(--green)');h+=_mrow('VMs',d.vm_count,0,'var(--blue)');
    var me=document.getElementById('hw-media');if(me)me.innerHTML=h;
  }).catch(function(e){console.error('API error:',e);});
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
    h+='<div class="text-sm text-dim" style="margin:12px 0 6px;font-weight:600">'+page+'</div>';
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
  toast(QUICK_START_WIDGETS.length+' widgets loaded','info');
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
document.getElementById('header-tagline').textContent=rt('home');

var _currentView='home';
var _viewCleanup=[];
function _onViewCleanup(fn){_viewCleanup.push(fn);}
function _runViewCleanup(){_viewCleanup.forEach(function(fn){try{fn();}catch(e){}});_viewCleanup=[];}
var VIEW_IDS=['home','fleet','topology','capacity','network','docker','media','security','sec-hardening','sec-access','sec-vault','sec-compliance','firewall','certs','vpn','tools','playbooks','gitops','chaos','dns','dr','incidents','metrics','automation','plugins','lab','settings'];
var VIEW_TITLES={home:'HOME',fleet:'FLEET',topology:'TOPOLOGY',capacity:'CAPACITY',network:'NETWORK',docker:'DOCKER',media:'MEDIA',security:'SECURITY','sec-hardening':'HARDENING','sec-access':'ACCESS','sec-vault':'VAULT','sec-compliance':'COMPLIANCE',firewall:'FIREWALL',certs:'CERTIFICATES',vpn:'VPN',tools:'SYSTEM',playbooks:'PLAYBOOKS',gitops:'CONFIG SYNC',chaos:'CHAOS',dns:'DNS',dr:'DISASTER RECOVERY',incidents:'INCIDENTS',metrics:'METRICS',automation:'AUTOMATION',plugins:'PLUGINS',lab:'LAB',settings:'SETTINGS'};
var VIEW_LOADERS={home:function(){loadHome()},fleet:function(){loadFleetPage()},topology:function(){loadTopology()},capacity:function(){loadCapacity()},network:function(){loadNetworkPage()},docker:function(){loadDockerPage()},media:function(){loadMediaPage()},security:function(){loadSecurityOverview()},'sec-hardening':function(){loadSecHardening()},'sec-access':function(){loadSecAccess()},'sec-vault':function(){loadSecVault()},'sec-compliance':function(){loadSecCompliance()},firewall:function(){loadFirewallPage()},certs:function(){loadCertsPage()},vpn:function(){loadVpnPage()},tools:function(){loadToolsPage()},playbooks:function(){loadPlaybooks()},gitops:function(){loadGitops()},chaos:function(){loadChaos()},dns:function(){loadDnsPage()},dr:function(){loadDrPage()},incidents:function(){loadIncidentsPage()},metrics:function(){loadMetricsPage()},automation:function(){loadAutomationPage()},plugins:function(){loadPluginsPage()},lab:function(){loadLabPage()},settings:function(){loadSettingsPage()}};
/* Nav grouping — maps sub-views to their parent nav button */
var VIEW_TO_NAV={home:'home',fleet:'fleet',topology:'fleet',capacity:'fleet',network:'fleet',docker:'docker',media:'media',security:'security','sec-hardening':'security','sec-access':'security','sec-vault':'security','sec-compliance':'security',firewall:'security',certs:'security',vpn:'security',tools:'tools',playbooks:'tools',gitops:'tools',chaos:'tools',dns:'tools',dr:'tools',incidents:'tools',metrics:'tools',automation:'tools',plugins:'tools',lab:'lab',settings:'settings'};
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
      document.getElementById('header-tagline').textContent=rt(VIEW_TO_NAV[_currentView]||'home');
      _safe(VIEW_LOADERS[_currentView]||loadHome);
    }else{
      var titles={infra:'INFRASTRUCTURE',system:'SYSTEM'};
      document.getElementById('page-title').textContent=titles[p]||p;
      document.getElementById('header-tagline').textContent=rt(p);
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
function switchView(view, skipPush){
  _runViewCleanup();
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
  /* Update header subtitle — deterministic per-view label from _viewLabels */
  var tl=document.getElementById('header-tagline');
  if(tl)tl.textContent=rt(navGroup);
  /* Make sure we're on p-home */
  document.querySelectorAll('.page').forEach(function(x){x.classList.remove('active')});
  document.getElementById('p-home').classList.add('active');
  /* URL routing — push state for bookmarkable views */
  if(!skipPush){try{window.history.pushState({view:view},'','/dashboard/'+view);}catch(e){}}
  /* Load data */
  _safe(VIEW_LOADERS[view]||loadHome);
}
var showView=switchView;
function refreshCurrentView(){_safe(VIEW_LOADERS[_currentView]||loadHome);}
/* Silent background refresh — updates values in-place without rebuilding DOM.
   Health (CPU/RAM/disk): every 10s — lightweight SSH.
   Fleet overview (VM status): every 60s — heavier PVE API call. */
var _healthTimer=null,_fleetTimer=null,_healthInFlight=false,_fleetInFlight=false;
function startSilentRefresh(){
  if(_healthTimer)clearInterval(_healthTimer);
  if(_fleetTimer)clearInterval(_fleetTimer);
  _healthTimer=setInterval(_silentHealthRefresh,10000);
  _fleetTimer=setInterval(_silentFleetRefresh,45000);
}
function _silentHealthRefresh(){
  if(_healthInFlight)return;/* skip if previous call still running */
  _healthInFlight=true;
  _authFetch(API.HEALTH).then(function(r){return r.json()}).then(function(hd){
    _healthInFlight=false;
    _fleetCache.hd=hd;/* keep cache fresh */
    hd.hosts.forEach(function(h){
      var card=document.querySelector('.host-card[data-host-id="'+h.label.toLowerCase()+'"]');
      if(!card)return;
        /* Update status */
        var meta=card.querySelector('.host-meta');
        if(meta){var spans=meta.querySelectorAll('span');var last=spans[spans.length-1];
          if(last&&(last.textContent==='UP'||last.textContent==='DOWN'||last.textContent==='ONLINE'||last.textContent==='OFFLINE')){
            if(h.status==='healthy'){last.style.color='var(--green)';last.textContent='UP';}
            else{last.style.color='var(--red)';last.textContent='DOWN';}}}
        /* Update metrics in-place */
        if(h.status!=='healthy')return;
        /* Skip PVE nodes — their metrics come from the PVE API poller which
           gives real CPU%. The SSH health data uses load_average which is wrong. */
        if(h.type==='pve')return;
        var cores=parseInt(h.cores)||1;var loadVal=parseFloat(h.load)||0;
        var loadPct=cores>0?Math.min(Math.round(loadVal/cores*100),100):0;
        var ramParts=(h.ram||'').match(/(\d+)\/(\d+)/);
        var ramUsed=ramParts?parseInt(ramParts[1]):0;var ramTotal=ramParts?parseInt(ramParts[2]):1;
        var ramPct=ramTotal>0?Math.round(ramUsed/ramTotal*100):0;
        var diskPct=parseInt((h.disk||'0').replace('%',''))||0;
        card.querySelectorAll('.metric-row').forEach(function(m){
          var lbl=m.querySelector('.metric-label');var val=m.querySelector('.metric-val');var bar=m.querySelector('.pbar-fill');
          if(!lbl||!val)return;var lt=lbl.textContent.trim();
          if(lt==='CPU'){val.textContent=loadPct+'% \u00b7 '+cores+(cores>1?' Cores':' Core');if(bar){bar.style.width=loadPct+'%';bar.style.background=loadPct>=80?'var(--red)':loadPct>=50?'var(--yellow)':'var(--green)';}}
          if(lt==='RAM'){val.textContent=ramPct+'% \u00b7 '+_ramGB(ramUsed)+' / '+_ramGB(ramTotal);if(bar){bar.style.width=ramPct+'%';var isStorage=h.type==='truenas';bar.style.background=isStorage?'var(--blue)':ramPct>=80?'var(--red)':ramPct>=50?'var(--yellow)':'var(--blue)';}}
          if(lt==='DISK'){val.textContent=h.disk||'?';if(bar){bar.style.width=diskPct+'%';bar.style.background=diskPct>=90?'var(--red)':diskPct>=75?'var(--yellow)':'var(--green)';}}
        });
    });
    /* Update fleet stats online/offline counts */
    var up=0,down=0;hd.hosts.forEach(function(h){if(h.status==='healthy')up++;else down++;});
    var sumEl=document.getElementById('metrics-summary');
    if(sumEl){var sts=sumEl.querySelectorAll('.st .vl');if(sts.length>=2){sts[0].textContent=up;sts[1].textContent=down;}}
    /* Update probe age indicator */
    var _age=Math.round(hd.age_seconds||hd.age||0);var _ageLbl=_age<60?_age+'s':Math.round(_age/60)+'m';var _ageClr=hd.probe_status==='error'?'var(--red)':_age<30?'var(--green)':_age<120?'var(--yellow)':'var(--red)';
    var ldEl=document.querySelector('#hw-fleet-stats .st:nth-child(4) .stat-pair:first-child span:first-child');if(ldEl){ldEl.textContent=_ageLbl;ldEl.style.color=_ageClr;}
    var ci=document.getElementById('sse-conn-status');if(ci){if(hd.probe_status==='error'){ci.textContent='PROBE FAILED';ci.style.color='var(--red)';}else{var _live=_evtSource&&_evtSource.readyState===1;ci.textContent=_live?'LIVE':'CACHED';ci.style.color=_live?'var(--green)':'var(--yellow)';}}
  }).catch(function(){_healthInFlight=false;});
}
function _silentFleetRefresh(){
  if(_fleetInFlight)return;
  _fleetInFlight=true;
  _authFetch(API.FLEET_OVERVIEW).then(function(r){return r.json()}).then(function(fo){
    _fleetInFlight=false;
    _fleetCache.fo=fo;/* keep cache fresh */
    if(!fo||!fo.vms)return;
    /* Update VM status badges + resource bars in PVE node sections */
    fo.vms.forEach(function(v){
      var card=document.querySelector('.host-card[data-host-id="'+v.name.toLowerCase()+'"]');
      if(!card)return;
        var meta=card.querySelector('.host-meta');
        if(!meta)return;
        var spans=meta.querySelectorAll('span');
        var running=v.status==='running';
        spans.forEach(function(sp){
          if(sp.textContent==='RUNNING'||sp.textContent==='STOPPED'){
            if(running){sp.textContent='RUNNING';sp.style.color='var(--green)';}
            else{sp.textContent=v.status.toUpperCase();sp.style.color='var(--red)';}
          }
        });
        /* Update CPU/RAM bars in-place — smooth, no flicker */
        var cpuPct=running?Math.round(v.cpu_pct||0):0;
        var ramPct=running?Math.round(v.ram_pct||0):0;
        card.querySelectorAll('.metric-row').forEach(function(m){
          var lbl=m.querySelector('.metric-label');
          var val=m.querySelector('.metric-val');
          var bar=m.querySelector('.pbar-fill');
          if(!lbl||!val)return;
          var lt=lbl.textContent.trim();
          if(lt==='CPU'){
            val.textContent=running?cpuPct+'% \u00b7 '+(v.cpu||0)+' Cores':(v.cpu||0)+' Cores';
            if(bar){bar.style.width=cpuPct+'%';bar.style.background=cpuPct>=90?'var(--red)':cpuPct>=75?'var(--yellow)':'var(--green)';}
          }
          if(lt==='RAM'){
            val.textContent=running?ramPct+'% \u00b7 '+_ramGB(v.ram_used_mb||0)+' / '+_ramGB(v.ram_mb||0):_ramGB(v.ram_mb||0);
            if(bar){bar.style.width=ramPct+'%';bar.style.background=ramPct>=90?'var(--red)':ramPct>=75?'var(--yellow)':'var(--blue)';}
          }
        });
    });
    /* Fleet data freshness — show probe errors on fleet overview */
    if(fo.probe_status==='error'){
      toast('Fleet probe failed'+(fo.probe_error?' — '+fo.probe_error:''),'error');
      var ci=document.getElementById('sse-conn-status');
      if(ci){ci.textContent='PROBE FAILED';ci.style.color='var(--red)';}
    }
  }).catch(function(){_fleetInFlight=false;});
}
startSilentRefresh();

/* === Skeleton Timeout ===
   If any skeleton loader is still visible after 15s, the API call failed
   silently (no .catch handler). Replace with a "Load failed" message so
   the operator knows something is wrong, not staring at an eternal spinner. */
setInterval(function(){
  document.querySelectorAll('.skeleton').forEach(function(el){
    if(!el.dataset.skelTs){el.dataset.skelTs=Date.now();return;}
    if(Date.now()-parseInt(el.dataset.skelTs)>15000){
      el.outerHTML='<span style="color:var(--text-dim);font-size:11px">Load failed — refresh to retry</span>';
    }
  });
},5000);

/* === PVE Node Real-Time Metrics ===
   Polls /api/pve/metrics every 5s for live CPU/RAM/DISK from PVE API.
   Updates node card progress bars in-place — smooth, no flicker. */
var _pveMetricsTimer=null;
function _pveMetricsRefresh(){
  _authFetch('/api/pve/metrics').then(function(r){return r.json()}).then(function(d){
    if(!d.nodes)return;
    d.nodes.forEach(function(n){
      if(!n.online)return;
      /* Find the host card for this PVE node by data attribute */
      var card=document.querySelector('.host-card[data-host-id="'+n.name.toLowerCase()+'"]');
      if(!card)return;
        /* Update metric rows in-place — all from PVE API, same as PVE web UI */
        card.querySelectorAll('.metric-row').forEach(function(m){
          var lbl=m.querySelector('.metric-label');
          var val=m.querySelector('.metric-val');
          var bar=m.querySelector('.pbar-fill');
          if(!lbl||!val)return;
          var lt=lbl.textContent.trim();
          if(lt==='CPU'){
            var cpuColor=n.cpu_pct>=80?'var(--red)':n.cpu_pct>=50?'var(--yellow)':'var(--green)';
            val.textContent=n.cpu_pct+'% \u00b7 '+n.cores+(n.cores>1?' Cores':' Core');
            if(bar){bar.style.width=n.cpu_pct+'%';bar.style.background=cpuColor;}
          }
          if(lt==='RAM'){
            var ramColor=n.ram_pct>=80?'var(--red)':n.ram_pct>=50?'var(--yellow)':'var(--blue)';
            val.textContent=n.ram_pct+'% \u00b7 '+n.ram_used_gb+'G / '+n.ram_total_gb+'G';
            if(bar){bar.style.width=n.ram_pct+'%';bar.style.background=ramColor;}
          }
          if(lt==='DISK IO'){
            var io=n.iowait||0;
            var ioColor=io>=50?'var(--red)':io>=20?'var(--yellow)':io>=5?'var(--orange)':'var(--cyan)';
            val.textContent=io+'% IO WAIT';
            if(bar){bar.style.width=io+'%';bar.style.background=ioColor;}
          }
          if(lt==='STORAGE'){
            var sPct=0;var sLabel='...';
            if(n.storage&&n.storage.length){
              var main=n.storage.find(function(s){return s.type==='lvmthin'||s.type==='zfspool'||s.type==='lvm'})||n.storage[0];
              sPct=main.pct;sLabel=main.pct+'% \u00b7 '+main.used_gb+'G / '+main.total_gb+'G \u00b7 '+main.name;
            }
            var sColor=sPct>=90?'var(--red)':sPct>=75?'var(--yellow)':'var(--green)';
            val.textContent=sLabel;
            if(bar){bar.style.width=sPct+'%';bar.style.background=sColor;}
          }
        });
        /* Update the utilization stats in the grid above the bars */
        var statSpans=card.querySelectorAll('.text-center');
        statSpans.forEach(function(s){
          var label=s.querySelector('div:last-child');
          var value=s.querySelector('div:first-child');
          if(!label||!value)return;
          var lt=label.textContent.trim();
          if(lt==='CPU LOAD'){
            var cpuColor=n.cpu_pct>=80?'var(--red)':n.cpu_pct>=50?'var(--yellow)':'var(--green)';
            value.textContent=n.cpu_pct+'%';value.style.color=cpuColor;
          }
          if(lt==='RAM USED'){
            var ramColor=n.ram_pct>=80?'var(--red)':n.ram_pct>=50?'var(--yellow)':'var(--blue)';
            value.textContent=n.ram_pct+'%';value.style.color=ramColor;
          }
        });
    });
  }).catch(function(e){console.error('API error:',e);});
}
function startPveMetrics(){
  /* Delay first call 2s to avoid login burst — let page render first */
  setTimeout(function(){
    _pveMetricsRefresh();
    if(_pveMetricsTimer)clearInterval(_pveMetricsTimer);
    _pveMetricsTimer=setInterval(_pveMetricsRefresh,5000);
  },2000);
}
/* startPveMetrics() called from loadFleetPage() after cards render */

/* === Sparkline Mini-Charts ===
   Canvas-based sparklines for PVE node cards.
   Fetches /api/pve/rrd every 60s — 1 hour of CPU/RAM/IO history.
   Renders inline on node cards next to the metric bars. */
function _sparkline(canvas,points,color,fillColor){
  if(!canvas||!points||points.length<2)return;
  var ctx=canvas.getContext('2d');
  var w=canvas.width;var h=canvas.height;
  var dpr=window.devicePixelRatio||1;
  canvas.width=w*dpr;canvas.height=h*dpr;
  canvas.style.width=w+'px';canvas.style.height=h+'px';
  ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,w,h);
  var vals=points.map(function(p){return p.v;});
  var mn=Math.min.apply(null,vals);
  var mx=Math.max.apply(null,vals);
  if(mx===mn)mx=mn+1;/* avoid division by zero */
  var pad=1;/* 1px padding */
  var range=mx-mn;
  var stepX=(w-pad*2)/(vals.length-1);
  /* Draw fill */
  ctx.beginPath();
  ctx.moveTo(pad,h-pad);
  vals.forEach(function(v,i){
    var x=pad+i*stepX;
    var y=h-pad-(v-mn)/range*(h-pad*2);
    if(i===0)ctx.lineTo(x,y);else ctx.lineTo(x,y);
  });
  ctx.lineTo(pad+(vals.length-1)*stepX,h-pad);
  ctx.closePath();
  ctx.fillStyle=fillColor||'rgba(168,85,247,0.08)';
  ctx.fill();
  /* Draw line */
  ctx.beginPath();
  vals.forEach(function(v,i){
    var x=pad+i*stepX;
    var y=h-pad-(v-mn)/range*(h-pad*2);
    if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
  });
  ctx.strokeStyle=color||getComputedStyle(document.documentElement).getPropertyValue('--purple-light').trim()||'#a78bfa';
  ctx.lineWidth=1.5;
  ctx.lineJoin='round';
  ctx.stroke();
  /* Draw current value dot */
  var lastX=pad+(vals.length-1)*stepX;
  var lastY=h-pad-(vals[vals.length-1]-mn)/range*(h-pad*2);
  ctx.beginPath();
  ctx.arc(lastX,lastY,2,0,Math.PI*2);
  ctx.fillStyle=color;
  ctx.fill();
}
var _rrdCache={};var _rrdTimer=null;
function _fetchRrdData(){
  _authFetch('/api/pve/rrd').then(function(r){return r.json()}).then(function(d){
    if(!d.nodes)return;
    d.nodes.forEach(function(n){_rrdCache[n.name]=n;});
    _renderSparklines();
  }).catch(function(e){console.error('API error:',e);});
}
function _renderSparklines(){
  Object.keys(_rrdCache).forEach(function(nodeName){
    var nd=_rrdCache[nodeName];
    /* Find the node card by data attribute */
    var card=document.querySelector('.host-card[data-host-id="'+nodeName.toLowerCase()+'"]');
    if(!card)return;
      /* Find or create sparkline container */
      var sparkDiv=card.querySelector('.sparkline-row');
      if(!sparkDiv){
        /* Insert after the metric rows */
        var metricParent=card.querySelector('.divider-light');
        if(!metricParent){
          /* Try the margin container for metric rows */
          var mRows=card.querySelectorAll('.metric-row');
          if(mRows.length)metricParent=mRows[mRows.length-1].parentElement;
        }
        if(!metricParent)return;
        sparkDiv=document.createElement('div');
        sparkDiv.className='sparkline-row';
        /* sparkline-row class handles flex/gap/margin/padding/border */
        sparkDiv.innerHTML=
          '<div style="flex:1;min-width:0"><div class="spark-label">CPU 1H</div><canvas class="spark-cpu" width="120" height="28" style="width:100%;height:28px;border-radius:3px"></canvas></div>'+
          '<div style="flex:1;min-width:0"><div class="spark-label">RAM 1H</div><canvas class="spark-ram" width="120" height="28" style="width:100%;height:28px;border-radius:3px"></canvas></div>'+
          '<div style="flex:1;min-width:0"><div class="spark-label">IO 1H</div><canvas class="spark-io" width="120" height="28" style="width:100%;height:28px;border-radius:3px"></canvas></div>';
        metricParent.appendChild(sparkDiv);
      }
      /* Render each sparkline */
      var cpuCanvas=sparkDiv.querySelector('.spark-cpu');
      var ramCanvas=sparkDiv.querySelector('.spark-ram');
      var ioCanvas=sparkDiv.querySelector('.spark-io');
      if(cpuCanvas&&nd.cpu&&nd.cpu.length>1){
        cpuCanvas.width=cpuCanvas.parentElement.offsetWidth||120;
        _sparkline(cpuCanvas,nd.cpu,'#22C55E','rgba(34,197,94,0.08)');
      }
      if(ramCanvas&&nd.ram&&nd.ram.length>1){
        ramCanvas.width=ramCanvas.parentElement.offsetWidth||120;
        _sparkline(ramCanvas,nd.ram,'#3B82F6','rgba(59,130,246,0.08)');
      }
      if(ioCanvas&&nd.iowait&&nd.iowait.length>1){
        ioCanvas.width=ioCanvas.parentElement.offsetWidth||120;
        _sparkline(ioCanvas,nd.iowait,'#F97316','rgba(249,115,22,0.08)');
      }
  });
}
function startSparklines(){
  /* Delay 5s — let node cards render first */
  setTimeout(function(){
    _fetchRrdData();
    if(_rrdTimer)clearInterval(_rrdTimer);
    _rrdTimer=setInterval(_fetchRrdData,60000);/* refresh every 60s */
  },5000);
}
startSparklines();

/* === SSE Live Updates ===
   EventSource connects to /api/events for push updates.
   When connected, polling slows to fallback intervals.
   On disconnect, original polling intervals are restored. */
var _evtSource=null;
function startSSE(){
  if(typeof EventSource==='undefined')return;/* browser doesn't support SSE */
  if(_evtSource)_evtSource.close();
  _evtSource=new EventSource(API.EVENTS);/* auth via cookie */

  _evtSource.addEventListener('cache_update',function(e){
    var d=JSON.parse(e.data);
    if(d.key==='health')_silentHealthRefresh();
    if(d.key==='fleet_overview')_silentFleetRefresh();
    if(d.key==='infra_quick'&&_currentView==='infra')_safe(VIEW_LOADERS.infra||loadHome);
  });

  _evtSource.addEventListener('health_change',function(e){
    var d=JSON.parse(e.data);
    var label=d['new']==='healthy'?'UP':'DOWN';
    toast(d.host+': SSH probe '+label,d['new']==='healthy'?'success':'error');
  });

  _evtSource.addEventListener('probe_error',function(e){
    var d=JSON.parse(e.data);
    toast('Probe failed: '+d.key+(d.consecutive>1?' ('+d.consecutive+'x)':''),'error');
    /* Update LIVE DATA indicator if visible */
    var ldEl=document.querySelector('#hw-fleet-stats .st:nth-child(4) .stat-pair:first-child span:first-child');
    if(ldEl){ldEl.textContent='STALE';ldEl.style.color='var(--red)';}
    var ci=document.getElementById('sse-conn-status');
    if(ci){ci.textContent='PROBE FAILED';ci.style.color='var(--red)';}
  });

  _evtSource.addEventListener('vm_state',function(e){
    var d=JSON.parse(e.data);
    var label=d.name||('VM '+d.vmid);
    toast(label+': '+d.old+' \u2192 '+d['new'],'info');
  });

  _evtSource.addEventListener('alert',function(e){
    var d=JSON.parse(e.data);
    toast('Alert: '+d.message,'error');
  });

  _evtSource.addEventListener('activity',function(e){
    var d=JSON.parse(e.data);
    if(d.severity==='error')toast(d.message,'error');
    else if(d.severity==='warning')toast(d.message,'warn');
    _updateActivityWidget(d);
  });

  _evtSource.addEventListener('capacity_update',function(e){
    var d=JSON.parse(e.data);
    toast('Capacity snapshot saved','info');
  });

  _evtSource.addEventListener('rule_fired',function(e){
    var d=JSON.parse(e.data);
    toast('Rule fired: '+d.rule,'warn');
  });

  _evtSource.addEventListener('playbook_complete',function(e){
    var d=JSON.parse(e.data);
    toast('Playbook completed: '+d.name,d.ok?'success':'error');
  });

  _evtSource.addEventListener('gitops_sync',function(e){
    var d=JSON.parse(e.data);
    toast('GitOps sync: '+d.status,'info');
  });

  _evtSource.onopen=function(){
    /* SSE connected — slow down polling to safety fallback */
    if(_healthTimer)clearInterval(_healthTimer);
    if(_fleetTimer)clearInterval(_fleetTimer);
    _healthTimer=setInterval(_silentHealthRefresh,30000);
    _fleetTimer=setInterval(_silentFleetRefresh,90000);
    /* Catch up on any events missed during disconnect gap */
    _silentHealthRefresh();_silentFleetRefresh();
    /* Update connection indicator */
    var ci=document.getElementById('sse-conn-status');
    if(ci){ci.textContent='LIVE';ci.style.color='var(--green)';}
  };

  _evtSource.onerror=function(){
    /* SSE disconnected — restore fast polling until reconnect */
    if(_healthTimer)clearInterval(_healthTimer);
    if(_fleetTimer)clearInterval(_fleetTimer);
    _healthTimer=setInterval(_silentHealthRefresh,10000);
    _fleetTimer=setInterval(_silentFleetRefresh,45000);
    /* Update connection indicator */
    var ci=document.getElementById('sse-conn-status');
    if(ci){ci.textContent='CACHED';ci.style.color='var(--yellow)';}
  };
}
startSSE();

/* === Page composite loaders === */
function renderGlobalSettings(){
  var s=_loadSettings();
  var hoverOn=s.hoverFx!==false;
  var _toggle=function(id,label,desc,checked,onchange){
    var on=checked;
    return '<div class="flex-between" style="padding:12px 0;border-bottom:1px solid var(--border)">'+
      '<div><div style="font-size:13px;font-weight:600;color:var(--text)">'+label+'</div><div class="text-meta">'+desc+'</div></div>'+
      '<label style="position:relative;width:44px;height:24px;cursor:pointer;display:block;flex-shrink:0">'+
      '<input type="checkbox" id="'+id+'" '+(on?'checked':'')+' onchange="'+onchange+'" class="d-none">'+
      '<span style="position:absolute;inset:0;background:'+(on?'var(--purple)':'var(--input-border)')+';border-radius:12px;transition:background 0.2s"></span>'+
      '<span style="position:absolute;top:3px;left:'+(on?'23px':'3px')+';width:18px;height:18px;background:var(--text);border-radius:50%;transition:left 0.2s"></span>'+
      '</label></div>';
  };
  var showTpl=s.showTemplates===true;
  var h='';
  var compactOn=s.compactMode===true;
  h+=_toggle('set-hover','Hover Effects','Cards lift and glow purple on hover',hoverOn,"saveSetting('hoverFx',this.checked)");
  h+=_toggle('set-tpl','Show Template VMs','Include template VMs (9000+) in counts and VM lists',showTpl,"saveSetting('showTemplates',this.checked);refreshCurrentView()");
  h+=_toggle('set-compact','Compact Mode','Reduce padding and font sizes for dense layouts',compactOn,"saveSetting('compactMode',this.checked);_applyCompactMode(this.checked)");
  var el=document.getElementById('global-settings-body');
  if(el)el.innerHTML=h;
}
function _applyCompactMode(on){
  if(on)document.body.classList.add('compact');
  else document.body.classList.remove('compact');
}
/* Apply compact mode on load if saved */
(function(){var s=_loadSettings();if(s&&s.compactMode)_applyCompactMode(true);})();
function loadFleetPage(){
  /* Render from cache immediately if available — never show skeletons on page switch */
  if(_fleetCache.fo||_fleetCache.hd){
    _renderFleetData(_fleetCache.fo,_fleetCache.hd);
  } else {
    document.getElementById('metrics-summary').innerHTML='<div class="skeleton h-50" ></div>';
    document.getElementById('metrics-cards').innerHTML='<div class="skeleton"></div><div class="skeleton"></div>';
  }
  loadMetricsQuick();loadAgents();loadSpecialists();loadLxcContainers();startPveMetrics();
  /* Overview cards — render immediately if cached, otherwise fetch */
  if(_fleetCache.fo){_renderFleetOverview(_fleetCache.fo);_loadFleetOverviewMedia();}
  else{_authFetch(API.FLEET_OVERVIEW).then(function(r){return r.json()}).then(function(fo){_fleetCache.fo=fo;_renderFleetOverview(fo);_loadFleetOverviewMedia();}).catch(function(e){console.error('Fleet overview load failed:',e);});}
}
function _loadFleetOverviewMedia(){
  _authFetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(d){
    var h='';
    var _dn=Math.max(0,d.containers_total-d.containers_running);
    h+=_mrow('UP',d.containers_running+' / '+d.containers_total,0,'var(--green)');
    h+=_mrow('DOWN',_dn,0,_dn>0?'var(--red)':'var(--green)');
    h+=_mrow('VMs',d.vm_count,0,'var(--blue)');
    var me=document.getElementById('home-media');if(me)me.innerHTML=h;
  }).catch(function(){var me=document.getElementById('home-media');if(me)me.innerHTML='<span class="c-dim-fs12">NO MEDIA DATA</span>';});
}
function _renderFleetOverview(fo){
    if(!fo)return;
    /* Show fleet probe error if present */
    if(fo.probe_status==='error'){
      var ci=document.getElementById('sse-conn-status');
      if(ci){ci.textContent='PROBE FAILED';ci.style.color='var(--red)';}
    }
    fo.summary=fo.summary||{};fo.pve_nodes=fo.pve_nodes||[];fo.physical=fo.physical||[];
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
    if(pfDev){pf+=_mrow('DEVICE',pfDev.detail,0,'var(--purple-light)');pf+=_mrow('IP',pfDev.ip,0,'var(--purple-light)');pf+=_mrow('STATUS',pfDev.reachable?'REACHABLE':'UNREACHABLE',0,pfDev.reachable?'var(--green)':'var(--red)');}
    var pfe=document.getElementById('home-pfsense');if(pfe)pfe.innerHTML=pf||'<span class="c-dim-fs12">N/A</span>';
    /* TrueNAS */
    var tnDev=fo.physical?fo.physical.find(function(p){return p.type==='truenas'}):null;
    var tn='';
    if(tnDev){tn+=_mrow('DEVICE',tnDev.detail,0,'var(--purple-light)');tn+=_mrow('IP',tnDev.ip,0,'var(--purple-light)');tn+=_mrow('STATUS',tnDev.reachable?'REACHABLE':'UNREACHABLE',0,tnDev.reachable?'var(--green)':'var(--red)');}
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
  ['all','services','registry','compose','fleet-inv'].forEach(function(s){var el=document.getElementById('docker-sub-'+s);if(el){if(s===sub){el.classList.remove('d-none');el.style.display='';}else{el.classList.add('d-none');el.style.display='';}}});
  document.querySelectorAll('.docker-sub').forEach(function(b){b.classList.remove('active-view');});
  var btn=document.querySelector('.docker-sub[data-dsub="docker-'+sub+'"]');if(btn)btn.classList.add('active-view');
  if(sub==='services')loadServiceContainers();
  if(sub==='registry')loadContainerRegistry();
  if(sub==='compose')loadComposeVMs();
  if(sub==='fleet-inv')loadDockerFleet();
}
var _serverMediaTags=null;
function _getMediaTags(){if(_serverMediaTags!==null)return _serverMediaTags;try{return JSON.parse(localStorage.getItem('freq_media_tags')||'[]');}catch(e){return [];}}
function _setMediaTags(tags){_serverMediaTags=tags;localStorage.setItem('freq_media_tags',JSON.stringify(tags));_authFetch('/api/media/tags',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tags:tags})}).catch(function(e){console.error('media tags error:',e);});}
function _loadServerMediaTags(){_authFetch('/api/media/tags').then(function(r){return r.json()}).then(function(d){if(d.tags&&d.tags.length){_serverMediaTags=d.tags;localStorage.setItem('freq_media_tags',JSON.stringify(d.tags));}}).catch(function(e){console.error('media tags error:',e);});}
var _mediaCache=null;/* cached /api/media/status response */
var _mediaCacheTs=0;/* timestamp when media cache was last fetched */
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
  document.getElementById('media-container-cards').innerHTML=html||'<div class="empty-state"><p>0 containers tagged media. tag from ALL CONTAINERS view.</p></div>';
}
function _renderServicesFromCache(){
  if(!_mediaCache)return;
  var tags=_getMediaTags();var html='';
  _mediaCache.containers.forEach(function(c){if(tags.indexOf(c.name)>=0)return;
    var tagBtn='<button data-action="toggleMediaTag" data-arg="'+c.name+'" style="background:none;border:2px solid var(--input-border);border-radius:6px;padding:4px 6px;cursor:pointer;font-size:14px;margin-left:auto;opacity:0.4;transition:opacity 0.2s" onmouseover="this.style.opacity=\'0.8\'" onmouseout="this.style.opacity=\'0.4\'" title="Tag as media">&#127909;</button>';
    html+=_containerCard(c,tagBtn);});
  document.getElementById('services-container-cards').innerHTML=html||'<div class="empty-state"><p>0 service containers \u2014 all containers carry media tags</p></div>';
}
function _renderAllFromCache(){
  if(!_mediaCache)return;
  var html='';
  _mediaCache.containers.forEach(function(c){
    var isMedia=_getMediaTags().indexOf(c.name)>=0;
    var tagBtn='<button data-action="toggleMediaTag" data-arg="'+c.name+'" style="background:none;border:2px solid '+(isMedia?'var(--purple)':'var(--input-border)')+';border-radius:6px;padding:4px 6px;cursor:pointer;font-size:14px;margin-left:auto;opacity:'+(isMedia?'1':'0.4')+';transition:opacity 0.2s" onmouseover="this.style.opacity=\'0.8\'" onmouseout="this.style.opacity=\''+(isMedia?'1':'0.4')+'\'" title="'+(isMedia?'Remove media tag':'Tag as media')+'">&#127909;</button>';
    html+=_containerCard(c,tagBtn);});
  document.getElementById('container-cards').innerHTML=html||'<div class="empty-state"><p>0 containers returned by probe</p></div>';
}
function loadMediaContainers(){
  var stale=_mediaCache&&(Date.now()/1000-_mediaCacheTs)>60;
  if(_mediaCache&&!stale){_renderMediaFromCache();return;}
  _authFetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
    _mediaCache=d;_mediaCacheTs=Date.now()/1000;_renderMediaFromCache();
  });
}
function loadServiceContainers(){
  var stale=_mediaCache&&(Date.now()/1000-_mediaCacheTs)>60;
  if(_mediaCache&&!stale){_renderServicesFromCache();return;}
  _authFetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
    _mediaCache=d;_mediaCacheTs=Date.now()/1000;_renderServicesFromCache();
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
  var crdCls='crd'+(c.status==='up'?' crd-up':c.status==='down'?' crd-down':'');
  var h='<div class="'+crdCls+'" style="display:flex;flex-direction:column"><div class="flex-between"><h3 style="text-transform:uppercase">'+c.name+'</h3>'+badge(c.status)+'</div>';
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
  _loadServerMediaTags();
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
  _authFetch('/api/containers/registry').then(function(r){return r.json()}).then(function(d){
    if(!d.containers||d.containers.length===0){tbl.innerHTML=d.registry_configured===false?'<span class="c-dim-fs12">Container registry not configured — populate <code>conf/containers.toml</code></span>':'<span class="c-dim-fs12">No containers registered</span>';return;}
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
  _authFetch('/api/containers/edit?name='+encodeURIComponent(name)+'&old_vm_id='+oldVmId+'&new_vm_id='+newVmId+'&port='+port+'&api_path='+encodeURIComponent(apiPath),{method:'POST'})
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){toast(d.error,'error');return;}
    toast(name+' updated','success');closeModal();_mediaCache=null;loadContainerRegistry();loadContainerSection();
  });
}
/* ── Compose Management ────────────────────────────────────────── */
function loadComposeVMs(){
  var sel=document.getElementById('compose-vm-select');if(!sel)return;
  sel.innerHTML='<option value="">Loading...</option>';
  _authFetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
    var seen={};sel.innerHTML='<option value="">Select Docker VM...</option>';
    d.containers.forEach(function(c){if(!seen[c.vm_id]){seen[c.vm_id]=true;sel.innerHTML+='<option value="'+c.vm_id+'">'+_esc(c.vm_label)+' ('+c.vm_id+')</option>';}});
    if(!Object.keys(seen).length)sel.innerHTML='<option value="">No Docker VMs found</option>';
  }).catch(function(){sel.innerHTML='<option value="">Failed to load VMs</option>';});
}
function _getComposeVmId(){var v=(document.getElementById('compose-vm-select')||{}).value;if(!v){toast('Select a Docker VM','error');}return v;}
function composeUp(){
  var vmid=_getComposeVmId();if(!vmid)return;
  var out=document.getElementById('compose-out');if(out)out.innerHTML='<span class="c-yellow">Running compose up on VM '+vmid+'...</span>';
  _authFetch(API.COMPOSE_UP+'?vm_id='+vmid,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Compose up complete on '+d.vm,'success');if(out)out.innerHTML='<pre style="font-size:11px;color:var(--green);white-space:pre-wrap;margin:0">'+_esc(d.output||'Compose up complete')+'</pre>';}
    else{toast('Compose up failed','error');if(out)out.innerHTML='<pre style="font-size:11px;color:var(--red);white-space:pre-wrap;margin:0">'+_esc(d.error||'Unknown error')+'</pre>';}
  }).catch(function(e){toast('Compose up failed','error');if(out)out.innerHTML='<span class="c-red">'+e+'</span>';});
}
function composeDown(){
  var vmid=_getComposeVmId();if(!vmid)return;
  confirmAction('Bring down all compose services on VM <strong>'+vmid+'</strong>?',function(){
    var out=document.getElementById('compose-out');if(out)out.innerHTML='<span class="c-yellow">Running compose down on VM '+vmid+'...</span>';
    _authFetch(API.COMPOSE_DOWN+'?vm_id='+vmid,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast('Compose down complete on '+d.vm,'success');if(out)out.innerHTML='<pre style="font-size:11px;color:var(--green);white-space:pre-wrap;margin:0">'+_esc(d.output||'Compose down complete')+'</pre>';}
      else{toast('Compose down failed','error');if(out)out.innerHTML='<pre style="font-size:11px;color:var(--red);white-space:pre-wrap;margin:0">'+_esc(d.error||'Unknown error')+'</pre>';}
    }).catch(function(e){toast('Compose down failed','error');if(out)out.innerHTML='<span class="c-red">'+e+'</span>';});
  });
}
function composeView(){
  var vmid=_getComposeVmId();if(!vmid)return;
  var out=document.getElementById('compose-out');if(out)out.innerHTML='<span class="c-yellow">Loading compose file from VM '+vmid+'...</span>';
  _authFetch(API.COMPOSE_VIEW+'?vm_id='+vmid).then(function(r){return r.json()}).then(function(d){
    if(d.ok){if(out)out.innerHTML='<div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">'+_esc(d.vm)+' — docker-compose.yml</div><pre style="font-size:11px;color:var(--text);white-space:pre-wrap;margin:0;background:var(--bg2);padding:12px;border-radius:6px;border:1px solid var(--border);max-height:500px;overflow:auto">'+_esc(d.content)+'</pre>';}
    else{toast(d.error||'Failed to load compose file','error');if(out)out.innerHTML='<span class="c-red">'+(d.error||'Compose file not found')+'</span>';}
  }).catch(function(e){toast('Failed to load compose file','error');if(out)out.innerHTML='<span class="c-red">'+e+'</span>';});
}
function rescanContainers(){
  var st=document.getElementById('registry-status');
  var res=document.getElementById('rescan-results');
  if(st)st.textContent='Scanning fleet...';
  _authFetch('/api/containers/rescan',{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(st)st.textContent='Scan complete';
    if(!res)return;
    var h='';
    if(d.stale&&d.stale.length>0){
      h+='<div class="mb-sm"><strong style="color:var(--red)">Stale (not found on VM):</strong></div>';
      h+='<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">';
      d.stale.forEach(function(s){
        h+='<button class="fleet-btn" style="font-size:11px;border-color:var(--red);color:var(--red)" onclick="deleteContainer(\''+_esc(s.name)+'\','+s.vm_id+');rescanContainers()">Remove '+_esc(s.name)+' from '+_esc(s.vm_label)+'</button>';
      });
      h+='</div>';
    }
    if(d.new&&d.new.length>0){
      h+='<div class="mb-sm"><strong style="color:var(--green)">New (found but not registered):</strong></div>';
      h+='<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">';
      d.new.forEach(function(n){
        h+='<button class="fleet-btn" style="font-size:11px;border-color:var(--green);color:var(--green)" onclick="addContainerQuick(\''+_esc(n.name)+'\','+n.vm_id+')">Add '+_esc(n.name)+' to '+_esc(n.vm_label)+'</button>';
      });
      h+='</div>';
    }
    if(!d.stale.length&&!d.new.length){h='<span class="c-green text-sm">Registry is in sync with fleet</span>';}
    res.innerHTML=h;res.style.display='block';
  }).catch(function(e){if(st)st.textContent='Scan failed: '+e;});
}
function deleteContainer(name,vmId){
  if(!confirm('Remove "'+name+'" from registry?'))return;
  _authFetch('/api/containers/delete?name='+encodeURIComponent(name)+'&vm_id='+vmId,{method:'POST'})
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
  _authFetch('/api/containers/add?name='+encodeURIComponent(name)+'&vm_id='+vmId+'&port='+port,{method:'POST'})
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){if(msg)msg.innerHTML='<span class="c-red">'+d.error+'</span>';return;}
    if(msg)msg.innerHTML='<span class="c-green">Added</span>';
    document.getElementById('reg-name').value='';document.getElementById('reg-port').value='';
    _mediaCache=null;loadContainerRegistry();loadContainerSection();
  });
}
function addContainerQuick(name,vmId){
  _authFetch('/api/containers/add?name='+encodeURIComponent(name)+'&vm_id='+vmId+'&port=0',{method:'POST'})
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){toast(d.error,'error');return;}
    toast(name+' registered','success');_mediaCache=null;loadContainerRegistry();rescanContainers();
  });
}
function loadDockerFleet(){
  var stats=document.getElementById('docker-fleet-stats');
  var tbl=document.getElementById('docker-fleet-table');
  if(tbl)tbl.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch(API.DOCKER_FLEET).then(function(r){return r.json()}).then(function(d){
    var vms=d.vms||[];var total=d.total_containers||0;var running=d.running||0;
    if(stats)stats.innerHTML=_statCards([{l:'Docker VMs',v:vms.length},{l:'Total Containers',v:total},{l:'Running',v:running,c:'green'},{l:'Stopped',v:total-running,c:total-running>0?'yellow':'green'}]);
    if(!vms.length){if(tbl)tbl.innerHTML='<div class="exec-out">No Docker VMs found in fleet.</div>';return;}
    var h='';
    vms.forEach(function(vm){
      h+='<div style="margin-bottom:16px"><h4 style="color:var(--purple-light);margin-bottom:8px">'+_esc(vm.label||vm.host)+' <span style="color:var(--text-dim);font-weight:400;font-size:11px">('+_esc(vm.ip||'')+')</span></h4>';
      var containers=vm.containers||[];
      if(!containers.length){h+='<div class="exec-out">No containers found</div>';h+='</div>';return;}
      h+='<table><thead><tr><th>Container</th><th>Image</th><th>Status</th><th>Ports</th><th>Created</th></tr></thead><tbody>';
      containers.forEach(function(c){
        var status=(c.state||c.status||'unknown').toLowerCase();
        h+='<tr><td><strong>'+_esc(c.name||c.names)+'</strong></td><td class="mono-11">'+_esc(c.image||'-')+'</td><td>'+_statusBadge(status)+'</td><td class="mono-11">'+_esc(c.ports||'-')+'</td><td>'+_esc(c.created||'-')+'</td></tr>';
      });
      h+='</tbody></table></div>';
    });
    if(tbl)tbl.innerHTML=h;
  }).catch(function(e){if(tbl)tbl.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function loadInfraPage(){loadInfra();}
/* Security sub-view loaders */
function loadSecurityOverview(){loadRisk();loadSecPosture();}
function loadSecHardening(){/* audit + hardening sections are button-triggered */}
function loadSecAccess(){loadUsers();loadKeys();}
function loadSecVault(){loadVault();}
function loadSecCompliance(){loadPoliciesPage();loadComplianceData();}
function loadSecPosture(){
  /* Secrets audit */
  _authFetch(API.SECRETS_AUDIT).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('sec-secrets-audit');if(!el)return;
    el.innerHTML='<div style="display:flex;gap:16px;flex-wrap:wrap">'+
      '<div class="crd" style="flex:1;min-width:100px;text-align:center"><div style="font-size:20px;font-weight:700">'+d.leases+'</div><div class="c-dim-fs12">LEASES</div></div>'+
      '<div class="crd" style="flex:1;min-width:100px;text-align:center"><div style="font-size:20px;font-weight:700;color:var(--'+(d.expired>0?'red':'green')+')">'+d.expired+'</div><div class="c-dim-fs12">EXPIRED</div></div>'+
      '<div class="crd" style="flex:1;min-width:100px;text-align:center"><div style="font-size:20px;font-weight:700;color:var(--'+(d.scan_findings>0?'yellow':'green')+')">'+d.scan_findings+'</div><div class="c-dim-fs12">SCAN FINDINGS</div></div>'+
      '<div class="crd" style="flex:1;min-width:100px;text-align:center"><div style="font-size:14px;font-weight:600;color:var(--text-dim)">'+_esc(d.last_scan)+'</div><div class="c-dim-fs12">LAST SCAN</div></div>'+
      '</div>';
  }).catch(function(e){var el=document.getElementById('sec-secrets-audit');if(el)el.innerHTML='<div class="exec-out">'+_esc(e.toString())+'</div>';});
  /* Compliance status */
  _authFetch(API.COMPLY_STATUS).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('sec-comply-status');if(!el)return;
    el.innerHTML='<div style="display:flex;gap:16px;flex-wrap:wrap">'+
      '<div class="crd" style="flex:1;min-width:100px;text-align:center"><div style="font-size:20px;font-weight:700">'+d.total_checks+'</div><div class="c-dim-fs12">CIS CHECKS</div></div>'+
      '<div class="crd" style="flex:1;min-width:100px;text-align:center"><div style="font-size:20px;font-weight:700">'+d.scan_count+'</div><div class="c-dim-fs12">SCANS RUN</div></div>'+
      '<div class="crd" style="flex:1;min-width:100px;text-align:center"><div style="font-size:14px;font-weight:600;color:var(--text-dim)">'+_esc(d.last_scan)+'</div><div class="c-dim-fs12">LAST SCAN</div></div>'+
      '</div>';
  }).catch(function(e){var el=document.getElementById('sec-comply-status');if(el)el.innerHTML='<div class="exec-out">'+_esc(e.toString())+'</div>';});
  /* Cert summary */
  _authFetch(API.CERT_INVENTORY).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('sec-cert-summary');if(!el)return;
    var certs=d.certs||[];
    var valid=certs.filter(function(c){return c.status==='valid'}).length;
    var expiring=certs.filter(function(c){return c.days_left<30&&c.days_left>=0}).length;
    var expired=certs.filter(function(c){return c.status==='expired'}).length;
    el.innerHTML=_statCards([{l:'Certificates',v:certs.length},{l:'Valid',v:valid,c:'green'},{l:'Expiring (<30d)',v:expiring,c:'yellow'},{l:'Expired',v:expired,c:'red'}]);
  }).catch(function(e){var el=document.getElementById('sec-cert-summary');if(el)el.innerHTML='<div class="exec-out">'+_esc(e.toString())+'</div>';});
  /* Patch status */
  _authFetch(API.PATCH_STATUS).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('sec-patch-status');if(!el)return;
    var hist=d.history||[];var holds=d.holds||[];
    if(!hist.length&&!holds.length){el.innerHTML='<div class="exec-out">No patch history. Run <code>freq patch check</code> from CLI.</div>';return;}
    var h='';
    if(holds.length)h+='<div style="margin-bottom:8px"><strong style="color:var(--yellow)">'+holds.length+' package holds active</strong></div>';
    if(hist.length){
      h+='<table><thead><tr><th>Time</th><th>Host</th><th>Packages</th><th>Status</th></tr></thead><tbody>';
      hist.slice(-10).reverse().forEach(function(r){h+='<tr><td>'+_esc(r.time||'-')+'</td><td>'+_esc(r.host||'-')+'</td><td>'+(r.count||0)+'</td><td>'+_statusBadge(r.status||'ok')+'</td></tr>';});
      h+='</tbody></table>';
    }
    el.innerHTML=h;
  }).catch(function(e){var el=document.getElementById('sec-patch-status');if(el)el.innerHTML='<div class="exec-out">'+_esc(e.toString())+'</div>';});
}
function loadComplianceData(){
  /* Load compliance results on the compliance tab */
  _authFetch(API.COMPLY_RESULTS).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('policy-out');if(!el||!d.latest)return;
    var scan=d.latest;var hosts=scan.hosts||{};
    var h='<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">Last scan: '+_esc(scan.scan_time||'unknown')+' &mdash; '+d.total_scans+' total scans</div>';
    h+='<table><thead><tr><th>Host</th><th>Pass</th><th>Fail</th><th>Score</th></tr></thead><tbody>';
    Object.keys(hosts).forEach(function(host){
      var hr=hosts[host];var pass=hr.pass||0;var fail=hr.fail||0;var total=pass+fail;
      var pct=total>0?Math.round(pass/total*100):0;
      var color=pct>=80?'green':pct>=50?'yellow':'red';
      h+='<tr><td>'+_esc(host)+'</td><td style="color:var(--green)">'+pass+'</td><td style="color:var(--red)">'+fail+'</td><td style="color:var(--'+color+')">'+pct+'%</td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){console.error('API error:',e);});
  /* Load baselines */
  _authFetch(API.BASELINE_LIST).then(function(r){return r.json()}).then(function(d){
    var baselines=d.baselines||[];if(!baselines.length)return;
    var el=document.getElementById('patrol-out');if(!el)return;
    var existing=el.innerHTML;
    var h='<div style="margin-top:12px"><strong style="color:var(--purple-light)">Saved Baselines:</strong> ';
    baselines.forEach(function(b){h+='<span class="badge ok" style="margin-right:4px">'+_esc(b.name||b)+'</span>';});
    h+='</div>';
    if(existing.indexOf('Saved Baselines')===-1)el.innerHTML+=h;
  }).catch(function(e){console.error('API error:',e);});
}
function loadSecretsLeases(){
  var el=document.getElementById('sec-secrets-detail');if(!el)return;
  el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.SECRETS_LEASES).then(function(r){return r.json()}).then(function(d){
    var leases=d.leases||[];
    if(!leases.length){el.innerHTML='<div class="exec-out">No secret leases tracked.</div>';return;}
    var h='<table><thead><tr><th>Key</th><th>Host</th><th>Created</th><th>Expires</th><th>Status</th></tr></thead><tbody>';
    var now=Date.now()/1000;
    leases.forEach(function(l){
      var expired=l.expires_epoch>0&&l.expires_epoch<now;
      h+='<tr><td>'+_esc(l.key||'-')+'</td><td>'+_esc(l.host||'DEFAULT')+'</td><td>'+_esc(l.created||'-')+'</td><td>'+_esc(l.expires||'-')+'</td><td>'+_statusBadge(expired?'expired':'active')+'</td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
function loadSecretsScan(){
  var el=document.getElementById('sec-secrets-detail');if(!el)return;
  el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.SECRETS_SCAN).then(function(r){return r.json()}).then(function(d){
    var findings=d.findings||[];
    if(!findings.length){el.innerHTML='<div class="exec-out" style="color:var(--green)">No secrets found in scan. Last scan: '+_esc(d.scan_time||'never')+'</div>';return;}
    var h='<div style="color:var(--red);font-weight:600;margin-bottom:8px">'+findings.length+' finding(s) — last scan: '+_esc(d.scan_time||'unknown')+'</div>';
    h+='<table><thead><tr><th>File</th><th>Line</th><th>Type</th><th>Severity</th></tr></thead><tbody>';
    findings.forEach(function(f){h+='<tr><td class="mono-11">'+_esc(f.file||'-')+'</td><td>'+_esc(String(f.line||'-'))+'</td><td>'+_esc(f.type||'-')+'</td><td>'+_statusBadge(f.severity||'warning')+'</td></tr>';});
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
/* Stub loaders for extended views */
function loadMediaPage(){loadMediaContainers();loadDownloads();loadStreams();}
function loadToolsPage(){_populateHostDropdowns();_populateCompareDropdowns();}
function _populateCompareDropdowns(){
  _authFetch(API.HEALTH).then(function(r){return r.json()}).then(function(d){
    var hosts=d.hosts||[];
    ['compare-host-a','compare-host-b'].forEach(function(id){
      var sel=document.getElementById(id);if(!sel)return;
      sel.innerHTML='<option value="">Select host...</option>';
      hosts.forEach(function(h){sel.innerHTML+='<option value="'+_esc(h.label)+'">'+_esc(h.label)+'</option>';});
    });
  }).catch(function(e){console.error('API error:',e);});
}
function loadLabPage(){loadLabTools();}
function loadSettingsPage(){loadCosts();loadFederation();_loadSettingsPrefs();_loadLabAssignments();}
/* ── Domain Dashboard Loaders ── */
function loadNetworkPage(){
  _fetchAndRender('/api/v1/net/switches','net-switch-tbl',function(d){
    var stats=d.stats||{};
    var el=document.getElementById('net-switch-stats');
    if(el)el.innerHTML=_statCards([{l:'Switches',v:stats.total||0},{l:'Online',v:stats.online||0,c:'green'},{l:'Ports',v:stats.total_ports||0},{l:'Profiles',v:stats.profiles||0,c:'purple'}]);
    var tbl=document.getElementById('net-switch-tbl');
    if(tbl&&d.switches)tbl.innerHTML=d.switches.map(function(s){return '<tr><td>'+_esc(s.name)+'</td><td>'+_esc(s.model||'-')+'</td><td>'+_esc(s.firmware||'-')+'</td><td>'+(s.ports||'-')+'</td><td>'+_esc(s.uptime||'-')+'</td><td>'+_statusBadge(s.status)+'</td></tr>';}).join('');
    var pr=document.getElementById('net-profiles');
    if(pr&&d.profiles)pr.innerHTML='<div class="cards">'+d.profiles.map(function(p){return '<div class="crd"><h3>'+_esc(p.name)+'</h3><p>'+_esc(p.description||'')+'</p></div>';}).join('')+'</div>';
  });
}
function loadSwitchData(view){
  var out=document.getElementById('switch-detail-out');
  if(out)out.innerHTML='<div class="skeleton h-60"></div>';
  var urls={show:API.SWITCH_SHOW,facts:API.SWITCH_FACTS,interfaces:API.SWITCH_INTERFACES,vlans:API.SWITCH_VLANS,mac:API.SWITCH_MAC,arp:API.SWITCH_ARP,neighbors:API.SWITCH_NEIGHBORS,environment:API.SWITCH_ENV};
  var url=urls[view]||urls.facts;
  _authFetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.error){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(d.error)+'</div>';return;}
    var h='<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">'+_esc(d.host||'')+' ('+_esc(d.ip||'')+')</div>';
    if(view==='show'){
      var f=d.facts||{};var isum=d.interface_summary||{};
      h+=_statCards([{l:'Ports',v:isum.total||0},{l:'Up',v:isum.up||0,c:'green'},{l:'Down',v:isum.down||0,c:isum.down>0?'yellow':'green'},{l:'VLANs',v:d.vlan_count||0,c:'purple'}]);
      h+='<table style="margin-top:12px"><tbody>';
      Object.keys(f).forEach(function(k){h+='<tr><td style="color:var(--text-dim);width:200px">'+_esc(k)+'</td><td>'+_esc(String(f[k]))+'</td></tr>';});
      h+='</tbody></table>';
    }else if(view==='facts'){
      var f=d.facts||{};
      h+='<table><tbody>';
      Object.keys(f).forEach(function(k){h+='<tr><td style="color:var(--text-dim);width:200px">'+_esc(k)+'</td><td>'+_esc(String(f[k]))+'</td></tr>';});
      h+='</tbody></table>';
    }else if(view==='interfaces'){
      var ifaces=d.interfaces||[];
      h+='<table><thead><tr><th>Interface</th><th>Status</th><th>Speed</th><th>VLAN</th><th>Description</th></tr></thead><tbody>';
      ifaces.forEach(function(i){h+='<tr><td>'+_esc(i.name||i.interface)+'</td><td>'+_statusBadge(i.status)+'</td><td>'+_esc(i.speed||'-')+'</td><td>'+_esc(i.vlan||'-')+'</td><td>'+_esc(i.description||'-')+'</td></tr>';});
      h+='</tbody></table>';
    }else if(view==='vlans'){
      var vlans=d.vlans||[];
      h+='<table><thead><tr><th>VLAN</th><th>Name</th><th>Ports</th><th>Status</th></tr></thead><tbody>';
      vlans.forEach(function(v){h+='<tr><td>'+_esc(String(v.id||v.vlan))+'</td><td>'+_esc(v.name||'-')+'</td><td>'+_esc(v.ports||'-')+'</td><td>'+_statusBadge(v.status||'active')+'</td></tr>';});
      h+='</tbody></table>';
    }else if(view==='mac'){
      var macs=d.mac_table||[];
      h+='<table><thead><tr><th>MAC</th><th>VLAN</th><th>Type</th><th>Port</th></tr></thead><tbody>';
      macs.forEach(function(m){h+='<tr><td class="mono-11">'+_esc(m.mac)+'</td><td>'+_esc(String(m.vlan||'-'))+'</td><td>'+_esc(m.type||'-')+'</td><td>'+_esc(m.port||'-')+'</td></tr>';});
      h+='</tbody></table>';
    }else if(view==='arp'){
      var arps=d.arp_table||[];
      h+='<table><thead><tr><th>IP</th><th>MAC</th><th>Interface</th><th>Age</th></tr></thead><tbody>';
      arps.forEach(function(a){h+='<tr><td class="mono-11">'+_esc(a.ip)+'</td><td class="mono-11">'+_esc(a.mac)+'</td><td>'+_esc(a.interface||'-')+'</td><td>'+_esc(a.age||'-')+'</td></tr>';});
      h+='</tbody></table>';
    }else if(view==='neighbors'){
      var nb=d.neighbors||[];
      h+='<table><thead><tr><th>Local Port</th><th>Neighbor</th><th>Remote Port</th><th>Platform</th></tr></thead><tbody>';
      nb.forEach(function(n){h+='<tr><td>'+_esc(n.local_port||'-')+'</td><td>'+_esc(n.neighbor||n.device||'-')+'</td><td>'+_esc(n.remote_port||'-')+'</td><td>'+_esc(n.platform||'-')+'</td></tr>';});
      h+='</tbody></table>';
    }else if(view==='environment'){
      var env=d.environment||{};
      h+='<table><tbody>';
      Object.keys(env).forEach(function(k){
        var v=env[k];
        h+='<tr><td style="color:var(--text-dim);width:200px">'+_esc(k)+'</td><td>'+(typeof v==='object'?'<pre style="margin:0;font-size:11px">'+_esc(JSON.stringify(v,null,2))+'</pre>':_esc(String(v)))+'</td></tr>';
      });
      h+='</tbody></table>';
    }
    if(out)out.innerHTML=h;
  }).catch(function(e){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function loadConfigHistory(){
  var out=document.getElementById('config-backup-out');
  if(out)out.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.CONFIG_HISTORY).then(function(r){return r.json()}).then(function(d){
    var backups=d.backups||[];
    if(!backups.length){if(out)out.innerHTML='<div class="exec-out">No config backups found. Run <code>freq net config backup</code>.</div>';return;}
    var h='<table><thead><tr><th>Device</th><th>Timestamp</th><th>Size</th><th>File</th></tr></thead><tbody>';
    backups.forEach(function(b){h+='<tr><td>'+_esc(b.label)+'</td><td>'+_esc(b.timestamp)+'</td><td>'+b.size+' B</td><td class="mono-11">'+_esc(b.file)+'</td></tr>';});
    h+='</tbody></table>';
    if(out)out.innerHTML=h;
  }).catch(function(e){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function searchConfigs(){
  var pattern=document.getElementById('config-search-input').value.trim();
  var out=document.getElementById('config-backup-out');
  if(!pattern){if(out)out.textContent='Enter a search pattern.';return;}
  if(out)out.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.CONFIG_SEARCH+'?pattern='+encodeURIComponent(pattern)).then(function(r){return r.json()}).then(function(d){
    if(d.error){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(d.error)+'</div>';return;}
    var results=d.results||[];
    if(!results.length){if(out)out.innerHTML='<div class="exec-out">No matches for "'+_esc(pattern)+'" across '+d.total_devices+' devices.</div>';return;}
    var h='<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">Found matches in '+results.length+' device(s)</div>';
    results.forEach(function(r){
      h+='<div style="margin-bottom:12px"><strong style="color:var(--purple-light)">'+_esc(r.device)+'</strong>';
      h+='<pre style="font-size:11px;margin:4px 0 0 0;background:var(--bg2);padding:8px;border-radius:4px;overflow-x:auto">';
      r.matches.forEach(function(m){h+=_esc(m.line+': '+m.text)+'\n';});
      h+='</pre></div>';
    });
    if(out)out.innerHTML=h;
  }).catch(function(e){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function loadDepMap(){
  var out=document.getElementById('dep-map-out');
  if(out)out.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch(API.MAP_DATA).then(function(r){return r.json()}).then(function(d){
    var nodes=d.nodes||[];var edges=d.edges||[];
    if(!nodes.length){if(out)out.innerHTML='<div class="exec-out">No dependency data. Run <code>freq map build</code> from CLI.</div>';return;}
    var h='<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px">';
    h+=_statCards([{l:'Nodes',v:nodes.length},{l:'Edges',v:edges.length},{l:'Services',v:nodes.filter(function(n){return n.type==='service'}).length,c:'purple'}]);
    h+='</div>';
    h+='<table><thead><tr><th>Node</th><th>Type</th><th>Dependencies</th><th>Dependents</th></tr></thead><tbody>';
    nodes.forEach(function(n){
      var deps=(n.depends_on||[]).join(', ')||'none';
      var revs=(n.depended_by||[]).join(', ')||'none';
      h+='<tr><td><strong>'+_esc(n.name||n.id)+'</strong></td><td>'+_esc(n.type||'-')+'</td><td>'+_esc(deps)+'</td><td>'+_esc(revs)+'</td></tr>';
    });
    h+='</tbody></table>';
    if(out)out.innerHTML=h;
  }).catch(function(e){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function runImpactAnalysis(){
  var host=document.getElementById('impact-host-input').value.trim();
  var out=document.getElementById('dep-map-out');
  if(!host){if(out)out.textContent='Enter a host name.';return;}
  if(out)out.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.MAP_IMPACT+'?host='+encodeURIComponent(host)).then(function(r){return r.json()}).then(function(d){
    if(d.error){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(d.error)+'</div>';return;}
    var h='<h4 style="color:var(--purple-light);margin-bottom:8px">Impact: '+_esc(host)+'</h4>';
    var affected=d.affected||[];var services=d.services||[];
    h+='<div style="margin-bottom:8px">Affected hosts: <strong>'+(affected.length||0)+'</strong> &middot; Services impacted: <strong>'+(services.length||0)+'</strong></div>';
    if(affected.length){h+='<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">';affected.forEach(function(a){h+='<span class="badge CRITICAL">'+_esc(a)+'</span>';});h+='</div>';}
    if(services.length){h+='<div style="display:flex;gap:6px;flex-wrap:wrap">';services.forEach(function(s){h+='<span class="badge warn">'+_esc(s)+'</span>';});h+='</div>';}
    if(!affected.length&&!services.length)h+='<div class="exec-out">No downstream impact detected.</div>';
    if(out)out.innerHTML=h;
  }).catch(function(e){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function loadNetmonData(){
  var out=document.getElementById('netmon-out');
  if(out)out.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.NETMON_DATA).then(function(r){return r.json()}).then(function(d){
    var snaps=d.snapshots||[];
    if(!snaps.length){if(out)out.innerHTML='<div class="exec-out">No monitoring data. Run <code>freq netmon poll</code> to start collecting.</div>';return;}
    var h='<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">'+snaps.length+' snapshots (showing latest 20)</div>';
    h+='<table><thead><tr><th>Time</th><th>Host</th><th>Interface</th><th>RX</th><th>TX</th><th>Errors</th></tr></thead><tbody>';
    snaps.slice(-20).reverse().forEach(function(s){
      var ifaces=s.interfaces||[];
      ifaces.forEach(function(i){
        h+='<tr><td>'+_esc(s.time||'-')+'</td><td>'+_esc(s.host||'-')+'</td><td>'+_esc(i.name)+'</td><td>'+_esc(i.rx||'0')+'</td><td>'+_esc(i.tx||'0')+'</td><td>'+_esc(i.errors||'0')+'</td></tr>';
      });
      if(!ifaces.length)h+='<tr><td>'+_esc(s.time||'-')+'</td><td>'+_esc(s.host||'-')+'</td><td colspan="4"><pre style="margin:0;font-size:11px">'+_esc(JSON.stringify(s,null,2))+'</pre></td></tr>';
    });
    h+='</tbody></table>';
    if(out)out.innerHTML=h;
  }).catch(function(e){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function runNetScan(type){
  var out=document.getElementById('net-snmp-out');
  if(out)out.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch('/api/v1/net/scan?type='+type).then(function(r){return r.json();}).then(function(d){
    if(out)out.innerHTML='<pre>'+_esc(JSON.stringify(d.results||d,null,2))+'</pre>';
  }).catch(function(e){if(out)out.textContent='Scan failed: '+e;});
}
function loadFirewallPage(){
  _fetchAndRender('/api/v1/fw/status','fw-stats',function(d){
    var s=d.stats||{};
    var el=document.getElementById('fw-stats');
    if(el)el.innerHTML=_statCards([{l:'Rules',v:s.rules||0},{l:'NAT',v:s.nat||0},{l:'States',v:s.states||0,c:'green'},{l:'Interfaces',v:s.interfaces||0}]);
    var iface=document.getElementById('fw-interfaces');
    if(iface&&d.interfaces)iface.innerHTML='<div class="cards">'+d.interfaces.map(function(i){return '<div class="crd"><h3>'+_esc(i.name)+'</h3><p>'+_esc(i.ip||'no ip')+' &mdash; '+_statusBadge(i.status)+'</p></div>';}).join('')+'</div>';
  });
}
function loadFwRules(){
  var c=document.getElementById('fw-rules-content');
  if(c)c.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch('/api/v1/fw/rules').then(function(r){return r.json();}).then(function(d){
    if(c&&d.rules)c.innerHTML='<table><thead><tr><th>#</th><th>Action</th><th>Proto</th><th>Source</th><th>Dest</th><th>Port</th></tr></thead><tbody>'+d.rules.map(function(r,i){return '<tr><td>'+(i+1)+'</td><td>'+_esc(r.action)+'</td><td>'+_esc(r.proto||'*')+'</td><td>'+_esc(r.src||'*')+'</td><td>'+_esc(r.dst||'*')+'</td><td>'+_esc(r.port||'*')+'</td></tr>';}).join('')+'</tbody></table>';
  }).catch(function(e){if(c)c.innerHTML='<div class="exec-out">Failed to load rules: '+_esc(e.toString())+'</div>';});
}
function loadFwNat(){
  var c=document.getElementById('fw-rules-content');
  if(c)c.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch('/api/v1/fw/nat').then(function(r){return r.json();}).then(function(d){
    if(c)c.innerHTML='<pre>'+_esc(JSON.stringify(d.rules||d,null,2))+'</pre>';
  }).catch(function(e){if(c)c.innerHTML='<div class="exec-out">Failed: '+_esc(e.toString())+'</div>';});
}
function loadFwStates(){
  var c=document.getElementById('fw-rules-content');
  if(c)c.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch('/api/v1/fw/states').then(function(r){return r.json();}).then(function(d){
    if(c)c.innerHTML='<pre>'+_esc(JSON.stringify(d.states||d,null,2))+'</pre>';
  }).catch(function(e){if(c)c.innerHTML='<div class="exec-out">Failed: '+_esc(e.toString())+'</div>';});
}
function loadCertsPage(){
  _fetchAndRender('/api/v1/cert/list','cert-tbl',function(d){
    var s=d.stats||{};
    var el=document.getElementById('cert-stats');
    if(el)el.innerHTML=_statCards([{l:'Total',v:s.total||0},{l:'Valid',v:s.valid||0,c:'green'},{l:'Expiring',v:s.expiring||0,c:'yellow'},{l:'Expired',v:s.expired||0,c:'red'}]);
    var tbl=document.getElementById('cert-tbl');
    if(tbl&&d.certs)tbl.innerHTML=d.certs.map(function(c){
      var color=c.days_left<7?'red':c.days_left<30?'yellow':'green';
      return '<tr><td>'+_esc(c.domain)+'</td><td>'+_esc(c.issuer||'-')+'</td><td>'+_esc(c.expires||'-')+'</td><td><span style="color:var(--'+color+')">'+c.days_left+'</span></td><td>'+_statusBadge(c.status)+'</td></tr>';
    }).join('');
  });
}
function loadDnsPage(){
  _fetchAndRender('/api/v1/dns/status','dns-stats',function(d){
    var s=d.stats||{};
    var el=document.getElementById('dns-stats');
    if(el)el.innerHTML=_statCards([{l:'Zones',v:s.zones||0},{l:'Records',v:s.records||0},{l:'Healthy',v:s.healthy||0,c:'green'},{l:'Errors',v:s.errors||0,c:'red'}]);
    var rec=document.getElementById('dns-records');
    if(rec&&d.records)rec.innerHTML='<table><thead><tr><th>Name</th><th>Type</th><th>Value</th><th>TTL</th></tr></thead><tbody>'+d.records.map(function(r){return '<tr><td>'+_esc(r.name)+'</td><td>'+_esc(r.type)+'</td><td>'+_esc(r.value)+'</td><td>'+r.ttl+'</td></tr>';}).join('')+'</tbody></table>';
  });
}
function loadDnsInventory(){
  var out=document.getElementById('dns-inventory-out');
  if(out)out.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.DNS_INVENTORY).then(function(r){return r.json()}).then(function(d){
    var records=d.records||[];var hosts=d.hosts||[];
    if(!records.length&&!hosts.length){if(out)out.innerHTML='<div class="exec-out">No DNS inventory data. Run <code>freq dns scan</code> to discover records.</div>';return;}
    var h='';
    if(d.stats)h+=_statCards([{l:'Hosts',v:d.stats.hosts||hosts.length||0},{l:'Records',v:d.stats.records||records.length||0},{l:'Mismatches',v:d.stats.mismatches||0,c:d.stats.mismatches>0?'red':'green'}]);
    if(records.length){
      h+='<table style="margin-top:12px"><thead><tr><th>Host</th><th>Record</th><th>Type</th><th>Value</th><th>Status</th></tr></thead><tbody>';
      records.forEach(function(r){h+='<tr><td>'+_esc(r.host||'-')+'</td><td>'+_esc(r.name||'-')+'</td><td>'+_esc(r.type||'A')+'</td><td class="mono-11">'+_esc(r.value||'-')+'</td><td>'+_statusBadge(r.status||'ok')+'</td></tr>';});
      h+='</tbody></table>';
    } else {
      h+='<pre style="margin-top:12px;font-size:11px;background:var(--bg2);padding:12px;border-radius:6px;max-height:400px;overflow:auto">'+_esc(JSON.stringify(d,null,2))+'</pre>';
    }
    if(out)out.innerHTML=h;
  }).catch(function(e){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function runDnsCheck(){
  var domain=document.getElementById('dns-query-input').value.trim();
  var out=document.getElementById('dns-check-out');
  if(!domain){if(out)out.textContent='Enter a domain.';return;}
  if(out)out.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch('/api/v1/dns/check?domain='+encodeURIComponent(domain)).then(function(r){return r.json();}).then(function(d){
    if(out)out.innerHTML='<pre>'+_esc(JSON.stringify(d,null,2))+'</pre>';
  }).catch(function(e){if(out)out.textContent='Check failed: '+e;});
}
function loadVpnPage(){
  _fetchAndRender('/api/v1/vpn/status','vpn-stats',function(d){
    var s=d.stats||{};
    var el=document.getElementById('vpn-stats');
    if(el)el.innerHTML=_statCards([{l:'WG Tunnels',v:s.wg_tunnels||0},{l:'WG Peers',v:s.wg_peers||0,c:'green'},{l:'OVPN Tunnels',v:s.ovpn_tunnels||0},{l:'Connected',v:s.connected||0,c:'green'}]);
    var wg=document.getElementById('vpn-wg-content');
    if(wg&&d.wireguard)wg.innerHTML='<pre>'+_esc(JSON.stringify(d.wireguard,null,2))+'</pre>';
    else if(wg)wg.innerHTML='<div class="exec-out">No WireGuard data available.</div>';
    var ovpn=document.getElementById('vpn-ovpn-content');
    if(ovpn&&d.openvpn)ovpn.innerHTML='<pre>'+_esc(JSON.stringify(d.openvpn,null,2))+'</pre>';
    else if(ovpn)ovpn.innerHTML='<div class="exec-out">No OpenVPN data available.</div>';
  });
}
function loadDrPage(){
  _fetchAndRender('/api/v1/dr/status','dr-stats',function(d){
    var s=d.stats||{};
    var el=document.getElementById('dr-stats');
    if(el)el.innerHTML=_statCards([{l:'Hosts',v:s.hosts||0},{l:'Protected',v:s.protected||0,c:'green'},{l:'Stale',v:s.stale||0,c:'yellow'},{l:'Policies',v:s.policies||0}]);
    var tbl=document.getElementById('dr-backup-tbl');
    if(tbl&&d.backups)tbl.innerHTML=d.backups.map(function(b){return '<tr><td>'+_esc(b.host)+'</td><td>'+_esc(b.last_backup||'never')+'</td><td>'+_esc(b.size||'-')+'</td><td>'+_esc(b.policy||'none')+'</td><td>'+_statusBadge(b.status)+'</td></tr>';}).join('');
    var pol=document.getElementById('dr-policies');
    if(pol&&d.policies)pol.innerHTML='<div class="cards">'+d.policies.map(function(p){return '<div class="crd"><h3>'+_esc(p.name)+'</h3><p>Schedule: '+_esc(p.schedule||'manual')+'<br>Retention: '+_esc(p.retention||'default')+'</p></div>';}).join('')+'</div>';
    var rb=document.getElementById('dr-runbooks');
    if(rb&&d.runbooks)rb.innerHTML='<div class="cards">'+d.runbooks.map(function(r){return '<div class="crd"><h3>'+_esc(r.name)+'</h3><p>'+_esc(r.description||'')+'</p></div>';}).join('')+'</div>';
  });
  loadBackupPolicies();
}
function loadIncidentsPage(){
  _fetchAndRender('/api/v1/ops/incidents','incident-stats',function(d){
    var s=d.stats||{};
    var el=document.getElementById('incident-stats');
    if(el)el.innerHTML=_statCards([{l:'Open',v:s.open||0,c:'red'},{l:'Investigating',v:s.investigating||0,c:'yellow'},{l:'Resolved',v:s.resolved||0,c:'green'},{l:'Total',v:s.total||0}]);
    var tbl=document.getElementById('incident-tbl');
    if(tbl&&d.incidents)tbl.innerHTML=d.incidents.map(function(i){
      var sevColor=i.severity==='critical'?'red':i.severity==='high'?'yellow':'green';
      return '<tr><td>'+_esc(i.id)+'</td><td><span style="color:var(--'+sevColor+')">'+_esc(i.severity)+'</span></td><td>'+_esc(i.summary)+'</td><td>'+_esc(i.opened||'-')+'</td><td>'+_statusBadge(i.status)+'</td></tr>';
    }).join('');
    var cl=document.getElementById('change-log');
    if(cl&&d.changes)cl.innerHTML='<table><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Target</th></tr></thead><tbody>'+d.changes.map(function(c){return '<tr><td>'+_esc(c.time)+'</td><td>'+_esc(c.user)+'</td><td>'+_esc(c.action)+'</td><td>'+_esc(c.target)+'</td></tr>';}).join('')+'</tbody></table>';
  });
  loadOncall();
}
function loadOncallSchedule(){
  var el=document.getElementById('oncall-schedule-detail');if(!el)return;
  el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.ONCALL_SCHEDULE).then(function(r){return r.json()}).then(function(d){
    var h='<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">Rotation: '+_esc(d.rotation||'weekly')+'</div>';
    var users=d.users||[];var overrides=d.overrides||[];var schedule=d.schedule||[];
    if(users.length){h+='<div style="margin-bottom:8px"><strong>Roster:</strong> '+users.map(function(u){return '<span class="badge ok">'+_esc(u)+'</span>';}).join(' ')+'</div>';}
    if(schedule.length){
      h+='<table><thead><tr><th>Period</th><th>On-Call</th></tr></thead><tbody>';
      schedule.forEach(function(s){h+='<tr><td>'+_esc(s.start||'-')+' — '+_esc(s.end||'-')+'</td><td><strong>'+_esc(s.user||'-')+'</strong></td></tr>';});
      h+='</tbody></table>';
    }
    if(overrides.length){h+='<div style="margin-top:8px;font-size:11px;color:var(--yellow)">'+overrides.length+' override(s) active</div>';}
    if(!users.length&&!schedule.length)h+='<pre style="font-size:11px;background:var(--bg2);padding:12px;border-radius:6px">'+_esc(JSON.stringify(d,null,2))+'</pre>';
    el.innerHTML=h;
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
function loadOncall(){
  /* Who is on call */
  _authFetch(API.ONCALL_WHOAMI).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('oncall-info');if(!el)return;
    var h='<div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center">';
    h+='<div class="crd" style="padding:12px 20px;text-align:center"><div style="font-size:20px;font-weight:700;color:var(--green)">'+_esc(d.oncall||'unset')+'</div><div class="c-dim-fs12">CURRENT ON-CALL</div></div>';
    h+='<div class="crd" style="padding:12px 20px;text-align:center"><div style="font-size:16px;font-weight:600">'+_esc(d.rotation||'weekly')+'</div><div class="c-dim-fs12">ROTATION</div></div>';
    var users=d.users||[];
    if(users.length){h+='<div style="flex:1"><span class="c-dim-fs12">ROSTER: </span>';users.forEach(function(u){h+='<span class="badge ok" style="margin-right:4px">'+_esc(u)+'</span>';});h+='</div>';}
    h+='</div>';
    el.innerHTML=h;
  }).catch(function(e){var el=document.getElementById('oncall-info');if(el)el.innerHTML='<div class="exec-out">'+_esc(e.toString())+'</div>';});
  /* On-call incidents */
  _authFetch(API.ONCALL_INCIDENTS).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('oncall-incidents');if(!el)return;
    var incidents=d.incidents||[];
    if(!incidents.length){el.innerHTML='<div class="exec-out" style="color:var(--green)">No on-call incidents. All quiet.</div>';return;}
    var h='<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">'+d.total+' total, '+d.open+' open</div>';
    h+='<table><thead><tr><th>ID</th><th>Summary</th><th>Status</th><th>Assignee</th><th>Time</th></tr></thead><tbody>';
    incidents.forEach(function(i){
      h+='<tr><td>'+_esc(i.id||'-')+'</td><td>'+_esc(i.summary||'-')+'</td><td>'+_statusBadge(i.status||'open')+'</td><td>'+_esc(i.assignee||'-')+'</td><td>'+_esc(i.time||i.opened||'-')+'</td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){var el=document.getElementById('oncall-incidents');if(el)el.innerHTML='<div class="exec-out">'+_esc(e.toString())+'</div>';});
}
function loadMetricsPage(){
  _fetchAndRender('/api/v1/observe/metrics','metrics-top-stats',function(d){
    var s=d.stats||{};
    var el=document.getElementById('metrics-top-stats');
    if(el)el.innerHTML=_statCards([{l:'Hosts',v:s.hosts||0},{l:'Avg CPU',v:(s.avg_cpu||0)+'%'},{l:'Avg RAM',v:(s.avg_ram||0)+'%'},{l:'Alerts',v:s.alerts||0,c:s.alerts>0?'red':'green'}]);
    var charts=document.getElementById('metrics-charts');
    if(charts&&d.hosts)charts.innerHTML='<div class="cards">'+d.hosts.map(function(h){
      return '<div class="crd"><h3>'+_esc(h.name)+'</h3><p>CPU: '+h.cpu+'% &middot; RAM: '+h.ram+'% &middot; Disk: '+h.disk+'%</p></div>';
    }).join('')+'</div>';
    var mon=document.getElementById('synth-monitors');
    if(mon&&d.monitors)mon.innerHTML='<table><thead><tr><th>URL</th><th>Status</th><th>Latency</th><th>Last Check</th></tr></thead><tbody>'+d.monitors.map(function(m){return '<tr><td>'+_esc(m.url)+'</td><td>'+_statusBadge(m.status)+'</td><td>'+m.latency_ms+'ms</td><td>'+_esc(m.last_check||'-')+'</td></tr>';}).join('')+'</tbody></table>';
  });
  loadMetricAlerts();loadSlaData();
}
function loadMetricAlerts(){
  /* Alert rules */
  _authFetch(API.ALERT_RULES).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('metric-alert-rules');if(!el)return;
    var rules=d.rules||[];var silences=d.silences||[];
    if(!rules.length){el.innerHTML='<div class="exec-out">No alert rules configured. Create rules in SYSTEM > Alert Rules.</div>';return;}
    var h='<table><thead><tr><th>Rule</th><th>Condition</th><th>Target</th><th>Severity</th><th>Enabled</th></tr></thead><tbody>';
    rules.forEach(function(r){
      h+='<tr><td><strong>'+_esc(r.name)+'</strong></td><td>'+_esc(r.condition||'-')+' &gt; '+(r.threshold||0)+'</td>';
      h+='<td>'+_esc(r.target||'*')+'</td><td><span class="badge '+(r.severity==='critical'?'CRITICAL':r.severity)+'">'+_esc(r.severity||'warning')+'</span></td>';
      h+='<td>'+(r.enabled?'<span class="c-green">ON</span>':'<span class="c-red">OFF</span>')+'</td></tr>';
    });
    h+='</tbody></table>';
    if(silences.length)h+='<div style="margin-top:8px;font-size:12px;color:var(--yellow)">'+silences.length+' active silence(s)</div>';
    el.innerHTML=h;
  }).catch(function(e){var el=document.getElementById('metric-alert-rules');if(el)el.innerHTML='<div class="exec-out">'+_esc(e.toString())+'</div>';});
  /* Alert history */
  _authFetch(API.ALERT_HISTORY).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('metric-alert-history');if(!el)return;
    var hist=d.history||[];
    if(!hist.length){el.innerHTML='<div class="exec-out">No alert history yet.</div>';return;}
    var h='<table><thead><tr><th>Time</th><th>Rule</th><th>Host</th><th>Message</th><th>Severity</th></tr></thead><tbody>';
    hist.slice(-20).reverse().forEach(function(a){
      var t=a.fired_at?new Date(a.fired_at*1000).toLocaleString():(a.time||'?');
      h+='<tr><td style="white-space:nowrap">'+_esc(t)+'</td><td>'+_esc(a.rule||a.rule_name||'-')+'</td><td>'+_esc(a.host||'-')+'</td><td>'+_esc(a.message||'-')+'</td>';
      h+='<td><span class="badge '+(a.severity==='critical'?'CRITICAL':a.severity)+'">'+_esc(a.severity||'warning')+'</span></td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){var el=document.getElementById('metric-alert-history');if(el)el.innerHTML='<div class="exec-out">'+_esc(e.toString())+'</div>';});
}
function runAlertCheck(){
  var el=document.getElementById('metric-alert-triggered');
  if(el)el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.ALERT_CHECK).then(function(r){return r.json()}).then(function(d){
    if(!el)return;
    var alerts=d.alerts||[];
    if(!alerts.length){el.innerHTML='<div class="exec-out" style="color:var(--green)">All clear — '+d.rules_checked+' rules checked, 0 triggered.</div>';return;}
    var h='<div style="color:var(--red);font-weight:600;margin-bottom:8px">'+alerts.length+' ALERT(S) TRIGGERED</div>';
    h+='<table><thead><tr><th>Rule</th><th>Host</th><th>Value</th><th>Message</th><th>Severity</th></tr></thead><tbody>';
    alerts.forEach(function(a){
      h+='<tr><td><strong>'+_esc(a.rule)+'</strong></td><td>'+_esc(a.host)+'</td><td>'+_esc(String(a.value))+'</td><td>'+_esc(a.message)+'</td>';
      h+='<td><span class="badge '+(a.severity==='critical'?'CRITICAL':a.severity)+'">'+_esc(a.severity)+'</span></td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){if(el)el.innerHTML='<div class="exec-out" style="color:var(--red)">Check failed: '+_esc(e.toString())+'</div>';});
}
function runMonitorCheck(){
  var el=document.getElementById('synth-monitors');
  if(el)el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.MONITORS_CHECK).then(function(r){return r.json()}).then(function(d){
    if(!el)return;
    var results=d.results||[];
    if(!results.length){el.innerHTML='<div class="exec-out">No monitors configured. Add monitors to freq.toml.</div>';return;}
    var h='<div style="margin-bottom:8px">'+_statCards([{l:'Total',v:d.count||0},{l:'Healthy',v:d.healthy||0,c:'green'},{l:'Unhealthy',v:d.unhealthy||0,c:d.unhealthy>0?'red':'green'}])+'</div>';
    h+='<table><thead><tr><th>URL</th><th>Status</th><th>Latency</th><th>Code</th></tr></thead><tbody>';
    results.forEach(function(m){
      h+='<tr><td>'+_esc(m.url||m.name)+'</td><td>'+_statusBadge(m.ok?'ok':'fail')+'</td><td>'+(m.latency_ms||'-')+'ms</td><td>'+(m.status_code||'-')+'</td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){if(el)el.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function recordSlaCheck(){
  _authFetch(API.SLA_CHECK).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast('SLA check recorded','success');
    else toast('SLA check failed','error');
    loadSlaData();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function loadSlaData(){
  var el=document.getElementById('sla-data');
  if(el)el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.SLA).then(function(r){return r.json()}).then(function(d){
    if(!el)return;
    var hosts=d.hosts||{};var keys=Object.keys(hosts);
    if(!keys.length){el.innerHTML='<div class="exec-out">No SLA data. SLA checks run automatically with patrol. Run <code>freq sla record</code> to start.</div>';return;}
    var h='<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">'+d.total_checks+' total checks recorded</div>';
    h+='<table><thead><tr><th>Host</th><th>7-Day SLA</th><th>30-Day SLA</th><th>90-Day SLA</th></tr></thead><tbody>';
    keys.sort().forEach(function(host){
      var s=hosts[host];
      var fmt=function(pct){var p=parseFloat(pct)||0;var c=p>=99.9?'green':p>=99?'yellow':'red';return '<span style="color:var(--'+c+');font-weight:600">'+p.toFixed(2)+'%</span>';};
      h+='<tr><td>'+_esc(host)+'</td><td>'+fmt(s['7d'])+'</td><td>'+fmt(s['30d'])+'</td><td>'+fmt(s['90d'])+'</td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){if(el)el.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function loadAutomationPage(){
  _fetchAndRender('/api/v1/auto/status','auto-stats',function(d){
    var s=d.stats||{};
    var el=document.getElementById('auto-stats');
    if(el)el.innerHTML=_statCards([{l:'Reactors',v:s.reactors||0},{l:'Workflows',v:s.workflows||0},{l:'Jobs',v:s.jobs||0},{l:'Runs Today',v:s.runs_today||0,c:'green'}]);
    var react=document.getElementById('auto-reactors');
    if(react&&d.reactors)react.innerHTML='<div class="cards">'+d.reactors.map(function(r){return '<div class="crd"><h3>'+_esc(r.name)+'</h3><p>Trigger: '+_esc(r.trigger||'event')+'<br>Status: '+_statusBadge(r.status)+'</p></div>';}).join('')+'</div>';
    var wf=document.getElementById('auto-workflows');
    if(wf&&d.workflows)wf.innerHTML='<div class="cards">'+d.workflows.map(function(w){return '<div class="crd"><h3>'+_esc(w.name)+'</h3><p>Steps: '+(w.steps||0)+'<br>Last: '+_esc(w.last_run||'never')+'</p></div>';}).join('')+'</div>';
    var jobs=document.getElementById('auto-jobs');
    if(jobs&&d.jobs)jobs.innerHTML='<table><thead><tr><th>Name</th><th>Schedule</th><th>Last Run</th><th>Status</th></tr></thead><tbody>'+d.jobs.map(function(j){return '<tr><td>'+_esc(j.name)+'</td><td>'+_esc(j.schedule)+'</td><td>'+_esc(j.last_run||'never')+'</td><td>'+_statusBadge(j.status)+'</td></tr>';}).join('')+'</tbody></table>';
  });
  loadScheduleJobs();loadWebhooks();
}
function loadScheduleJobs(){
  _authFetch(API.SCHEDULE_JOBS).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('schedule-jobs');if(!el)return;
    var jobs=d.jobs||[];
    if(!jobs.length){el.innerHTML='<div class="exec-out">No scheduled jobs. Create jobs with <code>freq schedule create</code>.</div>';return;}
    var h='<table><thead><tr><th>Name</th><th>Schedule</th><th>Command</th><th>Target</th><th>Last Run</th><th>Status</th></tr></thead><tbody>';
    jobs.forEach(function(j){
      h+='<tr><td><strong>'+_esc(j.name)+'</strong></td><td>'+_esc(j.schedule||j.cron||'-')+'</td><td class="mono-11">'+_esc(j.command||'-')+'</td><td>'+_esc(j.target||'*')+'</td><td>'+_esc(j.last_run||'never')+'</td><td>'+_statusBadge(j.status||'idle')+'</td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){var el=document.getElementById('schedule-jobs');if(el)el.innerHTML='<div class="exec-out">'+_esc(e.toString())+'</div>';});
  /* Templates */
  _authFetch(API.SCHEDULE_TEMPLATES).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('schedule-templates');if(!el)return;
    var templates=d.templates||[];
    if(!templates.length){el.innerHTML='<div class="exec-out">No job templates available.</div>';return;}
    el.innerHTML='<div class="cards">'+templates.map(function(t){return '<div class="crd"><h3>'+_esc(t.name||t)+'</h3><p>'+_esc(t.description||t.schedule||'')+'</p></div>';}).join('')+'</div>';
  }).catch(function(e){console.error('API error:',e);});
  /* Execution log */
  _authFetch(API.SCHEDULE_LOG).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('schedule-log');if(!el)return;
    var log=d.log||[];
    if(!log.length){el.innerHTML='<div class="exec-out">No job executions yet.</div>';return;}
    var h='<table><thead><tr><th>Time</th><th>Job</th><th>Status</th><th>Duration</th></tr></thead><tbody>';
    log.slice(-15).reverse().forEach(function(l){
      h+='<tr><td>'+_esc(l.time||'-')+'</td><td>'+_esc(l.job||l.name||'-')+'</td><td>'+_statusBadge(l.status||'ok')+'</td><td>'+_esc(l.duration||'-')+'</td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){console.error('API error:',e);});
}
function loadWebhooks(){
  _authFetch(API.WEBHOOK_LIST).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('webhook-list');if(!el)return;
    var hooks=d.webhooks||[];
    if(!hooks.length){el.innerHTML='<div class="exec-out">No webhooks configured. Add webhooks with <code>freq webhook create</code>.</div>';return;}
    var h='<table><thead><tr><th>Name</th><th>URL</th><th>Events</th><th>Enabled</th></tr></thead><tbody>';
    hooks.forEach(function(w){
      h+='<tr><td><strong>'+_esc(w.name)+'</strong></td><td class="mono-11">'+_esc(w.url||'-')+'</td><td>'+_esc((w.events||[]).join(', ')||'all')+'</td><td>'+(w.enabled!==false?'<span class="c-green">ON</span>':'<span class="c-red">OFF</span>')+'</td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){var el=document.getElementById('webhook-list');if(el)el.innerHTML='<div class="exec-out">'+_esc(e.toString())+'</div>';});
  /* Webhook log */
  _authFetch(API.WEBHOOK_LOG).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('webhook-log');if(!el)return;
    var log=d.log||[];
    if(!log.length){el.innerHTML='<div class="exec-out">No webhook executions yet.</div>';return;}
    var h='<table><thead><tr><th>Time</th><th>Webhook</th><th>Event</th><th>Status</th></tr></thead><tbody>';
    log.slice(-15).reverse().forEach(function(l){
      h+='<tr><td>'+_esc(l.time||'-')+'</td><td>'+_esc(l.name||l.webhook||'-')+'</td><td>'+_esc(l.event||'-')+'</td><td>'+_statusBadge(l.status||l.result||'ok')+'</td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){console.error('API error:',e);});
}
function loadPluginsPage(){
  _fetchAndRender('/api/v1/plugin/list','plugin-stats',function(d){
    var plugins=d.plugins||[];
    var el=document.getElementById('plugin-stats');
    var types={};plugins.forEach(function(p){types[p.type]=(types[p.type]||0)+1;});
    if(el)el.innerHTML=_statCards([{l:'Total',v:plugins.length},{l:'Commands',v:types.command||0,c:'purple'},{l:'Deployers',v:types.deployer||0,c:'green'},{l:'Other',v:plugins.length-(types.command||0)-(types.deployer||0)}]);
    var list=document.getElementById('plugin-list');
    if(list)list.innerHTML=plugins.length?'<table><thead><tr><th>Name</th><th>Type</th><th>Version</th><th>Description</th></tr></thead><tbody>'+plugins.map(function(p){return '<tr><td>'+_esc(p.name)+'</td><td><span style="color:var(--purple)">'+_esc(p.type)+'</span></td><td>'+_esc(p.version||'local')+'</td><td>'+_esc(p.description)+'</td></tr>';}).join('')+'</tbody></table>':'<div class="exec-out">No plugins installed. Use <code>freq plugin install</code> or <code>freq plugin create</code>.</div>';
    var pt=document.getElementById('plugin-types');
    if(pt)_authFetch('/api/v1/plugin/types').then(function(r){return r.json();}).then(function(t){
      var types=t.types||{};
      pt.innerHTML='<div class="cards">'+Object.keys(types).map(function(k){return '<div class="crd"><h3>'+_esc(k)+'</h3><p>'+_esc(types[k])+'</p></div>';}).join('')+'</div>';
    });
  });
}
/* Helper: fetch JSON and invoke render callback */
function _fetchAndRender(url,statsId,renderFn){
  var el=document.getElementById(statsId);
  if(el)el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(url).then(function(r){return r.json();}).then(function(d){renderFn(d);}).catch(function(e){
    if(el)el.innerHTML='<div class="exec-out" style="color:var(--red)">Failed to load: '+_esc(e.toString())+'</div>';
  });
}
/* Helper: stat cards HTML */
/* ── Inventory ── */
function loadInventory(){
  var out=document.getElementById('inventory-out');
  if(out)out.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch(API.INVENTORY).then(function(r){return r.json()}).then(function(d){
    var hosts=d.hosts||[];var vms=d.vms||[];var containers=d.containers||[];
    var h=_statCards([{l:'Hosts',v:hosts.length},{l:'VMs',v:vms.length,c:'purple'},{l:'Containers',v:containers.length,c:'green'}]);
    h+='<div style="margin-top:16px"><h4 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">HOSTS</h4>';
    if(hosts.length){
      h+='<table><thead><tr><th>Label</th><th>IP</th><th>Type</th><th>OS</th><th>CPU</th><th>RAM</th></tr></thead><tbody>';
      hosts.forEach(function(ho){h+='<tr><td><strong>'+_esc(ho.label||ho.hostname)+'</strong></td><td class="mono-11">'+_esc(ho.ip)+'</td><td>'+_esc(ho.type||'-')+'</td><td>'+_esc(ho.os||'-')+'</td><td>'+_esc(ho.cpu||'-')+'</td><td>'+_esc(ho.ram||'-')+'</td></tr>';});
      h+='</tbody></table>';
    }else h+='<div class="exec-out">No hosts</div>';
    h+='</div>';
    h+='<div style="margin-top:16px"><h4 style="font-size:12px;color:var(--text-dim);margin-bottom:8px">VMS (showing first 50)</h4>';
    if(vms.length){
      h+='<table><thead><tr><th>VMID</th><th>Name</th><th>Node</th><th>Status</th><th>CPU</th><th>RAM</th></tr></thead><tbody>';
      vms.slice(0,50).forEach(function(v){h+='<tr><td>'+_esc(String(v.vmid))+'</td><td>'+_esc(v.name)+'</td><td>'+_esc(v.node||'-')+'</td><td>'+_statusBadge(v.status)+'</td><td>'+(v.cpus||'-')+'</td><td>'+_esc(v.maxmem||'-')+'</td></tr>';});
      h+='</tbody></table>';
    }else h+='<div class="exec-out">No VMs</div>';
    h+='</div>';
    if(out)out.innerHTML=h;
  }).catch(function(e){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function loadInventoryView(type){
  var out=document.getElementById('inventory-out');
  if(out)out.innerHTML='<div class="skeleton h-40"></div>';
  var url=type==='hosts'?API.INVENTORY_HOSTS:type==='vms'?API.INVENTORY_VMS:API.INVENTORY_CONTAINERS;
  _authFetch(url).then(function(r){return r.json()}).then(function(d){
    var items=d[type]||d.hosts||d.vms||d.containers||[];
    if(!items.length){if(out)out.innerHTML='<div class="exec-out">No '+type+' found.</div>';return;}
    if(out)out.innerHTML='<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">'+items.length+' '+type+'</div><pre style="font-size:11px;background:var(--bg2);padding:12px;border-radius:6px;max-height:500px;overflow:auto">'+_esc(JSON.stringify(items,null,2))+'</pre>';
  }).catch(function(e){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function runHostCompare(){
  var a=document.getElementById('compare-host-a').value;
  var b=document.getElementById('compare-host-b').value;
  var out=document.getElementById('compare-out');
  if(!a||!b){if(out)out.innerHTML='<div class="exec-out">Select two hosts.</div>';return;}
  if(a===b){if(out)out.innerHTML='<div class="exec-out">Select two different hosts.</div>';return;}
  if(out)out.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch(API.COMPARE+'?host_a='+encodeURIComponent(a)+'&host_b='+encodeURIComponent(b)).then(function(r){return r.json()}).then(function(d){
    if(d.error){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(d.error)+'</div>';return;}
    var ha=d.host_a||{};var hb=d.host_b||{};
    var h='<table><thead><tr><th>Property</th><th>'+_esc(a)+'</th><th>'+_esc(b)+'</th></tr></thead><tbody>';
    var keys=new Set(Object.keys(ha).concat(Object.keys(hb)));
    keys.forEach(function(k){
      var va=ha[k]!==undefined?String(ha[k]):'-';
      var vb=hb[k]!==undefined?String(hb[k]):'-';
      var diff=va!==vb?' style="color:var(--yellow)"':'';
      h+='<tr><td style="color:var(--text-dim)">'+_esc(k)+'</td><td'+diff+'>'+_esc(va)+'</td><td'+diff+'>'+_esc(vb)+'</td></tr>';
    });
    h+='</tbody></table>';
    if(out)out.innerHTML=h;
  }).catch(function(e){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
function generateReport(){
  var out=document.getElementById('inventory-out');
  if(out)out.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch(API.REPORT).then(function(r){return r.json()}).then(function(d){
    if(out)out.innerHTML='<pre style="font-size:11px;background:var(--bg2);padding:12px;border-radius:6px;max-height:600px;overflow:auto;white-space:pre-wrap">'+_esc(d.report||JSON.stringify(d,null,2))+'</pre>';
  }).catch(function(e){if(out)out.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
/* ── Backup Policies (DR page) ── */
function loadBackupPolicies(){
  _authFetch(API.BACKUP_POLICY_LIST).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('backup-policy-list');if(!el)return;
    var policies=d.policies||[];
    if(!policies.length){el.innerHTML='<div class="exec-out">No backup policies defined. Create policies with <code>freq backup-policy create</code>.</div>';return;}
    var h='<table><thead><tr><th>Name</th><th>Schedule</th><th>Retention</th><th>Targets</th><th>Enabled</th></tr></thead><tbody>';
    policies.forEach(function(p){
      h+='<tr><td><strong>'+_esc(p.name)+'</strong></td><td>'+_esc(p.schedule||p.cron||'-')+'</td><td>'+_esc(p.retention||'-')+'</td><td>'+_esc((p.targets||[]).join(', ')||p.target||'all')+'</td><td>'+(p.enabled!==false?'<span class="c-green">ON</span>':'<span class="c-red">OFF</span>')+'</td></tr>';
    });
    h+='</tbody></table>';
    el.innerHTML=h;
  }).catch(function(e){var el=document.getElementById('backup-policy-list');if(el)el.innerHTML='<div class="exec-out">'+_esc(e.toString())+'</div>';});
  /* Policy enforcement status */
  _authFetch(API.BACKUP_POLICY_STATUS).then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('backup-policy-stats');if(!el)return;
    var stats=d.stats||{};
    if(stats.total)el.innerHTML=_statCards([{l:'Policies',v:stats.total||0},{l:'Compliant',v:stats.compliant||0,c:'green'},{l:'Violations',v:stats.violations||0,c:stats.violations>0?'red':'green'}]);
  }).catch(function(e){console.error('API error:',e);});
}
/* ── Trend Data (Capacity page) ── */
function takeTrendSnapshot(){
  _authFetch(API.TREND_SNAPSHOT).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast('Trend snapshot saved','success');
    else toast(d.error||'Snapshot failed','error');
    loadTrendData();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function loadTrendData(){
  var el=document.getElementById('trend-data');
  if(el)el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.TREND_DATA).then(function(r){return r.json()}).then(function(d){
    var snaps=d.snapshots||[];
    if(!snaps.length){if(el)el.innerHTML='<div class="exec-out">No trend data. Run <code>freq trend snapshot</code> to start collecting capacity trends.</div>';return;}
    var h='<div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">'+d.total+' total snapshots (showing last '+snaps.length+')</div>';
    h+='<table><thead><tr><th>Time</th><th>Hosts</th><th>Avg CPU</th><th>Avg RAM</th><th>Avg Disk</th></tr></thead><tbody>';
    snaps.slice(-20).reverse().forEach(function(s){
      h+='<tr><td>'+_esc(s.time||'-')+'</td><td>'+(s.host_count||'-')+'</td><td>'+(s.avg_cpu||'-')+'%</td><td>'+(s.avg_ram||'-')+'%</td><td>'+(s.avg_disk||'-')+'%</td></tr>';
    });
    h+='</tbody></table>';
    if(el)el.innerHTML=h;
  }).catch(function(e){if(el)el.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
/* ── Capacity Recommendations ── */
function loadCapRecommend(){
  var el=document.getElementById('cap-recommend');
  if(el)el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.CAPACITY_RECOMMEND).then(function(r){return r.json()}).then(function(d){
    var recs=d.recommendations||[];
    if(!recs.length){if(el)el.innerHTML='<div class="exec-out" style="color:var(--text-dim);font-size:11px">0 recommendations at current thresholds</div>';return;}
    var h=_statCards([{l:'Recommendations',v:d.count||recs.length},{l:'Critical',v:d.critical||0,c:'red'},{l:'Warning',v:d.warning||0,c:'yellow'}]);
    h+='<div style="margin-top:12px">';
    recs.forEach(function(r){
      var color=r.urgency==='critical'?'red':r.urgency==='warning'?'yellow':'green';
      h+='<div style="padding:10px;margin-bottom:8px;border-left:3px solid var(--'+color+');background:var(--bg2);border-radius:4px">';
      h+='<strong style="color:var(--'+color+')">'+_esc(r.type||r.action||'recommendation')+'</strong>';
      if(r.vm)h+=' &mdash; VM '+_esc(r.vm);
      if(r.from)h+=' from '+_esc(r.from);
      if(r.to)h+=' &rarr; '+_esc(r.to);
      h+='<div style="font-size:12px;color:var(--text-dim);margin-top:4px">'+_esc(r.reason||r.message||'')+'</div>';
      h+='</div>';
    });
    h+='</div>';
    if(el)el.innerHTML=h;
  }).catch(function(e){if(el)el.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
/* ── Playbook Create ── */
function createPlaybook(){
  var name=document.getElementById('pb-create-name').value.trim();
  var desc=document.getElementById('pb-create-desc').value.trim();
  var trigger=document.getElementById('pb-create-trigger').value.trim();
  var msg=document.getElementById('pb-create-msg');
  if(!name){if(msg)msg.innerHTML='<span class="c-red">Name required</span>';return;}
  _authFetch(API.PLAYBOOKS_CREATE+'?name='+encodeURIComponent(name)+'&description='+encodeURIComponent(desc)+'&trigger='+encodeURIComponent(trigger))
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){if(msg)msg.innerHTML='<span class="c-red">'+_esc(d.error)+'</span>';return;}
    if(msg)msg.innerHTML='<span class="c-green">Created: '+_esc(d.filename)+'</span>';
    document.getElementById('pb-create-name').value='';
    document.getElementById('pb-create-desc').value='';
    document.getElementById('pb-create-trigger').value='';
    loadPlaybooks();
  }).catch(function(e){if(msg)msg.innerHTML='<span class="c-red">Failed: '+_esc(e.toString())+'</span>';});
}
/* ═══════════════════════════════════════════════════════════════════
   TERMINAL — in-browser SSH via xterm.js + WebSocket
   ═══════════════════════════════════════════════════════════════════ */
var _termSession=null;var _termSocket=null;var _termXterm=null;var _termFit=null;

function openTerminal(type,target,node,label,htype){
  var overlay=document.getElementById('terminal-overlay');
  var container=document.getElementById('terminal-container');
  var title=document.getElementById('terminal-title');
  if(!overlay||!container)return;

  overlay.style.display='block';
  container.innerHTML='';
  title.textContent=(label||target)+' ('+type+')';

  /* Create xterm instance */
  var term=new Terminal({
    cursorBlink:true,cursorStyle:'bar',
    fontFamily:"'JetBrains Mono','Fira Code','Cascadia Code',monospace",
    fontSize:13,lineHeight:1.3,
    theme:{
      background:'#08090D',foreground:'#E2E8F0',cursor:'#A855F7',
      cursorAccent:'#08090D',selectionBackground:'rgba(168,85,247,0.35)',
      black:'#0C0E14',red:'#EF4444',green:'#22C55E',yellow:'#EAB308',
      blue:'#3B82F6',magenta:'#A855F7',cyan:'#06B6D4',white:'#E2E8F0',
      brightBlack:'#4B5563',brightRed:'#F87171',brightGreen:'#4ADE80',
      brightYellow:'#FDE047',brightBlue:'#60A5FA',brightMagenta:'#C084FC',
      brightCyan:'#22D3EE',brightWhite:'#F8FAFC'
    },
    allowProposedApi:true,
    scrollback:5000,
  });

  /* Fit addon — auto-resize to container */
  var fitAddon=new FitAddon.FitAddon();
  term.loadAddon(fitAddon);

  /* Clipboard addon */
  if(typeof ClipboardAddon!=='undefined'){
    try{term.loadAddon(new ClipboardAddon.ClipboardAddon());}catch(e){}
  }

  term.open(container);
  fitAddon.fit();
  _termXterm=term;_termFit=fitAddon;

  /* Request session from server */
  var cols=term.cols;var rows=term.rows;
  /* Build display name: "VM 103 · qbit" for VMs, just label for nodes/infra */
  var _displayName=label||target;
  if(type==='vm'&&target&&target.match(/^\d+$/)&&label&&label!==target){
    _displayName='VM '+target+' \u00b7 '+label;
  }else if(type==='ct'&&target&&label){
    _displayName='CT '+target+' \u00b7 '+label;
  }

  /* Helper: center text in a 45-char field */
  function _center(txt,w){w=w||45;var pad=Math.max(0,Math.floor((w-txt.length)/2));return Array(pad+1).join(' ')+txt;}

  /* Show connecting state */
  term.writeln('\x1b[90m  Connecting to '+_esc(_displayName)+'...\x1b[0m');

  _authFetch('/api/terminal/open?type='+type+'&target='+encodeURIComponent(target)+
    (node?'&node='+encodeURIComponent(node):'')+
    (htype?'&htype='+encodeURIComponent(htype):'')+
    '&cols='+cols+'&rows='+rows)
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){term.writeln('\x1b[31mError: '+d.error+'\x1b[0m');return;}
    _termSession=d.session;

    /* Open websocket */
    var proto=location.protocol==='https:'?'wss:':'ws:';
    var ws=new WebSocket(proto+'//'+location.host+'/api/terminal/ws?session='+d.session);
    ws.binaryType='arraybuffer';
    _termSocket=ws;

    var enc=new TextEncoder();
    var ps1='\\[\\e[90m\\]\u250c\u2500 \\[\\e[35m\\]\u25c6 \\[\\e[36;1m\\]\\u\\[\\e[0m\\] \\[\\e[90m\\]\u00b7\\[\\e[0m\\] \\[\\e[1m\\]\\h\\[\\e[0m\\] \\[\\e[90m\\]:\\[\\e[34m\\] \\w\\[\\e[0m\\]\\n\\[\\e[90m\\]\u2514\u2500\\[\\e[35m\\]\u25b8\\[\\e[0m\\] ';
    var _muted=true;

    /* Draw banner immediately — no server data needed */
    var W=45;
    var dm='\x1b[90m',cy='\x1b[36m',pu='\x1b[35m',bd='\x1b[1m',rs='\x1b[0m';
    var bar=dm+'  '+Array(W+1).join('\u2550')+rs;
    term.writeln('');
    term.writeln(bar);
    term.writeln('');
    term.writeln(pu+bd+_center('\u25c6\u25c6\u25c6   PVE FREQ   \u25c6\u25c6\u25c6',W)+rs);
    term.writeln('');
    term.writeln(cy+bd+_center(_displayName,W)+rs);
    term.writeln('');
    term.writeln(dm+_center('~ \u223f ~ \u223f ~  LOW FREQ Labs  ~ \u223f ~ \u223f ~',W)+rs);
    term.writeln('');
    term.writeln(bar);
    term.writeln('');

    /* Mute SSH banner, unmute only after PS1 is set */
    ws.onmessage=function(e){
      if(_muted) return;
      if(e.data instanceof ArrayBuffer) term.write(new Uint8Array(e.data));
      else term.write(e.data);
    };

    ws.onopen=function(){
      term.focus();
      var ht=htype||'linux';
      var isBash=(ht==='linux'||ht==='pve'||ht==='docker');
      if(isBash){
        /* Bash shells: set FREQ prompt, clear SSH banner, unmute after 1.5s */
        ws.send(enc.encode('export PS1=\''+ps1+'\'; clear\n'));
        setTimeout(function(){
          if(ws.readyState!==WebSocket.OPEN) return;
          _muted=false;
          ws.send(enc.encode('\n'));
        }, 1500);
      }else{
        /* Non-bash (pfsense/truenas/idrac/switch): unmute fast, show native prompt.
           These often need password auth — user must see the password prompt. */
        _muted=false;
      }
    };
    ws.onclose=function(){
      term.writeln('\r\n\x1b[90m--- Session closed ---\x1b[0m');
      _termSession=null;_termSocket=null;
    };
    ws.onerror=function(){
      term.writeln('\r\n\x1b[31mConnection failed\x1b[0m');
    };

    /* Send keystrokes to server */
    term.onData(function(data){
      if(ws.readyState===WebSocket.OPEN){
        ws.send(new TextEncoder().encode(data));
      }
    });

    /* Handle resize */
    term.onResize(function(size){
      if(_termSession){
        _authFetch('/api/terminal/resize?session='+_termSession+'&cols='+size.cols+'&rows='+size.rows);
      }
    });

  }).catch(function(e){term.writeln('\x1b[31mFailed to open session: '+e+'\x1b[0m');});

  /* Resize on window resize */
  window._termResizeHandler=function(){if(_termFit)try{_termFit.fit();}catch(e){}};
  window.addEventListener('resize',window._termResizeHandler);

  /* Keyboard shortcut: Escape to close */
  /* Don't intercept Escape — terminal needs it. Use the CLOSE button. */
}

function closeTerminal(){
  if(_termSocket&&_termSocket.readyState===WebSocket.OPEN)_termSocket.close();
  if(_termSession)_authFetch('/api/terminal/close?session='+_termSession);
  if(_termXterm){_termXterm.dispose();_termXterm=null;}
  _termSession=null;_termSocket=null;_termFit=null;
  document.getElementById('terminal-overlay').style.display='none';
  if(window._termResizeHandler)window.removeEventListener('resize',window._termResizeHandler);
}

function termCopy(){
  if(!_termXterm)return;
  var sel=_termXterm.getSelection();
  if(sel){
    navigator.clipboard.writeText(sel).then(function(){toast('Copied to clipboard','success');});
  }else{toast('Nothing selected','info');}
}

function termPaste(){
  if(!_termXterm)return;
  navigator.clipboard.readText().then(function(text){
    if(_termSocket&&_termSocket.readyState===WebSocket.OPEN){
      _termSocket.send(new TextEncoder().encode(text));
    }
  }).catch(function(){toast('Clipboard access denied','error');});
}

/* Terminal target picker */
function updateTermTargets(){
  var type=document.getElementById('term-type').value;
  var sel=document.getElementById('term-target');if(!sel)return;
  sel.innerHTML='<option value="">Loading...</option>';
  if(type==='vm'){
    _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      sel.innerHTML='<option value="">Select VM...</option>';
      (d.vms||[]).forEach(function(v){if(v.status==='running')sel.innerHTML+='<option value="'+v.vmid+'" data-label="'+_esc(v.name)+'">'+v.vmid+' — '+_esc(v.name)+' ('+v.node+')</option>';});
    });
  }else if(type==='ct'){
    _authFetch(API.CT_LIST).then(function(r){return r.json()}).then(function(d){
      sel.innerHTML='<option value="">Select CT...</option>';
      (d.containers||[]).forEach(function(c){if(c.status==='running')sel.innerHTML+='<option value="'+c.ctid+'" data-label="CT '+c.ctid+' '+_esc(c.name)+'">CT '+c.ctid+' — '+_esc(c.name)+' ('+c.node+')</option>';});
    });
  }else if(type==='node'){
    if(_fleetCache.fo&&_fleetCache.fo.pve_nodes){
      sel.innerHTML='<option value="">Select node...</option>';
      _fleetCache.fo.pve_nodes.forEach(function(n){sel.innerHTML+='<option value="'+_esc(n.ip)+'" data-label="'+_esc(n.name)+'">'+_esc(n.name)+' ('+_esc(n.ip)+')</option>';});
    }else{
      _authFetch(API.FLEET_OVERVIEW).then(function(r){return r.json()}).then(function(fo){
        sel.innerHTML='<option value="">Select node...</option>';
        (fo.pve_nodes||[]).forEach(function(n){sel.innerHTML+='<option value="'+_esc(n.ip)+'" data-label="'+_esc(n.name)+'">'+_esc(n.name)+' ('+_esc(n.ip)+')</option>';});
      });
    }
  }else if(type==='pfsense'||type==='truenas'||type==='idrac'||type==='switch'){
    /* Infrastructure devices — filter fleet hosts by type */
    _authFetch(API.HEALTH).then(function(r){return r.json()}).then(function(d){
      sel.innerHTML='<option value="">Select device...</option>';
      (d.hosts||[]).forEach(function(h){
        if(h.type===type||(type==='pfsense'&&h.type==='pfsense')||(type==='truenas'&&h.type==='truenas')||(type==='idrac'&&h.type==='idrac')||(type==='switch'&&h.type==='switch'))
          sel.innerHTML+='<option value="'+_esc(h.ip)+'" data-label="'+_esc(h.label)+'" data-htype="'+_esc(h.type)+'">'+_esc(h.label)+' ('+_esc(h.ip)+')</option>';
      });
    });
  }else{
    _authFetch(API.HEALTH).then(function(r){return r.json()}).then(function(d){
      sel.innerHTML='<option value="">Select host...</option>';
      (d.hosts||[]).forEach(function(h){sel.innerHTML+='<option value="'+_esc(h.ip)+'" data-label="'+_esc(h.label)+'" data-htype="'+_esc(h.type||'linux')+'">'+_esc(h.label)+' ('+_esc(h.ip)+')</option>';});
    });
  }
}
function launchTermFromPicker(){
  var type=document.getElementById('term-type').value;
  var sel=document.getElementById('term-target');
  var target=sel.value;
  if(!target){toast('Select a target','error');return;}
  var opt=sel.options[sel.selectedIndex];
  var label=opt.getAttribute('data-label')||target;
  var htype=opt.getAttribute('data-htype')||type;
  /* For infra devices, use 'vm' type (direct SSH) but pass the htype for SSH config */
  var termType=(type==='pfsense'||type==='truenas'||type==='idrac'||type==='switch'||type==='host')?'vm':type;
  openTerminal(termType,target,'',label,htype);
}

/* ═══════════════════════════════════════════════════════════════════
   LXC CONTAINERS — first-class citizen
   ═══════════════════════════════════════════════════════════════════ */
function loadLxcContainers(){
  var section=document.getElementById('fleet-sec-ct');
  var stats=document.getElementById('ct-stats');
  var cards=document.getElementById('ct-cards');
  if(stats)stats.innerHTML='<div class="skeleton h-40"></div>';
  if(cards)cards.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch(API.CT_LIST).then(function(r){return r.json()}).then(function(d){
    var cts=d.containers||[];
    if(!cts.length){if(section)section.style.display='none';return;}
    if(section)section.style.display='';
    if(stats)stats.innerHTML=_statCards([{l:'Containers',v:d.count||0},{l:'Running',v:d.running||0,c:'green'},{l:'Stopped',v:d.stopped||0,c:d.stopped>0?'yellow':'green'}]);
    var h='';
    cts.forEach(function(c){
      var running=c.status==='running';
      var ramGB=c.maxmem>0?(c.maxmem/1073741824).toFixed(1)+'G':'?';
      var ramUsed=c.mem>0?(c.mem/1073741824).toFixed(1)+'G':'0';
      h+='<div class="crd '+(running?'crd-up':'crd-down')+'">';
      h+='<div style="display:flex;justify-content:space-between;align-items:center">';
      h+='<h3 style="margin:0">CT '+c.ctid+' — '+_esc(c.name)+'</h3>';
      h+='<div style="display:flex;gap:4px">';
      if(running){
        h+='<button class="fleet-btn" style="font-size:9px;padding:2px 6px" onclick="ctPower('+c.ctid+',\'stop\')">STOP</button>';
        h+='<button class="fleet-btn" style="font-size:9px;padding:2px 6px" onclick="ctPower('+c.ctid+',\'reboot\')">REBOOT</button>';
        h+='<button class="fleet-btn" style="font-size:9px;padding:2px 6px;color:var(--cyan)" onclick="openTerminal(\'ct\',\''+c.ctid+'\',\'\',\'CT '+c.ctid+' '+_esc(c.name)+'\')">&#9002; TERM</button>';
      }else{
        h+='<button class="fleet-btn" style="font-size:9px;padding:2px 6px;color:var(--green)" onclick="ctPower('+c.ctid+',\'start\')">START</button>';
        h+='<button class="fleet-btn" style="font-size:9px;padding:2px 6px;color:var(--red)" onclick="ctDestroy('+c.ctid+',\''+_esc(c.name)+'\')">DESTROY</button>';
      }
      h+='</div></div>';
      h+='<p style="margin-top:6px">'+_statusBadge(c.status)+' &middot; '+_esc(c.node)+' &middot; CPU: '+c.maxcpu+' &middot; RAM: '+ramUsed+'/'+ramGB+' ('+c.mem_pct+'%)';
      if(c.tags)h+=' &middot; <span style="color:var(--purple-light)">'+_esc(c.tags)+'</span>';
      h+='</p></div>';
    });
    if(cards)cards.innerHTML=h;
  }).catch(function(e){
    if(stats)stats.innerHTML='';
    if(cards)cards.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';
  });
}
function ctPower(ctid,action){
  var msg=action==='stop'?'Stop':'Reboot';
  if(action==='start')msg='Start';
  confirmAction(msg+' container <strong>CT '+ctid+'</strong>?',function(){
    toast(msg+'ing CT '+ctid+'...','info');
    _authFetch(API.CT_POWER+'?ctid='+ctid+'&action='+action,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      if(d.ok)toast('CT '+ctid+' '+action+' OK','success');
      else toast(d.error||'Failed','error');
      setTimeout(loadLxcContainers,1500);
    }).catch(function(e){toast('Failed: '+e,'error');});
  });
}
function ctDestroy(ctid,name){
  confirmAction('Destroy container <strong>CT '+ctid+' ('+_esc(name)+')</strong>? This cannot be undone.',function(){
    toast('Destroying CT '+ctid+'...','info');
    _authFetch(API.CT_DESTROY+'?ctid='+ctid,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      if(d.ok)toast('CT '+ctid+' destroyed','success');
      else toast(d.error||'Failed','error');
      setTimeout(loadLxcContainers,1500);
    }).catch(function(e){toast('Failed: '+e,'error');});
  });
}
function openCtTool(tool){
  var form=document.getElementById('ct-tool-form');
  var out=document.getElementById('ct-tool-out');
  if(out)out.innerHTML='';
  if(!form)return;
  if(tool==='create'){
    form.innerHTML='<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:8px">'+
      '<div><label class="c-dim-fs12">Template</label><input id="ct-create-tpl" class="input" placeholder="local:vztmpl/debian-12..." style="width:320px"></div>'+
      '<div><label class="c-dim-fs12">Hostname</label><input id="ct-create-name" class="input" placeholder="my-container" style="width:160px"></div>'+
      '<div><label class="c-dim-fs12">Cores</label><select id="ct-create-cores" class="input"><option>1</option><option selected>2</option><option>4</option></select></div>'+
      '<div><label class="c-dim-fs12">RAM (MB)</label><select id="ct-create-ram" class="input"><option>256</option><option selected>512</option><option>1024</option><option>2048</option><option>4096</option></select></div>'+
      '<div><label class="c-dim-fs12">Disk (GB)</label><input id="ct-create-disk" class="input" value="8" style="width:60px" type="number"></div>'+
      '<button class="fleet-btn c-purple-active" onclick="doCtCreate()">CREATE</button>'+
      '<button class="fleet-btn" onclick="loadCtTemplates()">LIST TEMPLATES</button>'+
      '</div>';
  }else if(tool==='clone'){
    _ctSelectForm(form,'CLONE','ct-clone-src','<button class="fleet-btn c-purple-active" onclick="doCtClone()">CLONE</button>',
      '<div><label class="c-dim-fs12">New Name</label><input id="ct-clone-name" class="input" placeholder="clone-name" style="width:160px"></div>');
  }else if(tool==='migrate'){
    _ctSelectForm(form,'MIGRATE','ct-mig-src','<div><label class="c-dim-fs12">Target Node</label><input id="ct-mig-target" class="input" placeholder="pve02" style="width:120px"></div><button class="fleet-btn c-purple-active" onclick="doCtMigrate()">MIGRATE</button>');
  }else if(tool==='resize'){
    _ctSelectForm(form,'RESIZE DISK','ct-rsz-src','<div><label class="c-dim-fs12">Size</label><input id="ct-rsz-size" class="input" placeholder="+5G" style="width:80px"></div><button class="fleet-btn c-purple-active" onclick="doCtResize()">RESIZE</button>');
  }else if(tool==='snapshot'){
    _ctSelectForm(form,'SNAPSHOT','ct-snap-src','<div><label class="c-dim-fs12">Name</label><input id="ct-snap-name" class="input" placeholder="snap-name" style="width:140px"></div><button class="fleet-btn c-purple-active" onclick="doCtSnapshot()">CREATE</button>');
  }else if(tool==='rollback'){
    _ctSelectForm(form,'ROLLBACK','ct-rb-src','<div><label class="c-dim-fs12">Snapshot</label><input id="ct-rb-name" class="input" placeholder="(blank=latest)" style="width:140px"></div><button class="fleet-btn c-purple-active" onclick="doCtRollback()">ROLLBACK</button>');
  }else if(tool==='exec'){
    _ctSelectForm(form,'EXEC','ct-exec-src','<div><label class="c-dim-fs12">Command</label><input id="ct-exec-cmd" class="input" placeholder="apt update && apt upgrade -y" style="width:300px"></div><button class="fleet-btn c-purple-active" onclick="doCtExec()">RUN</button>');
  }else if(tool==='config'){
    _ctSelectForm(form,'CONFIG','ct-cfg-src','<button class="fleet-btn c-purple-active" onclick="doCtConfig()">VIEW CONFIG</button>');
  }else if(tool==='templates'){
    form.innerHTML='';loadCtTemplates();
  }
}
function _ctSelectForm(form,label,selId,extra,before){
  form.innerHTML='<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:8px">'+
    '<div><label class="c-dim-fs12">Container</label><select id="'+selId+'" class="input" style="width:220px"><option value="">Loading...</option></select></div>'+
    (before||'')+extra+'</div>';
  _authFetch(API.CT_LIST).then(function(r){return r.json()}).then(function(d){
    var sel=document.getElementById(selId);if(!sel)return;
    sel.innerHTML='<option value="">Select CT...</option>';
    (d.containers||[]).forEach(function(c){sel.innerHTML+='<option value="'+c.ctid+'">CT '+c.ctid+' — '+_esc(c.name)+' ('+c.status+')</option>';});
  });
}
function doCtCreate(){
  var tpl=document.getElementById('ct-create-tpl').value.trim();
  var name=document.getElementById('ct-create-name').value.trim();
  var cores=document.getElementById('ct-create-cores').value;
  var ram=document.getElementById('ct-create-ram').value;
  var disk=document.getElementById('ct-create-disk').value;
  var out=document.getElementById('ct-tool-out');
  if(!tpl||!name){toast('Template and hostname required','error');return;}
  if(out)out.innerHTML='<div class="c-yellow">Creating container...</div>';
  _authFetch(API.CT_CREATE+'?template='+encodeURIComponent(tpl)+'&hostname='+encodeURIComponent(name)+'&cores='+cores+'&ram='+ram+'&disk='+disk)
  .then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('CT '+d.ctid+' created','success');if(out)out.innerHTML='<div class="c-green">Container CT '+d.ctid+' ('+_esc(d.hostname)+') created.</div>';loadLxcContainers();}
    else{toast(d.error||'Failed','error');if(out)out.innerHTML='<div class="c-red">'+_esc(d.error)+'</div>';}
  }).catch(function(e){if(out)out.innerHTML='<div class="c-red">'+_esc(e.toString())+'</div>';});
}
function doCtClone(){
  var ctid=document.getElementById('ct-clone-src').value;var name=document.getElementById('ct-clone-name').value.trim();
  var out=document.getElementById('ct-tool-out');
  if(!ctid){toast('Select a container','error');return;}
  if(out)out.innerHTML='<div class="c-yellow">Cloning CT '+ctid+'...</div>';
  _authFetch(API.CT_CLONE+'?ctid='+ctid+(name?'&name='+encodeURIComponent(name):''))
  .then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Cloned to CT '+d.new_ctid,'success');if(out)out.innerHTML='<div class="c-green">Cloned CT '+ctid+' → CT '+d.new_ctid+'</div>';loadLxcContainers();}
    else{if(out)out.innerHTML='<div class="c-red">'+_esc(d.error)+'</div>';}
  }).catch(function(e){if(out)out.innerHTML='<div class="c-red">'+_esc(e.toString())+'</div>';});
}
function doCtMigrate(){
  var ctid=document.getElementById('ct-mig-src').value;var target=document.getElementById('ct-mig-target').value.trim();
  var out=document.getElementById('ct-tool-out');
  if(!ctid||!target){toast('Container and target node required','error');return;}
  if(out)out.innerHTML='<div class="c-yellow">Migrating CT '+ctid+' → '+_esc(target)+'...</div>';
  _authFetch(API.CT_MIGRATE+'?ctid='+ctid+'&target='+encodeURIComponent(target))
  .then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('CT '+ctid+' migrated to '+_esc(target),'success');if(out)out.innerHTML='<div class="c-green">Migrated</div>';loadLxcContainers();}
    else{if(out)out.innerHTML='<div class="c-red">'+_esc(d.error)+'</div>';}
  }).catch(function(e){if(out)out.innerHTML='<div class="c-red">'+_esc(e.toString())+'</div>';});
}
function doCtResize(){
  var ctid=document.getElementById('ct-rsz-src').value;var size=document.getElementById('ct-rsz-size').value.trim();
  var out=document.getElementById('ct-tool-out');
  if(!ctid||!size){toast('Container and size required','error');return;}
  if(out)out.innerHTML='<div class="c-yellow">Resizing...</div>';
  _authFetch(API.CT_RESIZE+'?ctid='+ctid+'&size='+encodeURIComponent(size))
  .then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('CT '+ctid+' resized','success');if(out)out.innerHTML='<div class="c-green">Resized to '+_esc(size)+'</div>';}
    else{if(out)out.innerHTML='<div class="c-red">'+_esc(d.error)+'</div>';}
  }).catch(function(e){if(out)out.innerHTML='<div class="c-red">'+_esc(e.toString())+'</div>';});
}
function doCtSnapshot(){
  var ctid=document.getElementById('ct-snap-src').value;var name=document.getElementById('ct-snap-name').value.trim()||('freq-snap-'+ctid);
  var out=document.getElementById('ct-tool-out');
  if(!ctid){toast('Select a container','error');return;}
  if(out)out.innerHTML='<div class="c-yellow">Creating snapshot...</div>';
  _authFetch(API.CT_SNAPSHOT+'?ctid='+ctid+'&name='+encodeURIComponent(name))
  .then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Snapshot "'+_esc(d.snapshot)+'" created','success');if(out)out.innerHTML='<div class="c-green">Snapshot created</div>';}
    else{if(out)out.innerHTML='<div class="c-red">'+_esc(d.error)+'</div>';}
  }).catch(function(e){if(out)out.innerHTML='<div class="c-red">'+_esc(e.toString())+'</div>';});
}
function doCtRollback(){
  var ctid=document.getElementById('ct-rb-src').value;var name=document.getElementById('ct-rb-name').value.trim();
  var out=document.getElementById('ct-tool-out');
  if(!ctid){toast('Select a container','error');return;}
  confirmAction('Roll back CT '+ctid+(name?' to "'+_esc(name)+'"':' to latest snapshot')+'?',function(){
    if(out)out.innerHTML='<div class="c-yellow">Rolling back...</div>';
    _authFetch(API.CT_ROLLBACK+'?ctid='+ctid+(name?'&name='+encodeURIComponent(name):''))
    .then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast('CT '+ctid+' rolled back','success');if(out)out.innerHTML='<div class="c-green">Rolled back to "'+_esc(d.snapshot)+'"</div>';loadLxcContainers();}
      else{if(out)out.innerHTML='<div class="c-red">'+_esc(d.error)+'</div>';}
    }).catch(function(e){if(out)out.innerHTML='<div class="c-red">'+_esc(e.toString())+'</div>';});
  });
}
function doCtExec(){
  var ctid=document.getElementById('ct-exec-src').value;var cmd=document.getElementById('ct-exec-cmd').value.trim();
  var out=document.getElementById('ct-tool-out');
  if(!ctid||!cmd){toast('Container and command required','error');return;}
  if(out)out.innerHTML='<div class="c-yellow">Executing on CT '+ctid+'...</div>';
  _authFetch(API.CT_EXEC+'?ctid='+ctid+'&command='+encodeURIComponent(cmd))
  .then(function(r){return r.json()}).then(function(d){
    if(d.ok){if(out)out.innerHTML='<pre style="font-size:10px;background:var(--bg2);padding:12px;border-radius:6px;max-height:400px;overflow:auto;white-space:pre-wrap">'+_esc(d.stdout||'(no output)')+'</pre>';}
    else{if(out)out.innerHTML='<div class="c-red">'+_esc(d.error)+'</div>';}
  }).catch(function(e){if(out)out.innerHTML='<div class="c-red">'+_esc(e.toString())+'</div>';});
}
function doCtConfig(){
  var ctid=document.getElementById('ct-cfg-src').value;
  var out=document.getElementById('ct-tool-out');
  if(!ctid){toast('Select a container','error');return;}
  if(out)out.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.CT_CONFIG+'?ctid='+ctid).then(function(r){return r.json()}).then(function(d){
    if(d.error){if(out)out.innerHTML='<div class="c-red">'+_esc(d.error)+'</div>';return;}
    var config=d.config||{};
    var h='<h4 style="font-size:11px;color:var(--purple-light);margin-bottom:8px">CT '+ctid+' Configuration</h4>';
    h+='<table><tbody>';
    Object.keys(config).sort().forEach(function(k){h+='<tr><td style="color:var(--text-dim);width:180px">'+_esc(k)+'</td><td>'+_esc(config[k])+'</td></tr>';});
    h+='</tbody></table>';
    if(out)out.innerHTML=h;
  }).catch(function(e){if(out)out.innerHTML='<div class="c-red">'+_esc(e.toString())+'</div>';});
}
function loadCtTemplates(){
  var out=document.getElementById('ct-tool-out');
  if(out)out.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.CT_TEMPLATES).then(function(r){return r.json()}).then(function(d){
    var tpls=d.templates||[];
    if(!tpls.length){if(out)out.innerHTML='<div class="exec-out">No templates found. Download with: <code>pveam download local debian-12-standard_12.2-1_amd64.tar.zst</code></div>';return;}
    var h='<h4 style="font-size:11px;color:var(--purple-light);margin-bottom:8px">Available Templates ('+tpls.length+')</h4>';
    h+='<table><thead><tr><th>Volume ID</th><th>Name</th><th>Size</th></tr></thead><tbody>';
    tpls.forEach(function(t){h+='<tr><td class="mono-11">'+_esc(t.volid)+'</td><td>'+_esc(t.name)+'</td><td>'+_esc(t.size)+'</td></tr>';});
    h+='</tbody></table>';
    if(out)out.innerHTML=h;
  }).catch(function(e){if(out)out.innerHTML='<div class="c-red">'+_esc(e.toString())+'</div>';});
}

/* ═══════════════════════════════════════════════════════════════════
   FINAL WIRING — remaining endpoints
   ═══════════════════════════════════════════════════════════════════ */
/* Docker: stack status/health */
function loadStackInfo(type){
  var el=document.getElementById('stack-info');if(!el)return;
  el.innerHTML='<div class="skeleton h-40"></div>';
  var url=type==='health'?API.STACK_HEALTH:API.STACK_STATUS;
  _authFetch(url).then(function(r){return r.json()}).then(function(d){
    if(type==='status'){
      var stacks=d.stacks||[];
      if(!stacks.length){el.innerHTML='<div class="exec-out">No Docker Compose stacks found across fleet.</div>';return;}
      var h=_statCards([{l:'Stacks',v:d.total||stacks.length}]);
      h+='<table style="margin-top:8px"><thead><tr><th>Host</th><th>Stack</th><th>Status</th><th>Services</th></tr></thead><tbody>';
      stacks.forEach(function(s){h+='<tr><td><strong>'+_esc(s.host)+'</strong></td><td>'+_esc(s.name)+'</td><td>'+_statusBadge(s.status)+'</td><td>'+_esc(s.services)+'</td></tr>';});
      h+='</tbody></table>';
      el.innerHTML=h;
    }else{
      var containers=d.containers||[];
      if(!containers.length){el.innerHTML='<div class="exec-out">No running containers found.</div>';return;}
      var h=_statCards([{l:'Containers',v:d.total||0},{l:'Healthy',v:d.healthy||0,c:'green'},{l:'Unhealthy',v:d.unhealthy||0,c:d.unhealthy>0?'red':'green'}]);
      h+='<table style="margin-top:8px"><thead><tr><th>Host</th><th>Container</th><th>Status</th><th>Image</th></tr></thead><tbody>';
      containers.forEach(function(c){h+='<tr><td>'+_esc(c.host)+'</td><td><strong>'+_esc(c.name)+'</strong></td><td>'+_statusBadge(c.healthy?'healthy':'unhealthy')+'</td><td class="mono-11">'+_esc((c.image||'').split('/').pop())+'</td></tr>';});
      h+='</tbody></table>';
      el.innerHTML=h;
    }
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
/* System info panel */
function loadSysInfo(type){
  var el=document.getElementById('sysinfo-out');if(!el)return;
  el.innerHTML='<div class="skeleton h-40"></div>';
  var urls={db:API.DB_STATUS,logs:API.LOGS_STATS,proxy:API.PROXY_LIST,pool:API.POOL,deploy:API.DEPLOY_AGENT,setup:API.SETUP_STATUS};
  _authFetch(urls[type]||urls.db).then(function(r){return r.json()}).then(function(d){
    if(d.info||d.message){el.innerHTML='<div class="exec-out">'+_esc(d.info||d.message)+(d.usage?'<br><code>'+_esc(d.usage)+'</code>':'')+(d.note?'<br><span style="color:var(--text-dim)">'+_esc(d.note)+'</span>':'')+'</div>';return;}
    if(type==='db'){
      var dbs=d.databases||[];
      if(!dbs.length){el.innerHTML='<div class="exec-out">No PostgreSQL or MySQL/MariaDB instances detected across fleet.</div>';return;}
      var h=_statCards([{l:'DB Hosts',v:d.total||dbs.length}]);
      h+='<table style="margin-top:8px"><thead><tr><th>Host</th><th>PostgreSQL</th><th>MySQL</th><th>Connections</th><th>Size</th></tr></thead><tbody>';
      dbs.forEach(function(db){h+='<tr><td><strong>'+_esc(db.host)+'</strong></td><td>'+_statusBadge(db.postgres==='no'?'off':db.postgres)+'</td><td>'+_statusBadge(db.mysql==='no'?'off':db.mysql)+'</td><td>'+db.active_connections+'</td><td>'+(db.db_size_mb>0?db.db_size_mb+'MB':'-')+'</td></tr>';});
      h+='</tbody></table>';
      el.innerHTML=h;return;
    }
    if(type==='logs'){
      var patterns=d.patterns||[];
      if(!patterns.length){el.innerHTML='<div class="exec-out" style="color:var(--green)">No errors in the last '+_esc(d.period||'1h')+' across '+d.hosts_scanned+' hosts.</div>';return;}
      var h='<div style="font-size:11px;color:var(--text-dim);margin-bottom:8px">'+d.total_errors+' total errors in last '+_esc(d.period||'1h')+' across '+d.hosts_scanned+' hosts</div>';
      h+='<table><thead><tr><th>Count</th><th>Error Pattern</th></tr></thead><tbody>';
      patterns.forEach(function(p){h+='<tr><td style="color:var(--red);font-weight:700">'+p.count+'</td><td>'+_esc(p.pattern)+'</td></tr>';});
      h+='</tbody></table>';
      el.innerHTML=h;return;
    }
    if(type==='proxy'){
      var routes=d.routes||[];
      if(!routes.length){el.innerHTML='<div class="exec-out">No proxy routes configured.</div>';return;}
      var h='<table><thead><tr><th>Path</th><th>Target</th><th>Host</th></tr></thead><tbody>';
      routes.forEach(function(r){h+='<tr><td>'+_esc(r.path||'-')+'</td><td class="mono-11">'+_esc(r.target||'-')+'</td><td>'+_esc(r.host||'-')+'</td></tr>';});
      h+='</tbody></table>';
      el.innerHTML=h;return;
    }
    if(type==='pool'){
      var pools=d.pools||[];
      if(!pools.length){el.innerHTML='<div class="exec-out">No storage pools found.</div>';return;}
      var h='<table><thead><tr><th>Pool</th><th>Type</th><th>Size</th><th>Used</th><th>Status</th></tr></thead><tbody>';
      pools.forEach(function(p){h+='<tr><td><strong>'+_esc(p.name||p.pool)+'</strong></td><td>'+_esc(p.type||'-')+'</td><td>'+_esc(p.size||'-')+'</td><td>'+_esc(p.used||'-')+'</td><td>'+_statusBadge(p.status||'ok')+'</td></tr>';});
      h+='</tbody></table>';
      el.innerHTML=h;return;
    }
    if(type==='setup'){
      var h='<table><tbody>';
      Object.keys(d).forEach(function(k){
        var v=d[k];var vs=typeof v==='boolean'?(v?'<span style="color:var(--green)">true</span>':'<span style="color:var(--red)">false</span>'):_esc(String(v));
        h+='<tr><td style="color:var(--text-dim);width:200px">'+_esc(k)+'</td><td>'+vs+'</td></tr>';
      });
      h+='</tbody></table>';
      el.innerHTML=h;return;
    }
    el.innerHTML='<pre style="font-size:11px;background:var(--bg2);padding:12px;border-radius:6px;max-height:400px;overflow:auto">'+_esc(JSON.stringify(d,null,2))+'</pre>';
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
/* DR: migration planning */
function loadMigratePlan(){
  var el=document.getElementById('migrate-plan-out');if(!el)return;
  el.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch(API.MIGRATE_PLAN).then(function(r){return r.json()}).then(function(d){
    if(d.error){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(d.error)+'</div>';return;}
    var nodes=d.nodes||[];var recs=d.recommendations||[];
    var h=_statCards([{l:'Nodes',v:nodes.length},{l:'VMs',v:d.total_vms||0},{l:'Avg RAM',v:(d.avg_mem_pct||0)+'%'},{l:'Recommendations',v:recs.length,c:recs.length>0?'yellow':'green'}]);
    if(nodes.length){
      h+='<h4 style="font-size:11px;color:var(--text-dim);margin:12px 0 6px">NODE RESOURCES</h4>';
      h+='<table><thead><tr><th>Node</th><th>CPU</th><th>RAM %</th><th>RAM Used</th><th>RAM Total</th><th>Balance</th></tr></thead><tbody>';
      nodes.forEach(function(n){
        var mc=n.mem_pct>85?'red':n.mem_pct>70?'yellow':'green';
        var bc=n.balance>5?'red':n.balance<-5?'green':'text-dim';
        h+='<tr><td><strong>'+_esc(n.node)+'</strong></td><td>'+n.cpu_pct+'%</td><td style="color:var(--'+mc+')">'+n.mem_pct+'%</td><td>'+n.mem_used_gb+'G</td><td>'+n.mem_total_gb+'G</td><td style="color:var(--'+bc+')">'+(n.balance>0?'+':'')+n.balance+'%</td></tr>';
      });
      h+='</tbody></table>';
    }
    if(recs.length){
      h+='<h4 style="font-size:11px;color:var(--text-dim);margin:12px 0 6px">RECOMMENDED MIGRATIONS</h4>';
      recs.forEach(function(r,i){
        h+='<div style="padding:8px 12px;margin-bottom:6px;border-left:3px solid var(--yellow);background:var(--bg2);border-radius:4px">';
        h+='<strong>'+(i+1)+'. Move VM '+r.vmid+' ('+_esc(r.vm_name)+') ['+(r.vm_ram_mb||0)+'MB]</strong><br>';
        h+='<span style="color:var(--text-dim)">'+_esc(r.from_node)+' ('+r.from_mem_pct+'% → '+r.projected_from+'%) → '+_esc(r.to_node)+' ('+r.to_mem_pct+'% → '+r.projected_to+'%)</span>';
        if(r.impact)h+='<br><span style="font-size:10px;color:var(--text-dim)">'+_esc(r.impact)+'</span>';
        h+='</div>';
      });
    }else if(nodes.length){
      h+='<div class="exec-out" style="color:var(--text-dim);margin-top:12px;font-size:11px">0 migration candidates at current mem thresholds across '+nodes.length+' nodes</div>';
    }
    el.innerHTML=h;
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
function loadVmwareMigration(){
  var el=document.getElementById('migrate-plan-out');if(!el)return;
  el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.MIGRATE_VMWARE).then(function(r){return r.json()}).then(function(d){
    var scans=d.scans||[];var imports=d.imports||[];
    if(!scans.length&&!imports.length){el.innerHTML='<div class="exec-out">No VMware migration data. Run <code>freq dr migrate-vmware scan</code> to discover.</div>';return;}
    var h='';
    if(scans.length){h+='<h4 style="font-size:11px;color:var(--text-dim);margin-bottom:8px">SCANS</h4><pre style="font-size:11px;background:var(--bg2);padding:12px;border-radius:6px;max-height:200px;overflow:auto">'+_esc(JSON.stringify(scans,null,2))+'</pre>';}
    if(imports.length){h+='<h4 style="font-size:11px;color:var(--text-dim);margin:12px 0 8px">IMPORTS</h4><pre style="font-size:11px;background:var(--bg2);padding:12px;border-radius:6px;max-height:200px;overflow:auto">'+_esc(JSON.stringify(imports,null,2))+'</pre>';}
    el.innerHTML=h;
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
/* Cost analysis */
function loadCostAnalysis(type){
  var el=document.getElementById('cost-analysis-out');if(!el)return;
  el.innerHTML='<div class="skeleton h-40"></div>';
  var url=type==='waste'?API.COST_WASTE:API.COST_COMPARE;
  _authFetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.error){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(d.error)+'</div>';return;}
    if(type==='waste'){
      var waste=d.waste||[];var stopped=d.stopped||[];
      var h=_statCards([{l:'Running VMs',v:d.running||0},{l:'Overprovisioned',v:waste.length,c:waste.length>0?'yellow':'green'},{l:'Stopped',v:stopped.length,c:stopped.length>0?'yellow':'green'},{l:'Potential Savings',v:'$'+(d.potential_savings||0)+'/mo',c:'green'}]);
      if(waste.length){
        h+='<h4 style="font-size:11px;color:var(--text-dim);margin:12px 0 8px">OVERPROVISIONED VMS</h4>';
        h+='<table><thead><tr><th>VMID</th><th>Name</th><th>Issue</th><th>CPU Use</th><th>RAM Use</th><th>Savings</th></tr></thead><tbody>';
        waste.forEach(function(w){h+='<tr><td>'+w.vmid+'</td><td><strong>'+_esc(w.name)+'</strong></td><td style="color:var(--yellow)">'+_esc(w.issues.join('; '))+'</td><td>'+w.cpu_usage+'%</td><td>'+w.mem_usage+'%</td><td style="color:var(--green)">$'+w.savings_month+'/mo</td></tr>';});
        h+='</tbody></table>';
      }
      if(stopped.length){
        h+='<h4 style="font-size:11px;color:var(--text-dim);margin:12px 0 8px">STOPPED VMS (allocated but idle)</h4>';
        h+='<div style="display:flex;gap:6px;flex-wrap:wrap">';
        stopped.forEach(function(s){h+='<span class="badge warn">'+s.vmid+' '+_esc(s.name)+' ('+s.vcpu+'c/'+s.ram_mb+'MB)</span>';});
        h+='</div>';
      }
      if(!waste.length&&!stopped.length)h+='<div class="exec-out" style="color:var(--green);margin-top:12px">No significant waste detected.</div>';
      el.innerHTML=h;
    }else{
      var vms=d.vms||[];
      var h=_statCards([{l:'On-Prem/mo',v:'$'+d.total_onprem},{l:'AWS/mo',v:'$'+d.total_aws,c:'red'},{l:'Monthly Savings',v:'$'+d.monthly_savings,c:'green'},{l:'Cheaper',v:d.pct_cheaper_onprem+'%',c:'green'}]);
      h+='<div style="font-size:11px;color:var(--text-dim);margin:8px 0">Annual savings: <strong style="color:var(--green)">$'+d.annual_savings+'</strong> &middot; Rate: $'+d.rate_per_kwh+'/kWh</div>';
      if(vms.length){
        h+='<table style="margin-top:8px"><thead><tr><th>VMID</th><th>Name</th><th>Specs</th><th>On-Prem</th><th>AWS</th><th>Savings</th></tr></thead><tbody>';
        vms.forEach(function(v){h+='<tr><td>'+v.vmid+'</td><td><strong>'+_esc(v.name)+'</strong></td><td>'+v.vcpu+'c/'+v.ram_gb+'G</td><td>$'+v.onprem_month+'</td><td style="color:var(--red)">$'+v.aws_month+'</td><td style="color:var(--green)">$'+v.savings+'</td></tr>';});
        h+='</tbody></table>';
      }
      el.innerHTML=h;
    }
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
/* API docs */
function openApiDocs(){
  var el=document.getElementById('api-docs-out');if(!el)return;
  el.innerHTML='<iframe src="'+API.API_DOCS+'" style="width:100%;height:600px;border:1px solid var(--border);border-radius:8px;background:#0d1117"></iframe>';
}
function loadOpenApi(){
  var el=document.getElementById('api-docs-out');if(!el)return;
  el.innerHTML='<div class="skeleton h-60"></div>';
  _authFetch(API.OPENAPI).then(function(r){return r.json()}).then(function(d){
    var paths=Object.keys(d.paths||{});
    var h=_statCards([{l:'Endpoints',v:paths.length},{l:'Version',v:d.info?.version||'?'}]);
    h+='<pre style="margin-top:12px;font-size:10px;background:var(--bg2);padding:12px;border-radius:6px;max-height:500px;overflow:auto">'+_esc(JSON.stringify(d,null,2))+'</pre>';
    el.innerHTML=h;
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
function loadPrometheus(){
  var el=document.getElementById('api-docs-out');if(!el)return;
  el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.METRICS_PROMETHEUS).then(function(r){return r.text()}).then(function(txt){
    el.innerHTML='<pre style="font-size:11px;background:var(--bg2);padding:12px;border-radius:6px;max-height:500px;overflow:auto;color:var(--green)">'+_esc(txt)+'</pre>';
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
/* Patch compliance */
function loadPatchCompliance(){
  var el=document.getElementById('patrol-out');if(!el)return;
  el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.PATCH_COMPLIANCE).then(function(r){return r.json()}).then(function(d){
    if(d.error){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(d.error)+'</div>';return;}
    var pct=d.compliance_pct||0;var color=pct>=95?'green':pct>=80?'yellow':'red';
    var h=_statCards([{l:'Compliance',v:pct+'%',c:color},{l:'Compliant',v:d.compliant||0,c:'green'},{l:'Total Scanned',v:d.total||0}]);
    var hosts=d.hosts||[];
    if(hosts.length){
      h+='<table style="margin-top:12px"><thead><tr><th>Host</th><th>Status</th><th>Updates Available</th></tr></thead><tbody>';
      hosts.forEach(function(ho){
        var sc=ho.status==='compliant'?'green':ho.status==='unreachable'?'red':'yellow';
        h+='<tr><td><strong>'+_esc(ho.host)+'</strong></td><td>'+_statusBadge(ho.status)+'</td><td>'+(ho.updates>0?'<span style="color:var(--yellow)">'+ho.updates+'</span>':'-')+'</td></tr>';
      });
      h+='</tbody></table>';
    }
    el.innerHTML=h;
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
/* Netmon interfaces */
function loadNetmonInterfaces(){
  var el=document.getElementById('netmon-out');if(!el)return;
  el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.NETMON_INTERFACES).then(function(r){return r.json()}).then(function(d){
    var allHosts=d.hosts||[];
    if(!allHosts.length){el.innerHTML='<div class="exec-out">No interface data. Hosts may be unreachable.</div>';return;}
    var h='<div style="font-size:11px;color:var(--text-dim);margin-bottom:8px">'+d.total_interfaces+' interfaces across '+allHosts.length+' hosts</div>';
    allHosts.forEach(function(host){
      var ifaces=host.interfaces||[];
      if(!ifaces.length)return;
      h+='<h4 style="font-size:11px;color:var(--purple-light);margin:12px 0 6px">'+_esc(host.host)+'</h4>';
      h+='<table><thead><tr><th>Interface</th><th>State</th><th>IPs</th><th>MAC</th><th>MTU</th></tr></thead><tbody>';
      ifaces.forEach(function(i){
        h+='<tr><td><strong>'+_esc(i.name)+'</strong></td><td>'+_statusBadge(i.state)+'</td><td class="mono-11">'+_esc((i.ips||[]).join(', ')||'-')+'</td><td class="mono-11">'+_esc(i.mac||'-')+'</td><td>'+_esc(String(i.mtu||'-'))+'</td></tr>';
      });
      h+='</tbody></table>';
    });
    el.innerHTML=h;
  }).catch(function(e){el.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
/* GitOps init */
function gitopsInit(){
  confirmAction('Initialize GitOps config tracking? This creates the git repo in your config directory.',function(){
    _authFetch(API.GITOPS_INIT).then(function(r){return r.json()}).then(function(d){
      if(d.error){toast(d.error,'error');return;}
      toast('GitOps initialized','success');loadGitops();
    }).catch(function(e){toast('Failed: '+e,'error');});
  });
}
/* Media downloads detail */
function loadDownloadDetail(){
  var el=document.getElementById('dl-detail');if(!el)return;
  el.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.MEDIA_DOWNLOADS_DETAIL).then(function(r){return r.json()}).then(function(d){
    var active=d.active||[];var queued=d.queued||[];var hist=d.history||[];
    if(!active.length&&!queued.length&&!hist.length){el.innerHTML='<div class="exec-out">No download activity.</div>';return;}
    var h='';
    if(active.length)h+='<div style="margin-bottom:8px;color:var(--green);font-weight:600">'+active.length+' active download(s)</div>';
    if(queued.length)h+='<div style="margin-bottom:8px;color:var(--yellow)">'+queued.length+' queued</div>';
    if(hist.length)h+='<div style="margin-bottom:8px;color:var(--text-dim)">'+hist.length+' in history</div>';
    h+='<pre style="font-size:10px;background:var(--bg2);padding:12px;border-radius:6px;max-height:300px;overflow:auto">'+_esc(JSON.stringify(d,null,2))+'</pre>';
    el.innerHTML=h;
  }).catch(function(e){el.innerHTML='';});
}
function _statCards(items){
  return '<div style="display:flex;gap:12px;flex-wrap:wrap">'+items.map(function(i){
    var color=i.c?'color:var(--'+i.c+')':'';
    return '<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:8px 14px;text-align:center;min-width:85px"><div style="font-size:18px;font-weight:700;'+color+'">'+i.v+'</div><div style="font-size:8px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">'+i.l+'</div></div>';
  }).join('')+'</div>';
}
/* Helper: status badge */
function _statusBadge(status){
  var s=(status||'unknown').toLowerCase();
  var c=s==='up'||s==='online'||s==='ok'||s==='pass'||s==='valid'||s==='active'||s==='resolved'||s==='healthy'||s==='protected'?'green':s==='down'||s==='offline'||s==='fail'||s==='critical'||s==='expired'||s==='error'?'red':s==='warning'||s==='degraded'||s==='stale'||s==='expiring'||s==='investigating'?'yellow':'text-dim';
  return '<span style="color:var(--'+c+');font-weight:600;text-transform:uppercase;font-size:11px">'+_esc(s)+'</span>';
}
/* _esc() defined at top of file — single-quote escaping included */

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
var _labAssignments;try{_labAssignments=JSON.parse(localStorage.getItem('freq_lab_assign')||'{}');}catch(e){_labAssignments={};}
function _getLabLabels(healthHosts){
  /* Merge: server-side groups + label matching + client-side overrides */
  var labels={};
  if(healthHosts){healthHosts.forEach(function(h){
    if(h.groups&&h.groups.indexOf('lab')>=0)labels[h.label]=true;
    else if(h.label&&h.label.toLowerCase().indexOf('lab')>=0)labels[h.label]=true;
  });}
  /* Also tag VMs in fleet-boundaries lab category */
  PROD_VMS.forEach(function(v){if(v.category==='lab')labels[v.label]=true;});
  /* Apply user overrides from Settings */
  if(_labAssignments&&typeof _labAssignments==='object'){Object.keys(_labAssignments).forEach(function(k){
    if(_labAssignments[k])labels[k]=true;
    else delete labels[k];
  });}
  return labels;
}
function _loadLabAssignments(){
  var el=document.getElementById('lab-assign-list');if(!el)return;
  /* Need both fleet overview (for VMs) and health (for hosts) */
  Promise.all([
    _authFetch(API.FLEET_OVERVIEW).then(function(r){return r.json();}),
    _authFetch(API.HEALTH).then(function(r){return r.json();})
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
    var h='<table><thead><tr><th>Name</th><th>Type</th><th>Node</th><th>Status</th><th class="text-center">LAB</th></tr></thead><tbody>';
    items.forEach(function(it){
      var isLab=_labAssignments[it.label]!==undefined?_labAssignments[it.label]:it.serverLab;
      var statusColor=it.status==='online'||it.status==='running'?'var(--green)':'var(--text-dim)';
      h+='<tr><td><strong>'+it.label+'</strong></td>';
      h+='<td class="mono-11">'+it.type.toUpperCase()+'</td>';
      h+='<td class="mono-11">'+(it.node||'-')+'</td>';
      h+='<td><span style="color:'+statusColor+'">'+it.status.toUpperCase()+'</span></td>';
      h+='<td class="text-center"><span onclick="toggleLabAssign(\''+it.label+'\','+!isLab+')" style="cursor:pointer;display:inline-block;padding:2px 10px;border-radius:4px;font-size:11px;font-weight:600;border:1px solid '+(isLab?'var(--green)':'var(--border-light)')+';background:'+(isLab?'rgba(63,185,80,0.15)':'transparent')+';color:'+(isLab?'var(--green)':'var(--text-dim)')+'">'+(isLab?'LAB':'—')+'</span></td>';
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
  _authFetch('/api/rules').then(function(r){return r.json()}).then(function(d){
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
  _authFetch('/api/rules/create?name='+encodeURIComponent(n)+'&condition='+c+'&target='+encodeURIComponent(t)+'&threshold='+th+'&duration='+dur+'&cooldown='+cd+'&severity='+sev)
  .then(function(r){return r.json()}).then(function(d){
    if(d.error){msg.innerHTML='<span class="c-red">'+d.error+'</span>';return;}
    msg.innerHTML='<span class="c-green">Rule created</span>';loadRules();
    document.getElementById('rule-name').value='';
  }).catch(function(e){msg.innerHTML='<span class="c-red">Failed: '+e+'</span>';});
}
function toggleRule(name,enabled){
  _authFetch('/api/rules/update?name='+encodeURIComponent(name)+'&enabled='+enabled)
  .then(function(r){return r.json()}).then(function(d){loadRules();});
}
function deleteRule(name){
  if(!confirm('Delete rule "'+name+'"?'))return;
  _authFetch('/api/rules/delete?name='+encodeURIComponent(name))
  .then(function(r){return r.json()}).then(function(d){loadRules();});
}
function loadAlertHistory(){
  _authFetch('/api/rules/history').then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.ADMIN_BOUNDARIES).then(function(r){return r.json()}).then(function(d){
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
  h+='<p class="desc-line">Change host type or groups. Updates hosts.toml immediately.</p>';
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
      h+='<div class="flex-center mt-sm">';
      h+='<span class="text-sub">VMID Range:</span>';
      h+='<input id="rs-'+cat+'" type="number" value="'+info.range_start+'" class="input-sm">';
      h+='<span class="c-dim">—</span>';
      h+='<input id="re-'+cat+'" type="number" value="'+info.range_end+'" class="input-sm">';
      h+='<button class="fleet-btn pill-ok-sm" data-action="updateCategoryRange" data-arg="'+cat+'" >SAVE</button>';
      h+='</div>';
    } else {
      var vmids=(info.vmids||[]).join(', ');
      h+='<div class="mt-8">';
      h+='<div class="text-sm text-dim" style="margin-bottom:4px">VMIDs: <span style="color:var(--text)">'+vmids+'</span></div>';
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
  var url='/api/admin/hosts/update?label='+encodeURIComponent(label)+'&type='+encodeURIComponent(typeEl.value)+'&groups='+encodeURIComponent(groupEl.value);
  _authFetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.error){toast('Error: '+d.error,'error');return;}
    toast(label+' updated','success');
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function updateCategoryTier(cat,tier){
  _authFetch(API.ADMIN_BOUNDARIES_UPDATE+'?action=update_category_tier&category='+encodeURIComponent(cat)+'&tier='+encodeURIComponent(tier)).then(function(r){return r.json()}).then(function(d){
    if(d.error){toast('Error: '+d.error,'error');return;}
    toast(cat+' tier \u2192 '+tier,'success');loadFleetAdmin();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function updateCategoryRange(cat){
  var rs=document.getElementById('rs-'+cat);
  var re=document.getElementById('re-'+cat);
  if(!rs||!re)return;
  _authFetch(API.ADMIN_BOUNDARIES_UPDATE+'?action=update_range&category='+encodeURIComponent(cat)+'&range_start='+rs.value+'&range_end='+re.value).then(function(r){return r.json()}).then(function(d){
    if(d.error){toast('Error: '+d.error,'error');return;}
    toast(cat+' range updated','success');loadFleetAdmin();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function addVmidToCategory(cat){
  var el=document.getElementById('vmid-add-'+cat);
  if(!el||!el.value)return;
  _authFetch(API.ADMIN_BOUNDARIES_UPDATE+'?action=add_vmid&category='+encodeURIComponent(cat)+'&vmid='+el.value).then(function(r){return r.json()}).then(function(d){
    if(d.error){toast('Error: '+d.error,'error');return;}
    toast('VMID '+el.value+' added to '+cat,'success');loadFleetAdmin();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function removeVmidFromCategory(cat,vmid){
  confirmAction('Remove VMID '+vmid+' from '+cat+'?',function(){
    _authFetch(API.ADMIN_BOUNDARIES_UPDATE+'?action=remove_vmid&category='+encodeURIComponent(cat)+'&vmid='+vmid).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.INFO).then(function(r){return r.json()}).then(function(d){
    document.getElementById('nav-ver').textContent='V'+d.version;
    if(d.install_method)window._freqInstallMethod=d.install_method;
    var vf=document.getElementById('home-ver-footer');if(vf)vf.textContent='v'+d.version;
    document.title=(d.brand||'PVE FREQ')+' Dashboard';
    var cr=document.getElementById('about-credits');if(cr)cr.textContent=(d.cluster||'')+(d.cluster?' · ':'')+(d.brand||'PVE FREQ');
  });
  /* Watchdog probe status — distinguish not-installed (501), down (503), and working (200) */
  _authFetch(API.WATCHDOG_HEALTH).then(function(r){
    var status=r.status;
    return r.json().then(function(d){return{status:status,data:d};}).catch(function(){return{status:status,data:{}};});
  }).then(function(res){
    var el=document.getElementById('watchdog-status');if(!el)return;
    var d=res.data||{};
    /* Not installed (501) — optional add-on, render plainly */
    if(res.status===501||d.watchdog_installed===false){
      el.innerHTML='<span style="color:var(--text-dim);font-size:11px">Watchdog: not installed (optional add-on)</span>';
      return;
    }
    /* Installed but daemon unreachable (503) */
    if(res.status===503||d.watchdog_down){
      el.innerHTML='<span style="color:var(--yellow);font-size:11px;font-weight:600">Watchdog: daemon not reachable</span>';
      return;
    }
    /* Error from daemon itself */
    if(d.error){
      el.innerHTML='<span style="color:var(--yellow);font-size:11px;font-weight:600">Watchdog: '+_esc(String(d.error)).substring(0,60)+'</span>';
      return;
    }
    /* Working — show probe evidence */
    var hosts=d.hosts||0;var errors=d.errors||0;var age=d.age_seconds?Math.round(d.age_seconds):null;
    var clr=errors>0?'yellow':hosts>0?'green':'text-dim';
    var parts=[];
    parts.push(hosts+' hosts probed');
    if(errors>0)parts.push(errors+' errors');
    if(age!==null)parts.push(age+'s ago');
    el.innerHTML='<span style="color:var(--'+clr+');font-size:11px;font-weight:600">Watchdog: '+parts.join(' · ')+'</span>';
  }).catch(function(){var el=document.getElementById('watchdog-status');if(el)el.innerHTML='<span style="color:var(--text-dim);font-size:11px">Watchdog: status unavailable</span>';});
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
var NODE_COLORS=Object.create(null);
function _assignNodeColors(){var pveHosts=PROD_HOSTS.filter(function(h){return h.type==='pve';});pveHosts.forEach(function(h,i){NODE_COLORS[h.label]=_NODE_PALETTE[i%_NODE_PALETTE.length];});}
var INFRA_GOLD='var(--text)';
function _hostColor(label,htype,node){
  /* Infra devices → gold */
  if(htype==='pfsense'||htype==='truenas'||htype==='switch'||htype==='docker'||htype==='idrac')return INFRA_GOLD;
  /* PVE nodes → node color */
  if(htype==='pve'){return (NODE_COLORS||{})[label]||INFRA_GOLD;}
  /* VMs → inherit from node */
  if(node)return (NODE_COLORS||{})[node]||'#79c0ff';
  /* Lab VMs → dim */
  var pv=(PROD_VMS||[]).find(function(v){return v.label===label;});
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
  if(!ph||!ph.type)return '';
  var roleInfo=(INFRA_ROLES||{})[ph.type]||{role:(ph.type||'DEVICE').toUpperCase(),icon:'\u2726',color:'var(--text-dim)'};
  var live=healthMap[ph.label];
  var up=ph.reachable||false;if(live&&live.status==='healthy')up=true;
  var safeId=ph.label.replace(/[^a-zA-Z0-9]/g,'-');
  var c='<div class="infra-role-card" onclick="openHost(\''+ph.label+'\')">';
  /* Role label row */
  c+='<div class="role-label" style="color:'+roleInfo.color+'"><span class="role-icon">'+roleInfo.icon+'</span>'+roleInfo.role+'</div>';
  /* Device name + status */
  c+='<div class="flex-between">';
  c+='<h3 class="device-name">'+ph.label+'</h3>';
  c+='<span id="infra-status-'+safeId+'" style="font-size:11px;font-weight:600;display:flex;align-items:center"><span class="status-dot '+(up?'up':'down')+'"></span>'+(up?'REACHABLE':'UNREACHABLE')+'</span>';
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
  _authFetch(API.INFRA_QUICK).then(function(r){return r.json()}).then(function(d){
    var ageEl=document.getElementById('core-systems-age');
    if(d.warming){
      /* Cache still warming — tell the operator instead of silently
       * retrying. "CACHE WARMING" is the operator-facing state; the
       * 3s retry still runs in the background. */
      if(ageEl){ageEl.textContent='CACHE WARMING';ageEl.style.color='var(--yellow)';}
      setTimeout(_enrichInfraCards,3000);
      return;
    }
    /* Show freshness on CORE SYSTEMS header */
    if(ageEl&&d.age!==undefined){
      var a=Math.round(d.age);
      ageEl.textContent=a<60?a+'s':Math.round(a/60)+'m';
      ageEl.style.color=a<30?'var(--green)':a<120?'var(--yellow)':'var(--red)';
    }
    d.devices.forEach(function(dev){
      var safeId=dev.label.replace(/[^a-zA-Z0-9]/g,'-');
      var el=document.getElementById('infra-metrics-'+safeId);
      var statusEl=document.getElementById('infra-status-'+safeId);
      if(!el)return;
      /* Update status dot */
      if(statusEl){
        statusEl.innerHTML='<span class="status-dot '+(dev.reachable?'up':'down')+'"></span>'+(dev.reachable?'REACHABLE':'UNREACHABLE');
      }
      if(!dev.reachable){
        var roleInfo=INFRA_ROLES[dev.type]||{};
        el.innerHTML=_roleOfflineMetrics(dev.type,roleInfo);
        return;
      }
      var m=dev.metrics;var h='';
      var _m=function(val,lbl,color){return '<div class="role-metric"><span class="rm-val" style="color:'+color+'">'+val+'</span><span class="rm-lbl">'+lbl+'</span></div>';};
      if(dev.type==='pfsense'||dev.type==='opnsense'){
        if(m.states||m.interfaces||m.uptime){
          h+=_m(m.states||'—','STATES','var(--cyan)');
          if(m.interfaces)h+=_m(m.interfaces,'IFACES','var(--text)');
          if(m.uptime){var pfUp=m.uptime.replace(/^up\s+/i,'').replace(/,\s*\d+:\d+$/,'');h+=_m(pfUp,'UPTIME','var(--green)');}
        } else {
          h+=_m('REACHABLE','GATEWAY','var(--green)');
          h+=_m('No SSH','METRICS','var(--text-dim)');
        }
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
  pfsense:[
    {l:'STATUS',f:"pfAction('status')"},{l:'RULES',f:"pfAction('rules')"},{l:'NAT',f:"pfAction('nat')"},{l:'STATES',f:"pfAction('states')"},{l:'INTERFACES',f:"pfAction('interfaces')"},{l:'GATEWAYS',f:"pfAction('gateways')"},{l:'GATEWAY MONITOR',f:"pfAction('gateway_monitor')"},{l:'DNS',f:"pfAction('dns')"},{l:'TRAFFIC',f:"pfAction('traffic')"},{l:'VPN',f:"pfAction('vpn')"},{l:'SERVICES',f:"pfAction('services')"},{l:'FIREWALL LOG',f:"pfAction('log')"},{l:'SYSTEM LOG',f:"pfAction('syslog')"},{l:'ARP TABLE',f:"pfAction('arp')"},{l:'DHCP LEASES',f:"pfAction('dhcp')"},{l:'ALIASES',f:"pfAction('aliases')"},{l:'BACKUP CONFIG',f:"pfAction('backup')"},
    /* Write operations */
    {l:'\u2699 RESTART SVC',f:"pfWriteService()",w:1},{l:'\u2699 DHCP RESERVE',f:"pfWriteDhcp()",w:1},{l:'\u2699 ADD FW RULE',f:"pfWriteRule()",w:1},{l:'\u2699 ADD NAT RULE',f:"pfWriteNat()",w:1},{l:'\u2699 WG PEERS',f:"pfWriteWgPeer()",w:1},{l:'\u2699 BACKUP NOW',f:"pfBackupNow()",w:1},{l:'\u2699 CHECK UPDATES',f:"pfCheckUpdates()",w:1},{l:'\u26a0 REBOOT',f:"pfReboot()",w:2}
  ],
  truenas:[
    {l:'SYSTEM',f:"tnAction('status')"},{l:'POOLS',f:"tnAction('pools')"},{l:'HEALTH',f:"tnAction('health')"},{l:'DATASETS',f:"tnAction('datasets')"},{l:'SHARES',f:"tnAction('shares')"},{l:'ALERTS',f:"tnAction('alerts')"},{l:'SMART DISKS',f:"tnAction('smart')"},{l:'SNAPSHOTS',f:"tnAction('snapshots')"},{l:'REPLICATION',f:"tnAction('replication')"},{l:'SERVICES',f:"tnAction('services')"},{l:'NETWORK',f:"tnAction('network')"},{l:'SYSTEM LOG',f:"tnAction('syslog')"},
    /* Write operations */
    {l:'\u2699 CREATE SNAP',f:"tnWriteSnapshot('create')",w:1},{l:'\u2699 DELETE SNAP',f:"tnWriteSnapshot('delete')",w:1},{l:'\u2699 ROLLBACK SNAP',f:"tnWriteSnapshot('rollback')",w:2},{l:'\u2699 RESTART SVC',f:"tnWriteService()",w:1},{l:'\u2699 SCRUB POOL',f:"tnWriteScrub()",w:1},{l:'\u2699 CREATE DATASET',f:"tnWriteDataset('create')",w:1},{l:'\u2699 DELETE DATASET',f:"tnWriteDataset('delete')",w:2},{l:'\u2699 CREATE SHARE',f:"tnWriteShare()",w:1},{l:'\u2699 RUN REPLICATION',f:"tnWriteReplication()",w:1},{l:'\u26a0 REBOOT',f:"tnReboot()",w:2}
  ],
  switch:[
    {l:'STATUS',f:"swAction('status')"},{l:'VLANS',f:"swAction('vlans')"},{l:'INTERFACES',f:"swAction('interfaces')"},{l:'MAC TABLE',f:"swAction('mac')"},{l:'TRUNKS',f:"swAction('trunk')"},{l:'PORT ERRORS',f:"swAction('errors')"},{l:'SPANNING TREE',f:"swAction('spanning')"},{l:'LOG',f:"swAction('log')"},{l:'CDP NEIGHBORS',f:"swAction('cdp')"},{l:'INVENTORY',f:"swAction('inventory')"},
    /* Write operations */
    {l:'\u2699 CREATE VLAN',f:"swWriteVlan('create')",w:1},{l:'\u2699 DELETE VLAN',f:"swWriteVlan('delete')",w:2},{l:'\u2699 MANAGE ACL',f:"swWriteAcl()",w:1}
  ],
  idrac:[
    {l:'SYSTEM INFO',f:"idracAction('status')"},{l:'SENSORS',f:"idracAction('sensors')"},{l:'EVENT LOG',f:"idracAction('sel')"},{l:'STORAGE / RAID',f:"idracAction('storage')"},{l:'NETWORK',f:"idracAction('network')"},{l:'FIRMWARE',f:"idracAction('firmware')"},{l:'LICENSE',f:"idracAction('license')"},
    /* Write operations */
    {l:'\u26a1 POWER ON',f:"idracWrite('poweron')",w:1},{l:'\u26a1 POWER OFF',f:"idracWrite('poweroff')",w:2},{l:'\u26a1 POWER CYCLE',f:"idracWrite('powercycle')",w:2},{l:'\u26a1 HARD RESET',f:"idracWrite('hardreset')",w:2},{l:'\u26a1 GRACEFUL OFF',f:"idracWrite('graceshutdown')",w:1},{l:'\u2699 CLEAR SEL',f:"idracWrite('clearsel')",w:1},{l:'\u2699 BOOT PXE',f:"idracWrite('bootpxe')",w:1},{l:'\u2699 BOOT BIOS',f:"idracWrite('bootbios')",w:1}
  ],
  /* ── OPNsense (REST API — not SSH) ── */
  opnsense:[
    {l:'STATUS',f:"opnAction('status')"},{l:'SERVICES',f:"opnAction('services')"},{l:'FW RULES',f:"opnAction('rules')"},{l:'DHCP',f:"opnAction('dhcp')"},{l:'DNS OVERRIDES',f:"opnAction('dns')"},{l:'WIREGUARD',f:"opnAction('wireguard')"},{l:'FIRMWARE',f:"opnAction('firmware')"},
    {l:'\u2699 RESTART SVC',f:"opnWriteService()",w:1},{l:'\u2699 ADD FW RULE',f:"opnWriteRule()",w:1},{l:'\u2699 DELETE FW RULE',f:"opnDeleteRule()",w:2},{l:'\u2699 ADD DHCP',f:"opnWriteDhcp()",w:1},{l:'\u2699 ADD DNS',f:"opnWriteDns()",w:1},{l:'\u2699 ADD WG PEER',f:"opnWriteWg()",w:1},{l:'\u26a0 REBOOT',f:"opnReboot()",w:2}
  ],
  /* ── Synology DSM (REST API) ── */
  synology:[
    {l:'SYSTEM',f:"synAction('status')"},{l:'STORAGE',f:"synAction('storage')"},{l:'SHARES',f:"synAction('shares')"},{l:'DOCKER',f:"synAction('docker')"},{l:'PACKAGES',f:"synAction('packages')"},
    {l:'\u2699 START/STOP PKG',f:"synWriteService()",w:1},{l:'\u26a0 REBOOT',f:"synReboot()",w:2}
  ],
  /* ── Generic IPMI (ipmitool from controller) ── */
  ipmi:[
    {l:'STATUS',f:"ipmiAction('status')"},{l:'SENSORS',f:"ipmiAction('sensors')"},{l:'EVENT LOG',f:"ipmiAction('sel')"},
    {l:'\u26a1 POWER ON',f:"ipmiWrite('on')",w:1},{l:'\u26a1 POWER OFF',f:"ipmiWrite('off')",w:2},{l:'\u26a1 POWER CYCLE',f:"ipmiWrite('cycle')",w:2},{l:'\u26a1 RESET',f:"ipmiWrite('reset')",w:2},{l:'\u2699 BOOT PXE',f:"ipmiWriteBoot('pxe')",w:1},{l:'\u2699 BOOT BIOS',f:"ipmiWriteBoot('bios')",w:1},{l:'\u2699 CLEAR SEL',f:"ipmiClearSel()",w:1}
  ],
  /* ── HP iLO / Redfish ── */
  ilo:[
    {l:'SYSTEM',f:"redfishAction('system')"},{l:'THERMAL',f:"redfishAction('thermal')"},{l:'POWER USAGE',f:"redfishAction('power-usage')"},{l:'EVENTS',f:"redfishAction('events')"},
    {l:'\u26a1 POWER ON',f:"redfishWrite('On')",w:1},{l:'\u26a1 FORCE OFF',f:"redfishWrite('ForceOff')",w:2},{l:'\u26a1 GRACEFUL OFF',f:"redfishWrite('GracefulShutdown')",w:1},{l:'\u26a1 FORCE RESTART',f:"redfishWrite('ForceRestart')",w:2}
  ]
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
    _authFetch(API.FLEET_OVERVIEW).then(function(r){return r.json()}).catch(function(){return null;}),
    _authFetch(API.HEALTH).then(function(r){return r.json()}).catch(function(){return null;}),
    _authFetch(API.MEDIA_STATUS).then(function(r){return r.json()}).catch(function(){return null;})
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
    var c='<div class="host-card cursor-ptr" data-host-id="'+h.label.toLowerCase()+'" onclick="openHost(\''+h.label+'\')" >';
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
  /* Also show lab-tagged or lab-category VMs from PVE that aren't in hosts.toml */
  var hostSet={};if(hosts)hosts.forEach(function(h){hostSet[h.label]=true;});
  PROD_VMS.forEach(function(v){
    if(hostSet[v.label])return;
    if(!labLabels[v.label]&&v.category!=='lab')return;
    var isRunning=v.status==='running';
    var cl=_hostColor(v.label,'vm',v.node);
    var c='<div class="host-card" data-host-id="'+v.label.toLowerCase()+'">';
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
    var up=(live&&live.status==='healthy')||pn.online===true;
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
    var detailRam=(pn.detail||'').match(/(\d+)GB/);var nodeRamStr=detailRam?detailRam[1]+'GB':(pn.ram_gb?pn.ram_gb+'GB':'?');
    var nodeCard='<div class="host-card" data-host-id="'+nodeName.toLowerCase()+'" style="cursor:pointer;" onclick="openVmInfo(\''+nodeName+'\',\''+pn.ip+'\',0)">';
    nodeCard+='<div class="mb-8"><div class="host-head" style="margin-bottom:2px"><h3 style="color:'+cl+'">'+nodeName+'</h3><div class="host-meta"><span>'+pn.ip+'</span><span>\u00b7</span><span>HYPERVISOR</span><span>\u00b7</span>'+(up?'<span class="c-green">ONLINE</span>':'<span class="c-red">OFFLINE</span>')+'</div></div><div style="font-size:12px;color:var(--text);font-weight:400">'+pn.detail+'</div></div>';
    nodeCard+='<div class="divider-light">';
    if(up){
      if(!live)live={cores:'0',load:'0',disk:'0%',ram:'0/0MB'};
      var cores=parseInt(live.cores)||1;var loadVal=parseFloat(live.load)||0;
      var loadPct=cores>0?Math.round(loadVal/cores*100):0;
      var diskPct=parseInt((live.disk||'0').replace('%',''))||0;
      var ramParts=(live.ram||'0/0MB').match(/(\d+)\/(\d+)/);
      var ramUsed=ramParts?parseInt(ramParts[1]):0;var ramTotal=ramParts?parseInt(ramParts[2]):1;
      var ramPct=ramTotal>0?Math.round(ramUsed/ramTotal*100):0;
      /* Initial render — PVE API poller fills real values within 2 seconds */
      var ramColor=ramPct>=80?'var(--red)':ramPct>=50?'var(--yellow)':'var(--blue)';
      nodeCard+='<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:6px 0">';
      nodeCard+=_fGrp('UTILIZATION',2,_fStat('...','CPU LOAD','var(--text-dim)')+_fStat('...','RAM USED','var(--text-dim)'));
      nodeCard+=_fGrp('VMs',3,_fStat(nVms,'TOTAL','var(--purple-light)')+_fStat(nOnline,'RUNNING','var(--green)')+_fStat(nOffline,'STOPPED','var(--red)'));
      nodeCard+=_fGrp('CONTAINERS',3,_fStat(dockerCount,'TOTAL','var(--purple-light)')+_fStat(dockerUp,'UP','var(--green)')+_fStat(dockerDown,'DOWN',dockerDown>0?'var(--red)':'var(--green)'));
      nodeCard+='</div>';
      nodeCard+='<div style="margin:6px 0">';
      nodeCard+=_mrow('CPU','...',0,'var(--text-dim)');
      nodeCard+=_mrow('RAM','...',0,'var(--text-dim)');
      nodeCard+=_mrow('DISK IO','...',0,'var(--text-dim)');
      nodeCard+=_mrow('STORAGE','...',0,'var(--text-dim)');
      nodeCard+='</div>';
    } else {
      nodeCard+='<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:6px 0">';
      nodeCard+=_fGrp('PVE NODE',2,_fStat(nCores,'CPU ALLOC','var(--purple-light)')+_fStat(nRamGb+'<span class="fs-12-fade">GB</span>','RAM ALLOC','var(--purple-light)'));
      nodeCard+=_fGrp('VMs',3,_fStat(nVms,'TOTAL','var(--purple-light)')+_fStat(nOnline,'RUNNING','var(--green)')+_fStat(nOffline,'STOPPED','var(--red)'));
      nodeCard+=_fGrp('CONTAINERS',3,_fStat(dockerCount,'TOTAL','var(--purple-light)')+_fStat(dockerUp,'UP','var(--green)')+_fStat(dockerDown,'DOWN',dockerDown>0?'var(--red)':'var(--green)'));
      nodeCard+='</div>';
      nodeCard+='<div id="pve-live-'+nodeName+'" style="margin:6px 0;padding:6px 8px;background:rgba(248,81,73,0.05);border:1px dashed var(--border);border-radius:6px;text-align:center">';
      nodeCard+='<span style="font-size:12px;color:var(--red);letter-spacing:0.5px">PVE METRICS: NOT REACHABLE</span>';
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
    var nodeColor=(NODE_COLORS||{})[nodeName]||'var(--text)';
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
  var ageLabel=hdAge<60?hdAge+'s':Math.round(hdAge/60)+'m';
  var ageColor=hdAge<30?'var(--green)':hdAge<120?'var(--yellow)':'var(--red)';
  var vmRunning=summary.running||0;var vmStopped=summary.stopped||0;
  var sumEl=document.getElementById('metrics-summary');
  sumEl.innerHTML=
    _fDual('FLEET SPLIT',summary.prod_count||0,'PROD','var(--purple-light)',summary.lab_count||0,'LAB','var(--cyan)')+
    _fDual('FLEET',prodCount,'PROD','var(--purple-light)',labCount,'LAB','var(--cyan)')+
    _fDual('PVE NODES',prodPveNodes,'PROD','var(--purple-light)',labPveNodes,'LAB','var(--cyan)')+
    _fDual('SSH PROBE',totalUp,'UP','var(--green)',totalDown,'DOWN','var(--red)')+
    _fDual('VMs',vmRunning,'RUN','var(--green)',vmStopped,'STOP','var(--red)')+
    _fDual('DATA',ageLabel,'AGE',ageColor,responseDur+'s','RESPONSE','var(--text-dim)')+
    st('CONTAINERS','...','p')+
    st('ACTIVITY','...','p');
  _authFetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(md){
    var _cdn2=Math.max(0,md.containers_down||0);var c=sumEl.querySelector('.st:nth-child(7)');if(c)c.innerHTML='<div class="lb">CONTAINERS</div><div class="flex-row-24"><span class="stat-pair"><span class="stat-big-green">'+(md.containers_running||0)+'</span><span class="label-hint">UP</span></span><span class="stat-pair"><span class="stat-big-red">'+_cdn2+'</span><span class="label-hint">DOWN</span></span></div>';
  }).catch(function(e){console.error('API error:',e);});
  Promise.all([
    _authFetch(API.MEDIA_DOWNLOADS).then(function(r){return r.json()}).catch(function(){return {count:0}}),
    _authFetch(API.MEDIA_STREAMS).then(function(r){return r.json()}).catch(function(){return {count:0}})
  ]).then(function(res){
    var dl=res[0].count||0;var str=res[1].count||0;
    var a=sumEl.querySelector('.st:nth-child(8)');if(a)a.innerHTML='<div class="lb">ACTIVITY</div><div class="flex-row-24"><span class="stat-pair"><span class="stat-big-orange">'+dl+'</span><span class="label-hint">DL</span></span><span class="stat-pair"><span class="stat-big-blue">'+str+'</span><span class="label-hint">STREAM</span></span></div>';
  });
}
function _enrichFleetNtpUpdates(){
  _authFetch(API.FLEET_NTP).then(function(r){return r.json()}).then(function(nd){
    nd.hosts.forEach(function(x){
      var el=document.getElementById('ntp-'+x.label.replace(/[^a-z0-9]/gi,''));
      if(el){var synced=x.synced;el.innerHTML='<div class="metric-top"><span class="metric-label">NTP</span><span class="metric-val" style="font-size:11px;color:'+(synced?'var(--green)':'var(--red)')+'">'+(synced?'SYNCED':'NOT SYNCED')+' <span style="color:var(--text-dim);font-weight:400">'+x.time+'</span></span></div>';}
    });
  }).catch(function(e){console.error('API error:',e);});
  _authFetch(API.FLEET_UPDATES).then(function(r){return r.json()}).then(function(ud){
    ud.hosts.forEach(function(x){
      var el=document.getElementById('upd-'+x.label.replace(/[^a-z0-9]/gi,''));
      if(el){
        var n=x.updates;var color=n>0?'var(--yellow)':'var(--green)';
        var txt=n>0?n+' PENDING':'UP TO DATE';
        var btn=n>0?' <button class="btn" onclick="event.stopPropagation();runHostUpdate(\''+x.label+'\')" style="padding:2px 8px;font-size:12px;margin-left:6px;color:var(--yellow)">UPDATE</button>':'';
        el.innerHTML='<div class="metric-top"><span class="metric-label">UPDATES</span><span class="metric-val" style="font-size:11px;color:'+color+'">'+txt+btn+'</span></div>';
      }
    });
  }).catch(function(e){console.error('API error:',e);});
}
function _renderFleetData(fo,hd,md){
  try{
    if(!fo&&!hd){document.getElementById('metrics-cards').innerHTML='<p class="c-red">Both fleet overview and health APIs failed.</p>';return;}
    /* Guard against null sub-fields */
    if(fo){fo.vms=fo.vms||[];fo.physical=fo.physical||[];fo.pve_nodes=fo.pve_nodes||[];fo.summary=fo.summary||{};}
    if(hd){hd.hosts=hd.hosts||[];}
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
    var _infraOrder={pfsense:1,opnsense:1,switch:2,truenas:3,synology:3,unraid:3,bmc:4,idrac:4,ilo:4,ipmi:4};
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
      var cpuPct=running?Math.round(v.cpu_pct||0):0;
      var ramPct=running?Math.round(v.ram_pct||0):0;
      var ramUsedGb=_ramGB(v.ram_used_mb||0);
      var cpuLabel=running?cpuPct+'% \u00b7 '+(v.cpu||0)+' Cores':(v.cpu||0)+' Cores';
      var ramLabel=running?ramPct+'% \u00b7 '+ramUsedGb+' / '+ramGb:ramGb;
      var c='<div class="host-card" data-host-id="'+v.name.toLowerCase()+'" style="cursor:pointer;" data-action="openVmInfo" data-label="'+v.name+'" data-vmid="'+v.vmid+'">';
      c+='<div class="host-head"><h3 style="color:'+cl+'">'+v.name+'</h3><div class="host-meta"><span>VM '+v.vmid+'</span><span>\u00b7</span>'+(running?'<span class="c-green">RUNNING</span>':'<span class="c-red">'+v.status.toUpperCase()+'</span>')+'</div></div>';
      c+='<div class="divider-light">';
      c+=_mrow('CPU',cpuLabel,running?cpuPct:0,'var(--green)');
      c+=_mrow('RAM',ramLabel,running?ramPct:0,'var(--blue)');
      if(v.category&&v.category!=='unknown')c+='<div class="metric-row"><div class="metric-top"><span class="metric-label">CATEGORY</span><span class="metric-val fs-11" >'+v.category+'</span></div></div>';
      if(v.tier)c+='<div class="metric-row"><div class="metric-top"><span class="metric-label">TIER</span><span class="metric-val fs-11" >'+v.tier+'</span></div></div>';
      c+='</div></div>';
      nodeData[nodeName].vms+=c;
    });
    /* Assemble and render */
    document.getElementById('metrics-cards').innerHTML=_assembleFleetOutput(infraCards,nodeData,pveNodes);
    _enrichFleetNtpUpdates();
    /* Re-render sparklines after card rebuild */
    if(Object.keys(_rrdCache).length)setTimeout(_renderSparklines,200);
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
  _authFetch(API.METRICS).then(function(r){return r.json()}).then(function(d){
    var html='<h3 class="section-label-pl">DEEP SCAN — '+d.hosts.length+' HOSTS</h3>';
    if(!d.hosts.length){html+='<div class="empty-state"><p>0 hosts returned deep metrics \u2014 check agent deploy and connectivity</p></div>';}
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
  _authFetch(API.STATUS).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.FLEET_NTP).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.FLEET_UPDATES).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.LAB_STATUS).then(function(r){return r.json()}).then(function(d){
    var up=0,dn=0;d.hosts.forEach(function(x){if(x.status==='up')up++;else dn++;});
    var h='<div class="stats mb-12" >'+st('HOSTS',d.hosts.length,'p')+st('UP',up,'g')+st('DOWN',dn,dn>0?'r':'g');
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
    _buildToolTabs('VM MANAGEMENT',[{id:'vmlist',label:'VM LIST'},{id:'vmcreate',label:'CREATE VM'},{id:'vmclone',label:'CLONE VM'},{id:'vmmigrate',label:'MIGRATE'},{id:'vmresize',label:'RESIZE'},{id:'vmadddisk',label:'ADD DISK'},{id:'vmtag',label:'TAGS'},{id:'vmrollback',label:'ROLLBACK'}],'vm-tab','switchVmMgmt','vm-subtitle','vm-form',content);return;
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
    _authFetch(API.USERS).then(function(r){return r.json()}).then(function(d){
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
    _authFetch(API.HEALTH).then(function(r){return r.json()}).then(function(d){
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
    _buildToolTabs('MONITORING',[{id:'monhealth',label:'HEALTH PROBE'},{id:'mondoctor',label:'DOCTOR'},{id:'monjournal',label:'JOURNAL'},{id:'monwatch',label:'WATCH'}],'mon-tab','switchMonitoring','mon-subtitle','mon-form',content);return;
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
      '<div class="text-sm text-dim mb-sm">Run a comprehensive scan across all fleet hosts — CPU, RAM, disk, services, uptime.</div>'+
      '<button class="fleet-btn pill-active-self" onclick="loadMetrics()" >RUN DEEP SCAN</button>'+
      '</div>';
    return;
  }
  var fakePanel={style:{display:'block'}};
  _fleetToolInner(tab,fakePanel,foForm);
  var innerH3=foForm.querySelector('h3');if(innerH3)innerH3.remove();
}
var _vmLabels={vmlist:'VM LIST',vmcreate:'CREATE VM',vmclone:'CLONE VM',vmmigrate:'MIGRATE',vmsnapshot:'SNAPSHOTS',vmresize:'RESIZE',vmadddisk:'ADD DISK',vmtag:'TAGS',vmrollback:'ROLLBACK'};
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
    _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var nodes={};d.vms.forEach(function(v){nodes[v.node]=true;});
      var sel=document.getElementById('vmt-c-node');if(!sel)return;
      Object.keys(nodes).sort().forEach(function(n){sel.innerHTML+='<option value="'+n+'">'+n+'</option>';});
    }).catch(function(e){console.error('API error:',e);});
  } else if(tab==='vmclone'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">SOURCE VMID</label><select id="vmt-cl-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">NEW NAME</label><input id="vmt-cl-name" placeholder="e.g. clone-of-myvm" class="input-primary-lg"></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtClone" >CLONE VM</button></div>'+
      '</div><div id="vmt-cl-out" class="mt-12"></div>';
    _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-cl-source');if(!sel)return;sel.innerHTML='';
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+' ('+v.node+')</option>';});
    }).catch(function(e){console.error('API error:',e);});
  } else if(tab==='vmmigrate'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM TO MIGRATE</label><select id="vmt-m-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">TARGET NODE</label><select id="vmt-m-target" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub" style="display:flex;align-items:center;gap:8px"><input type="checkbox" id="vmt-m-online"> LIVE MIGRATION (online)</label></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtMigrate" >MIGRATE</button></div>'+
      '</div><div id="vmt-m-out" class="mt-12"></div>';
    _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-m-source');var tgt=document.getElementById('vmt-m-target');
      if(!sel||!tgt)return;sel.innerHTML='';var nodes={};
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+' ('+v.node+')</option>';nodes[v.node]=true;});
      tgt.innerHTML='';Object.keys(nodes).sort().forEach(function(n){tgt.innerHTML+='<option value="'+n+'">'+n+'</option>';});
    }).catch(function(e){console.error('API error:',e);});
  } else if(tab==='vmsnapshot'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM</label><select id="vmt-s-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtSnapshot" >CREATE SNAPSHOT</button></div>'+
      '</div><div id="vmt-s-out" class="mt-12"></div>';
    _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-s-source');if(!sel)return;sel.innerHTML='';
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+' ('+v.node+')</option>';});
    }).catch(function(e){console.error('API error:',e);});
  } else if(tab==='vmresize'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM</label><select id="vmt-r-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">NEW CPU CORES</label><select id="vmt-r-cores" class="input-primary"><option value="">Keep current</option><option>1</option><option>2</option><option>4</option><option>8</option><option>16</option></select></div>'+
      '<div><label class="label-sub">NEW RAM</label><select id="vmt-r-ram" class="input-primary"><option value="">Keep current</option><option value="512">512MB</option><option value="1024">1GB</option><option value="2048">2GB</option><option value="4096">4GB</option><option value="8192">8GB</option><option value="16384">16GB</option><option value="32768">32GB</option></select></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtResize" >RESIZE VM</button></div>'+
      '</div><div id="vmt-r-out" class="mt-12"></div>';
    _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-r-source');if(!sel)return;sel.innerHTML='<option value="">Select VM...</option>';
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+' ('+v.cpu+' cores, '+_ramGB(v.ram_mb)+')</option>';});
    }).catch(function(e){console.error('API error:',e);});
  } else if(tab==='vmadddisk'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM</label><select id="vmt-ad-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">DISK SIZE</label><div class="flex-center"><input id="vmt-ad-size" placeholder="e.g. 32" class="input-primary" style="width:100px" type="number" min="1"><select id="vmt-ad-unit" class="input-primary" style="width:80px"><option value="G" selected>GB</option><option value="T">TB</option></select></div></div>'+
      '<div><label class="label-sub">STORAGE POOL</label><input id="vmt-ad-storage" placeholder="local-lvm" class="input-primary" value="local-lvm"></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtAddDisk" >ADD DISK</button></div>'+
      '</div><div id="vmt-ad-out" class="mt-12"></div>';
    _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-ad-source');if(!sel)return;sel.innerHTML='<option value="">Select VM...</option>';
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+' ('+v.node+')</option>';});
    }).catch(function(e){console.error('API error:',e);});
  } else if(tab==='vmtag'){
    vmForm.innerHTML='<div class="form-vertical">'+
      '<div><label class="label-sub">VM</label><select id="vmt-tag-source" class="input-primary"><option value="">Loading...</option></select></div>'+
      '<div><label class="label-sub">TAGS</label><input id="vmt-tag-tags" placeholder="e.g. prod,critical,backup" class="input-primary-lg"><div class="text-sub" style="margin-top:4px">Comma-separated. Allowed: letters, numbers, hyphens, underscores.</div></div>'+
      '<div class="btn-row"><button class="fleet-btn c-purple-active" data-action="vmtTag" >SET TAGS</button></div>'+
      '</div><div id="vmt-tag-out" class="mt-12"></div>';
    _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('vmt-tag-source');if(!sel)return;sel.innerHTML='<option value="">Select VM...</option>';
      d.vms.forEach(function(v){
        var tagInfo=v.tags?' ['+v.tags+']':'';
        sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+tagInfo+'</option>';
      });
    }).catch(function(e){console.error('API error:',e);});
  } else if(tab==='vmrollback'){
    vmtRollback();
  }
}
/* VM Management action handlers */
function vmtLoadList(){
  var el=document.getElementById('vmt-list');if(!el)return;
  el.innerHTML='<div class="skeleton"></div>';
  _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
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
      if(acts.indexOf('stop')>=0&&isRun)h+='<button class="fleet-btn pill-warn-xs" data-action="vmPower" data-vmid="'+v.vmid+'" data-arg="stop" >STOP</button>';
      if(acts.indexOf('start')>=0&&!isRun)h+='<button class="fleet-btn pill-ok-3-8" data-action="vmPower" data-vmid="'+v.vmid+'" data-arg="start" >START</button>';
      if(acts.indexOf('configure')>=0)h+='<button class="fleet-btn pill-xs" data-action="vmQuickTag" data-vmid="'+v.vmid+'" >TAG</button>';
      if(acts.indexOf('destroy')>=0)h+='<button class="fleet-btn pill-err-3-8" data-action="vmDestroy" data-vmid="'+v.vmid+'" >DESTROY</button>';
      if(isRun)h+='<button class="fleet-btn" style="font-size:9px;padding:2px 6px;color:var(--cyan)" onclick="openTerminal(\'vm\',\''+v.vmid+'\',\'\',\''+_esc(v.name)+'\')">&#9002; TERM</button>';
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
  _authFetch(API.VM_CREATE+'?name='+encodeURIComponent(n)+'&cores='+c+'&ram='+r,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.VM_CLONE+'?vmid='+src+'&name='+encodeURIComponent(name)+'&full=1',{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
    _authFetch(API.VM_MIGRATE+'?vmid='+src+'&target_node='+encodeURIComponent(tgt)+'&online='+online,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.VM_ADD_DISK+'?vmid='+vmid+'&size='+size+unit+'&storage='+encodeURIComponent(storage),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Disk '+d.disk+' added to VM '+vmid,'success');if(out)out.innerHTML='<div class="c-green">Added '+d.size+' disk as '+d.disk+' on '+d.storage+'</div>';}
    else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<div class="c-red">'+d.error+'</div>';}
  }).catch(function(e){toast('Add disk failed','error');if(out)out.innerHTML='<div class="c-red">'+e+'</div>';});
}
function vmtTag(){
  var vmid=(document.getElementById('vmt-tag-source')||{}).value;
  var tags=(document.getElementById('vmt-tag-tags')||{}).value;
  if(!vmid){toast('Select a VM','error');return;}
  var out=document.getElementById('vmt-tag-out');if(out)out.innerHTML='<div class="c-yellow">Setting tags on VM '+vmid+'...</div>';
  _authFetch(API.VM_TAG+'?vmid='+vmid+'&tags='+encodeURIComponent(tags||''),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Tags updated on VM '+vmid,'success');if(out)out.innerHTML='<div class="c-green">VM '+vmid+' tags set to: '+(d.tags||'(cleared)')+'</div>';}
    else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<div class="c-red">'+d.error+'</div>';}
  }).catch(function(e){toast('Tag update failed','error');if(out)out.innerHTML='<div class="c-red">'+e+'</div>';});
}
function vmtSnapshot(){
  var src=(document.getElementById('vmt-s-source')||{}).value;
  if(!src){toast('Select a VM','error');return;}
  var out=document.getElementById('vmt-s-out');if(out)out.innerHTML='<div class="c-yellow">Creating snapshot...</div>';
  _authFetch(API.VM_SNAPSHOT+'?vmid='+src,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Snapshot "'+d.snapshot+'" created','success');if(out)out.innerHTML='<div class="c-green">Snapshot "'+d.snapshot+'" created for VM '+src+'</div>';}
    else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<div class="c-red">'+d.error+'</div>';}
  });
}
function vmtRollback(){
  var vmForm=document.getElementById('vm-form');if(!vmForm)return;
  vmForm.innerHTML='<div class="form-vertical">'+
    '<div><label class="label-sub">VM</label><select id="vmt-rb-source" class="input-primary"><option value="">Loading...</option></select></div>'+
    '<div><label class="label-sub">SNAPSHOT (blank = latest)</label><input id="vmt-rb-snap" class="input-primary" placeholder="Snapshot name (optional)"></div>'+
    '<div><label class="label-sub" style="display:flex;align-items:center;gap:8px"><input type="checkbox" id="vmt-rb-start" checked> START AFTER ROLLBACK</label></div>'+
    '<div class="btn-row"><button class="fleet-btn c-purple-active" onclick="doRollback()">ROLLBACK</button></div>'+
    '</div><div id="vmt-rb-out" class="mt-12"></div>';
  _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
    var sel=document.getElementById('vmt-rb-source');if(!sel)return;
    sel.innerHTML='<option value="">Select VM...</option>';
    (d.vms||[]).forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+_esc(v.name)+'</option>';});
  });
}
function doRollback(){
  var vmid=(document.getElementById('vmt-rb-source')||{}).value;
  var snap=(document.getElementById('vmt-rb-snap')||{}).value.trim();
  var startAfter=document.getElementById('vmt-rb-start')?.checked!==false;
  if(!vmid){toast('Select a VM','error');return;}
  var out=document.getElementById('vmt-rb-out');
  confirmAction('Roll back VM <strong>'+vmid+'</strong>'+(snap?' to snapshot <strong>'+_esc(snap)+'</strong>':' to latest snapshot')+'?<br>The VM will be stopped during rollback.',function(){
    if(out)out.innerHTML='<div class="c-yellow">Rolling back VM '+vmid+'...</div>';
    var url=API.ROLLBACK+'?vmid='+vmid+'&start='+startAfter;
    if(snap)url+='&name='+encodeURIComponent(snap);
    _authFetch(url).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast('VM '+vmid+' rolled back to '+d.snapshot,'success');if(out)out.innerHTML='<div class="c-green">Rolled back to "'+_esc(d.snapshot)+'"'+(d.started?' — VM is running':' — VM stopped')+'</div>';}
      else{toast(d.error||'Rollback failed','error');if(out)out.innerHTML='<div class="c-red">'+(d.error||'Rollback failed')+'</div>';}
    }).catch(function(e){toast('Rollback failed','error');if(out)out.innerHTML='<div class="c-red">'+_esc(e.toString())+'</div>';});
  });
}
function deployAgent(target){
  target=target||'all';
  confirmAction('Deploy FREQ metrics agent to <strong>'+_esc(target)+'</strong>?<br>Requires sudo on target hosts.',function(){
    toast('Deploying agent to '+target+'...','info');
    _authFetch(API.DEPLOY_AGENT+'?target='+encodeURIComponent(target)).then(function(r){return r.json()}).then(function(d){
      if(d.error){toast(d.error,'error');return;}
      toast(d.deployed+'/'+d.total+' deployed, '+d.failed+' failed','success');
      /* Show results in sysinfo panel if available */
      var el=document.getElementById('sysinfo-out');if(!el)return;
      var h=_statCards([{l:'Deployed',v:d.deployed,c:'green'},{l:'Failed',v:d.failed,c:d.failed>0?'red':'green'},{l:'Port',v:d.agent_port}]);
      h+='<table style="margin-top:8px"><thead><tr><th>Host</th><th>Status</th><th>Steps</th></tr></thead><tbody>';
      (d.results||[]).forEach(function(r){
        var color=r.status==='deployed'?'green':r.status==='failed'?'red':'yellow';
        var steps=(r.steps||[]).map(function(s){return (s.ok?'<span class="c-green">'+_esc(s.step)+'</span>':'<span class="c-red">'+_esc(s.step)+'</span>');}).join(' → ');
        h+='<tr><td><strong>'+_esc(r.host)+'</strong></td><td>'+_statusBadge(r.status)+'</td><td>'+steps+'</td></tr>';
      });
      h+='</tbody></table>';
      el.innerHTML=h;
    }).catch(function(e){toast('Deploy failed: '+e,'error');});
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
  _authFetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('VM '+src+' resized','success');if(out)out.innerHTML='<div class="c-green">VM '+src+' resized successfully.</div>';}
    else{toast('Error: '+d.error,'error');if(out)out.innerHTML='<div class="c-red">'+d.error+'</div>';}
  });
}
/* ── MONITORING ─────────────────────────────────────────────────── */
var _monLabels={monhealth:'HEALTH PROBE',mondoctor:'DOCTOR',monjournal:'JOURNAL',monwatch:'WATCH'};
function switchMonitoring(tab){
  document.querySelectorAll('.mon-tab').forEach(function(b){b.classList.remove('active-view');});
  var active=document.querySelector('.mon-tab[data-montab="'+tab+'"]');if(active)active.classList.add('active-view');
  var sub=document.getElementById('mon-subtitle');if(sub)sub.textContent=_monLabels[tab]||'';
  var f=document.getElementById('mon-form');if(!f)return;
  if(tab==='monhealth'){
    f.innerHTML='<div id="mon-h-out"><div class="skeleton"></div></div>';
    _authFetch(API.HEALTH).then(function(r){return r.json()}).then(function(d){
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
    _authFetch(API.JOURNAL).then(function(r){return r.json()}).then(function(d){
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
  _authFetch('/api/doctor').then(function(r){return r.json()}).then(function(d){
    var txt=d.output||d.error||'';
    out.textContent=txt||'(no output)';
  }).catch(function(){out.textContent='Failed to run doctor';});
}
function monWatchStart(){
  var out=document.getElementById('mon-w-out');if(out)out.textContent='Starting watch daemon...';
  _authFetch('/api/watch/start',{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    var txt=d.output||d.error||'';
    if(out)out.textContent=txt||'Watch started.';
  });
}
function monWatchStop(){
  var out=document.getElementById('mon-w-out');if(out)out.textContent='Stopping watch daemon...';
  _authFetch('/api/watch/stop',{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    var txt=d.output||d.error||'';
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
  _authFetch('/api/dns/lookup?host='+encodeURIComponent(host)).then(function(r){return r.json()}).then(function(d){
    var txt=d.ips?d.ips.join('\n'):(d.error||'No results');
    if(out)out.textContent=txt||'(no results)';
  });
}
function netPingAll(){
  var out=document.getElementById('net-ping-out');if(out)out.innerHTML='<div class="skeleton"></div>';
  _authFetch(API.HEALTH).then(function(r){return r.json()}).then(function(d){
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
  _authFetch('/api/net/portscan?host='+encodeURIComponent(host)+'&ports='+encodeURIComponent(ports)).then(function(r){return r.json()}).then(function(d){
    var txt='';if(d.results)d.results.forEach(function(r){txt+='PORT '+r.port+' '+(r.open?'OPEN':'CLOSED')+'\n';});
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
    _authFetch(API.BACKUP_LIST).then(function(r){return r.json()}).then(function(d){
      var h='<div class="desc-line">Snapshots and backup exports across the cluster.</div>';
      var snaps=d.snapshots||[];var exports=d.exports||[];
      if(snaps.length){
        h+='<h4 class="text-sm text-dim" style="margin:12px 0 8px">VM SNAPSHOTS</h4>';
        h+='<table class="w-full"><thead><tr><th>VMID</th><th>VM NAME</th><th>SNAPSHOT</th><th>ACTION</th></tr></thead><tbody>';
        snaps.forEach(function(s){h+='<tr><td><strong>'+s.vmid+'</strong></td><td>'+_esc(s.vm_name)+'</td><td>'+_esc(s.snapshot)+'</td><td><button class="fleet-btn pill-xs" onclick="bkRestoreSnap('+s.vmid+',\''+_esc(s.snapshot)+'\')">RESTORE</button></td></tr>';});
        h+='</tbody></table>';
      } else {h+='<div class="empty-state"><p>0 VM snapshots \u2014 create one from VM SNAPSHOTS tab</p></div>';}
      if(exports.length){
        h+='<h4 class="text-sm text-dim" style="margin:12px 0 8px">BACKUP EXPORTS</h4>';
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
    _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('bk-snap-vm');if(!sel)return;sel.innerHTML='<option value="">Select VM...</option>';
      d.vms.forEach(function(v){sel.innerHTML+='<option value="'+v.vmid+'">'+v.vmid+' — '+v.name+'</option>';});
    }).catch(function(e){console.error('API error:',e);});
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
    _authFetch(API.BACKUP_LIST).then(function(r){return r.json()}).then(function(d){
      var sel=document.getElementById('bk-rest-vm');if(!sel)return;sel.innerHTML='<option value="">Select VM...</option>';
      var seen={};(d.snapshots||[]).forEach(function(s){if(!seen[s.vmid]){seen[s.vmid]=true;sel.innerHTML+='<option value="'+s.vmid+'">'+s.vmid+' — '+_esc(s.vm_name)+'</option>';}});
    }).catch(function(e){console.error('API error:',e);});
  }
}
function bkCheckSchedules(){
  var out=document.getElementById('bk-sched-out');if(out){out.style.display='block';out.textContent='Checking schedules...';}
  _authFetch('/api/backup/schedules').then(function(r){return r.json()}).then(function(d){
    var txt=d.raw||d.error||'No backup schedules found';
    if(out)out.textContent=txt||'(no schedules)';
  });
}
function bkTakeSnap(){
  var vmid=(document.getElementById('bk-snap-vm')||{}).value;if(!vmid){toast('Select a VM','error');return;}
  var name=(document.getElementById('bk-snap-name')||{}).value.trim();
  var out=document.getElementById('bk-snap-out');if(out)out.innerHTML='<div class="c-yellow">Creating snapshot...</div>';
  var url=API.BACKUP_CREATE+'?vmid='+vmid;
  if(name)url+='&name='+encodeURIComponent(name);
  _authFetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast('Snapshot "'+d.snapshot+'" created','success');if(out)out.innerHTML='<div class="c-green">Snapshot "'+d.snapshot+'" created for VM '+vmid+'</div>';}
    else{toast(d.error||'Snapshot failed','error');if(out)out.innerHTML='<div class="c-red">'+(d.error||'Failed')+'</div>';}
  }).catch(function(e){toast('Snapshot failed','error');if(out)out.innerHTML='<div class="c-red">'+e+'</div>';});
}
function bkListSnaps(){
  var vmid=(document.getElementById('bk-snap-vm')||{}).value;if(!vmid){toast('Select a VM','error');return;}
  var out=document.getElementById('bk-snap-out');if(out)out.innerHTML='<div class="skeleton"></div>';
  _authFetch('/api/vm/snapshots?vmid='+vmid).then(function(r){return r.json()}).then(function(d){
    var txt=d.snapshots?d.snapshots.join('\n')+(d.live_migration?'\n\nLive migration: ELIGIBLE':'\n\nLive migration: BLOCKED'):'No snapshots';
    if(out)out.innerHTML='<pre style="font-size:11px;color:var(--text);white-space:pre-wrap;margin:0">'+(txt||'No snapshots')+'</pre>';
  });
}
function bkExportConfig(){
  var out=document.getElementById('bk-exp-out');if(out){out.style.display='block';out.textContent='Exporting configuration...';}
  _authFetch(API.CONFIG).then(function(r){return r.json()}).then(function(d){
    if(out)out.textContent=JSON.stringify(d,null,2);
  });
}
function bkRestore(){
  var vmid=(document.getElementById('bk-rest-vm')||{}).value;if(!vmid){toast('Select a VM','error');return;}
  var name=(document.getElementById('bk-rest-name')||{}).value.trim();if(!name){toast('Enter a snapshot name','error');return;}
  confirmAction('Restore VM <strong>'+vmid+'</strong> from snapshot <strong>'+_esc(name)+'</strong>? This will revert the VM.',function(){
    var out=document.getElementById('bk-rest-out');if(out)out.innerHTML='<div class="c-yellow">Restoring VM '+vmid+' from "'+_esc(name)+'"...</div>';
    _authFetch(API.BACKUP_RESTORE+'?vmid='+vmid+'&name='+encodeURIComponent(name)).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.EXEC+'?target='+encodeURIComponent(host)+'&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
  _authFetch('/api/containers/action?host=docker-dev&name='+encodeURIComponent(name)+'&action='+encodeURIComponent(action)).then(function(r){return r.json()}).then(function(d){
    var txt=d.output||d.error||'';
    if(out)out.innerHTML='<pre style="font-size:11px;color:var(--green);white-space:pre-wrap;margin:0">'+name+': '+(txt||action+' OK')+'</pre>';
    toast(name+' '+action+' complete','success');
  });
}

/* User dropdown (reusable for passwd/sshkey) */
var _userDropdownData={};
function _loadUserDropdown(prefix){
  _authFetch(API.USERS).then(function(r){return r.json()}).then(function(d){
    var rc={admin:'var(--red)',operator:'var(--yellow)',viewer:'var(--green)'};
    var users=d.users.map(function(u){return {value:u.username,label:u.username.toUpperCase(),detail:u.role.toUpperCase(),color:rc[u.role]||'var(--text-dim)'};});
    _userDropdownData[prefix]=users;
    _renderUserDropdown(prefix,users);
  }).catch(function(e){console.error('API error:',e);});
}
function _renderUserDropdown(prefix,items){
  var dd=document.getElementById('ft-'+prefix+'-dropdown');if(!dd)return;
  var h='';
  items.forEach(function(item){
    h+='<div onmousedown="selectUserDropdown(\''+prefix+'\',\''+item.value+'\')" style="padding:10px 14px;cursor:pointer;border-bottom:1px solid var(--border);transition:background 0.15s" onmouseover="this.style.background=\'var(--purple-faint)\'" onmouseout="this.style.background=\'none\'">';
    h+='<div class="flex-between"><span style="font-size:12px;font-weight:600;color:var(--text)">'+item.label+'</span><span style="font-size:12px;color:'+item.color+';font-weight:600">'+item.detail+'</span></div>';
    h+='</div>';
  });
  if(!items.length)h='<div class="text-dim text-center" style="padding:14px;font-size:11px">No users found</div>';
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
  h+='<div class="text-sm text-dim" style="margin-bottom:16px">Registered tools appear in LAB view and are available as HOME widgets.</div>';
  if(typeof LAB_TOOLS!=='undefined'&&LAB_TOOLS.length){
    LAB_TOOLS.forEach(function(t){
      var connected=false;for(var k in _ltState){if(k.indexOf(t.id)>=0&&_ltState[k])connected=true;}
      var dotColor=connected?'var(--green)':'var(--text-dim)';var statusText=connected?'CONNECTED':'NOT CONNECTED';
      h+='<div style="display:flex;align-items:center;gap:12px;padding:12px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px">';
      h+='<span style="width:10px;height:10px;border-radius:50%;background:'+dotColor+';flex-shrink:0"></span>';
      h+='<div class="flex-1"><div style="font-size:13px;font-weight:600;color:var(--text)">'+t.name+'</div><div class="text-meta">'+t.subtitle+'</div></div>';
      h+='<span style="font-size:11px;color:'+dotColor+';font-weight:600">'+statusText+'</span>';
      h+='</div>';
    });
  } else {
    h+='<div class="text-center text-dim" style="padding:24px">No tools registered</div>';
  }
  h+='<div class="text-dim" style="margin-top:16px;font-size:11px">To add a new tool, register it in the <code>LAB_TOOLS</code> array (JS) and <code>LAB_TOOL_REGISTRY</code> dict (Python).</div>';
  h+='</div>';
  ov.innerHTML=h;ov.style.display='flex';
}
/* Vault lock/unlock */
var _vaultUnlocked=false;
function unlockVault(){
  var user=document.getElementById('vault-auth-user').value.trim();
  var pass=document.getElementById('vault-auth-pass').value;
  if(!user||!pass){toast('Enter admin credentials','error');return;}
  /* Verify credentials by attempting actual login */
  toast('Verifying credentials...','info');
  fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:user,password:pass})}).then(function(r){return r.json()}).then(function(d){
    if(!d.ok||!d.token){toast('Invalid credentials','error');document.getElementById('vault-auth-pass').value='';return;}
    /* Login succeeded — now verify admin role */
    _authFetch(API.USERS).then(function(r){return r.json()}).then(function(ud){
      var isAdmin=ud.users.some(function(u){return u.username===user&&u.role==='admin';});
      if(!isAdmin){toast('Access denied — admin role required','error');document.getElementById('vault-auth-pass').value='';return;}
      _vaultUnlocked=true;
      document.getElementById('vault-locked').classList.add('d-none');
      document.getElementById('vault-unlocked').classList.remove('d-none');
      toast('Vault unlocked','success');
      loadSensitiveVault();
    });
  }).catch(function(){toast('Authentication failed','error');document.getElementById('vault-auth-pass').value='';});
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
  _authFetch(API.VAULT).then(function(r){return r.json()}).then(function(d){
    _vaultData=d;
    /* Also load FREQ users for the users tab */
    _authFetch(API.USERS).then(function(r2){return r2.json()}).then(function(ud){
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
    if(!users.length)html+='<div class="empty-state"><p>0 users in users.conf</p></div>';
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
    if(!apiEntries.length)html+='<div class="empty-state"><p>0 API keys in vault</p></div>';
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
    if(!d.entries.length)html+='<div class="empty-state"><p>0 vault entries</p></div>';
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
    _authFetch(API.USERS_PROMOTE+'?username='+username,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast(username+' promoted','success');fleetTool('promote');}else toast(d.error||'Failed','error');
    });
  });
}
function demoteUser(username){
  confirmAction('Demote <strong>'+username.toUpperCase()+'</strong> to a lower role level?',function(){
    _authFetch(API.USERS_DEMOTE+'?username='+username,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast(username+' demoted','success');fleetTool('promote');}else toast(d.error||'Failed','error');
    });
  });
}
/* Fleet user/password/key — input validation to prevent shell injection */
function _validUnixUser(s){return /^[a-z_][a-z0-9_-]{0,31}$/.test(s);}
function _validSshKey(s){return /^ssh-(ed25519|rsa|ecdsa|dsa)\s+[A-Za-z0-9+\/=]+(\s+[A-Za-z0-9@._-]+)?$/.test(s);}
function _b64(s){try{return btoa(unescape(encodeURIComponent(s)));}catch(e){return '';}}
function _fleetUserCmd(user,pass,role,key){
  /* Build shell command with base64-encoded password to avoid injection */
  var passB64=_b64(user+':'+pass);
  var cmd='useradd -m -s /bin/bash \''+user+'\' 2>/dev/null; echo \''+passB64+'\' | base64 -d | chpasswd';
  if(role==='admin')cmd+='; echo \''+user+' ALL=(ALL) NOPASSWD:ALL\' > /etc/sudoers.d/\''+user+'\'; chmod 440 /etc/sudoers.d/\''+user+'\'';
  else if(role==='operator')cmd+='; echo \''+user+' ALL=(ALL) ALL\' > /etc/sudoers.d/\''+user+'\'; chmod 440 /etc/sudoers.d/\''+user+'\'';
  if(key)cmd+='; mkdir -p /home/\''+user+'\'/.ssh; echo \''+key+'\' >> /home/\''+user+'\'/.ssh/authorized_keys; chmod 700 /home/\''+user+'\'/.ssh; chmod 600 /home/\''+user+'\'/.ssh/authorized_keys; chown -R \''+user+'\':\''+user+'\' /home/\''+user+'\'/.ssh';
  return cmd;
}
function fleetNewUser(){
  var user=document.getElementById('ft-nu-user').value.trim();
  var pass=document.getElementById('ft-nu-pass').value;
  var key=document.getElementById('ft-nu-key').value.trim();
  var role=document.getElementById('ft-nu-role').value;
  if(!user){toast('Username required','error');return;}
  if(!_validUnixUser(user)){toast('Invalid username — lowercase letters, digits, hyphens, underscores only','error');return;}
  if(!pass){toast('Password required','error');return;}
  if(pass.length<8){toast('Password must be at least 8 characters','error');return;}
  if(key&&!_validSshKey(key)){toast('Invalid SSH key format — must start with ssh-ed25519 or ssh-rsa','error');return;}
  confirmAction('Create user <strong>'+_esc(user)+'</strong> as <strong>'+_esc(role).toUpperCase()+'</strong> and deploy to ALL fleet hosts?<br><br>SSH Key: '+(key?'provided':'none'),function(){
    toast('Creating '+user+' ('+role+') across fleet...','info');
    var cmd=_fleetUserCmd(user,pass,role,key);
    var out=document.getElementById('ft-nu-out');out.innerHTML='<div class="skeleton"></div>';
    _authFetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      var h='<table class="w-full"><thead><tr><th>HOST</th><th>RESULT</th></tr></thead><tbody>';
      d.results.forEach(function(r,i){h+='<tr><td><strong>'+_esc(r.host).toUpperCase()+'</strong></td><td>'+(r.ok?'<span class="c-green">DEPLOYED</span>':'<span class="c-red">'+_esc(r.error)+'</span>')+'</td></tr>';});
      h+='</tbody></table>';out.innerHTML=h;
      toast('User '+user+' deployed to '+d.results.length+' hosts','success');
      _authFetch(API.USERS_CREATE+'?username='+encodeURIComponent(user)+'&role='+encodeURIComponent(role)).catch(function(e){console.error('FREQ user register failed:',e);});
    }).catch(function(e){toast('Fleet exec failed: '+e,'error');});
  });
}
function fleetPasswdUpdate(){
  var user=document.getElementById('ft-pw-user').value.trim();
  var pass=document.getElementById('ft-pw-pass').value;
  var confirm=document.getElementById('ft-pw-confirm').value;
  if(!user){toast('Username required','error');return;}
  if(!_validUnixUser(user)){toast('Invalid username','error');return;}
  if(!pass){toast('Password required','error');return;}
  if(pass!==confirm){toast('Passwords do not match','error');return;}
  if(pass.length<8){toast('Password must be at least 8 characters','error');return;}
  confirmAction('Update password for <strong>'+_esc(user)+'</strong> on ALL fleet hosts?',function(){
    toast('Updating password for '+user+'...','info');
    var passB64=_b64(user+':'+pass);
    var cmd='echo \''+passB64+'\' | base64 -d | chpasswd && echo OK || echo FAIL';
    var out=document.getElementById('ft-pw-out');out.innerHTML='<div class="skeleton"></div>';
    _authFetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      var h='<table class="w-full"><thead><tr><th>HOST</th><th>RESULT</th></tr></thead><tbody>';
      var ok=0;
      d.results.forEach(function(r,i){
        var success=r.ok&&r.output.trim()==='OK';if(success)ok++;
        h+='<tr><td><strong>'+_esc(r.host).toUpperCase()+'</strong></td><td>'+(success?'<span class="c-green">UPDATED</span>':'<span class="c-red">FAILED</span>')+'</td></tr>';
      });
      h+='</tbody></table>';out.innerHTML=h;
      toast('Password updated on '+ok+'/'+d.results.length+' hosts','success');
    }).catch(function(e){toast('Fleet exec failed: '+e,'error');});
  });
}
function fleetSshKeyDeploy(){
  var user=document.getElementById('ft-sk-user').value.trim();
  var key=document.getElementById('ft-sk-key').value.trim();
  if(!user){toast('Username required','error');return;}
  if(!_validUnixUser(user)){toast('Invalid username','error');return;}
  if(!key){toast('Public key required','error');return;}
  if(!_validSshKey(key)){toast('Invalid key — must start with ssh-ed25519 or ssh-rsa','error');return;}
  confirmAction('Deploy SSH key to <strong>'+_esc(user)+'</strong> on ALL fleet hosts?<br><br><code style="font-size:12px;word-break:break-all">'+_esc(key.substring(0,60))+'...</code>',function(){
    toast('Deploying SSH key for '+user+'...','info');
    var cmd='mkdir -p /home/\''+user+'\'/.ssh; echo \''+key+'\' >> /home/\''+user+'\'/.ssh/authorized_keys; chmod 700 /home/\''+user+'\'/.ssh; chmod 600 /home/\''+user+'\'/.ssh/authorized_keys; chown -R \''+user+'\':\''+user+'\' /home/\''+user+'\'/.ssh && echo OK || echo FAIL';
    var out=document.getElementById('ft-sk-out');out.innerHTML='<div class="skeleton"></div>';
    _authFetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.HEALTH).then(function(r){return r.json()}).then(function(d){
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
    _authFetch(API.EXEC+'?target='+encodeURIComponent(h)+'&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
    _authFetch(API.EXEC+'?target='+encodeURIComponent(label)+'&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
      _authFetch(API.EXEC+'?target='+encodeURIComponent(h)+'&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
      _authFetch(API.EXEC+'?target='+encodeURIComponent(h)+'&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.EXEC+'?target='+encodeURIComponent(target)+'&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
    _authFetch(API.EXEC+'?target='+encodeURIComponent(label)+'&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      var out=d.results&&d.results[0]?d.results[0].output:'no output';
      toast(label+': '+out.substring(0,80),d.results&&d.results[0]&&d.results[0].ok?'success':'error');
      loadFleetPage();
    });
  });
}
function loadAgents(){
  _authFetch(API.AGENTS).then(function(r){return r.json()}).then(function(d){
    document.getElementById('agent-stats').innerHTML=s('Agents',d.count,'p');
    if(d.count>0){var h='<table><thead><tr><th>Name</th><th>Template</th><th>VMID</th><th>Status</th><th>Created</th></tr></thead><tbody>';
      d.agents.forEach(function(a){h+='<tr><td><strong>'+a.name+'</strong></td><td>'+a.template+'</td><td>'+a.vmid+'</td><td>'+badge(a.status)+'</td><td>'+(a.created||'')+'</td></tr>';});
      h+='</tbody></table>';document.getElementById('agent-list').innerHTML=h;
    }else{document.getElementById('agent-list').innerHTML='<div class="empty-state"><p>0 agents registered \u2014 <code class="c-purple">freq agent create &lt;template&gt;</code></p></div>';}
  });
  var tpls=[{n:'Infra-Manager',d:'Infrastructure operator — fleet monitoring, incident response, maintenance'},{n:'Security-Ops',d:'Security specialist — auditing, hardening, compliance'},{n:'Dev',d:'Development specialist — building, testing, shipping code'},{n:'Media-Ops',d:'Media stack operator — Plex, Sonarr, Radarr, downloads'},{n:'Blank',d:'Empty template — start from scratch'}];
  var h='';tpls.forEach(function(t){h+='<div class="crd"><h3>'+t.n+'</h3><p>'+t.d+'</p></div>';});
  document.getElementById('agent-templates').innerHTML=h;
}
function loadSpecialists(){
  _authFetch(API.SPECIALISTS).then(function(r){return r.json()}).then(function(d){
    var h='';d.agents.forEach(function(a){h+='<tr><td><strong>'+a.name+'</strong></td><td>'+a.template+'</td><td>'+(a.vmid||'-')+'</td><td>'+a.status+'</td></tr>';});
    document.getElementById('specialist-table').innerHTML=h||'<tr><td colspan="4" class="c-dim">No specialists registered.</td></tr>';
  });
}

/* ═══════════════════════════════════════════════════════════════════
   VMs
   ═══════════════════════════════════════════════════════════════════ */
function loadVMs(){
  document.getElementById('vms-c').innerHTML='<div class="skeleton"></div><div class="skeleton"></div>';
  _authFetch(API.VMS).then(function(r){return r.json()}).then(function(d){
    if(!d.count){document.getElementById('vms-c').innerHTML='<div class="empty-state"><p>0 VMs on cluster</p></div>';document.getElementById('vm-stats').innerHTML='';return;}
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
      html+='<div class="host-card cursor-ptr" data-host-id="'+v.name.toLowerCase()+'" data-action="openVmInfo" data-label="'+v.name+'" data-vmid="'+v.vmid+'" >';
      html+='<div class="host-head"><h3 style="color:'+cl+'">'+v.name+'</h3><div style="display:flex;align-items:center;gap:6px">'+
        '<span class="cat-badge cat-'+(v.category||'unknown')+'">'+catLabel+'</span>'+badge(displayStatus)+'</div></div>';
      html+='<div class="divider-light">';
      html+='<div class="metric-row"><div class="metric-top"><span class="metric-label">VMID</span><span class="metric-val">'+v.vmid+' · '+v.node+'</span></div></div>';
      html+=_mrow('CPU',v.cpu+' Cores',0,'var(--purple-light)');
      html+='<div class="metric-row"><div class="metric-top"><span class="metric-label">RAM</span><span class="metric-val">'+_ramGB(v.ram_mb)+'</span></div></div>';
      html+='<div style="display:flex;gap:4px;margin-top:8px;flex-wrap:wrap" onclick="event.stopPropagation()">';
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
  _authFetch(API.MEDIA_DASHBOARD).then(function(r){return r.json()}).then(function(d){
    if(d.registry_configured===false){document.getElementById('container-stats').innerHTML='<span class="c-dim-fs12">Container registry not configured — populate containers.toml or use Docker Fleet Inventory</span>';return;}
    var _coff=Math.max(0,d.containers_down||0);document.getElementById('container-stats').innerHTML=st('Total',d.containers_total,'p')+st('Online',d.containers_running,'g')+st('Offline',_coff,_coff>0?'r':'g')+st('VMs',d.vm_count,'b');
  }).catch(function(){document.getElementById('container-stats').innerHTML='<span class="c-red">Failed to load stats</span>';});
  _authFetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
    _mediaCache=d;if(d.registry_configured===false&&(!d.containers||d.containers.length===0)){var cards=document.getElementById('container-cards');if(cards)cards.innerHTML='<div class="exec-out">No container registry configured. Add containers to <code>conf/containers.toml</code> or use the Docker Fleet Inventory tab to view live containers.</div>';return;}
    _renderAllFromCache();
  }).catch(function(){toast('Failed to load containers','error');});
}
function loadDownloads(){
  var tbl=document.getElementById('dl-table');if(tbl)tbl.innerHTML='<tr><td colspan="6"><div class="skeleton"></div></td></tr>';
  _authFetch(API.MEDIA_DOWNLOADS).then(function(r){return r.json()}).then(function(d){
    document.getElementById('dl-stats').innerHTML=st('Active',d.count,d.count>0?'y':'g');
    var h='';d.downloads.forEach(function(dl){
      var sz=dl.size>1073741824?(dl.size/1073741824).toFixed(1)+'GB':(dl.size/1048576).toFixed(0)+'MB';
      var sp=dl.speed>1048576?(dl.speed/1048576).toFixed(1)+'MB/s':(dl.speed/1024).toFixed(0)+'KB/s';
      var pPct=Math.round(dl.progress||0);
      var pColor=pPct>=100?'var(--green)':pPct>=50?'var(--blue)':'var(--yellow)';
      h+='<tr><td>'+dl.name.substring(0,50)+'</td><td>'+dl.client+'</td><td>'+dl.vm+'</td><td class="mono-11">'+sz+'</td><td style="min-width:120px"><div style="display:flex;align-items:center;gap:6px"><span class="mono-11">'+pPct+'%</span>'+_pbar(pPct,pColor)+'</div></td><td class="mono-11">'+sp+'</td></tr>';
    });document.getElementById('dl-table').innerHTML=h||'<tr><td colspan="6" class="c-dim">No active downloads</td></tr>';
  }).catch(function(){toast('Failed to load downloads','error');if(tbl)tbl.innerHTML='<tr><td colspan="6" class="c-red">Failed to load</td></tr>';});
}
function loadStreams(){
  var tbl=document.getElementById('stream-table');if(tbl)tbl.innerHTML='<tr><td colspan="5"><div class="skeleton"></div></td></tr>';
  _authFetch(API.MEDIA_STREAMS).then(function(r){return r.json()}).then(function(d){
    document.getElementById('stream-stats').innerHTML=st('Active Streams',d.count,d.count>0?'g':'p');
    var h='';d.sessions.forEach(function(ss){
      var stateB=ss.state==='playing'?'<span class="badge up">PLAYING</span>':ss.state==='paused'?'<span class="badge paused">PAUSED</span>':badge(ss.state);
      h+='<tr><td><strong>'+ss.user+'</strong></td><td>'+ss.title+'</td><td>'+ss.type+'</td><td class="mono-11">'+ss.quality+'</td><td>'+stateB+'</td></tr>';
    });
    document.getElementById('stream-table').innerHTML=h||'<tr><td colspan="5" class="c-dim">No active streams</td></tr>';
  }).catch(function(){toast('Failed to load streams','error');if(tbl)tbl.innerHTML='<tr><td colspan="5" class="c-red">Failed to load</td></tr>';});
}
function mediaRestart(name){
  confirmAction('Restart container <strong>'+name+'</strong>?',function(){
    _authFetch(API.MEDIA_RESTART+'?name='+encodeURIComponent(name),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      toast(d.ok?name+' restarted':'Restart failed: '+(d.error||'unknown'),d.ok?'success':'error');loadContainerSection();
    });
  });
}
function mediaLogs(name){
  var el=document.getElementById('container-logs');el.style.display='block';
  el.textContent='Loading logs for '+name+'...';
  _authFetch(API.MEDIA_LOGS+'?name='+encodeURIComponent(name)+'&lines=50').then(function(r){return r.json()}).then(function(d){el.textContent=d.logs||'No logs available.';}).catch(function(e){el.textContent='Failed to load logs: '+e;toast('Failed to load logs','error');});
}

/* ═══════════════════════════════════════════════════════════════════
   INFRA
   ═══════════════════════════════════════════════════════════════════ */
function loadInfra(){
  _authFetch(API.INFRA_OVERVIEW).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.INFRA_PFSENSE+'?action='+action).then(function(r){return r.json()}).then(function(d){
    if(d.reachable){o.innerHTML=_infraPre('PFSENSE \u2014 '+action.toUpperCase(),d.output);}
    else{o.innerHTML='<div class="c-red">Cannot reach pfSense at '+d.host+'</div><div class="c-dim-mt8">'+d.error+'</div>';}
  }).catch(function(e){o.innerHTML='<div class="c-red">Error: '+e+'</div>';});
}
function tnAction(action){
  var o=_infraOut('tn-out');if(!o)return;
  o.innerHTML='<span class="c-dim">Querying TrueNAS ('+action+')...</span>';
  _authFetch(API.INFRA_TRUENAS+'?action='+action).then(function(r){return r.json()}).then(function(d){
    if(d.reachable){o.innerHTML=_infraPre('TRUENAS \u2014 '+action.toUpperCase(),d.output);}
    else{o.innerHTML='<div class="c-red">Cannot reach TrueNAS at '+d.host+'</div><div class="c-dim-mt8">'+d.error+'</div>';}
  }).catch(function(e){o.innerHTML='<div class="c-red">Error: '+e+'</div>';});
}
function idracAction(action){
  var o=_infraOut('idrac-out');if(!o)return;
  o.innerHTML='<div class="skeleton"></div>';
  _authFetch(API.INFRA_IDRAC+'?action='+action).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.SWITCH+'?action='+action).then(function(r){return r.json()}).then(function(d){
    if(d.reachable)o.innerHTML=_infraPre('SWITCH \u2014 '+action.toUpperCase(),d.output);
    else o.innerHTML='<div class="c-red">Cannot reach switch at '+d.host+'</div><div class="c-dim-mt8">'+d.error+'</div>';
  });
}

/* ═══════════════════════════════════════════════════════════════════
   DEVICE WRITE OPERATIONS — Admin-only management actions
   ═══════════════════════════════════════════════════════════════════ */

/* ── Shared helpers for write ops ── */
function _writeOut(){
  var o=document.getElementById('hd-infra-out');
  if(o)o.style.display='block';
  return o;
}
function _writePost(url,body,label){
  var o=_writeOut();if(!o)return;
  o.innerHTML='<span class="c-dim">'+label+'...</span>';
  _authFetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json()})
    .then(function(d){
      if(d.ok){o.innerHTML='<div class="c-green" style="font-weight:600;margin-bottom:8px">\u2713 '+label+' \u2014 SUCCESS</div>'+(d.output?_infraPre('OUTPUT',d.output):'')+(d.message?'<div class="c-dim mt-8">'+d.message+'</div>':'');}
      else{o.innerHTML='<div class="c-red" style="font-weight:600;margin-bottom:8px">\u2717 '+label+' \u2014 FAILED</div><div class="c-dim">'+(d.error||'Unknown error')+'</div>';}
    })
    .catch(function(e){o.innerHTML='<div class="c-red">Error: '+e+'</div>';});
}
function _writeForm(fields,submitLabel,onSubmit){
  /* Build a simple inline form. fields: [{id,label,type,placeholder,options}] */
  var html='<div style="background:var(--bg-alt);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:12px">';
  fields.forEach(function(f){
    html+='<div style="margin-bottom:10px"><label style="font-size:11px;color:var(--text-dim);display:block;margin-bottom:3px">'+f.label+'</label>';
    if(f.type==='select'){
      html+='<select id="wf-'+f.id+'" style="background:var(--bg);color:var(--text);border:1px solid var(--border);padding:6px 10px;border-radius:4px;width:100%;font-size:12px">';
      (f.options||[]).forEach(function(opt){html+='<option value="'+opt+'">'+opt+'</option>';});
      html+='</select>';
    } else {
      html+='<input id="wf-'+f.id+'" type="'+(f.type||'text')+'" placeholder="'+(f.placeholder||'')+'" style="background:var(--bg);color:var(--text);border:1px solid var(--border);padding:6px 10px;border-radius:4px;width:100%;font-size:12px;box-sizing:border-box">';
    }
    html+='</div>';
  });
  html+='<button class="fleet-btn" style="color:var(--yellow);margin-top:4px" id="wf-submit">'+submitLabel+'</button>';
  html+='</div>';
  var o=_writeOut();if(!o)return;
  o.innerHTML=html;
  document.getElementById('wf-submit').addEventListener('click',function(){
    var vals={};
    fields.forEach(function(f){var el=document.getElementById('wf-'+f.id);vals[f.id]=el?el.value:'';});
    onSubmit(vals);
  });
}

/* ── iDRAC Write Operations ── */
function idracWrite(action){
  var target=_cardState.host||'';
  if(!target){toast('Open an iDRAC card first','error');return;}
  var msgs={poweron:'POWER ON',poweroff:'POWER OFF',powercycle:'POWER CYCLE',hardreset:'HARD RESET',graceshutdown:'GRACEFUL SHUTDOWN',clearsel:'CLEAR EVENT LOG',bootpxe:'SET NEXT BOOT TO PXE',bootbios:'SET NEXT BOOT TO BIOS'};
  var label=msgs[action]||action.toUpperCase();
  if(!confirm(label+' on '+target.toUpperCase()+'?'))return;
  var o=_writeOut();if(!o)return;
  o.innerHTML='<span class="c-dim">Executing '+label+' on '+target+'...</span>';
  _authFetch(API.INFRA_IDRAC+'?action='+action+'&target='+encodeURIComponent(target))
    .then(function(r){return r.json()})
    .then(function(d){
      if(d.error){o.innerHTML='<div class="c-red">'+d.error+'</div>';return;}
      var html='';
      (d.targets||[]).forEach(function(t){
        if(t.reachable)html+='<div class="c-green" style="font-weight:600;margin-bottom:8px">\u2713 '+t.name.toUpperCase()+' \u2014 '+label+' sent</div>'+(t.output?_infraPre('RESPONSE',t.output):'');
        else html+='<div class="c-red" style="font-weight:600">'+t.name.toUpperCase()+' \u2014 UNREACHABLE</div><div class="c-dim">'+(t.error||'')+'</div>';
      });
      o.innerHTML=html||'<div class="c-green">\u2713 '+label+' command sent</div>';
    })
    .catch(function(e){o.innerHTML='<div class="c-red">Error: '+e+'</div>';});
}

/* ── TrueNAS Write Operations ── */
function tnWriteSnapshot(action){
  var fields=[{id:'dataset',label:'Dataset',placeholder:'tank/dataset'},{id:'name',label:'Snapshot Name',placeholder:'snap-2026-04-03'}];
  _writeForm(fields,action.toUpperCase()+' SNAPSHOT',function(v){
    if(!v.dataset){toast('Dataset required','error');return;}
    if(action!=='list'&&!v.name){toast('Snapshot name required','error');return;}
    if(action==='rollback'&&!confirm('ROLLBACK '+v.dataset+'@'+v.name+'? This will revert the dataset!')){return;}
    if(action==='delete'&&!confirm('DELETE snapshot '+v.dataset+'@'+v.name+'?')){return;}
    _writePost(API.TRUENAS_SNAPSHOT,{action:action,dataset:v.dataset,name:v.name},action.toUpperCase()+' snapshot '+v.dataset+'@'+v.name);
  });
}
function tnWriteService(){
  _writeForm([
    {id:'service',label:'Service',type:'select',options:['smb','nfs','iscsitarget','ssh','ftp','snmp','ups','smartd']},
    {id:'action',label:'Action',type:'select',options:['restart','start','stop']}
  ],'EXECUTE',function(v){
    if(!confirm(v.action.toUpperCase()+' '+v.service+'?'))return;
    _writePost(API.TRUENAS_SERVICE,{action:v.action,service:v.service},v.action.toUpperCase()+' '+v.service);
  });
}
function tnWriteScrub(){
  _writeForm([{id:'pool',label:'Pool Name',placeholder:'tank'}],'START SCRUB',function(v){
    if(!v.pool){toast('Pool name required','error');return;}
    if(!confirm('Start scrub on pool '+v.pool+'?'))return;
    _writePost(API.TRUENAS_SCRUB,{pool:v.pool},'Scrub '+v.pool);
  });
}
function tnWriteDataset(action){
  if(action==='create'){
    _writeForm([
      {id:'dataset',label:'Dataset Path',placeholder:'tank/newdataset'},
      {id:'compression',label:'Compression',type:'select',options:['lz4','gzip','zstd','off']},
      {id:'quota',label:'Quota (optional)',placeholder:'100G'}
    ],'CREATE DATASET',function(v){
      if(!v.dataset){toast('Dataset path required','error');return;}
      var props={};
      if(v.compression&&v.compression!=='lz4')props.compression=v.compression;
      if(v.quota)props.quota=v.quota;
      _writePost(API.TRUENAS_DATASET,{action:'create',dataset:v.dataset,properties:props},'Create dataset '+v.dataset);
    });
  } else {
    _writeForm([{id:'dataset',label:'Dataset Path',placeholder:'tank/dataset'}],'DELETE DATASET',function(v){
      if(!v.dataset){toast('Dataset path required','error');return;}
      if(!confirm('DELETE dataset '+v.dataset+'? This is PERMANENT!')){return;}
      _writePost(API.TRUENAS_DATASET,{action:'delete',dataset:v.dataset,confirm:true},'Delete dataset '+v.dataset);
    });
  }
}
function tnWriteShare(){
  _writeForm([
    {id:'type',label:'Share Type',type:'select',options:['smb','nfs']},
    {id:'name',label:'Share Name',placeholder:'myshare'},
    {id:'path',label:'Path',placeholder:'/mnt/tank/dataset'}
  ],'CREATE SHARE',function(v){
    if(!v.name||!v.path){toast('Name and path required','error');return;}
    _writePost(API.TRUENAS_SHARE,{action:'create',type:v.type,name:v.name,path:v.path},'Create '+v.type.toUpperCase()+' share '+v.name);
  });
}
function tnWriteReplication(){
  _writeForm([{id:'id',label:'Replication Task ID',placeholder:'1'}],'RUN REPLICATION',function(v){
    if(!v.id){toast('Task ID required','error');return;}
    if(!confirm('Run replication task #'+v.id+'?'))return;
    _writePost(API.TRUENAS_REPLICATION,{action:'run',id:parseInt(v.id)},'Run replication task #'+v.id);
  });
}
function tnReboot(){
  if(!confirm('REBOOT TrueNAS? All services will be interrupted!'))return;
  if(!confirm('Are you REALLY sure? This will take the storage offline.'))return;
  _writePost(API.TRUENAS_REBOOT,{confirm:true},'Reboot TrueNAS');
}

/* ── pfSense Write Operations ── */
function pfWriteService(){
  _writeForm([
    {id:'service',label:'Service',type:'select',options:['dhcpd','unbound','openvpn','ipsec','dpinger','ntpd','sshd','syslogd','filterdns']},
    {id:'action',label:'Action',type:'select',options:['restart','start','stop']}
  ],'EXECUTE',function(v){
    if(!confirm(v.action.toUpperCase()+' '+v.service+' on pfSense?'))return;
    _writePost(API.PFSENSE_SERVICE,{service:v.service,action:v.action},v.action.toUpperCase()+' '+v.service);
  });
}
function pfWriteDhcp(){
  _writeForm([
    {id:'action',label:'Action',type:'select',options:['add','delete','list']},
    {id:'mac',label:'MAC Address',placeholder:'AA:BB:CC:DD:EE:FF'},
    {id:'ip',label:'IP Address',placeholder:'10.25.10.50'},
    {id:'hostname',label:'Hostname',placeholder:'my-device'},
    {id:'description',label:'Description (optional)',placeholder:'Lab server'}
  ],'SUBMIT',function(v){
    if(v.action==='list'){
      _writePost(API.PFSENSE_DHCP,{action:'list'},'List DHCP reservations');
      return;
    }
    if(!v.mac){toast('MAC address required','error');return;}
    if(v.action==='add'&&!v.ip){toast('IP address required','error');return;}
    if(!confirm(v.action.toUpperCase()+' DHCP reservation: '+v.mac+' → '+v.ip+'?'))return;
    _writePost(API.PFSENSE_DHCP,{action:v.action,mac:v.mac,ip:v.ip,hostname:v.hostname,description:v.description||v.hostname},v.action.toUpperCase()+' DHCP reservation');
  });
}
function pfWriteRule(){
  _writeForm([
    {id:'type',label:'Rule Type',type:'select',options:['pass','block']},
    {id:'direction',label:'Direction',type:'select',options:['in','out']},
    {id:'interface',label:'Interface',placeholder:'lan'},
    {id:'proto',label:'Protocol',type:'select',options:['any','tcp','udp','icmp']},
    {id:'src',label:'Source',placeholder:'any or 10.25.10.0/24'},
    {id:'dst',label:'Destination',placeholder:'any or 10.25.20.0/24'},
    {id:'dst_port',label:'Dest Port (tcp/udp only)',placeholder:'443'},
    {id:'description',label:'Description',placeholder:'Allow HTTPS from lab'}
  ],'ADD RULE',function(v){
    if(!confirm('Add '+v.type.toUpperCase()+' rule: '+v.proto+' '+v.src+' → '+v.dst+(v.dst_port?':'+v.dst_port:'')+'?'))return;
    _writePost(API.PFSENSE_RULES,{action:'add',type:v.type,direction:v.direction,interface:v.interface||'lan',proto:v.proto,src:v.src||'any',dst:v.dst||'any',dst_port:v.dst_port,description:v.description||'Added via FREQ'},'Add firewall rule');
  });
}
function pfWriteNat(){
  _writeForm([
    {id:'interface',label:'Interface',placeholder:'wan'},
    {id:'proto',label:'Protocol',type:'select',options:['tcp','udp','tcp/udp']},
    {id:'src_port',label:'External Port',placeholder:'8080'},
    {id:'dst_ip',label:'Internal IP',placeholder:'10.25.10.50'},
    {id:'dst_port',label:'Internal Port',placeholder:'80'},
    {id:'description',label:'Description',placeholder:'Web server forward'}
  ],'ADD NAT RULE',function(v){
    if(!v.src_port||!v.dst_ip||!v.dst_port){toast('External port, internal IP, and internal port required','error');return;}
    if(!confirm('Add NAT rule: :'+v.src_port+' → '+v.dst_ip+':'+v.dst_port+'?'))return;
    _writePost(API.PFSENSE_NAT,{action:'add',interface:v.interface||'wan',proto:v.proto,src_port:v.src_port,dst_ip:v.dst_ip,dst_port:v.dst_port,description:v.description||'Added via FREQ'},'Add NAT rule');
  });
}
function pfWriteWgPeer(){
  _writeForm([
    {id:'action',label:'Action',type:'select',options:['list','add','remove']},
    {id:'interface',label:'WG Interface',placeholder:'wg0'},
    {id:'public_key',label:'Public Key',placeholder:'Base64 public key'},
    {id:'allowed_ips',label:'Allowed IPs',placeholder:'10.25.100.5/32'},
    {id:'endpoint',label:'Endpoint (optional)',placeholder:'1.2.3.4:51820'}
  ],'SUBMIT',function(v){
    if(v.action==='list'){
      _writePost(API.PFSENSE_WG_PEER,{action:'list',interface:v.interface||'wg0'},'List WireGuard peers');
      return;
    }
    if(!v.public_key){toast('Public key required','error');return;}
    if(v.action==='add'&&!v.allowed_ips){toast('Allowed IPs required','error');return;}
    if(!confirm(v.action.toUpperCase()+' WireGuard peer?'))return;
    _writePost(API.PFSENSE_WG_PEER,{action:v.action,interface:v.interface||'wg0',public_key:v.public_key,allowed_ips:v.allowed_ips,endpoint:v.endpoint},v.action.toUpperCase()+' WireGuard peer');
  });
}
function pfBackupNow(){
  if(!confirm('Create pfSense config backup?'))return;
  _writePost(API.PFSENSE_CONFIG_BACKUP,{action:'create'},'Create config backup');
}
function pfCheckUpdates(){
  _writePost(API.PFSENSE_UPDATES,{action:'check'},'Check for updates');
}
function pfReboot(){
  if(!confirm('REBOOT pfSense? All network services will be interrupted!'))return;
  if(!confirm('Are you REALLY sure? This will take the FIREWALL offline.'))return;
  _writePost(API.PFSENSE_REBOOT,{confirm:true},'Reboot pfSense');
}

/* ── Switch Write Operations ── */
function swWriteVlan(action){
  if(action==='create'){
    _writeForm([
      {id:'vlan_id',label:'VLAN ID (1-4094)',placeholder:'100'},
      {id:'name',label:'VLAN Name',placeholder:'SERVERS'}
    ],'CREATE VLAN',function(v){
      if(!v.vlan_id){toast('VLAN ID required','error');return;}
      if(!confirm('Create VLAN '+v.vlan_id+(v.name?' ('+v.name+')':'')+'?'))return;
      _writePost(API.SWITCH_VLAN_CREATE,{target:_cardState.host||'',vlan_id:parseInt(v.vlan_id),name:v.name},'Create VLAN '+v.vlan_id);
    });
  } else {
    _writeForm([{id:'vlan_id',label:'VLAN ID to delete',placeholder:'100'}],'DELETE VLAN',function(v){
      if(!v.vlan_id){toast('VLAN ID required','error');return;}
      if(!confirm('DELETE VLAN '+v.vlan_id+'? This will remove it from all ports!'))return;
      _writePost(API.SWITCH_VLAN_DELETE,{target:_cardState.host||'',vlan_id:parseInt(v.vlan_id)},'Delete VLAN '+v.vlan_id);
    });
  }
}
function swWriteAcl(){
  _writeForm([
    {id:'action',label:'Action',type:'select',options:['list','create','delete','apply','remove']},
    {id:'name',label:'ACL Name',placeholder:'MY_ACL'},
    {id:'entries',label:'Rules (one per line, for create)',placeholder:'permit tcp any host 10.0.0.1 eq 80'},
    {id:'port',label:'Interface (for apply/remove)',placeholder:'GigabitEthernet1/0/1'},
    {id:'direction',label:'Direction',type:'select',options:['in','out']}
  ],'SUBMIT',function(v){
    var body={action:v.action,target:_cardState.host||'',name:v.name};
    if(v.action==='create'){
      if(!v.name||!v.entries){toast('Name and rules required','error');return;}
      body.entries=v.entries.split('\n').filter(function(l){return l.trim();});
      if(!confirm('Create ACL '+v.name+' with '+body.entries.length+' rules?'))return;
    } else if(v.action==='delete'){
      if(!v.name){toast('ACL name required','error');return;}
      if(!confirm('DELETE ACL '+v.name+'?'))return;
    } else if(v.action==='apply'||v.action==='remove'){
      if(!v.name||!v.port){toast('ACL name and port required','error');return;}
      body.port=v.port;body.direction=v.direction;
      if(!confirm(v.action.toUpperCase()+' ACL '+v.name+' on '+v.port+'?'))return;
    }
    _writePost(API.SWITCH_ACL,body,v.action.toUpperCase()+' ACL'+(v.name?' '+v.name:''));
  });
}

/* ═══════════════════════════════════════════════════════════════════
   OPNSENSE — REST API handlers (separate from pfSense SSH)
   ═══════════════════════════════════════════════════════════════════ */
function opnAction(action){
  var o=_infraOut('pf-out');if(!o)return;
  o.innerHTML='<div class="skeleton"></div>';
  var url={status:API.OPN_STATUS,services:API.OPN_SERVICES,rules:API.OPN_RULES,dhcp:API.OPN_DHCP,dns:API.OPN_DNS,wireguard:API.OPN_WG,firmware:API.OPN_FW};
  _authFetch(url[action]||API.OPN_STATUS).then(function(r){return r.json()}).then(function(d){
    if(d.error){o.innerHTML='<div class="c-red">'+d.error+'</div>';return;}
    if(d.rows){
      var html='<div class="c-green mb-8" style="font-weight:600">OPNSENSE \u2014 '+action.toUpperCase()+' ('+d.rows.length+' items)</div>';
      html+='<pre style="font-size:11px;color:var(--text);white-space:pre-wrap;font-family:monospace;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:12px">'+JSON.stringify(d.rows.slice(0,20),null,2).replace(/</g,'&lt;')+'</pre>';
      o.innerHTML=html;
    } else {
      o.innerHTML=_infraPre('OPNSENSE \u2014 '+action.toUpperCase(),JSON.stringify(d,null,2));
    }
  }).catch(function(e){o.innerHTML='<div class="c-red">Error: '+e+'</div>';});
}
function opnWriteService(){
  _writeForm([
    {id:'service',label:'Service Name',placeholder:'unbound'},
    {id:'action',label:'Action',type:'select',options:['restart','start','stop']}
  ],'EXECUTE',function(v){
    if(!v.service){toast('Service name required','error');return;}
    if(!confirm(v.action.toUpperCase()+' '+v.service+' on OPNsense?'))return;
    _writePost(API.OPN_SVC_ACTION,{service:v.service,action:v.action},v.action.toUpperCase()+' '+v.service);
  });
}
function opnWriteRule(){
  _writeForm([
    {id:'action',label:'Action',type:'select',options:['pass','block']},
    {id:'direction',label:'Direction',type:'select',options:['in','out']},
    {id:'interface',label:'Interface',placeholder:'lan'},
    {id:'protocol',label:'Protocol',type:'select',options:['any','TCP','UDP','ICMP']},
    {id:'source',label:'Source',placeholder:'any or 10.0.0.0/24'},
    {id:'destination',label:'Destination',placeholder:'any or 10.0.0.0/24'},
    {id:'port',label:'Port',placeholder:'443'},
    {id:'description',label:'Description',placeholder:'Allow HTTPS'}
  ],'ADD RULE (with savepoint)',function(v){
    if(!confirm('Add '+v.action+' rule? OPNsense will use savepoint/rollback for safety.'))return;
    _writePost(API.OPN_RULES_ADD,{action:v.action,direction:v.direction,interface:v.interface||'lan',protocol:v.protocol,source:v.source||'any',destination:v.destination||'any',port:v.port,description:v.description||'Added via FREQ'},'Add firewall rule (with savepoint)');
  });
}
function opnDeleteRule(){
  _writeForm([{id:'uuid',label:'Rule UUID',placeholder:'paste UUID from rule list'}],'DELETE RULE',function(v){
    if(!v.uuid){toast('UUID required','error');return;}
    if(!confirm('DELETE rule '+v.uuid+'?'))return;
    _writePost(API.OPN_RULES_DEL,{uuid:v.uuid},'Delete firewall rule');
  });
}
function opnWriteDhcp(){
  _writeForm([
    {id:'mac',label:'MAC Address',placeholder:'AA:BB:CC:DD:EE:FF'},
    {id:'ip',label:'IP Address',placeholder:'10.0.0.50'},
    {id:'hostname',label:'Hostname',placeholder:'my-device'}
  ],'ADD DHCP RESERVATION',function(v){
    if(!v.mac||!v.ip){toast('MAC and IP required','error');return;}
    if(!confirm('Add DHCP reservation: '+v.mac+' \u2192 '+v.ip+'?'))return;
    _writePost(API.OPN_DHCP_ADD,{mac:v.mac,ip:v.ip,hostname:v.hostname},'Add DHCP reservation');
  });
}
function opnWriteDns(){
  _writeForm([
    {id:'host',label:'Hostname',placeholder:'myapp'},
    {id:'domain',label:'Domain',placeholder:'lab.local'},
    {id:'ip',label:'IP Address',placeholder:'10.0.0.50'}
  ],'ADD DNS OVERRIDE',function(v){
    if(!v.host||!v.ip){toast('Hostname and IP required','error');return;}
    _writePost(API.OPN_DNS_ADD,{host:v.host,domain:v.domain||'',ip:v.ip},'Add DNS override');
  });
}
function opnWriteWg(){
  _writeForm([
    {id:'name',label:'Peer Name',placeholder:'my-laptop'},
    {id:'pubkey',label:'Public Key',placeholder:'base64 key'},
    {id:'tunneladdress',label:'Tunnel Address',placeholder:'10.25.100.5/32'}
  ],'ADD WIREGUARD PEER',function(v){
    if(!v.pubkey||!v.tunneladdress){toast('Public key and tunnel address required','error');return;}
    _writePost(API.OPN_WG_ADD,{name:v.name,pubkey:v.pubkey,tunneladdress:v.tunneladdress},'Add WireGuard peer');
  });
}
function opnReboot(){
  if(!confirm('REBOOT OPNsense? All network services will be interrupted!'))return;
  if(!confirm('Are you REALLY sure?'))return;
  _writePost(API.OPN_REBOOT,{confirm:true},'Reboot OPNsense');
}

/* ═══════════════════════════════════════════════════════════════════
   GENERIC IPMI — ipmitool from controller
   ═══════════════════════════════════════════════════════════════════ */
function ipmiAction(action){
  var target=_cardState.host||'';
  var o=_infraOut('idrac-out');if(!o)return;
  o.innerHTML='<div class="skeleton"></div>';
  var url={status:API.IPMI_STATUS,sensors:API.IPMI_SENSORS,sel:API.IPMI_SEL};
  _authFetch((url[action]||API.IPMI_STATUS)+(target?'?target='+encodeURIComponent(target):'')).then(function(r){return r.json()}).then(function(d){
    if(d.error){o.innerHTML='<div class="c-red">'+d.error+'</div>';return;}
    o.innerHTML=_infraPre((target||'IPMI').toUpperCase()+' \u2014 '+action.toUpperCase(),d.output||JSON.stringify(d,null,2));
  }).catch(function(e){o.innerHTML='<div class="c-red">Error: '+e+'</div>';});
}
function ipmiWrite(action){
  var target=_cardState.host||'';
  if(!target){toast('Open an IPMI card first','error');return;}
  var msgs={on:'POWER ON',off:'POWER OFF',cycle:'POWER CYCLE',reset:'HARD RESET'};
  if(!confirm((msgs[action]||action)+' on '+target.toUpperCase()+'?'))return;
  _writePost(API.IPMI_POWER,{target:target,action:action},(msgs[action]||action)+' '+target);
}
function ipmiWriteBoot(device){
  var target=_cardState.host||'';
  if(!target){toast('Open an IPMI card first','error');return;}
  if(!confirm('Set next boot to '+device.toUpperCase()+' on '+target.toUpperCase()+'?'))return;
  _writePost(API.IPMI_BOOT,{target:target,device:device},'Set boot '+device+' on '+target);
}
function ipmiClearSel(){
  var target=_cardState.host||'';
  if(!target){toast('Open an IPMI card first','error');return;}
  if(!confirm('Clear event log on '+target.toUpperCase()+'?'))return;
  _writePost(API.IPMI_SEL_CLEAR,{target:target},'Clear SEL on '+target);
}

/* ═══════════════════════════════════════════════════════════════════
   REDFISH — HP iLO + Supermicro + any Redfish BMC
   ═══════════════════════════════════════════════════════════════════ */
function redfishAction(action){
  var target=_cardState.host||'';
  var o=_infraOut('idrac-out');if(!o)return;
  o.innerHTML='<div class="skeleton"></div>';
  var url={system:API.RF_SYSTEM,thermal:API.RF_THERMAL,'power-usage':API.RF_POWER_USAGE,events:API.RF_EVENTS};
  _authFetch((url[action]||API.RF_SYSTEM)+(target?'?target='+encodeURIComponent(target):'')).then(function(r){return r.json()}).then(function(d){
    if(d.error){o.innerHTML='<div class="c-red">'+d.error+'</div>';return;}
    o.innerHTML=_infraPre((target||'REDFISH').toUpperCase()+' \u2014 '+action.toUpperCase(),JSON.stringify(d,null,2));
  }).catch(function(e){o.innerHTML='<div class="c-red">Error: '+e+'</div>';});
}
function redfishWrite(action){
  var target=_cardState.host||'';
  if(!target){toast('Open a BMC card first','error');return;}
  var msgs={On:'POWER ON',ForceOff:'FORCE OFF',GracefulShutdown:'GRACEFUL SHUTDOWN',ForceRestart:'FORCE RESTART'};
  if(!confirm((msgs[action]||action)+' on '+target.toUpperCase()+'?'))return;
  _writePost(API.RF_POWER,{target:target,action:action},(msgs[action]||action)+' '+target);
}

/* ═══════════════════════════════════════════════════════════════════
   SYNOLOGY DSM — REST API handlers
   ═══════════════════════════════════════════════════════════════════ */
function synAction(action){
  var o=_infraOut('tn-out');if(!o)return;
  o.innerHTML='<div class="skeleton"></div>';
  var url={status:API.SYN_STATUS,storage:API.SYN_STORAGE,shares:API.SYN_SHARES,docker:API.SYN_DOCKER,packages:API.SYN_PACKAGES};
  _authFetch(url[action]||API.SYN_STATUS).then(function(r){return r.json()}).then(function(d){
    if(d.error){o.innerHTML='<div class="c-red">'+d.error+'</div>';return;}
    o.innerHTML=_infraPre('SYNOLOGY \u2014 '+action.toUpperCase(),JSON.stringify(d,null,2));
  }).catch(function(e){o.innerHTML='<div class="c-red">Error: '+e+'</div>';});
}
function synWriteService(){
  _writeForm([
    {id:'package',label:'Package Name',placeholder:'ContainerManager'},
    {id:'action',label:'Action',type:'select',options:['start','stop']}
  ],'EXECUTE',function(v){
    if(!v.package){toast('Package name required','error');return;}
    if(!confirm(v.action.toUpperCase()+' '+v.package+' on Synology?'))return;
    _writePost(API.SYN_SERVICE,{package:v.package,action:v.action},v.action.toUpperCase()+' '+v.package);
  });
}
function synReboot(){
  if(!confirm('REBOOT Synology NAS? All services will be interrupted!'))return;
  if(!confirm('Are you REALLY sure? This will take storage offline.'))return;
  _writePost(API.SYN_REBOOT,{confirm:true},'Reboot Synology');
}

/* ═══════════════════════════════════════════════════════════════════
   SECURITY
   ═══════════════════════════════════════════════════════════════════ */
function loadVault(){
  _authFetch(API.VAULT).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.VAULT_SET+'?key='+encodeURIComponent(k)+'&value='+encodeURIComponent(v)+'&host='+h,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.ok){document.getElementById('v-key').value='';document.getElementById('v-val').value='';toast('Credential stored','success');loadVault();}else toast(d.error,'error');
  });
}
function vaultDelGroup(host){
  confirmAction('Delete ALL credentials for <strong>'+host.toUpperCase()+'</strong>?',function(){
    _authFetch(API.VAULT).then(function(r){return r.json()}).then(function(d){
      var promises=d.entries.filter(function(e){return e.host===host;}).map(function(e){
        return _authFetch(API.VAULT_DELETE+'?host='+e.host+'&key='+encodeURIComponent(e.key));
      });
      Promise.all(promises).then(function(){toast(host.toUpperCase()+' credentials deleted','success');loadVault();});
    });
  });
}
function loadUsers(){
  _authFetch(API.USERS).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.USERS_CREATE+'?username='+n+'&role='+r,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.ok){document.getElementById('u-name').value='';toast('User created','success');loadUsers();}else toast(d.error,'error');
  });
}
function userPromote(u){
  confirmAction('Promote <strong>'+u+'</strong>?',function(){
    _authFetch(API.USERS_PROMOTE+'?username='+u,{method:'POST'}).then(function(r){return r.json()}).then(function(d){if(d.ok){toast(u+' promoted','success');loadUsers();}else toast(d.error,'error');});
  });
}
function userDemote(u){
  confirmAction('Demote <strong>'+u+'</strong>?',function(){
    _authFetch(API.USERS_DEMOTE+'?username='+u,{method:'POST'}).then(function(r){return r.json()}).then(function(d){if(d.ok){toast(u+' demoted','success');loadUsers();}else toast(d.error,'error');});
  });
}
function loadKeys(){
  document.getElementById('keys-c').innerHTML='<div class="skeleton"></div>';
  _authFetch(API.KEYS).then(function(r){return r.json()}).then(function(d){
    if(!d.hosts||!d.hosts.length){document.getElementById('keys-c').innerHTML='<p class="c-dim-fs12">No hosts registered. Add hosts with <code>freq host add</code>.</p>';return;}
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
  }).catch(function(e){document.getElementById('keys-c').innerHTML='<p style="color:var(--red)">Failed to load SSH keys</p>';});
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
    _authFetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(chk.cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
    _authFetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(c.cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
    _authFetch(API.EXEC+'?target=all&cmd='+encodeURIComponent(chk.cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.HARDEN).then(function(r){return r.json()}).then(function(d){
    var html='<table><thead><tr><th>Host</th><th>Check</th><th>Status</th></tr></thead><tbody>';
    d.results.forEach(function(r,i){html+='<tr><td><strong>'+r.host+'</strong></td><td>'+r.check+'</td><td>'+badge(r.ok?'ok':'CRITICAL')+'</td></tr>';});
    html+='</tbody></table>';var cb2='<button class="fleet-btn my-8" onclick="document.getElementById(\'harden-c\').innerHTML=\'\'" >CLOSE RESULTS</button>';document.getElementById('harden-c').innerHTML=cb2+html+cb2;
    toast('Hardening audit complete','success');
  });
}
function loadRisk(){
  var rc=document.getElementById('risk-chain');rc.innerHTML='';
  _authFetch(API.RISK).then(function(r){return r.json()}).then(function(d){
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
  document.getElementById('policies-c').innerHTML='<div class="skeleton"></div>';
  _authFetch(API.POLICIES).then(function(r){return r.json()}).then(function(d){
    if(!d.policies||!d.policies.length){document.getElementById('policies-c').innerHTML='<p class="c-dim-fs12">No policies configured.</p>';return;}
    var h='<div class="cards">';
    d.policies.forEach(function(p){h+='<div class="crd"><h3>'+p.name+'</h3><p>'+p.description+'</p><div class="mt-8">';p.scope.forEach(function(ss){h+='<span class="tag">'+ss+'</span>';});h+='</div></div>';});
    h+='</div>';document.getElementById('policies-c').innerHTML=h;
  }).catch(function(e){document.getElementById('policies-c').innerHTML='<p style="color:var(--red)">Failed to load policies</p>';});
}

/* ═══════════════════════════════════════════════════════════════════
   SYSTEM
   ═══════════════════════════════════════════════════════════════════ */
function loadConfig(){
  _authFetch(API.CONFIG).then(function(r){return r.json()}).then(function(d){
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
  }).catch(function(e){document.getElementById('config-c').innerHTML='<p style="color:var(--red)">Failed to load configuration</p>';});
}
function runSysInfo(){
  document.getElementById('doctor-c').innerHTML='<div class="skeleton"></div>';
  _authFetch(API.INFO).then(function(r){return r.json()}).then(function(d){
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
  _authFetch('/api/fleet/connectivity').then(function(r){return r.json()}).then(function(d){
    document.getElementById('backup-c').innerHTML='<div class="crd"><h3>Config Export</h3><p>Fleet snapshot: '+d.reachable+'/'+d.total+' hosts reachable</p><p class="text-dim mt-sm">Run from CLI: <code class="c-purple">freq backup export</code></p></div>';
    toast('Backup snapshot complete','success');
  });
}
function loadJournal(){
  _authFetch(API.JOURNAL).then(function(r){return r.json()}).then(function(d){
    if(!d.entries.length){document.getElementById('journal-c').innerHTML='<div class="empty-state"><p>0 journal entries</p></div>';return;}
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
  _authFetch(API.LEARN+'?q='+encodeURIComponent(q)).then(function(r){return r.json()}).then(function(d){
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
  document.getElementById('distro-c').innerHTML='<div class="skeleton"></div>';
  _authFetch(API.DISTROS).then(function(r){return r.json()}).then(function(d){
    if(!d.distros||!d.distros.length){document.getElementById('distro-c').innerHTML='<p class="c-dim-fs12">No cloud images available.</p>';return;}
    var html='<div class="cards">';
    d.distros.forEach(function(i){html+='<div class="crd"><h3>'+i.name+'</h3><div class="mt-4"><span class="tag">'+i.family+'</span><span class="tag">'+i.tier+'</span></div><p style="margin-top:8px;font-size:13px;color:var(--text);word-break:break-all">'+i.url+'</p></div>';});
    html+='</div>';document.getElementById('distro-c').innerHTML=html;
  }).catch(function(e){document.getElementById('distro-c').innerHTML='<p style="color:var(--red)">Failed to load distros</p>';});
}
function loadGroups(){
  document.getElementById('groups-c').innerHTML='<div class="skeleton"></div>';
  _authFetch(API.GROUPS).then(function(r){return r.json()}).then(function(d){
    var keys=Object.keys(d.groups||{});
    if(!keys.length){document.getElementById('groups-c').innerHTML='<p class="c-dim-fs12">No groups configured. Create groups with <code>freq groups add</code>.</p>';return;}
    var html='<div class="cards">';
    keys.forEach(function(g){html+='<div class="crd"><h3>'+g+'</h3><p>'+d.groups[g].join(', ')+'</p><div class="mt-4"><span class="tag">'+d.groups[g].length+' hosts</span></div></div>';});
    html+='</div>';document.getElementById('groups-c').innerHTML=html;
  }).catch(function(e){document.getElementById('groups-c').innerHTML='<p style="color:var(--red)">Failed to load groups</p>';});
}
function loadNotify(){
  document.getElementById('notify-status').innerHTML='<div class="skeleton" style="height:40px"></div>';
  _authFetch(API.CONFIG).then(function(r){return r.json()}).then(function(d){
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
    html+='<p class="text-dim mt-sm" style="font-size:11px">Configure in freq.toml under [notifications]</p>';
    document.getElementById('notify-status').innerHTML=html;
  });
}
function testNotify(){_authFetch(API.NOTIFY_TEST,{method:'POST'}).then(function(r){return r.json()}).then(function(d){document.getElementById('notify-result').innerHTML='<p class="c-dim">'+JSON.stringify(d)+'</p>';toast('Test notification sent','info');});}

/* ═══════════════════════════════════════════════════════════════════
   VM ACTIONS (toast + modal)
   ═══════════════════════════════════════════════════════════════════ */
function vmDestroy(vmid){
  confirmAction('Destroy VM <strong>'+vmid+'</strong>? This cannot be undone.',function(){
    _authFetch(API.VM_DESTROY+'?vmid='+vmid,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      if(d.ok)toast('VM '+vmid+' destroyed','success');else toast('Error: '+d.error,'error');refreshCurrentView();
    });
  });
}
function vmSnap(vmid){
  _authFetch(API.VM_SNAPSHOT+'?vmid='+vmid,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast('Snapshot "'+d.snapshot+'" created','success');else toast('Error: '+d.error,'error');
  });
}
function vmPower(vmid,action){
  _authFetch(API.VM_POWER+'?vmid='+vmid+'&action='+action,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    toast(d.action+': '+(d.ok?d.output:d.error),d.ok?'success':'error');refreshCurrentView();
  });
}
function vmPushKey(ip){
  if(!ip){toast('No IP available for this VM','error');return;}
  confirmAction('Push freq SSH key to <strong>'+ip+'</strong>?<br><span class="text-sm text-dim">Deploys the FREQ service account authorized_keys so FREQ can manage this host.</span>',function(){
    toast('Pushing key to '+ip+'...','info');
    _authFetch('/api/vm/push-key?ip='+encodeURIComponent(ip)).then(function(r){return r.json()}).then(function(d){
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
    _authFetch(API.VM_RENAME+'?vmid='+vmid+'&name='+encodeURIComponent(name),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
    _authFetch(API.VM_CHANGE_ID+'?vmid='+vmid+'&newid='+newid,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
      _authFetch(API.VM_SNAPSHOT+'?vmid='+vmid,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
        if(d.ok){toast('Snapshot "'+d.snapshot+'" created — live migration DISABLED until deleted','success');}
        else{toast('Error: '+d.error,'error');}
      });
    }
  );
}
function _vmListSnaps(vmid){
  var out=document.getElementById('vm-ctrl-out');if(!out)return;
  out.innerHTML='<span class="c-dim">Loading snapshots...</span>';
  _authFetch(API.VM_SNAPSHOTS+'?vmid='+vmid).then(function(r){return r.json()}).then(function(d){
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
    _authFetch(API.VM_DELETE_SNAP+'?vmid='+vmid+'&name='+encodeURIComponent(name),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      if(d.ok){toast('Snapshot '+name+' deleted','success');_vmListSnaps(vmid);}
      else{toast('Error: '+d.error,'error');}
    });
  });
}
function _vmDelAllSnaps(vmid){
  confirmAction('Delete <strong>ALL</strong> snapshots from VM '+vmid+'?<br><span class="c-green">This will restore live migration eligibility.</span>',function(){
    toast('Deleting all snapshots...','info');
    _authFetch(API.VM_SNAPSHOTS+'?vmid='+vmid).then(function(r){return r.json()}).then(function(d){
      var chain=Promise.resolve();
      d.snapshots.forEach(function(s){
        chain=chain.then(function(){return _authFetch(API.VM_DELETE_SNAP+'?vmid='+vmid+'&name='+encodeURIComponent(s),{method:'POST'}).then(function(r){return r.json()});});
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
    _authFetch(API.VM_RESIZE+'?vmid='+vmid+(cores?'&cores='+cores:'')+(ram?'&ram='+ram:''),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
  confirmAction('Live migrate VM <strong>'+vmid+'</strong> to <strong>'+target+'</strong>?<br><span class="c-dim">Uses direct node-to-node transfer with local disks. May take several minutes.</span>',function(){
    if(out)out.innerHTML='<span class="c-yellow">Live migrating to '+target+'... (this may take several minutes)</span>';
    _authFetch(API.VM_MIGRATE+'?vmid='+vmid+'&target_node='+target,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      if(d.error==='snapshots_block_migration'){
        confirmAction('VM has <strong>'+d.count+'</strong> snapshot(s) blocking live migration:<br><strong>'+d.snapshots.join(', ')+'</strong><br><br>Delete snapshots and migrate?',function(){
          if(out)out.innerHTML='<span class="c-yellow">Deleting snapshots and migrating...</span>';
          _authFetch(API.VM_MIGRATE+'?vmid='+vmid+'&target_node='+target+'&delete_snapshots=1',{method:'POST'}).then(function(r2){return r2.json()}).then(function(d2){
            if(d2.ok){if(out)out.innerHTML='<span class="c-green">VM '+vmid+' migrated to '+target+' ('+d2.target_storage+', '+d2.snapshots_deleted+' snapshots deleted)</span>';toast('Migration complete','success');}
            else{if(out)out.innerHTML='<span class="c-red">'+d2.error+'</span>';toast('Migration failed','error');}
          }).catch(function(e){if(out)out.innerHTML='<span class="c-red">'+e+'</span>';});
        });
        return;
      }
      if(d.ok){if(out)out.innerHTML='<span class="c-green">VM '+vmid+' migrated to '+target+' (storage: '+d.target_storage+')</span>';toast('Migration complete','success');}
      else{if(out)out.innerHTML='<span class="c-red">'+(d.error||'Migration failed')+'</span>';toast('Migration failed','error');}
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
  _authFetch(API.VM_CHECK_IP+'?ip='+encodeURIComponent(ip)).then(function(r){return r.json()}).then(function(d){
    if(d.in_use){
      if(status)status.innerHTML='<span class="c-red">'+ip+' is IN USE \u2014 pick another</span>';
      toast(ip+' is already in use','error');
      return;
    }
    if(status)status.innerHTML='<span class="c-green">'+ip+' is AVAILABLE</span>';
    var cidr=opt.getAttribute('data-cidr')||'24';
    confirmAction('Add NIC to VM <strong>'+vmid+'</strong>:<br><span style="font-family:monospace">'+opt.textContent+' \u2192 '+ip+'/'+cidr+'</span>'+(gw?'<br><span style="font-family:monospace;color:var(--text-dim)">gw '+gw+'</span>':'')+'<br><br><span class="c-dim">This adds a new NIC without touching existing ones. Reboot to activate.</span>',function(){
      if(status)status.innerHTML='<span class="c-yellow">Adding NIC...</span>';
      _authFetch(API.VM_ADD_NIC+'?vmid='+vmid+'&ip='+encodeURIComponent(ip+'/'+cidr)+'&gw='+encodeURIComponent(gw)+'&vlan='+vlan,{method:'POST'}).then(function(r){return r.json()}).then(function(d2){
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
    _authFetch(API.VM_CLEAR_NICS+'?vmid='+vmid,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
      if(out)out.innerHTML='<span class="c-yellow">Applying '+configs.length+' NICs...</span>';
      var chain=Promise.resolve();
      configs.forEach(function(c){
        chain=chain.then(function(){
          return _authFetch(API.VM_CHANGE_IP+'?vmid='+vmid+'&ip='+encodeURIComponent(c.ip)+'&gw='+encodeURIComponent(c.gw)+'&nic='+c.nic+'&vlan='+c.vlan,{method:'POST'}).then(function(r){return r.json();});
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
  stats+=st('STATUS',up?'REACHABLE':'UNREACHABLE',up?'g':'r');
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
  btns+='<button class="fleet-btn min-w-120-center" style="color:var(--cyan)" onclick="event.stopPropagation();openTerminal(\'node\',\''+_esc(ip)+'\',\'\',\''+_esc(label)+'\')">&#9002; TERMINAL</button>';
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
  stats+=st('STATUS',up?'REACHABLE':'UNREACHABLE',up?'g':'r');
  if(live){
    if(live.cores)stats+=st('CPU',live.cores+' Cores','p');
    if(live.ram)stats+=st('RAM',_ramStr(live.ram),'b');
    if(live.disk)stats+=st('DISK',live.disk,'g');
    if(live.uptime)stats+=st('UPTIME',live.uptime.replace('up ','').split(',').slice(0,2).join(','),'p');
  }
  var html='<div class="card-box"><div class="stats mb-0" >'+stats+'</div></div>';
  var actions=INFRA_ACTIONS[infraType];
  if(actions){
    var readBtns='',writeBtns='';
    actions.forEach(function(a){
      if(a.w){
        /* Write operation — call function directly, style by severity */
        var color=a.w===2?'var(--red)':'var(--yellow)';
        var fn=a.f.replace(/"/g,'');
        writeBtns+='<button class="fleet-btn min-w-120-center" style="color:'+color+'" onclick="event.stopPropagation();'+fn+'">'+a.l+'</button>';
      } else {
        /* Read operation — dispatch through _runInfraAction */
        var match=a.f.match(/\('([^']+)'\)/);
        var actionName=match?match[1]:'status';
        readBtns+='<button class="fleet-btn min-w-120-center"  onclick="event.stopPropagation();_runInfraAction(\''+infraType+'\',\''+actionName+'\')">'+a.l+'</button>';
      }
    });
    /* Add TERMINAL button for SSH-capable devices */
    var termIp=ph?ph.ip:'';
    var termHtype=infraType||'linux';
    if(termIp)readBtns+='<button class="fleet-btn min-w-120-center" style="color:var(--cyan)" onclick="event.stopPropagation();openTerminal(\'vm\',\''+_esc(termIp)+'\',\'\',\''+_esc(label)+'\',\''+_esc(termHtype)+'\')">&#9002; TERMINAL</button>';
    html+=_infraPanelHtml(roleInfo.role+' MONITORING',roleInfo.color,readBtns);
    if(writeBtns)html+=_infraPanelHtml(roleInfo.role+' MANAGEMENT','var(--yellow)',writeBtns);
  }
  _infraOutputTarget='hd-infra-out';
  _cardReady(html);
}

/* ── Renderer: Host (async SSH probe) — adaptive layout ── */
function renderHostCard(config){
  var label=config.label;
  _authFetch(API.HOST_DETAIL+'?host='+encodeURIComponent(label)).then(function(r){return r.json()}).then(function(d){
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
    html+='<button style="color:var(--cyan)" onclick="openTerminal(\'vm\',\''+_esc(d.ip||'')+'\',\'\',\''+_esc(label)+'\')">&#9002; TERMINAL</button>';
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
      html+='<div class="flex-center">';
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
        html+='<div class="flex-between" style="margin-bottom:6px">';
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
  _authFetch('/api/containers/action?host='+encodeURIComponent(host)+'&name='+encodeURIComponent(name)+'&action=restart')
    .then(function(r){return r.json()}).then(function(d){toast(d.ok?'Restarted '+name:(d.error||'Failed'),'success');}).catch(function(e){toast('Error: '+e,'error');});
}
function hdDockerLogs(name){
  var host=_cardState.host;
  var panel=document.getElementById('hd-tool-panel');if(panel)panel.style.display='block';
  var out=document.getElementById('hd-exec-out');if(out)out.textContent='Loading logs for '+name+'...';
  _authFetch('/api/containers/logs?host='+encodeURIComponent(host)+'&name='+encodeURIComponent(name))
    .then(function(r){return r.json()}).then(function(d){if(out)out.textContent=d.output||'(no output)';}).catch(function(e){if(out)out.textContent='Error: '+e;});
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
  if(acts.length<=1)ctrl+='<span class="text-sm text-dim" style="grid-column:1/-1">View only \u2014 no actions for '+catLabel+'</span>';
  ctrl+='<div style="grid-column:1/-1;border-top:1px solid var(--input-border);margin-top:6px;padding-top:8px;font-size:11px;color:var(--text-dim);letter-spacing:0.5px">HOST TOOLS</div>';
  ctrl+='<button class="fleet-btn pad-v8-fs11" data-action="hdExec" >RUN CMD</button>';
  ctrl+='<button class="fleet-btn pad-v8-fs11" data-action="hdLogs" >LOGS</button>';
  ctrl+='<button class="fleet-btn pad-v8-fs11" data-action="hdDiagnose" >DIAGNOSE</button>';
  ctrl+='<button class="fleet-btn pad-v8-warn" data-action="hdRestart" >RESTART SVC</button>';
  ctrl+='<button class="fleet-btn pad-v8-fs11" onclick="vmPushKey(\''+(ip||'')+'\')" >PUSH KEY</button>';
  if(isRunning)ctrl+='<button class="fleet-btn pad-v8-fs11" style="color:var(--cyan)" onclick="openTerminal(\'vm\',\''+vmid+'\',\'\',\''+_esc(label)+'\')">&#9002; TERMINAL</button>';
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
  _authFetch(API.MEDIA_STATUS).then(function(r){return r.json()}).then(function(d){
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
  }).catch(function(e){console.error('API error:',e);});
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
  /* Snapshot info section */
  html+='<div class="ho-section mt-10"><h3>SNAPSHOTS</h3><div id="hd-snap-list"><span class="text-meta">Loading...</span></div></div>';
  setTimeout(function(){
    _authFetch('/api/vm/snapshots?vmid='+vmid).then(function(r){return r.json()}).then(function(d){
      var el=document.getElementById('hd-snap-list');if(!el)return;
      if(!d.snapshots||!d.snapshots.length){el.innerHTML='<span class="text-meta">No snapshots</span>';return;}
      var h='';d.snapshots.forEach(function(s){
        h+=kv(s.name||'snap',s.date||s.description||'','var(--text-dim)');
      });
      el.innerHTML=h;
    }).catch(function(){var el=document.getElementById('hd-snap-list');if(el)el.innerHTML='<span class="text-meta">Snapshot info unavailable</span>';});
  },500);
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
  var map={pfsense:pfAction,opnsense:opnAction,truenas:tnAction,synology:synAction,unraid:tnAction,switch:swAction,idrac:idracAction,ilo:redfishAction,ipmi:ipmiAction};
  return map[type]||null;
}
function _runPveNodeCmd(label,ip,cmd){
  _infraOutputTarget='hd-infra-out';
  var o=document.getElementById('hd-infra-out');
  o.style.display='block';
  o.innerHTML='<span class="c-dim">Querying '+label.toUpperCase()+'...</span>';
  _authFetch(API.EXEC+'?target='+encodeURIComponent(label)+'&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.LOG+'?target='+encodeURIComponent(_cardState.host)+'&lines=50').then(function(r){return r.json()}).then(function(d){
    var txt=d.lines?d.lines.join('\n'):(d.error||'No logs available.');document.getElementById('hd-exec-out').textContent=txt;
  }).catch(function(e){document.getElementById('hd-exec-out').textContent='Error: '+e;});
}
function hdDiagnose(btn){
  _hdBtn(btn);document.getElementById('hd-tool-panel').style.display='block';
  document.getElementById('hd-exec-out').textContent='Running full diagnostic on '+_cardState.host+'...';
  _authFetch('/api/host/diagnostic?target='+encodeURIComponent(_cardState.host)).then(function(r){return r.json()}).then(function(d){
    document.getElementById('hd-exec-out').textContent=d.output||d.error||'No output.';
  }).catch(function(e){document.getElementById('hd-exec-out').textContent='Error: '+e;});
}
function hdRestart(){
  confirmAction('Restart services on <strong>'+_cardState.host+'</strong>?',function(){
    document.getElementById('hd-tool-panel').style.display='block';
    document.getElementById('hd-exec-out').textContent='Use CLI: freq fleet exec '+_cardState.host+' sudo systemctl restart <service>';
    toast('Use CLI for service restarts','info');
  });
}
function hdRunCmd(){
  var cmd=document.getElementById('hd-cmd').value;if(!cmd)return;
  document.getElementById('hd-exec-out').textContent='Running: '+cmd+' ...';
  _authFetch(API.EXEC+'?target='+encodeURIComponent(_cardState.host)+'&cmd='+encodeURIComponent(cmd),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
    '<div id="'+pfx+'lt-offline" class="text-center" style="padding:60px 0"><div style="font-size:48px;opacity:0.15;margin-bottom:16px;font-weight:900;letter-spacing:4px;background:linear-gradient(135deg,var(--purple-light),var(--purple-dark));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">'+t.name+'</div><div class="mb-sm" style="font-size:15px;color:var(--text)">Station Offline</div><div class="text-sm text-dim" style="max-width:420px;margin:0 auto;line-height:1.7">'+(t.offlineHint||'Enter the IP and API key above to connect.')+'</div></div>';
}

function ltLoad(toolId,pfx){
  pfx=pfx||'';
  _authFetch(API.LAB_TOOL_CONFIG+'?tool='+encodeURIComponent(toolId)).then(function(r){return r.json()}).then(function(d){
    var hEl=_ltEl(pfx,'lt-host');var kEl=_ltEl(pfx,'lt-key');
    if(d.host&&hEl)hEl.value=d.host;
    if(d.key&&kEl)kEl.value=d.key;
    if(d.host&&d.key)ltConnect(toolId,pfx);
  }).catch(function(e){console.error('API error:',e);});
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
  _authFetch(API.LAB_TOOL_PROXY+'?tool='+encodeURIComponent(toolId)+'&method='+method+'&endpoint='+encodeURIComponent(endpoint)+'&host='+encodeURIComponent(host)+'&key='+encodeURIComponent(key)).then(function(r){return r.json()}).then(callback).catch(function(e){callback({error:String(e)});});
}

function ltSaveConfig(toolId,pfx){
  pfx=pfx||'';
  var host=((_ltEl(pfx,'lt-host')||{}).value||'').trim();var key=((_ltEl(pfx,'lt-key')||{}).value||'').trim();if(!host||!key)return;
  _authFetch(API.LAB_TOOL_SAVE+'?tool='+encodeURIComponent(toolId)+'&host='+encodeURIComponent(host)+'&key='+encodeURIComponent(key)).then(function(r){return r.json()}).then(function(){toast('Config saved to vault','success');});
}

function ltAction(toolId,action,pfx,confirm){
  var c=_ltHostKey(toolId,pfx);
  var url='/api/lab-tool/proxy?tool='+encodeURIComponent(toolId)+'&method=POST&endpoint='+encodeURIComponent(action)+'&host='+encodeURIComponent(c.host)+'&key='+encodeURIComponent(c.key);
  if(confirm)url+='&confirm=YES';
  _authFetch(url).then(function(r){return r.json()}).then(function(d){
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
  h+='<div class="mb-md"><label class="c-dim-fs12">Vault Namespace</label><input class="input" id="at-vault-ns" placeholder="tool-name (for freq vault set)" style="width:100%;margin-top:4px"></div>';
  h+='<div><label class="c-dim-fs12">Vault Keys</label><div class="fs-11-dim-mt2">Auto-generated: <code style="color:var(--purple-light)">&lt;namespace&gt;_host</code>, <code style="color:var(--purple-light)">&lt;namespace&gt;_api_key</code></div></div>';
  h+='</div>';
  h+='<div id="at-custom-fields" style="display:none">';
  h+='<div class="mb-md"><label class="c-dim-fs12">Connect Endpoint</label><input class="input" id="at-endpoint" value="status" placeholder="status, health, api/v1/ping..." style="width:100%;margin-top:4px"></div>';
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
    container.innerHTML='<div class="empty-state" style="grid-column:1/-1"><p>0 lab tools visible</p><button class="fleet-btn mt-12" onclick="openManageTools()">MANAGE TOOLS</button></div>';
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
  h+='<div class="text-sm text-dim" style="letter-spacing:1px;margin-bottom:6px">DRIVE IDENTITY</div>';
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
    h+='<div class="text-sm text-dim" style="display:flex;justify-content:space-between;margin-top:3px"><span>'+(b.wipe.speed||'')+'</span><span>ETA: '+(b.wipe.eta||'')+'</span></div></div>';
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
    _authFetch(API.LAB_TOOL_PROXY+'?tool=gwipe&method=POST&endpoint='+encodeURIComponent('bays/'+dev+'/wipe')+'&host='+encodeURIComponent(c.host)+'&key='+encodeURIComponent(c.key)+'&confirm=YES').then(function(r){return r.json()}).then(function(d){
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
  out.innerHTML='<span class="text-dim">Running policy '+action+'...</span>';
  var url=action==='check'?API.POLICY_CHECK:action==='diff'?API.POLICY_DIFF:API.POLICY_FIX;
  _authFetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'No output')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function runSweep(doFix){
  var out=document.getElementById('sweep-out');if(!out)return;
  out.innerHTML='<span class="text-dim">Running sweep'+(doFix?' with fixes':'...')+'</span>';
  _authFetch(API.SWEEP+'?fix='+doFix).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'No output')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function loadPatrolStatus(){
  var out=document.getElementById('patrol-out');if(!out)return;
  out.innerHTML='<span class="text-dim">Checking compliance...</span>';
  _authFetch(API.PATROL_STATUS).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.STATUS).then(function(r){return r.json()}).then(function(d){
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
  _authFetch('/api/topology').then(function(r){return r.json()}).then(function(d){
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
  _authFetch('/api/capacity').then(function(r){return r.json()}).then(function(d){
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
  _authFetch('/api/capacity/snapshot',{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
  _authFetch('/api/playbooks').then(function(r){return r.json()}).then(function(d){
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
      h+='<td><button class="fleet-btn" onclick="openPbRunner(\''+_esc(pb.filename)+'\',\''+_esc(pb.name)+'\')">STEP</button> <button class="fleet-btn" onclick="runPlaybookAll(\''+_esc(pb.filename)+'\',\''+_esc(pb.name)+'\')">RUN ALL</button></td></tr>';
    });
    h+='</table>';
    list.innerHTML=h;
  }).catch(function(e){list.innerHTML='<span class="c-red">Failed: '+e+'</span>';});
}
function runPlaybookAll(filename,name){
  var runner=document.getElementById('pb-runner');
  var stepsEl=document.getElementById('pb-steps');
  var titleEl=document.getElementById('pb-runner-title');
  runner.classList.remove('d-none');
  titleEl.textContent='Running all steps: '+name;
  stepsEl.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.PLAYBOOKS_RUN+'?filename='+encodeURIComponent(filename)).then(function(r){return r.json()}).then(function(d){
    if(d.error){stepsEl.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(d.error)+'</div>';return;}
    var results=d.results||[];
    var h='<div style="margin-bottom:8px;font-size:12px;color:var(--'+(d.completed?'green':'yellow')+')">'+
      (d.completed?'All steps passed':'Playbook stopped — not all steps completed')+'</div>';
    results.forEach(function(r,i){
      var color=r.status==='pass'?'var(--green)':r.status==='fail'?'var(--red)':r.status==='pending_confirm'?'var(--yellow)':'var(--text-dim)';
      h+='<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 12px;margin-bottom:4px;border-left:3px solid '+color+';background:var(--bg2);border-radius:4px">';
      h+='<span style="color:'+color+';font-weight:700;min-width:20px">'+(i+1)+'</span>';
      h+='<div style="flex:1"><strong>'+_esc(r.step_name||'Step '+(i+1))+'</strong>';
      if(r.output)h+='<pre style="font-size:10px;margin:4px 0 0;color:var(--text-dim);white-space:pre-wrap">'+_esc(r.output.substring(0,500))+'</pre>';
      if(r.error)h+='<div style="font-size:11px;color:var(--red);margin-top:4px">'+_esc(r.error)+'</div>';
      h+='</div></div>';
    });
    stepsEl.innerHTML=h;
  }).catch(function(e){stepsEl.innerHTML='<div class="exec-out" style="color:var(--red)">Failed: '+_esc(e.toString())+'</div>';});
}
var _pbSteps=[];var _pbFilename='';var _pbCurrentStep=0;
function openPbRunner(filename,name){
  _pbFilename=filename;_pbCurrentStep=0;_pbSteps=[];
  document.getElementById('pb-runner').classList.remove('d-none');
  document.getElementById('pb-runner-title').textContent='Running: '+name;
  var stepsEl=document.getElementById('pb-steps');
  stepsEl.innerHTML='<div class="skeleton"></div>';
  // Load playbook details to show step list
  _authFetch('/api/playbooks').then(function(r){return r.json()}).then(function(d){
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
  _authFetch('/api/playbooks/step?filename='+encodeURIComponent(_pbFilename)+'&step='+idx)
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
  _authFetch('/api/gitops/status').then(function(r){return r.json()}).then(function(d){
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
    _authFetch('/api/gitops/log').then(function(r){return r.json()}).then(function(ld){
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
  _authFetch('/api/gitops/sync',{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast('Sync complete','success');
    else toast('Error: '+(d.error||'unknown'),'error');
    loadGitops();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function gitopsApply(){
  toast('Applying changes...','info');
  _authFetch('/api/gitops/apply',{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
    _authFetch('/api/gitops/diff?full=1').then(function(r){return r.json()}).then(function(d){
      content.textContent=d.diff||'No differences.';
    }).catch(function(e){content.textContent='Error: '+e;});
  }
}
function gitopsRollback(hash){
  if(!confirm('Roll back config to commit '+hash+'?'))return;
  _authFetch('/api/gitops/rollback?commit='+encodeURIComponent(hash),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast(d.message||'Rolled back','success');
    else toast('Error: '+(d.error||'unknown'),'error');
    loadGitops();
  }).catch(function(e){toast('Failed: '+e,'error');});
}

// ── COST TRACKING ───────────────────────────────────────────────────
function showCostConfig(){
  var tbl=document.getElementById('cost-table');if(!tbl)return;
  tbl.innerHTML='<div class="skeleton h-40"></div>';
  _authFetch(API.COST_CONFIG).then(function(r){return r.json()}).then(function(d){
    var h='<h4 style="font-size:11px;color:var(--text-dim);margin-bottom:8px">COST CONFIGURATION</h4>';
    h+='<table><tbody>';
    Object.keys(d).forEach(function(k){
      var v=d[k];
      h+='<tr><td style="color:var(--text-dim);width:200px">'+_esc(k)+'</td><td>'+(typeof v==='object'?_esc(JSON.stringify(v)):_esc(String(v)))+'</td></tr>';
    });
    h+='</tbody></table>';
    h+='<div style="margin-top:8px"><button class="fleet-btn" onclick="loadCosts()">BACK TO COSTS</button></div>';
    tbl.innerHTML=h;
  }).catch(function(e){tbl.innerHTML='<div class="exec-out" style="color:var(--red)">'+_esc(e.toString())+'</div>';});
}
function loadCosts(){
  var sum=document.getElementById('cost-summary');
  var tbl=document.getElementById('cost-table');
  if(!tbl)return;
  tbl.innerHTML='<div class="skeleton"></div>';
  _authFetch('/api/cost').then(function(r){return r.json()}).then(function(d){
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
    if(hosts.length===0){tbl.innerHTML='<div class="c-dim-fs12 text-center" style="padding:20px">No host data.</div>';return;}
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
  _authFetch('/api/federation/status').then(function(r){return r.json()}).then(function(d){
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
    if(sl.length===0){sites.innerHTML='<div class="c-dim-fs12 text-center" style="padding:20px">No sites registered. Add a remote FREQ instance below.</div>';return;}
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
  _authFetch('/api/federation/poll',{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
  var q='/api/federation/register?name='+encodeURIComponent(name)+'&url='+encodeURIComponent(url);
  if(secret)q+='&secret='+encodeURIComponent(secret);
  _authFetch(q).then(function(r){return r.json()}).then(function(d){
    if(d.ok){toast(d.message||'Registered','success');document.getElementById('fed-name').value='';document.getElementById('fed-url').value='';document.getElementById('fed-secret').value='';}
    else toast('Error: '+(d.error||'unknown'),'error');
    loadFederation();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function fedToggle(name){
  _authFetch('/api/federation/toggle?name='+encodeURIComponent(name),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.ok)toast(name+' '+(d.enabled?'enabled':'disabled'),'success');
    else toast('Error: '+(d.error||'unknown'),'error');
    loadFederation();
  }).catch(function(e){toast('Failed: '+e,'error');});
}
function fedRemove(name){
  if(!confirm('Remove site "'+name+'"?'))return;
  _authFetch('/api/federation/unregister?name='+encodeURIComponent(name),{method:'POST'}).then(function(r){return r.json()}).then(function(d){
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
    _authFetch('/api/chaos/types').then(function(r){return r.json()}).then(function(d){
      (d.types||[]).forEach(function(t){
        var o=document.createElement('option');o.value=t.type;o.textContent=t.type+' — '+t.description;
        sel.appendChild(o);
      });
    });
  }
  // Load experiment log
  log.innerHTML='<div class="skeleton"></div>';
  _authFetch('/api/chaos/log').then(function(r){return r.json()}).then(function(d){
    var exps=d.experiments||[];
    if(exps.length===0){log.innerHTML='<div class="c-dim-fs12 text-center" style="padding:20px">No experiments run yet.</div>';return;}
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
  var q='/api/chaos/run?name='+encodeURIComponent(name)+'&type='+encodeURIComponent(type);
  q+='&target='+encodeURIComponent(target)+'&service='+encodeURIComponent(service)+'&duration='+duration;
  _authFetch(q).then(function(r){return r.json()}).then(function(d){
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
  out.innerHTML='<span class="text-dim">Running self-diagnostic...</span>';
  _authFetch(API.DOCTOR).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'OK')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function runDiagnose(){
  var host=document.getElementById('diag-host').value.trim();
  if(!host){toast('Select a host','error');return;}
  var out=document.getElementById('diag-out');if(!out)return;
  out.innerHTML='<span class="text-dim">Diagnosing '+_esc(host)+'...</span>';
  _authFetch(API.DIAGNOSE+'?target='+encodeURIComponent(host)).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    var h='<div style="font-size:14px;font-weight:700;color:var(--purple-light);margin-bottom:8px">'+_esc(d.host)+' ('+_esc(d.ip)+')</div>';
    var checks=d.checks||{};
    Object.keys(checks).forEach(function(k){
      h+='<div class="mb-sm"><div class="text-dim" style="font-size:11px;letter-spacing:1px;text-transform:uppercase">'+_esc(k)+'</div>';
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
  out.innerHTML='<span class="text-dim">Fetching logs from '+_esc(host)+'...</span>';
  var url=API.LOG+'?target='+encodeURIComponent(host)+'&lines='+lines;
  if(unit)url+='&unit='+encodeURIComponent(unit);
  _authFetch(url).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    var logLines=d.lines||[];
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:11px;color:var(--text);line-height:1.5">'+_esc(logLines.join('\n'))+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function loadZfs(){
  var out=document.getElementById('zfs-out');if(!out)return;
  out.innerHTML='<span class="text-dim">Loading ZFS status...</span>';
  _authFetch(API.ZFS).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'No ZFS data')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function loadBackups(action){
  var out=document.getElementById('backup-out');if(!out)return;
  out.innerHTML='<span class="text-dim">Loading backups...</span>';
  _authFetch(API.BACKUP+'?action='+action).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(d.output||'No backup data')+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
function runDiscover(){
  var subnet=document.getElementById('discover-subnet').value.trim();
  var out=document.getElementById('discover-out');if(!out)return;
  out.innerHTML='<span class="text-dim">Scanning network...</span>';
  var url=API.DISCOVER;
  if(subnet)url+='?subnet='+encodeURIComponent(subnet);
  _authFetch(url).then(function(r){return r.json()}).then(function(d){
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
  _authFetch(API.ADMIN_HOSTS_UPDATE+'?label='+encodeURIComponent(label)+'&type='+encodeURIComponent(htype)+(groups?'&groups='+encodeURIComponent(groups):'')+'&ip='+encodeURIComponent(ip)).then(function(r){return r.json()}).then(function(d){
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
  out.innerHTML='<span class="text-dim">Loading GWIPE '+action+'...</span>';
  _authFetch(API.GWIPE+'?action='+action,{method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.error){out.innerHTML='<span style="color:var(--red)">'+d.error+'</span>';return;}
    var data=d.data||{};
    out.innerHTML='<pre style="white-space:pre-wrap;font-size:12px;color:var(--text)">'+_esc(JSON.stringify(data,null,2))+'</pre>';
  }).catch(function(e){out.innerHTML='<span style="color:var(--red)">Error: '+e+'</span>';});
}
/* ═══════════════════════════════════════════════════════════════════
   ACTIVITY FEED + MONITORS WIDGETS
   ═══════════════════════════════════════════════════════════════════ */
function _loadActivityFeed(){
  _authFetch('/api/activity?limit=20').then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('hw-activity-list');if(!el)return;
    if(!d.events||!d.events.length){el.innerHTML='<div class="empty-state"><p>0 recent events</p></div>';return;}
    var h='';d.events.forEach(function(ev){
      var icon=ev.severity==='error'?'\u274c':ev.severity==='warning'?'\u26a0':ev.severity==='success'?'\u2705':'\u2139\ufe0f';
      var ts=new Date(ev.ts*1000);var timeStr=ts.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'});
      h+='<div class="activity-item" style="display:flex;gap:8px;padding:4px 0;border-bottom:1px solid var(--border)">';
      h+='<span style="flex-shrink:0">'+icon+'</span>';
      h+='<span style="flex:1;font-size:13px">'+_esc(ev.message)+'</span>';
      h+='<span style="flex-shrink:0;font-size:11px;color:var(--text-dim)">'+timeStr+'</span>';
      h+='</div>';
    });
    el.innerHTML=h;
  }).catch(function(e){var el=document.getElementById('hw-activity-list');if(el)el.innerHTML='<div class="empty-state"><p>activity probe failed \u2014 check /api/activity</p></div>';});
}
function _updateActivityWidget(ev){
  var el=document.getElementById('hw-activity-list');if(!el)return;
  var icon=ev.severity==='error'?'\u274c':ev.severity==='warning'?'\u26a0':ev.severity==='success'?'\u2705':'\u2139\ufe0f';
  var ts=new Date(ev.ts*1000);var timeStr=ts.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'});
  var item=document.createElement('div');item.className='activity-item';
  item.style.cssText='display:flex;gap:8px;padding:4px 0;border-bottom:1px solid var(--border)';
  item.innerHTML='<span style="flex-shrink:0">'+icon+'</span><span style="flex:1;font-size:13px">'+_esc(ev.message)+'</span><span style="flex-shrink:0;font-size:11px;color:var(--text-dim)">'+timeStr+'</span>';
  el.insertBefore(item,el.firstChild);
  /* Trim to 20 items */
  while(el.children.length>20)el.removeChild(el.lastChild);
}
function _loadMonitorsWidget(){
  _authFetch('/api/monitors/check').then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('hw-monitors-list');if(!el)return;
    if(!d.results||!d.results.length){el.innerHTML='<div class="empty-state"><p>0 monitors configured</p></div>';return;}
    var h='';d.results.forEach(function(r){
      var icon=r.ok?'\u2705':'\u274c';
      var status=r.ok?'<span style="color:var(--green)">OK</span>':'<span style="color:var(--red)">'+(r.error||'HTTP '+r.status)+'</span>';
      h+='<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border)">';
      h+='<span>'+icon+'</span>';
      h+='<span style="flex:1;font-weight:500">'+_esc(r.name)+'</span>';
      h+=status;
      h+='<span style="font-size:11px;color:var(--text-dim)">'+r.latency_ms+'ms</span>';
      h+='</div>';
    });
    h+='<div class="text-sm text-dim mt-sm">'+d.healthy+'/'+d.count+' healthy</div>';
    el.innerHTML=h;
  }).catch(function(e){var el=document.getElementById('hw-monitors-list');if(el)el.innerHTML='<div class="empty-state"><p>monitor probe failed \u2014 check /api/monitors</p></div>';});
}
/* ═══════════════════════════════════════════════════════════════════
   COMMAND PALETTE (Ctrl+K)
   VSCode-style: search VMs/hosts, navigate views, run actions.
   Categories: vm, host, nav, action, tool
   ═══════════════════════════════════════════════════════════════════ */
var _searchItems=[];var _searchIdx=-1;
var _cmdIcons={vm:'\u26a1',host:'\u2699',nav:'\u2192',action:'\u25b6',tool:'\u2692'};
var _cmdColors={vm:'var(--cyan)',host:'var(--green)',nav:'var(--purple-light)',action:'var(--yellow)',tool:'var(--orange)'};
function openSearch(){
  var ov=document.getElementById('search-overlay');if(!ov)return;
  ov.style.display='block';
  var inp=document.getElementById('search-input');if(inp){inp.value='';inp.focus();}
  _buildSearchIndex();
  _renderSearchResults(_searchItems.slice(0,20));
}
function closeSearch(){var ov=document.getElementById('search-overlay');if(ov)ov.style.display='none';_searchIdx=-1;}
function _buildSearchIndex(){
  _searchItems=[];
  /* ── Navigation ── */
  var views=[
    {label:'Home',view:'home',keys:'dashboard home overview'},
    {label:'Fleet',view:'fleet',keys:'fleet hosts vms nodes'},
    {label:'Docker',view:'docker',keys:'docker containers services'},
    {label:'Media',view:'media',keys:'media plex streams downloads'},
    {label:'Security',view:'security',keys:'security audit hardening'},
    {label:'System',view:'tools',keys:'system settings config'},
    {label:'Lab',view:'lab',keys:'lab sandbox test'},
    {label:'Settings',view:'settings',keys:'settings preferences config'},
    {label:'Topology',view:'topology',keys:'topology map network'},
    {label:'Capacity',view:'capacity',keys:'capacity planning resources'},
    {label:'Playbooks',view:'playbooks',keys:'playbooks automation runbooks'}
  ];
  views.forEach(function(v){_searchItems.push({type:'nav',label:'Go to '+v.label,detail:v.keys,action:function(){showView(v.view);closeSearch();}});});
  /* ── Security sub-views ── */
  var secViews=[
    {label:'Hardening',view:'sec-hardening'},{label:'Access Control',view:'sec-access'},
    {label:'Vault',view:'sec-vault'},{label:'Compliance',view:'sec-compliance'},
    {label:'Firewall',view:'firewall'},{label:'Certificates',view:'certs'},{label:'VPN',view:'vpn'}
  ];
  secViews.forEach(function(v){_searchItems.push({type:'nav',label:'Security \u203a '+v.label,detail:'security '+v.label.toLowerCase(),action:function(){switchView(v.view);closeSearch();}});});
  /* ── System sub-views ── */
  var sysViews=[
    {label:'Config',view:'sys-config'},{label:'Doctor',view:'sys-doctor'},
    {label:'Journal',view:'sys-journal'},{label:'Groups',view:'sys-groups'},
    {label:'Alert Rules',view:'sys-alerts'},{label:'Notifications',view:'sys-notify'},
    {label:'About',view:'sys-about'}
  ];
  sysViews.forEach(function(v){_searchItems.push({type:'nav',label:'System \u203a '+v.label,detail:'system '+v.label.toLowerCase(),action:function(){switchView(v.view);closeSearch();}});});
  /* ── Actions ── */
  _searchItems.push({type:'action',label:'Deep Scan',detail:'Run deep metrics scan on all hosts',action:function(){closeSearch();showView('fleet');loadMetrics();}});
  _searchItems.push({type:'action',label:'Rescan Containers',detail:'Discover containers across fleet',action:function(){closeSearch();showView('docker');rescanContainers();}});
  _searchItems.push({type:'action',label:'Full Security Audit',detail:'Run all security audit checks',action:function(){closeSearch();switchView('sec-hardening');runAuditCheck('all');}});
  _searchItems.push({type:'action',label:'Run Hardening Audit',detail:'Check hardening status across fleet',action:function(){closeSearch();switchView('sec-hardening');if(typeof runHarden==='function')runHarden();}});
  _searchItems.push({type:'action',label:'Check NTP Sync',detail:'View NTP sync status for all hosts',action:function(){closeSearch();showView('fleet');fleetTool('ntp');}});
  _searchItems.push({type:'action',label:'Check OS Updates',detail:'View pending updates across fleet',action:function(){closeSearch();showView('fleet');fleetTool('updates');}});
  _searchItems.push({type:'action',label:'Fleet Exec',detail:'Run a command across all hosts',action:function(){closeSearch();showView('fleet');fleetTool('exec');}});
  /* ── Tools ── */
  _searchItems.push({type:'tool',label:'pfSense Status',detail:'Query pfSense firewall',action:function(){closeSearch();showView('fleet');if(typeof pfAction==='function')pfAction('status');}});
  _searchItems.push({type:'tool',label:'TrueNAS Status',detail:'Query TrueNAS storage',action:function(){closeSearch();showView('fleet');if(typeof tnAction==='function')tnAction('status');}});
  _searchItems.push({type:'tool',label:'Reload Dashboard',detail:'Force refresh all dashboard data',action:function(){closeSearch();location.reload();}});
  /* ── VMs from fleet cache ── */
  if(_fleetCache.fo&&_fleetCache.fo.vms){
    _fleetCache.fo.vms.forEach(function(v){
      var vmName=v.name||'VM '+v.vmid;
      _searchItems.push({type:'vm',label:vmName,detail:'VMID '+v.vmid+' \u2022 '+v.node+' \u2022 '+v.status,action:function(){openHost(vmName);closeSearch();}});
      /* VM power actions for running VMs */
      if(v.status==='running'){
        _searchItems.push({type:'action',label:'Stop '+vmName,detail:'Power off VM '+v.vmid,action:function(){closeSearch();confirmAction('Stop <strong>'+vmName+'</strong>?',function(){vmPower(v.vmid,'stop');});}});
        _searchItems.push({type:'action',label:'Reboot '+vmName,detail:'Reboot VM '+v.vmid,action:function(){closeSearch();confirmAction('Reboot <strong>'+vmName+'</strong>?',function(){vmPower(v.vmid,'reboot');});}});
      } else if(v.status==='stopped'){
        _searchItems.push({type:'action',label:'Start '+vmName,detail:'Start VM '+v.vmid,action:function(){closeSearch();vmPower(v.vmid,'start');}});
      }
    });
  }
  /* ── Hosts from health cache ── */
  if(_fleetCache.hd&&_fleetCache.hd.hosts){
    _fleetCache.hd.hosts.forEach(function(h){
      _searchItems.push({type:'host',label:h.label,detail:h.ip+' \u2022 '+h.type+' \u2022 '+h.status,action:function(){openHost(h.label);closeSearch();}});
    });
  }
}
function _globalSearchFilter(query){
  if(!query){_renderSearchResults(_searchItems.slice(0,20));_searchIdx=-1;return;}
  var q=query.toLowerCase();
  /* Score-based ranking: label match > detail match, prefix > substring */
  var scored=[];
  _searchItems.forEach(function(item){
    var ll=item.label.toLowerCase();var dl=item.detail.toLowerCase();
    var score=0;
    if(ll===q)score=100;
    else if(ll.indexOf(q)===0)score=80;
    else if(ll.indexOf(q)>=0)score=60;
    else if(dl.indexOf(q)>=0)score=40;
    /* Boost actions when query starts with > */
    if(q.charAt(0)==='>'&&(item.type==='action'||item.type==='tool')){
      var aq=q.substring(1).trim();
      if(!aq)score=70;
      else if(ll.indexOf(aq)>=0)score+=20;
    }
    if(score>0)scored.push({item:item,score:score});
  });
  scored.sort(function(a,b){return b.score-a.score;});
  var matches=scored.map(function(s){return s.item;});
  _renderSearchResults(matches.slice(0,20));
  _searchIdx=-1;
}
function _renderSearchResults(items){
  var el=document.getElementById('search-results');if(!el)return;
  if(!items.length){el.innerHTML='<div class="text-center text-dim" style="padding:16px">No results</div>';return;}
  /* Group by category */
  var groups={};var order=['nav','action','tool','vm','host'];
  var labels={nav:'NAVIGATE',action:'ACTIONS',tool:'TOOLS',vm:'VIRTUAL MACHINES',host:'HOSTS'};
  items.forEach(function(item){if(!groups[item.type])groups[item.type]=[];groups[item.type].push(item);});
  var h='';var idx=0;
  order.forEach(function(cat){
    if(!groups[cat])return;
    h+='<div style="padding:4px 12px;font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1.5px;font-weight:700;margin-top:4px">'+(labels[cat]||cat)+'</div>';
    groups[cat].forEach(function(item){
      var icon=_cmdIcons[item.type]||'\u2022';
      var color=_cmdColors[item.type]||'var(--text-dim)';
      h+='<div class="search-item" data-idx="'+idx+'" style="display:flex;align-items:center;gap:10px;padding:7px 12px;cursor:pointer;border-radius:6px;transition:background 0.1s" onmouseenter="this.style.background=\'rgba(168,85,247,0.08)\'" onmouseleave="this.style.background=\'transparent\'" onclick="_searchItems._filtered['+idx+'].action()">';
      h+='<span style="color:'+color+';font-size:14px;width:20px;text-align:center">'+icon+'</span>';
      h+='<div style="flex:1;min-width:0"><div style="font-weight:500;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+_esc(item.label)+'</div></div>';
      h+='<span style="font-size:10px;color:var(--text-dim);white-space:nowrap;flex-shrink:0">'+_esc(item.detail.length>40?item.detail.substring(0,40)+'\u2026':item.detail)+'</span>';
      h+='</div>';
      idx++;
    });
  });
  el.innerHTML=h;
  _searchItems._filtered=items;
}
function _globalSearchKeydown(e){
  var items=_searchItems._filtered||[];
  if(e.key==='Escape'){closeSearch();return;}
  if(e.key==='ArrowDown'){e.preventDefault();_searchIdx=Math.min(_searchIdx+1,items.length-1);_highlightSearchItem();return;}
  if(e.key==='ArrowUp'){e.preventDefault();_searchIdx=Math.max(_searchIdx-1,0);_highlightSearchItem();return;}
  if(e.key==='Enter'&&_searchIdx>=0&&items[_searchIdx]){items[_searchIdx].action();return;}
}
function _highlightSearchItem(){
  var el=document.getElementById('search-results');if(!el)return;
  var items=el.querySelectorAll('.search-item');
  items.forEach(function(it,i){it.style.background=i===_searchIdx?'rgba(168,85,247,0.12)':'transparent';});
  if(items[_searchIdx])items[_searchIdx].scrollIntoView({block:'nearest'});
}
/* ═══════════════════════════════════════════════════════════════════
   KEYBOARD SHORTCUTS
   ═══════════════════════════════════════════════════════════════════ */
var _NAV_KEYS={'1':'home','2':'fleet','3':'docker','4':'media','5':'security','6':'topology','7':'capacity','8':'playbooks'};
/* ═══════════════════════════════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════════════════════════════ */
document.addEventListener('keydown',function(e){
  /* Ctrl+K — global search */
  if((e.ctrlKey||e.metaKey)&&e.key==='k'){e.preventDefault();openSearch();return;}
  /* ? — keyboard shortcuts help */
  if(e.key==='?'&&!e.ctrlKey&&!e.metaKey&&document.activeElement.tagName!=='INPUT'&&document.activeElement.tagName!=='TEXTAREA'){
    var m=document.getElementById('shortcuts-modal');if(m)m.style.display=m.style.display==='none'?'block':'none';return;
  }
  /* Escape — close everything */
  if(e.key==='Escape'){closeSearch();closeHost();closeModal();var sm=document.getElementById('shortcuts-modal');if(sm)sm.style.display='none';return;}
  /* 1-8 — navigate views (only when not in input) */
  if(_NAV_KEYS[e.key]&&document.activeElement.tagName!=='INPUT'&&document.activeElement.tagName!=='TEXTAREA'&&!e.ctrlKey&&!e.metaKey){
    showView(_NAV_KEYS[e.key]);return;
  }
});
/* URL routing: popstate for back/forward, initial route on load */
window.addEventListener('popstate',function(e){
  if(e.state&&e.state.view&&VIEW_LOADERS[e.state.view])switchView(e.state.view,true);
});
try{
  var _initPath=window.location.pathname.replace('/dashboard/','').replace('/','');
  if(_initPath&&VIEW_LOADERS[_initPath])switchView(_initPath);
  else loadHome();
  renderGlobalSettings();
}catch(e){console.error(e);}