/* Pure presentation helpers. No DOM, transport, timers or application state. */
(function(root){
  'use strict';
  function create(){
function _healthState(h){return (h&&(h.state||h.status))||'unknown';}
function _healthIsLive(h){var s=_healthState(h);return s==='live'||s==='recovering'||s==='healthy'||s==='up'||s==='ok';}
function _healthIsBad(h){var s=_healthState(h);return s==='unreachable'||s==='auth_failed'||s==='degraded'||s==='down';}
function _healthIsStale(h){return _healthState(h)==='stale';}
function _healthLabel(h){if(_healthIsLive(h))return 'UP';if(_healthIsStale(h))return 'STALE';if(_healthIsBad(h))return 'DOWN';return 'UNKNOWN';}
function _healthColor(h){if(_healthIsLive(h))return 'var(--green)';if(_healthIsStale(h))return 'var(--yellow)';if(_healthIsBad(h))return 'var(--red)';return 'var(--text-dim)';}
function _ramGB(mb){mb=parseInt(mb)||0;if(mb>=1024)return (mb/1024).toFixed(1).replace(/\.0$/,'')+'GB';return mb+'MB';}
function _esc(s){if(!s)return '';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function _rawLabel(obj){
  obj=obj||{};
  return obj.raw_label||obj.label||obj.name||obj.key||'';
}
function _displayName(obj){
  obj=obj||{};
  return obj.display_label||obj.display_name||obj.name||obj.label||obj.raw_label||obj.key||'';
}
function _secondaryIdentity(obj){
  obj=obj||{};
  var raw=_rawLabel(obj);
  var display=_displayName(obj);
  var parts=[];
  if(raw&&raw!==display)parts.push(raw);
  if(obj.ip)parts.push(obj.ip);
  return parts.join(' · ');
}
function _fmtBytes(value){
  var n=Number(value||0);if(!isFinite(n)||n<=0)return '0B';
  var u=['B','KiB','MiB','GiB','TiB','PiB'];var i=0;
  while(n>=1024&&i<u.length-1){n=n/1024;i++;}
  return (n>=10||i===0?n.toFixed(0):n.toFixed(1))+' '+u[i];
}
    return Object.freeze({
      _healthState: _healthState,
      _healthIsLive: _healthIsLive,
      _healthIsBad: _healthIsBad,
      _healthIsStale: _healthIsStale,
      _healthLabel: _healthLabel,
      _healthColor: _healthColor,
      _ramGB: _ramGB,
      _esc: _esc,
      _rawLabel: _rawLabel,
      _displayName: _displayName,
      _secondaryIdentity: _secondaryIdentity,
      _fmtBytes: _fmtBytes
    });
  }
  root.FreqPresentation=Object.freeze({create:create});
})(globalThis);
