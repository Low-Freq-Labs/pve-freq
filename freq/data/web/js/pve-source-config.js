(function (global) {
  'use strict';

  function create(options) {
    var root = options.root, doc = root.ownerDocument;
    var disposed = false, generation = 0, revision = 0;
    var controller = null, timer = null, busy = false, configured = false, pendingPayload = null;
    var inputs = [], form = null;
    function node(tag, text) {
      var element = doc.createElement(tag);
      if (text !== undefined) element.textContent = text;
      return element;
    }
    var heading = node('h2', 'PVE source configuration');
    var explanation = node('p', 'Use a read-only PVE API token and a trusted HTTPS certificate. Saving a source does not verify its connection; refresh inventory to check it.');
    var status = node('p', 'Refresh to inspect saved configuration.');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    var refresh = node('button', 'Refresh source configuration');
    refresh.className = 'fleet-btn';
    refresh.type = 'button';
    var content = node('div');
    root.append(heading, explanation, refresh, status, content);

    function current() {
      if (disposed) return false;
      try { return options.isCurrent() === true; } catch (_) { return false; }
    }
    function clearFields() {
      inputs.forEach(function (input) { input.value = ''; });
    }
    function stop() {
      if (timer !== null) { global.clearTimeout(timer); timer = null; }
      if (controller) { controller.abort(); controller = null; }
      if (pendingPayload) {
        pendingPayload.token_secret = '';
        pendingPayload.ca_pem = '';
        pendingPayload = null;
      }
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      generation++;
      stop();
      clearFields();
      root.replaceChildren();
      inputs = [];
      form = null;
    }
    function available() {
      if (current()) return true;
      dispose();
      return false;
    }
    function safeState(data) {
      if (!data || !Array.isArray(data.addresses) || data.addresses.length > 8 ||
          !data.addresses.every(function (address) { return typeof address === 'string' && address.length > 0 && address.length <= 253; }) ||
          !(data.token_principal === null || typeof data.token_principal === 'string') ||
          typeof data.ca_configured !== 'boolean') throw Error('invalid_response');
      return {addresses: data.addresses.slice(), token_principal: data.token_principal, ca_configured: data.ca_configured};
    }
    function setBusy(value) {
      busy = value;
      root.setAttribute('aria-busy', String(value));
      refresh.disabled = value;
      if (form) Array.from(form.elements).forEach(function (input) { input.disabled = value; });
    }
    function field(labelText, tag, type) {
      var label = node('label', labelText);
      var input = node(tag);
      if (type) input.type = type;
      input.autocomplete = 'off';
      input.spellcheck = false;
      label.append(input);
      form.append(label);
      inputs.push(input);
      input.addEventListener('input', function () { revision++; });
      return input;
    }
    function render(data) {
      clearFields();
      inputs = [];
      form = null;
      content.replaceChildren();
      configured = data.addresses.length > 0;
      if (configured) {
        content.append(node('p', 'PVE sources are configured. This interface cannot update or delete them.'));
        var list = node('ul');
        data.addresses.forEach(function (address) { list.append(node('li', address)); });
        content.append(list, node('p', 'Token principal: ' + (data.token_principal || 'Unknown')),
          node('p', 'Trusted CA certificate: ' + (data.ca_configured ? 'Configured' : 'Not configured')));
        return;
      }
      content.append(node('p', 'No PVE sources are configured. Add up to eight unique DNS names or IP addresses.'));
      form = node('form');
      form.autocomplete = 'off';
      var addresses = field('PVE addresses', 'textarea');
      addresses.required = true;
      addresses.rows = 3;
      var tokenId = field('API token ID', 'input', 'text');
      tokenId.required = true;
      var secret = field('API token secret', 'input', 'password');
      secret.required = true;
      var ca = field('Trusted CA certificate (optional)', 'textarea');
      ca.rows = 4;
      var submit = node('button', 'Save PVE source configuration');
      submit.className = 'fleet-btn';
      submit.type = 'submit';
      form.append(submit);
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        if (!available() || busy || configured) return;
        var values = addresses.value.split(/[\n,]/).map(function (value) { return value.trim(); }).filter(Boolean);
        if (!values.length || values.length > 8 || new Set(values).size !== values.length ||
            values.some(function (value) { return value.length > 253 || /[\s/?#@]/.test(value); }) ||
            !tokenId.value.trim() || !secret.value) {
          status.textContent = 'Enter one to eight unique PVE DNS names or IP addresses, an API token ID and its secret.';
          return;
        }
        var payload = {addresses: values, token_id: tokenId.value.trim(), token_secret: secret.value};
        if (ca.value.trim()) payload.ca_pem = ca.value.trim();
        // Remove the write-only secret before any asynchronous response can arrive.
        secret.value = '';
        send('POST', payload);
      });
      content.append(form);
    }
    function failure(error) {
      var code = error && error.message;
      if (code === '409' || code === 'configured' || code === 'already_configured' || code === 'conflict') {
        configured = true;
        clearFields();
        content.replaceChildren(node('p', 'Configuration already exists. Refresh to inspect its saved state.'));
        form = null;
        inputs = [];
        return 'Configuration already exists. Refresh to inspect its saved state.';
      }
      return 'Source configuration could not be confirmed. Refresh to inspect saved state before trying again.';
    }
    function send(method, payload) {
      if (!available() || busy) return Promise.resolve();
      stop();
      pendingPayload = payload;
      var mine = ++generation, draft = revision;
      var abort = new global.AbortController();
      controller = abort;
      setBusy(true);
      status.textContent = method === 'POST' ? 'Saving source configuration…' : 'Reading source configuration…';
      function owned() { return mine === generation && !abort.signal.aborted && available(); }
      timer = global.setTimeout(function () {
        if (!owned()) return;
        generation++;
        stop();
        setBusy(false);
        clearFields();
        // A timed-out POST may have committed. Remove create until a GET resolves it.
        if (method === 'POST') {
          content.replaceChildren(); form = null; inputs = [];
        }
        status.textContent = 'The request timed out. Refresh to inspect saved configuration.';
      }, 20000);
      return Promise.resolve().then(function () {
        if (!owned()) return null;
        return options.request(method, payload, abort.signal);
      }).then(function (data) {
        if (!owned()) return;
        if (revision !== draft) {
          stop();
          setBusy(false);
          clearFields();
          content.replaceChildren(); form = null; inputs = [];
          status.textContent = 'The draft changed during the request. Refresh to inspect saved configuration.';
          return;
        }
        if (method === 'POST' && (!data || data.ok !== true)) throw Error('invalid_response');
        var safe = safeState(data);
        if (method === 'POST' && !safe.addresses.length) throw Error('invalid_response');
        stop();
        setBusy(false);
        render(safe);
        status.textContent = method === 'POST' ? 'Configuration saved. Inventory is being refreshed to check the PVE connection.' : 'Saved configuration loaded. Refresh inventory to check the PVE connection.';
        if (method === 'POST' && typeof options.onSaved === 'function') {
          try { options.onSaved(); } catch (_) { /* Never display raw callback errors. */ }
        }
      }).catch(function (error) {
        if (!owned()) return;
        stop();
        setBusy(false);
        clearFields();
        status.textContent = failure(error);
        if (method === 'POST' && form) {
          content.replaceChildren(); form = null; inputs = [];
        }
      }).finally(function () {
        if (payload) { payload.token_secret = ''; payload.ca_pem = ''; }
      });
    }
    function load() {
      if (!available()) return Promise.resolve();
      if (busy) return Promise.resolve();
      return send('GET', null);
    }
    refresh.addEventListener('click', load);
    return Object.freeze({load: load, dispose: dispose});
  }
  global.FreqPveSourceConfig = Object.freeze({create: create});
})(globalThis);
