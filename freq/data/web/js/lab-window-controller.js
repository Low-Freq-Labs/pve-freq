(function (global) {
  'use strict';
  var PATH = '/api/lab/window', HEX64 = /^[a-f0-9]{64}$/;
  function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
  function keys(value, names) { return object(value) && Object.keys(value).length === names.length && names.every(function (name) { return Object.prototype.hasOwnProperty.call(value, name); }); }
  function identity(value) { return typeof value === 'string' && value.trim().length > 0 && value.length <= 512 && !/[\u0000-\u001f\u007f-\u009f]/.test(value); }
  function revision(value) { return typeof value === 'string' && HEX64.test(value); }
  function code(value) { return value === null || (typeof value === 'string' && /^[a-z][a-z0-9_]{0,127}$/.test(value)); }
  function utc(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)) return false;
    var time = Date.parse(value);
    return Number.isFinite(time) && new Date(time).toISOString().slice(0, 19) === value.slice(0, 19);
  }
  function dto(value) {
    if (!keys(value, ['schema', 'target', 'policy', 'window', 'busy', 'can_request', 'reason']) || value.schema !== 'pve-freq-lab-window-v1' ||
        !keys(value.policy, ['enabled', 'revision', 'duration_seconds', 'audience']) || typeof value.policy.enabled !== 'boolean' ||
        !(value.policy.revision === null || revision(value.policy.revision)) || (value.policy.enabled && !revision(value.policy.revision)) ||
        value.policy.duration_seconds !== 900 || value.policy.audience !== 'original_session' ||
        !(value.busy === null || typeof value.busy === 'boolean') || typeof value.can_request !== 'boolean' || !code(value.reason)) return null;
    var target = value.target, window = value.window;
    if (target !== null && (!keys(target, ['ref', 'configuration_revision', 'estate', 'source', 'node', 'kind', 'vmid', 'name']) ||
        !['ref', 'estate', 'source', 'node', 'name'].every(function (name) { return identity(target[name]); }) ||
        !revision(target.configuration_revision) || target.kind !== 'qemu' || !Number.isSafeInteger(target.vmid) || target.vmid <= 0)) return null;
    if (window !== null) {
      if (!target || !keys(window, ['ref', 'state', 'registration_revision', 'qualified_at', 'expires_at', 'error']) || !identity(window.ref) ||
          !['preparing', 'active', 'expired', 'rejected', 'retired'].includes(window.state) || !code(window.error)) return null;
      var absent = window.registration_revision === null && window.qualified_at === null && window.expires_at === null;
      var finite = revision(window.registration_revision) && utc(window.qualified_at) && utc(window.expires_at) && Date.parse(window.qualified_at) < Date.parse(window.expires_at) && Date.parse(window.expires_at) - Date.parse(window.qualified_at) <= 900000;
      if (!absent && !finite) return null;
      if (window.state === 'active' && (!finite || window.error !== null)) return null;
    }
    if (!target && (value.policy.enabled || value.can_request)) return null;
    if (value.can_request && (!target || !value.policy.enabled || value.busy !== false || value.reason !== null ||
        (window && ['preparing', 'active'].includes(window.state)))) return null;
    return {schema: 'pve-freq-lab-window-v1', target: target ? Object.assign({}, target) : null, policy: Object.assign({}, value.policy),
      window: window ? Object.assign({}, window) : null, busy: value.busy, can_request: value.can_request, reason: value.reason};
  }
  function errorCode(response) {
    return response && keys(response.data, ['error']) && response.data.error !== null && code(response.data.error) ? response.data.error : null;
  }
  function definitiveRefusal(response) {
    var error = errorCode(response);
    return !!error && ((response.status === 400 && error === 'invalid_request') ||
      (response.status === 404 && error === 'not_found') || (response.status === 405 && error === 'method_not_allowed') ||
      (response.status === 403 && ['https_required', 'authentication_required', 'same_origin_required', 'csrf_required', 'role_required'].includes(error)) ||
      (response.status === 409 && ['registration_changed', 'policy_changed', 'request_conflict', 'qualification_busy', 'target_busy'].includes(error)));
  }
  function create(options) {
    // Only this controller understands the exact window wire contract. The view
    // receives bounded normalized display facts, never request keys or refs.
    var root = options.root, doc = root.ownerDocument, originalID = root.id;
    var isCurrent = options.isCurrent, isAdmin = options.isAdmin, parentCanRequest = options.canRequest, request = options.request;
    var onStateChange = options.onStateChange, onGrant = options.onGrant, onReadSettled = options.onReadSettled;
    var crypto = global.crypto, randomUUID = crypto && crypto.randomUUID;
    var path = [], part = root;
    while (part) { path.push(part); part = part.parentNode; }
    var disposed = false, generation = 0, observer = null, view = null;
    var active = null, expiryTimer = null, metadata = null, loading = false, confirmed = false;
    var knownWindows = new Map();
    var intent = null, pending = false, unknown = false, requestState = 'none', lastGrantKey = null;

    function gate(callback) { try { return typeof callback === 'function' && callback() === true; } catch (_) { return false; } }
    function changes(records) {
      if (disposed) return;
      function collision(node) {
        return originalID && node.nodeType === 1 && ((node !== root && node.id === originalID) ||
          Array.from(node.querySelectorAll('[id]')).some(function (item) { return item !== root && item.id === originalID; }));
      }
      records.forEach(function (record) {
        if (record.type === 'attributes') {
          if (originalID && (record.target === root || record.oldValue === originalID || record.target.id === originalID)) dispose();
        } else if (Array.from(record.removedNodes).some(function (node) { return path.some(function (item) { return node === item || (node.contains && node.contains(item)); }); }) ||
            Array.from(record.removedNodes).concat(Array.from(record.addedNodes)).some(collision)) dispose();
      });
    }
    function alive() {
      if (disposed) return false;
      if (observer) changes(observer.takeRecords());
      if (disposed) return false;
      var valid = root.isConnected && root.ownerDocument === doc && path.every(function (node, index) { return node.parentNode === (path[index + 1] || null); });
      if (originalID) valid = valid && root.id === originalID && doc.getElementById(originalID) === root &&
        Array.from(doc.querySelectorAll('[id]')).filter(function (node) { return node.id === originalID; }).length === 1;
      try { valid = valid && typeof isCurrent === 'function' && isCurrent() === true; } catch (_) { valid = false; }
      if (observer) changes(observer.takeRecords());
      valid = valid && !disposed && root.isConnected && root.ownerDocument === doc && path.every(function (node, index) { return node.parentNode === (path[index + 1] || null); });
      if (!valid) dispose();
      return valid;
    }
    function clearExpiry() { if (expiryTimer !== null) global.clearTimeout(expiryTimer); expiryTimer = null; }
    function dispose() {
      if (disposed) return;
      disposed = true; generation++; clearExpiry();
      if (observer) observer.disconnect();
      if (active) { active.controller.abort(); active.cancel(); active = null; }
      metadata = intent = null; knownWindows.clear(); confirmed = false; pending = false; unknown = false; lastGrantKey = null;
      if (view) view.dispose();
    }
    function sameBinding(value, captured) {
      return value && value.target && captured && value.policy.revision === captured.policyRevision &&
        value.target.configuration_revision === captured.configurationRevision &&
        ['ref', 'estate', 'source', 'node', 'kind', 'vmid', 'name'].every(function (key) { return value.target[key] === captured.target[key]; });
    }
    function committed(window) {
      return window && window.registration_revision !== null ? {revision: window.registration_revision, startsAt: window.qualified_at, expiresAt: window.expires_at} : null;
    }
    function sameCommitted(window, captured) {
      return !captured || (window && window.registration_revision === captured.revision && window.qualified_at === captured.startsAt && window.expires_at === captured.expiresAt);
    }
    function rememberWindow(value) {
      if (!value.window) return true;
      var window = value.window, prior = knownWindows.get(window.ref);
      if (prior && (!sameCommitted(window, prior.committed) || (window.state !== 'retired' && !sameBinding(value, prior)))) return false;
      if (!prior && knownWindows.size >= 1024) return false;
      if (!prior) {
        prior = {target: Object.assign({}, value.target), configurationRevision: value.target.configuration_revision,
          policyRevision: value.policy.revision, committed: null};
        knownWindows.set(window.ref, prior);
      }
      if (!prior.committed) prior.committed = committed(window);
      return true;
    }
    function currentGrant() {
      if (!alive() || !confirmed || loading || active || !metadata || !metadata.target || !metadata.policy.enabled || metadata.busy === null) return null;
      var value = metadata, captured = generation;
      if (!gate(isAdmin) || !alive() || captured !== generation || metadata !== value || !confirmed || loading || active) return null;
      var window = value.window;
      if (!window || window.state !== 'active' || !revision(window.registration_revision) ||
          Date.now() < Date.parse(window.qualified_at) || Date.now() >= Date.parse(window.expires_at)) return null;
      var known = knownWindows.get(window.ref);
      if (!known || !sameBinding(value, known) || !sameCommitted(window, known.committed)) return null;
      return {ref: value.target.ref, revision: window.registration_revision, startsAt: window.qualified_at, expiresAt: window.expires_at};
    }
    function getGrant() { var grant = currentGrant(); return grant ? Object.freeze(Object.assign({}, grant)) : null; }
    function hasUnresolvedSubmission() { return alive() && (pending || unknown); }
    function canSubmit() {
      if (!alive() || loading || active || pending || unknown || !metadata || !metadata.target || !metadata.can_request ||
          !metadata.policy.enabled || !revision(metadata.policy.revision) || metadata.busy !== false) return false;
      var value = metadata, captured = generation;
      if (!gate(isAdmin) || !alive() || captured !== generation || metadata !== value || loading || active || pending || unknown) return false;
      var window = value.window;
      if (window && ['preparing', 'active'].includes(window.state)) return false;
      return gate(parentCanRequest) && alive() && generation === captured && metadata === value && !loading && !active && !pending && !unknown;
    }
    function canRefresh() { return alive() && !active && !loading && !(pending && intent && !intent.windowRef && intent.outcome === 'pending'); }
    function clip(value) { return value.length <= 256 ? value : value.slice(0, 255) + '…'; }
    function publish() {
      if (!alive() || !view) return;
      var captured = generation, admin = gate(isAdmin), target = metadata && metadata.target, window = metadata && metadata.window;
      if (!alive() || generation !== captured) return;
      var state = loading ? 'loading' : !metadata ? 'unavailable' : !target ? 'unavailable' : !window ? 'inactive' :
        window.state === 'preparing' ? 'inactive' : window.state === 'active' ?
          (Date.now() >= Date.parse(window.expires_at) ? 'expired' : Date.now() < Date.parse(window.qualified_at) ? 'future' : 'active') :
          window.state === 'expired' && window.qualified_at !== null ? 'expired' : 'inactive';
      var model = {windowState: state, requestState: unknown ? 'unknown' : requestState,
        target: target ? {name: clip(target.name), source: clip(target.source), node: clip(target.node), kind: 'qemu', vmid: target.vmid} : null,
        window: window && window.qualified_at !== null ? {startsAt: window.qualified_at, expiresAt: window.expires_at} : null,
        isAdmin: admin, requestEligible: !!(metadata && metadata.can_request && !loading && !active && !pending && !unknown),
        exclusion: metadata && metadata.busy !== false ? 'busy' : 'none'};
      if (view.render(model) !== true) { dispose(); return; }
      if (!alive() || generation !== captured) return;
      if (typeof onStateChange === 'function') { try { onStateChange(Object.freeze({pending: pending, unknown: unknown, loading: loading})); } catch (_) {} }
      if (!alive() || generation !== captured) return;
      var grant = currentGrant(), key = grant ? JSON.stringify(grant) : null;
      if (grant && key !== lastGrantKey) {
        lastGrantKey = key;
        if (typeof onGrant === 'function') { try { onGrant(Object.freeze(Object.assign({}, grant))); } catch (_) {} }
      }
    }
    function armExpiry() {
      clearExpiry();
      if (!alive() || !confirmed || !metadata || !metadata.window || metadata.window.qualified_at === null) return;
      var captured = generation, window = metadata.window;
      var delay = Date.parse(window.expires_at) - Date.now();
      if (delay <= 0) return;
      expiryTimer = global.setTimeout(function () {
        expiryTimer = null;
        if (!alive() || generation !== captured || !confirmed || !metadata || metadata.window !== window) return;
        if (Date.now() < Date.parse(window.expires_at)) { armExpiry(); return; }
        // Expiry changes local display/eligibility only. No GET, POST or renewal.
        publish();
      }, Math.min(delay, 2147483647));
    }
    async function call(method, payload) {
      if (!alive() || active || typeof request !== 'function') throw Error('unavailable');
      var captured = generation, token = {controller: new global.AbortController(), cancel: null};
      active = token;
      var timer;
      var deadline = new Promise(function (_, reject) {
        token.cancel = function () { reject(Error('retired')); };
        timer = global.setTimeout(function () { token.controller.abort(); reject(Error('deadline')); }, 20000);
      });
      try {
        var result = await Promise.race([Promise.resolve().then(function () {
          if (!alive() || captured !== generation || token.controller.signal.aborted) throw Error('retired');
          return request(method, PATH, payload, token.controller.signal);
        }), deadline]);
        if (!alive() || captured !== generation || token.controller.signal.aborted) throw Error('retired');
        return result;
      } finally {
        global.clearTimeout(timer);
        if (active === token) active = null;
      }
    }
    function applyRead(value) {
      if (!rememberWindow(value)) throw Error('binding_changed');
      metadata = value; confirmed = true;
      if (intent) {
        var matches = sameBinding(value, intent) && intent.windowRef && value.window && value.window.ref === intent.windowRef;
        if (intent.outcome === 'refused') {
          pending = false; unknown = false; requestState = 'refused';
        } else if (matches) {
          pending = value.window.state === 'preparing';
          unknown = false;
          requestState = pending ? 'pending' : value.window.state === 'rejected' ? 'refused' : ['expired', 'retired'].includes(value.window.state) ? 'none' : 'acknowledged';
          intent.outcome = pending ? 'pending' : requestState === 'refused' ? 'refused' : 'acknowledged';
        } else if (intent.outcome === 'acknowledged') {
          // Another tab may have a newer original-session window. It does not
          // change the acknowledgement already received for this click.
          pending = false; unknown = false;
          requestState = value.can_request ? 'none' : 'acknowledged';
        } else {
          // Current session authority and attribution to this particular click
          // are independent. Never assign a latest ref to a lost acknowledgement.
          pending = false; unknown = true; requestState = 'unknown';
          intent.outcome = 'unknown';
        }
      } else {
        pending = !!(value.window && value.window.state === 'preparing');
        requestState = pending ? 'pending' : 'none';
      }
      armExpiry();
    }
    function settled(ok, value, captured) {
      if (!alive() || generation !== captured || typeof onReadSettled !== 'function') return;
      var copy = value ? Object.freeze({schema: value.schema, target: value.target ? Object.freeze(Object.assign({}, value.target)) : null,
        policy: Object.freeze(Object.assign({}, value.policy)), window: value.window ? Object.freeze(Object.assign({}, value.window)) : null,
        busy: value.busy, can_request: value.can_request, reason: value.reason}) : null;
      try { onReadSettled(Object.freeze({ok: ok, metadata: copy})); } catch (_) {}
    }
    async function read() {
      if (!alive() || active || loading || (pending && intent && !intent.windowRef && intent.outcome === 'pending')) return;
      var captured = ++generation;
      loading = true; confirmed = false; clearExpiry(); metadata = null;
      publish();
      if (!alive() || generation !== captured) return;
      try {
        var response = await call('GET', null);
        if (!alive() || generation !== captured) return;
        if (errorCode(response) === 'session_retired') { dispose(); return; }
        var value = response && response.status === 200 ? dto(response.data) : null;
        if (!value) throw Error('unavailable');
        loading = false; applyRead(value); publish(); settled(true, value, captured);
      } catch (_) {
        if (!alive() || generation !== captured) return;
        metadata = null; confirmed = false; loading = false;
        if (intent && ['refused', 'acknowledged'].includes(intent.outcome)) {
          // A failed current-window read cannot erase an already known click
          // acknowledgement. Authority remains revoked until a valid fresh GET.
          pending = false; unknown = false; requestState = intent.outcome;
        } else if (intent) { pending = false; unknown = true; requestState = 'unknown'; intent.outcome = 'unknown'; }
        publish(); settled(false, null, captured);
      }
    }
    async function submit() {
      if (!canSubmit()) return;
      var captured = generation, key;
      try { key = typeof randomUUID === 'function' ? randomUUID.call(crypto) : null; } catch (_) { key = null; }
      if (typeof key !== 'string' || !/^[\x21-\x7e]{1,128}$/.test(key) || !alive() || generation !== captured || !canSubmit()) return;
      intent = {target: Object.assign({}, metadata.target), configurationRevision: metadata.target.configuration_revision,
        policyRevision: metadata.policy.revision, windowRef: null, key: key, outcome: 'pending'};
      pending = true; unknown = false; requestState = 'pending'; confirmed = false; clearExpiry();
      publish();
      if (!alive() || generation !== captured) return;
      var payload = {target_ref: intent.target.ref, configuration_revision: intent.configurationRevision,
        policy_revision: intent.policyRevision, request_key: intent.key};
      try {
        var response = await call('POST', payload);
        if (!alive() || generation !== captured) return;
        if (errorCode(response) === 'session_retired') { dispose(); return; }
        if (definitiveRefusal(response)) {
          intent.outcome = 'refused'; pending = false; unknown = false; requestState = 'refused';
          await read(); return;
        }
        var value = response && [200, 201, 202, 409].includes(response.status) ? dto(response.data) : null;
        if (!value || !sameBinding(value, intent) || !value.window || !rememberWindow(value)) throw Error('unavailable');
        intent.windowRef = value.window.ref;
        // Admission metadata is never a grant publication. Confirm independently.
        requestState = value.window.state === 'rejected' ? 'refused' : value.window.state === 'preparing' ? 'pending' : 'acknowledged';
        intent.outcome = requestState;
        await read();
      } catch (_) {
        if (!alive() || generation !== captured) return;
        pending = false; unknown = true; requestState = 'unknown'; intent.outcome = 'unknown'; confirmed = false; metadata = null;
        publish();
      }
    }
    observer = new doc.defaultView.MutationObserver(changes);
    observer.observe(doc, {subtree: true, childList: true, attributes: true, attributeFilter: ['id'], attributeOldValue: true});
    view = global.FreqLabWindowPanel.create({root: root, isCurrent: alive, canRequest: canSubmit, onRequest: submit,
      canRefresh: canRefresh, onRefresh: read});
    // Repaint private eligibility after local power-state changes; no I/O.
    return Object.freeze({load: read, dispose: dispose, hasUnresolvedSubmission: hasUnresolvedSubmission, getGrant: getGrant, refreshEligibility: publish});
  }
  global.FreqLabWindowController = Object.freeze({create: create});
})(window);
