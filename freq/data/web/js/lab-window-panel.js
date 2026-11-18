(function (global) {
  'use strict';
  var serial = 0;
  var windowLabels = {loading: 'Loading', unavailable: 'Unavailable', not_configured: 'Not configured', inactive: 'Inactive', active: 'Active', expired: 'Expired', future: 'Not started'};
  var requestLabels = {none: 'No request pending', pending: 'Pending', acknowledged: 'Acknowledged', refused: 'Refused', unknown: 'Unknown outcome'};
  var exclusionLabels = {none: 'None reported', busy: 'Busy', uncertain: 'Uncertain prior operation'};
  function create(options) {
    // This is an internal normalized display model, NOT a backend DTO or an
    // authorization source. The parent owns all reads, admission and recovery.
    var root = options.root, doc = root.ownerDocument;
    var isCurrent = options.isCurrent, canRequest = options.canRequest, onRequest = options.onRequest;
    var canRefresh = options.canRefresh, onRefresh = options.onRefresh;
    var path = [], cursor = root;
    while (cursor) { path.push(cursor); cursor = cursor.parentNode; }
    var observer = null;
    var originalID = root.id, disposed = false, generation = 0, model = null, consumed = false;
    var hadClass = root.classList.contains('lab-window-panel');
    var prefix = 'lab-window-' + (++serial);
    var shell = node('section', undefined, 'lab-window-shell');
    var heading = node('h2', 'Lab access window');
    heading.id = prefix + '-heading';
    shell.setAttribute('aria-labelledby', heading.id);
    var introduction = node('p', 'Request a 15-minute lab window for the owner-configured target. Power actions are separate.', 'lab-window-intro');
    var grid = node('div', undefined, 'lab-window-grid');
    var targetBox = box('Configured lab target', 'data-lab-window-target');
    var windowBox = box('Window and request status', 'data-lab-window-facts');
    var status = node('p', undefined, 'lab-window-status');
    status.id = prefix + '-status'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite'); status.setAttribute('aria-atomic', 'true');
    var controls = node('div', undefined, 'lab-window-actions');
    var requestReason = node('p', undefined, 'lab-window-reason'); requestReason.id = prefix + '-request-reason';
    var refreshReason = node('p', undefined, 'lab-window-reason'); refreshReason.id = prefix + '-refresh-reason';
    var requestButton = button('Request lab window', requestReason.id);
    var refreshButton = button('Refresh window status', refreshReason.id);
    controls.append(requestButton, refreshButton);
    grid.append(targetBox.section, windowBox.section);
    shell.append(heading, introduction, grid, status, controls, requestReason, refreshReason);
    root.classList.add('lab-window-panel');

    function node(tag, text, className) {
      var value = doc.createElement(tag);
      if (text !== undefined) value.textContent = text;
      if (className) value.className = className;
      return value;
    }
    function box(title, attribute) {
      var section = node('section', undefined, 'lab-window-card'), body = node('div');
      section.setAttribute(attribute, ''); section.append(node('h3', title), body);
      return {section: section, body: body};
    }
    function button(label, reason) {
      var value = node('button', label, 'fleet-btn lab-window-button');
      value.type = 'button'; value.disabled = true;
      value.setAttribute('aria-describedby', reason + ' ' + status.id);
      return value;
    }
    function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
    function keys(value, names) { return object(value) && Object.keys(value).length === names.length && names.every(function (name) { return Object.prototype.hasOwnProperty.call(value, name); }); }
    function label(value) { return typeof value === 'string' && value.trim().length > 0 && value.length <= 256 && !/[\u0000-\u001f\u007f-\u009f]/.test(value); }
    function member(value, labels) { return typeof value === 'string' && Object.prototype.hasOwnProperty.call(labels, value); }
    function utc(value) {
      if (typeof value !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)) return false;
      var time = Date.parse(value);
      return Number.isFinite(time) && new Date(time).toISOString().slice(0, 19) === value.slice(0, 19);
    }
    function normalize(value) {
      if (!keys(value, ['windowState', 'requestState', 'target', 'window', 'isAdmin', 'requestEligible', 'exclusion']) ||
          !member(value.windowState, windowLabels) || !member(value.requestState, requestLabels) || !member(value.exclusion, exclusionLabels) ||
          typeof value.isAdmin !== 'boolean' || typeof value.requestEligible !== 'boolean') return null;
      var target = value.target, window = value.window;
      if (target !== null && (!keys(target, ['name', 'source', 'node', 'kind', 'vmid']) ||
          !['name', 'source', 'node'].every(function (key) { return label(target[key]); }) || target.kind !== 'qemu' ||
          !Number.isSafeInteger(target.vmid) || target.vmid <= 0)) return null;
      if (window !== null && (!keys(window, ['startsAt', 'expiresAt']) || !utc(window.startsAt) || !utc(window.expiresAt) || Date.parse(window.startsAt) >= Date.parse(window.expiresAt))) return null;
      if (['active', 'expired', 'future'].includes(value.windowState) && (!target || !window)) return null;
      if (value.windowState === 'not_configured' && (target !== null || window !== null)) return null;
      return {windowState: value.windowState, requestState: value.requestState, exclusion: value.exclusion,
        isAdmin: value.isAdmin, requestEligible: value.requestEligible,
        target: target ? {name: target.name, source: target.source, node: target.node, kind: 'qemu', vmid: target.vmid} : null,
        window: window ? {startsAt: window.startsAt, expiresAt: window.expiresAt} : null};
    }
    function mutationRecords(records) {
      if (disposed) return;
      var ownedNodes = path.concat([shell, controls, requestButton, refreshButton]);
      function collision(part) {
        if (!originalID || part.nodeType !== 1) return false;
        return (part !== root && part.id === originalID) || Array.from(part.querySelectorAll('[id]')).some(function (item) { return item !== root && item.id === originalID; });
      }
      for (var index = 0; index < records.length; index++) {
        var change = records[index];
        if (change.type === 'attributes') {
          if ((change.target === root && originalID) || (change.target !== root && originalID && (change.oldValue === originalID || change.target.id === originalID))) { dispose(); return; }
        } else {
          var removed = Array.from(change.removedNodes), added = Array.from(change.addedNodes);
          if (removed.some(function (part) { return ownedNodes.some(function (item) { return part === item || (part.contains && part.contains(item)); }); }) || removed.concat(added).some(collision)) { dispose(); return; }
        }
      }
    }
    function current() {
      if (disposed) return false;
      if (observer) mutationRecords(observer.takeRecords());
      if (disposed) return false;
      var valid = root.isConnected && root.ownerDocument === doc && path.every(function (part, index) { return part.parentNode === (path[index + 1] || null); });
      if (originalID) valid = valid && root.id === originalID && doc.getElementById(originalID) === root &&
        Array.from(doc.querySelectorAll('[id]')).filter(function (part) { return part.id === originalID; }).length === 1;
      try { valid = valid && typeof isCurrent === 'function' && isCurrent() === true; } catch (_) { valid = false; }
      if (!valid) dispose();
      return valid;
    }
    function owned(version, control) {
      return current() && version === generation && shell.parentNode === root && controls.parentNode === shell && control.parentNode === controls;
    }
    function privateGate(gate) { try { return typeof gate === 'function' && gate() === true; } catch (_) { return false; } }
    function requestModelEligible() {
      return model && model.target && model.isAdmin && model.requestEligible && ['inactive', 'expired'].includes(model.windowState) &&
        model.exclusion === 'none' && ['none', 'refused'].includes(model.requestState) && !consumed;
    }
    function disabledReason() {
      if (!model) return 'Lab window status is unavailable. Refresh window status before requesting a window.';
      if (!model.isAdmin) return 'An administrator is required to request a lab window.';
      if (!model.target || model.windowState === 'not_configured') return 'No current configured lab target is available.';
      if (model.exclusion === 'uncertain') return 'Reconcile the prior operation before requesting a new window.';
      if (model.exclusion === 'busy') return 'The lab target is busy. A new window request is unavailable.';
      if (model.requestState === 'unknown') return 'The click outcome is unknown. Refresh reads the current session window; it does not retry this request.';
      if (model.requestState === 'pending' || consumed) return 'A window request has been handed off. No repeat request is available in this view state.';
      if (model.requestState === 'acknowledged') return model.windowState === 'active' ? 'A lab window is active. A replacement request is unavailable.' : 'The request was acknowledged. Refresh window status to confirm the grant.';
      if (model.windowState === 'active') return 'A lab window is active. No automatic renewal or extension is available.';
      if (model.windowState === 'future') return 'The configured window has not started. A replacement request is unavailable.';
      return 'A lab window request is unavailable in the current state.';
    }
    function updateControls(version) {
      requestButton.disabled = true; refreshButton.disabled = true;
      var requestAllowed = !!requestModelEligible() && typeof onRequest === 'function' && privateGate(canRequest);
      if (!owned(version, requestButton)) return false;
      requestButton.disabled = !requestAllowed;
      requestReason.textContent = requestAllowed ? 'Request 15 minutes for this configured lab target. No power action is submitted by this control.' : disabledReason();
      var refreshAllowed = !!model && model.windowState !== 'loading' && typeof onRefresh === 'function' && privateGate(canRefresh);
      if (!owned(version, refreshButton)) return false;
      refreshButton.disabled = !refreshAllowed;
      refreshReason.textContent = refreshAllowed ? 'Refresh reads window status only.' : 'Window status refresh is unavailable in the current state.';
      [requestButton, refreshButton].forEach(function (control) {
        if (control.disabled) control.dataset.actionUnavailable = 'true'; else delete control.dataset.actionUnavailable;
      });
      return true;
    }
    function fields(entries) {
      var list = node('dl', undefined, 'lab-window-fields');
      entries.forEach(function (entry) { list.append(node('dt', entry[0]), node('dd', entry[1])); });
      return list;
    }
    function render(input) {
      if (!current()) return false;
      var version = ++generation;
      model = normalize(input); consumed = false;
      requestButton.disabled = true; refreshButton.disabled = true;
      targetBox.body.replaceChildren(); windowBox.body.replaceChildren();
      if (!model) {
        targetBox.body.append(node('p', 'Configured target unavailable.', 'lab-window-empty'));
        windowBox.body.append(fields([['Window status', 'Unknown'], ['Request status', 'Unknown'], ['Pending work', 'Unknown']]));
        status.textContent = 'Lab window status is unavailable. No current window or request eligibility is established.';
      } else {
        if (model.target) targetBox.body.append(fields([['Name', model.target.name], ['Source', model.target.source], ['Node', model.target.node], ['Kind', 'QEMU virtual machine'], ['VMID', String(model.target.vmid)]]));
        else targetBox.body.append(node('p', model.windowState === 'not_configured' ? 'No lab target is configured.' : 'Configured target unavailable.', 'lab-window-empty'));
        windowBox.body.append(fields([['Window status', windowLabels[model.windowState]], ['Window starts at', model.window ? model.window.startsAt + ' (UTC)' : 'Unknown'],
          ['Window expires at', model.window ? model.window.expiresAt + ' (UTC)' : 'Unknown'], ['Request status', requestLabels[model.requestState]], ['Pending work', exclusionLabels[model.exclusion]]]));
        status.textContent = model.requestState === 'unknown' ? 'This click outcome is unknown. The displayed session window is separate. Refresh reads its current status without retrying the request.' :
          model.requestState === 'pending' ? 'Requesting a lab window. Power actions remain separate.' :
          model.exclusion === 'uncertain' ? 'A prior operation is uncertain. A new window cannot resolve it.' :
          model.exclusion === 'busy' ? 'The lab target is busy. A new window request is unavailable.' :
          model.requestState === 'acknowledged' ? (model.windowState === 'active' ? 'The reported lab window is active. Power actions require a separate current guest observation.' : 'Request acknowledged. Refresh window status to confirm the grant.') :
          model.requestState === 'refused' ? 'The lab window request was refused. Current eligibility is checked before another explicit request.' :
          model.windowState === 'active' ? 'The reported lab window is active until the displayed expiry. Power actions require a separate current guest observation.' :
          model.windowState === 'expired' ? 'The lab window expired. Already submitted work is not cancelled. No automatic renewal occurs.' :
          model.windowState === 'future' ? 'The reported lab window has not started. No power permission is established here.' :
          model.windowState === 'not_configured' ? 'The installation owner must configure the lab target before a window can be requested.' :
          model.windowState === 'inactive' ? 'No lab window is active. An eligible administrator can request one for this configured target.' : 'Lab window status is unavailable.';
      }
      if (shell.parentNode !== root) root.append(shell);
      return updateControls(version);
    }
    function request(event) {
      var version = generation;
      if (!event.isTrusted || requestButton.disabled || !owned(version, requestButton) || !requestModelEligible() || typeof onRequest !== 'function') return;
      var allowed = privateGate(canRequest);
      if (!owned(version, requestButton) || requestButton.disabled || !requestModelEligible()) return;
      if (!allowed) { requestButton.disabled = true; requestButton.dataset.actionUnavailable = 'true'; requestReason.textContent = disabledReason(); return; }
      consumed = true; requestButton.disabled = true; requestButton.dataset.actionUnavailable = 'true';
      requestReason.textContent = 'A window request has been handed off. No repeat request is available in this view state.';
      status.textContent = 'Requesting a lab window. Power actions remain separate.';
      try { onRequest(); } catch (_) { if (owned(version, requestButton)) status.textContent = 'The window request handoff outcome is unknown. Refresh reads current session status without retrying the request.'; }
    }
    function refresh(event) {
      var version = generation;
      if (!event.isTrusted || refreshButton.disabled || !owned(version, refreshButton) || !model || model.windowState === 'loading' || typeof onRefresh !== 'function') return;
      var allowed = privateGate(canRefresh);
      if (!owned(version, refreshButton) || refreshButton.disabled) return;
      if (!allowed) { refreshButton.disabled = true; refreshButton.dataset.actionUnavailable = 'true'; refreshReason.textContent = 'Window status refresh is unavailable in the current state.'; return; }
      try { onRefresh(); } catch (_) { if (owned(version, refreshButton)) status.textContent = 'Window status refresh is unavailable. No window request was made by this refresh control.'; }
    }
    function dispose() {
      if (disposed) return;
      disposed = true; generation++; model = null; consumed = true;
      if (observer) observer.disconnect();
      requestButton.removeEventListener('click', request); refreshButton.removeEventListener('click', refresh);
      requestButton.disabled = true; refreshButton.disabled = true;
      shell.replaceChildren(); shell.remove();
      if (!hadClass) root.classList.remove('lab-window-panel');
    }
    observer = new doc.defaultView.MutationObserver(mutationRecords);
    observer.observe(doc, {subtree: true, childList: true, attributes: true, attributeFilter: ['id'], attributeOldValue: true});
    requestButton.addEventListener('click', request); refreshButton.addEventListener('click', refresh);
    render({windowState: 'loading', requestState: 'none', target: null, window: null, isAdmin: false, requestEligible: false, exclusion: 'none'});
    return Object.freeze({render: render, dispose: dispose});
  }
  global.FreqLabWindowPanel = Object.freeze({create: create});
})(window);
