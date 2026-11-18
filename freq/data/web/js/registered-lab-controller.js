(function (global) {
  'use strict';
  var GUEST = '/api/lab/guest', POWER = '/api/lab/power', OPERATIONS = '/api/lab/operations/';
  var HEX32 = /^[a-f0-9]{32}$/, HEX64 = /^[a-f0-9]{64}$/;
  var phases = ['dispatching', 'acknowledged', 'running', 'succeeded', 'failed', 'rejected', 'uncertain'];
  function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
  function keys(value, names) { return object(value) && Object.keys(value).length === names.length && names.every(function (name) { return Object.prototype.hasOwnProperty.call(value, name); }); }
  function identity(value) { return typeof value === 'string' && value.trim().length > 0 && value.length <= 512 && !/[\u0000-\u001f\u007f-\u009f]/.test(value); }
  function utc(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)) return false;
    var time = Date.parse(value);
    return Number.isFinite(time) && new Date(time).toISOString().slice(0, 19) === value.slice(0, 19);
  }
  function observation(value) {
    return keys(value, ['state', 'observed_at']) && ['unknown', 'running', 'stopped'].includes(value.state) &&
      (value.state === 'unknown' ? value.observed_at === null : utc(value.observed_at));
  }
  function summary(value) {
    return keys(value, ['ref', 'target_ref', 'registration_revision', 'retired', 'action', 'phase']) && HEX32.test(value.ref) &&
      HEX64.test(value.registration_revision) && typeof value.retired === 'boolean' &&
      (value.retired ? value.target_ref === null : identity(value.target_ref)) &&
      ['start', 'shutdown'].includes(value.action) && phases.includes(value.phase);
  }
  function guestDTO(value) {
    if (!keys(value, ['schema', 'target', 'capabilities', 'observation', 'busy', 'operation']) ||
        value.schema !== 'pve-freq-lab-guest-view-v1') return null;
    var target = value.target, cap = value.capabilities;
    if (!keys(target, ['ref', 'registration_revision', 'estate', 'source', 'node', 'kind', 'vmid', 'name', 'qualified_at', 'expires_at']) ||
        !identity(target.ref) || !HEX64.test(target.registration_revision) ||
        !['estate', 'source', 'node', 'name'].every(function (field) { return identity(target[field]); }) ||
        target.kind !== 'qemu' || !Number.isSafeInteger(target.vmid) || target.vmid <= 0 ||
        !utc(target.qualified_at) || !utc(target.expires_at) || Date.parse(target.expires_at) <= Date.parse(target.qualified_at) ||
        !keys(cap, ['lab_only', 'actions']) || cap.lab_only !== true || !Array.isArray(cap.actions) ||
        !cap.actions.every(function (action) { return ['start', 'shutdown'].includes(action); }) ||
        new Set(cap.actions).size !== cap.actions.length || !observation(value.observation) ||
        typeof value.busy !== 'boolean' || !(value.operation === null || summary(value.operation))) return null;
    return {target: Object.assign({}, target), capabilities: {lab_only: true, actions: cap.actions.slice()},
      observation: Object.assign({}, value.observation), busy: value.busy,
      operation: value.operation === null ? null : Object.assign({}, value.operation)};
  }
  function operationDTO(value) {
    if (!keys(value, ['schema', 'operation']) || value.schema !== 'pve-freq-lab-operation-view-v1') return null;
    var op = value.operation;
    if (!keys(op, ['ref', 'target_ref', 'registration_revision', 'retired', 'action', 'expected_state', 'phase', 'acknowledgement', 'task', 'observation', 'error', 'created_at', 'updated_at']) ||
        !HEX32.test(op.ref) || !HEX64.test(op.registration_revision) || typeof op.retired !== 'boolean' ||
        (op.retired ? op.target_ref !== null : !identity(op.target_ref)) ||
        !['start', 'shutdown'].includes(op.action) || op.expected_state !== (op.action === 'start' ? 'stopped' : 'running') ||
        !phases.includes(op.phase) || !['pending', 'received', 'not_submitted', 'uncertain'].includes(op.acknowledgement) ||
        (op.phase === 'rejected' && op.acknowledgement !== 'not_submitted') ||
        !keys(op.task, ['state', 'exit']) || !['unknown', 'running', 'succeeded', 'failed'].includes(op.task.state) ||
        ![null, 'OK', 'failed', 'unknown'].includes(op.task.exit) || !observation(op.observation) ||
        !(op.error === null || (typeof op.error === 'string' && /^[a-z][a-z0-9_]{0,127}$/.test(op.error))) ||
        !utc(op.created_at) || !utc(op.updated_at) || Date.parse(op.updated_at) < Date.parse(op.created_at)) return null;
    return Object.assign({}, op, {task: Object.assign({}, op.task), observation: Object.assign({}, op.observation)});
  }
  function terminal(op) { return !!op && ['succeeded', 'failed', 'rejected'].includes(op.phase); }
  function logical(a, b) { return !!a && !!b && a.ref === b.ref && a.registration_revision === b.registration_revision; }
  function sameIdentity(a, b) {
    return ['estate', 'source', 'node', 'kind', 'vmid', 'name', 'qualified_at', 'expires_at'].every(function (key) { return a[key] === b[key]; });
  }

  function create(options) {
    var root = options.root, parent = root.parentNode, doc = root.ownerDocument, id = root.id;
    var disposed = false, generation = 0, active = null, pollTimer = null, expiryTimer = null;
    var guest = null, previousTarget = null, intent = null, op = null;
    var pending = false, uncertainty = false, needsFresh = false, retired = false, loading = false, readingFresh = false;
    var observationUnknown = false, notice = '', pollStarted = 0, passes = 0;
    var currentObservationKnown = false;
    var lastUnsettled = null;
    var view = global.FreqRegisteredLabPanel.create({root: root, isCurrent: alive,
      canAct: canAct, onAction: act, onRefresh: load,
      canRefresh: function () { return alive() && !pending && !active; }});

    function alive() {
      if (disposed) return false;
      var valid = root.isConnected && root.parentNode === parent && root.ownerDocument === doc && (!id || doc.getElementById(id) === root);
      try { valid = valid && options.isCurrent() === true; } catch (_) { valid = false; }
      if (!valid) dispose();
      return valid;
    }
    function stopPoll() { if (pollTimer !== null) { global.clearTimeout(pollTimer); pollTimer = null; } }
    function dispose() {
      if (disposed) return;
      disposed = true; generation++; stopPoll();
      if (expiryTimer !== null) { global.clearTimeout(expiryTimer); expiryTimer = null; }
      if (active) { active.controller.abort(); active.cancel(); active = null; }
      guest = previousTarget = intent = op = null;
      if (view) view.dispose();
    }
    function qualified() {
      return !!guest && Date.parse(guest.target.qualified_at) <= Date.now() && Date.now() < Date.parse(guest.target.expires_at);
    }
    function bound() {
      return !!guest && !!intent && guest.target.ref === intent.target_ref &&
        guest.target.registration_revision === intent.registration_revision && !retired;
    }
    function baseCanAct(action) {
      return alive() && ['start', 'shutdown'].includes(action) && qualified() && !loading && !active &&
        !pending && !uncertainty && !needsFresh && currentObservationKnown && !retired && !guest.busy &&
        guest.capabilities.lab_only === true && guest.capabilities.actions.includes(action) &&
        guest.observation.state === (action === 'start' ? 'stopped' : 'running') && (!op || terminal(op));
    }
    function canAct(action) {
      if (!baseCanAct(action)) return false;
      // An optional original-owner gate can only remove admission. It never
      // replaces the existing registered-target/session/state checks.
      if (options.maySubmit !== undefined) {
        try { if (typeof options.maySubmit !== 'function' || options.maySubmit() !== true) return false; }
        catch (_) { return false; }
      }
      return baseCanAct(action);
    }
    function getCurrentBinding() {
      return alive() && guest ? {ref: guest.target.ref, revision: guest.target.registration_revision,
        startsAt: guest.target.qualified_at, expiresAt: guest.target.expires_at} : null;
    }
    function hasUnsettledAttempt() {
      return !alive() || loading || pending || uncertainty || needsFresh || retired || !!(op && !terminal(op)) || !!(guest && guest.busy);
    }
    function displayOperation() {
      if (!op || !guest || retired || op.retired || op.target_ref !== guest.target.ref ||
          op.registration_revision !== guest.target.registration_revision) return null;
      return {ref: op.ref, targetRef: op.target_ref, registrationRevision: op.registration_revision, action: op.action,
        phase: ({dispatching: 'admitting', acknowledged: 'submitted', running: 'tracking', succeeded: 'terminal', failed: 'terminal', rejected: 'terminal', uncertain: 'unknown'})[op.phase],
        ack: ({pending: 'pending', received: 'acknowledged', not_submitted: 'not_submitted', uncertain: 'unknown'})[op.acknowledgement],
        taskState: ({unknown: 'unknown', running: 'running', succeeded: 'success', failed: 'failed'})[op.task.state],
        observedState: op.observation.state, observedAt: op.observation.observed_at, observationUnknown: observationUnknown};
    }
    function publish() {
      if (!alive()) return;
      var state = loading && !readingFresh ? 'loading' : guest ? (Date.now() >= Date.parse(guest.target.expires_at) ? 'expired' : 'ready') : 'unavailable';
      var target = guest && (!loading || readingFresh) ? {ref: guest.target.ref, revision: guest.target.registration_revision,
        estate: guest.target.estate, source: guest.target.source, node: guest.target.node, kind: guest.target.kind,
        vmid: guest.target.vmid, name: guest.target.name, expiresAt: guest.target.expires_at,
        state: currentObservationKnown ? guest.observation.state : 'unknown',
        observedAt: currentObservationKnown ? guest.observation.observed_at : null} : null;
      view.render({registrationState: state, target: target, operation: loading && !readingFresh ? null : displayOperation(),
        loading: loading, notice: (state === 'expired' ? 'Power window expired. New actions require a new explicit qualification. ' : '') + notice,
        observationUnknown: observationUnknown});
      if (typeof options.onStateChange === 'function' && alive()) {
        var unsettled = hasUnsettledAttempt();
        if (unsettled !== lastUnsettled) {
          lastUnsettled = unsettled;
          try { options.onStateChange(Object.freeze({unsettled: unsettled})); } catch (_) {}
        }
      }
    }
    function armExpiry() {
      if (expiryTimer !== null) global.clearTimeout(expiryTimer);
      expiryTimer = null;
      if (!guest || !alive()) return;
      var delay = Date.parse(guest.target.expires_at) - Date.now();
      if (delay <= 0) return;
      expiryTimer = global.setTimeout(function () {
        expiryTimer = null;
        if (!alive() || !guest) return;
        if (Date.now() < Date.parse(guest.target.expires_at)) { armExpiry(); return; }
        // Expiry withdraws dispatch authority, not the original-session witness
        // for already submitted work. Existing GET/POST deadlines and bounded
        // operation polling remain unchanged; no qualification is issued here.
        notice = 'Observation of the original operation remains available within its existing limit.';
        publish();
      }, Math.min(delay, 2147483647));
    }
    async function call(method, path, payload) {
      if (!alive() || active) throw Error('unavailable');
      var captured = generation, token = {controller: new global.AbortController(), method: method, cancel: null};
      active = token;
      var timer, rejectDeadline;
      var deadline = new Promise(function (_, reject) {
        rejectDeadline = reject;
        timer = global.setTimeout(function () { token.controller.abort(); reject(Error('timeout')); }, 20000);
      });
      token.cancel = function () { rejectDeadline(Error('retired')); };
      try {
        var result = await Promise.race([Promise.resolve().then(function () {
          if (!alive() || captured !== generation || token.controller.signal.aborted) throw Error('retired');
          return options.request(method, path, payload, token.controller.signal);
        }), deadline]);
        if (!alive() || captured !== generation || token.controller.signal.aborted) throw Error('retired');
        return result;
      } finally {
        global.clearTimeout(timer);
        if (active === token) active = null;
      }
    }
    function matches(opValue) {
      return bound() && !opValue.retired && opValue.ref === intent.opRef && opValue.target_ref === intent.target_ref &&
        opValue.registration_revision === intent.registration_revision && opValue.action === intent.action &&
        opValue.expected_state === intent.expected_state;
    }
    function pollAllowed() {
      return alive() && bound() && !!intent.opRef && !uncertainty && !pending && !terminal(op);
    }
    function schedule() {
      stopPoll();
      if (!pollAllowed()) return;
      if (passes >= 30 || Date.now() - pollStarted >= 60000) {
        notice = 'Operation observation paused at its time limit. Refresh status to resume the original operation.';
        publish(); return;
      }
      pollTimer = global.setTimeout(function () {
        pollTimer = null;
        if (!pollAllowed()) return;
        if (passes >= 30 || Date.now() - pollStarted >= 60000) {
          notice = 'Operation observation paused at its time limit. Refresh status to resume the original operation.';
          publish(); return;
        }
        observe();
      }, 2000);
    }
    async function accept(value) {
      if (!alive() || !matches(value)) return false;
      op = value; pending = false; observationUnknown = false;
      uncertainty = value.phase === 'uncertain' || value.acknowledgement === 'uncertain';
      if (uncertainty) {
        stopPoll(); notice = 'The original submission outcome is uncertain. No repeat submission is available.'; publish();
      } else if (terminal(value)) {
        stopPoll(); needsFresh = true;
        notice = 'Operation facts are historical. Reading the current registered guest separately.';
        publish(); await refreshGuest(true);
      } else {
        notice = 'Submission, task and guest observations are separate facts. The original operation is being observed.';
        publish(); schedule();
      }
      return true;
    }
    async function observe() {
      if (!alive() || !bound() || !intent.opRef || pending || active) return;
      var captured = generation, reference = intent.opRef;
      passes++;
      try {
        var response = await call('GET', OPERATIONS + reference, null);
        if (!alive() || captured !== generation) return;
        var value = response && response.status === 200 ? operationDTO(response.data) : null;
        if (value && value.retired && value.ref === reference && value.registration_revision === intent.registration_revision && value.action === intent.action) {
          retired = true; uncertainty = true; op = null; stopPoll();
          notice = 'The original operation belongs to a retired registration and cannot join this target.'; publish(); return;
        }
        if (!value || !matches(value)) throw Error('unavailable');
        await accept(value);
      } catch (_) {
        if (!alive() || captured !== generation) return;
        stopPoll(); observationUnknown = true; currentObservationKnown = false;
        notice = 'Operation observation is unavailable. Known submission and task facts are retained. Refresh status to resume.';
        publish();
      }
    }
    async function refreshGuest(afterTerminal) {
      if (!alive() || active || pending) return;
      stopPoll(); loading = true; readingFresh = afterTerminal;
      notice = afterTerminal ? 'Operation facts are historical. Waiting for a separate fresh guest read; controls remain unavailable.' : 'Reading the registered lab target.';
      publish();
      var captured = generation;
      try {
        var response = await call('GET', GUEST, null);
        if (!alive() || captured !== generation) return;
        var value = response && response.status === 200 ? guestDTO(response.data) : null;
        if (!value) throw Error('unavailable');
        if (previousTarget && logical(previousTarget, value.target) && !sameIdentity(previousTarget, value.target)) throw Error('unavailable');
        guest = value; loading = false; readingFresh = false; currentObservationKnown = true;
        if (previousTarget && !logical(previousTarget, guest.target)) {
          var wasTerminal = terminal(op);
          op = null;
          if (intent && (!wasTerminal || uncertainty || pending)) uncertainty = true;
          else { intent = null; needsFresh = false; retired = false; }
        }
        previousTarget = Object.assign({}, guest.target);
        armExpiry();
        var recovery = guest.operation;
        if (recovery && recovery.retired) {
          retired = true; op = null;
          notice = 'The previous operation belongs to a retired registration and cannot join this target.'; publish(); return;
        }
        if (recovery && recovery.target_ref === guest.target.ref && recovery.registration_revision === guest.target.registration_revision &&
            (!intent || (intent.target_ref === recovery.target_ref && intent.registration_revision === recovery.registration_revision &&
              intent.action === recovery.action && (!intent.opRef || intent.opRef === recovery.ref)))) {
          if (!intent) intent = {target_ref: recovery.target_ref, registration_revision: recovery.registration_revision,
            action: recovery.action, expected_state: recovery.action === 'start' ? 'stopped' : 'running', request_key: null, opRef: recovery.ref};
          else intent.opRef = recovery.ref;
          retired = false;
          if (!afterTerminal) { notice = 'Reading this session’s original operation reference.'; publish(); await observe(); return; }
        } else if (recovery) {
          uncertainty = true;
          notice = 'Operation recovery did not match this intent and registration. No submission is available.'; publish(); return;
        }
        if (afterTerminal && op && terminal(op) && bound() && !uncertainty) needsFresh = false;
        notice = uncertainty ? 'The prior submission remains uncertain. Refresh can recover only its original operation.' :
          guest.busy ? 'The registered target is busy. No action is available.' : 'Current guest state is a separate registered-target observation.';
        publish();
        if (!afterTerminal && intent && intent.opRef && bound() && !terminal(op)) await observe();
      } catch (_) {
        if (!alive() || captured !== generation) return;
        guest = null; loading = false; readingFresh = false; observationUnknown = !!op; currentObservationKnown = false;
        if (expiryTimer !== null) { global.clearTimeout(expiryTimer); expiryTimer = null; }
        notice = 'Registered lab state is unavailable. No power action is available.'; publish();
      }
    }
    async function act(action) {
      if (!canAct(action)) return;
      var key;
      try { key = global.crypto.randomUUID(); } catch (_) { notice = 'An intent key could not be created. No request was submitted.'; publish(); return; }
      if (typeof key !== 'string' || !/^[\x21-\x7e]{1,128}$/.test(key) || !canAct(action)) return;
      intent = {target_ref: guest.target.ref, registration_revision: guest.target.registration_revision,
        action: action, expected_state: action === 'start' ? 'stopped' : 'running', request_key: key, opRef: null};
      op = null; pending = true; uncertainty = false; retired = false; needsFresh = true; observationUnknown = false;
      currentObservationKnown = false;
      stopPoll(); pollStarted = Date.now(); passes = 0;
      notice = 'One power intent is being submitted. No repeat submission will be attempted.'; publish();
      var captured = generation;
      var payload = {target_ref: intent.target_ref, registration_revision: intent.registration_revision,
        action: intent.action, expected_state: intent.expected_state, request_key: intent.request_key};
      try {
        var response = await call('POST', POWER, payload);
        if (!alive() || captured !== generation) return;
        var value = response && [200, 202, 409].includes(response.status) ? operationDTO(response.data) : null;
        if (!value || value.retired || value.target_ref !== intent.target_ref || value.registration_revision !== intent.registration_revision ||
            value.action !== intent.action || value.expected_state !== intent.expected_state) throw Error('unavailable');
        intent.opRef = value.ref;
        if (!await accept(value)) throw Error('unavailable');
      } catch (_) {
        if (!alive() || captured !== generation) return;
        pending = false; uncertainty = true; stopPoll();
        notice = 'The submission response is unknown. No retry is available; refresh status to recover the original operation.'; publish();
      }
    }
    function load() {
      if (!alive() || active || pending) return Promise.resolve();
      pollStarted = Date.now(); passes = 0;
      return refreshGuest(false);
    }
    return Object.freeze({load: load, dispose: dispose, getCurrentBinding: getCurrentBinding,
      hasUnsettledAttempt: hasUnsettledAttempt, refreshEligibility: publish});
  }
  global.FreqRegisteredLabController = Object.freeze({create: create});
})(window);
