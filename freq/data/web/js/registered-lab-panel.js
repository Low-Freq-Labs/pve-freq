(function (global) {
  'use strict';
  var sequence = 0;

  // Internal display model only; this is not a backend wire schema or an
  // authorization decision. The parent adapter validates its API join and owns
  // all requests. This consumer forwards only privately gated action constants
  // from trusted clicks, and never infers an overall operation result.
  function create(options) {
    var root = options.root, doc = root.ownerDocument, parent = root.parentNode;
    var isCurrent = options.isCurrent;
    var onAction = options.onAction, canAct = options.canAct;
    var onRefresh = options.onRefresh, canRefresh = options.canRefresh;
    var generation = 0, listeners = [];
    var disposed = false, hadClass = root.classList.contains('registered-lab-panel');
    var shell = node('section', undefined, 'lab-panel-shell');
    var prefix = 'registered-lab-' + (++sequence);
    root.classList.add('registered-lab-panel');

    function node(tag, text, className) {
      var item = doc.createElement(tag);
      if (text !== undefined) item.textContent = text;
      if (className) item.className = className;
      return item;
    }
    function record(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
    function text(value) {
      if (typeof value === 'number' && Number.isFinite(value)) return String(value);
      if (typeof value !== 'string' || !value.trim()) return 'Unknown';
      return value.length > 200 ? value.slice(0, 199) + '…' : value;
    }
    function identity(value) { return typeof value === 'string' && value.trim().length > 0 && value.length <= 512; }
    function revision(value) { return identity(value) || (Number.isSafeInteger(value) && value >= 0); }
    function enumLabel(value, labels) { return typeof value === 'string' && Object.prototype.hasOwnProperty.call(labels, value) ? labels[value] : 'Unknown'; }
    function observation(value) { return enumLabel(value, {running: 'Running', stopped: 'Stopped', unknown: 'Unknown'}); }
    function targetValid(target) {
      return record(target) && identity(target.ref) && revision(target.revision) && identity(target.source) && identity(target.node) &&
        (target.kind === 'qemu' || target.kind === 'lxc') &&
        ((Number.isSafeInteger(target.vmid) && target.vmid > 0) || (typeof target.vmid === 'string' && /^[1-9][0-9]{0,15}$/.test(target.vmid)));
    }
    function clearListeners() {
      generation++;
      listeners.forEach(function (entry) { entry[0].removeEventListener('click', entry[1]); });
      listeners = [];
    }
    function allowed(action) {
      try { return typeof onAction === 'function' && typeof canAct === 'function' && canAct(action) === true; } catch (_) { return false; }
    }
    function refreshAllowed(loading) {
      if (loading || typeof onRefresh !== 'function') return false;
      try { return canRefresh === undefined || (typeof canRefresh === 'function' && canRefresh() === true); } catch (_) { return false; }
    }
    function ownedCurrent(button, version) {
      return current() && version === generation && !button.disabled && shell.parentNode === root && shell.contains(button);
    }
    function control(label, enabled, callback) {
      var button = node('button', label, 'fleet-btn lab-power-button');
      var version = generation;
      button.type = 'button';
      button.disabled = !enabled;
      button.title = enabled ? label : 'Unavailable for the current registration';
      button.setAttribute('aria-describedby', prefix + '-status');
      if (!enabled) button.dataset.actionUnavailable = 'true';
      var handler = function (event) {
        if (!event.isTrusted || !ownedCurrent(button, version)) return;
        callback(button, version);
      };
      button.addEventListener('click', handler);
      listeners.push([button, handler]);
      return button;
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      clearListeners();
      shell.replaceChildren();
      shell.remove();
      if (!hadClass) root.classList.remove('registered-lab-panel');
    }
    function current() {
      if (disposed) return false;
      var valid = root.isConnected && root.parentNode === parent && root.ownerDocument === doc;
      try { valid = valid && typeof isCurrent === 'function' && isCurrent() === true; } catch (_) { valid = false; }
      if (!valid) dispose();
      return valid;
    }
    function fields(values) {
      var list = node('dl', undefined, 'lab-fields');
      values.forEach(function (entry) { list.append(node('dt', entry[0]), node('dd', text(entry[1]))); });
      return list;
    }
    function card(title, attribute) {
      var box = node('section', undefined, 'lab-card');
      box.setAttribute(attribute, '');
      box.append(node('h3', title));
      return box;
    }
    function render(input) {
      if (!current()) return false;
      // Clear before each transition: loading/failure/replacement cannot retain
      // prior registration identity, acknowledgement, or task observations.
      clearListeners();
      shell.replaceChildren();
      var model = record(input) ? input : {};
      var registration = enumLabel(model.registrationState, {
        loading: 'Loading registration', ready: 'Registration received', none: 'No registered lab target',
        unavailable: 'Registration unavailable', expired: 'Registration expired'
      });
      var target = ['ready', 'expired'].includes(model.registrationState) && targetValid(model.target) ? model.target : null;
      var header = node('header', undefined, 'lab-panel-header');
      var heading = node('div');
      heading.append(node('span', 'REGISTERED LAB', 'lab-eyebrow'), node('h2', 'Registered lab power'));
      var headerControls = node('div', undefined, 'lab-header-controls');
      var loading = model.loading === true;
      var refresh = control('Refresh status', refreshAllowed(loading), function (button, version) {
        if (!refreshAllowed(loading)) { button.disabled = true; return; }
        if (ownedCurrent(button, version)) onRefresh();
      });
      refresh.classList.add('lab-refresh-button');
      headerControls.append(node('span', target ? 'Registered target' : registration, 'lab-registration-state'), refresh);
      header.append(heading, headerControls);
      var status = node('p', undefined, 'lab-panel-status');
      status.id = prefix + '-status';
      status.setAttribute('role', 'status');
      var cards = node('div', undefined, 'lab-card-grid');
      var targetCard = card('Registered target', 'data-lab-target');
      if (target) {
        targetCard.append(node('h4', text(target.name), 'lab-target-name'));
        var targetFields = [
          ['Source', target.source], ['Node', target.node], ['Kind', target.kind === 'qemu' ? 'QEMU virtual machine' : 'LXC container'],
          ['VMID', target.vmid],
          ['Current guest observation', observation(target.state)], ['Guest observed at', target.observedAt]
        ];
        if (typeof target.estate === 'string' && target.estate.trim()) targetFields.push(['Estate', target.estate]);
        if (typeof target.expiresAt === 'string' && target.expiresAt.trim()) targetFields.push(['Registration expires at', target.expiresAt]);
        targetCard.append(fields(targetFields));
      } else {
        targetCard.append(node('p', model.registrationState === 'ready' ? 'Registration has no complete supported target identity.' : registration, 'lab-empty'));
      }
      var controls = node('div', undefined, 'lab-power-actions');
      var anyAction = false;
      [['Start', 'start'], ['Shut down', 'shutdown']].forEach(function (entry) {
        var action = entry[1];
        var enabled = !!target && model.registrationState === 'ready' && allowed(action);
        anyAction = anyAction || enabled;
        controls.append(control(entry[0], enabled, function (button, version) {
          if (!target || model.registrationState !== 'ready' || !allowed(action)) { button.disabled = true; return; }
          if (ownedCurrent(button, version)) onAction(action);
        }));
      });
      status.textContent = anyAction ? 'Actions apply only to this registered lab guest.' :
        (typeof model.notice === 'string' && model.notice.trim() ? text(model.notice) :
          (target ? 'Power controls are unavailable for this registered lab target.' : 'No current registered lab target is available.'));
      targetCard.append(controls);
      var operationCard = card('Operation facts', 'data-lab-operation');
      var operation = record(model.operation) ? model.operation : null;
      var matches = target && operation && identity(operation.ref) && operation.targetRef === target.ref &&
        operation.registrationRevision === target.revision;
      if (matches) {
        operationCard.append(fields([
          ['Operation reference', operation.ref],
          ['Requested action', enumLabel(operation.action, {start: 'Start', shutdown: 'Shut down'})],
          ['Operation phase', enumLabel(operation.phase, {admitting: 'Admitting', submitted: 'Submitted', tracking: 'Tracking', terminal: 'Terminal', unknown: 'Unknown'})],
          ['Submission acknowledgement', enumLabel(operation.ack, {pending: 'Pending', acknowledged: 'Acknowledged', not_submitted: 'Not submitted', unknown: 'Unknown'})],
          ['Provider task observation', enumLabel(operation.taskState, {not_observed: 'Not observed', running: 'Running', success: 'Success', failed: 'Failed', unknown: 'Unknown'})],
          ['Operation guest observation', observation(operation.observedState)],
          ['Operation observed at', operation.observedAt]
        ]));
        operationCard.append(node('p', 'Submission status, provider task state and guest observations are reported separately.', 'lab-fact-note'));
      } else {
        operationCard.append(node('p', 'No operation facts for the current registration.', 'lab-empty'));
        operationCard.append(node('p', 'Operation details are shown for the current selection.', 'lab-fact-note'));
      }
      cards.append(targetCard, operationCard);
      shell.append(header, status, cards);
      if (shell.parentNode !== root) root.append(shell);
      return true;
    }
    render({registrationState: 'loading'});
    return {render: render, dispose: dispose};
  }
  global.FreqRegisteredLabPanel = {create: create};
})(window);
