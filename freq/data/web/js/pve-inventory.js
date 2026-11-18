(function (global) {
  'use strict';
  var instances = 0;

  // The parent owns authenticated transport and normalizes observed provider data.
  function create(options) {
    var root = options.root, doc = root.ownerDocument, prefix = 'pve-cockpit-' + (++instances);
    var generation = 0, disposed = false, controller = null, timer = null;
    var knownHosts = [], groups = [], activeButton = null, nextId = 0;
    var section = element('section', undefined, 'pve-inventory pve-cockpit');
    var content = element('div', undefined, 'pve-inventory-hosts');
    var details = element('section', undefined, 'pve-inventory-details cockpit-detail');
    var summary = element('p', 'Refresh inventory to read configured PVE endpoints.', 'pve-inventory-status');
    var filterSummary = element('p', 'No current inventory rows to filter.', 'pve-inventory-filter-summary');
    var filter = element('input'), refresh = button('Refresh inventory', load, 'pve-inventory-refresh');

    function element(tag, text, className) {
      var result = doc.createElement(tag);
      if (text !== undefined) result.textContent = String(text);
      if (className) result.className = className;
      return result;
    }
    function value(input) {
      return input === null || input === undefined || input === '' ? 'Unknown' : String(input);
    }
    function time(input) {
      return typeof input === 'string' && Number.isFinite(Date.parse(input)) ? new Date(input).toLocaleString() : 'Unknown';
    }
    function state(input) {
      return ({observed: 'Observed', partial: 'Partial', unavailable: 'Unavailable', unknown: 'Unknown'})[input] || 'Unknown';
    }
    function current() {
      if (disposed) return false;
      try { return options.isCurrent() === true; } catch (_) { return false; }
    }
    function stop() {
      if (timer !== null) { global.clearTimeout(timer); timer = null; }
      if (controller) { controller.abort(); controller = null; }
    }
    function dispose() {
      if (disposed) return;
      disposed = true; generation++; stop(); knownHosts = []; groups = [];
      if (section.parentNode === root) section.remove();
    }
    function available() {
      if (current()) return true;
      dispose(); return false;
    }
    function button(label, action, className) {
      var result = element('button', label, 'fleet-btn ' + (className || ''));
      result.type = 'button';
      if (action) result.addEventListener('click', function () { if (available()) action(); });
      return result;
    }
    function disabled(label) {
      var result = button(label, null, 'cockpit-action');
      result.disabled = true;
      result.dataset.actionUnavailable = '';
      result.title = 'Unavailable in this preview';
      return result;
    }
    function badge(text, className) {
      return element('span', value(text), 'cockpit-badge ' + (className || ''));
    }
    function statusBadge(status) {
      var result = badge(status, 'cockpit-status');
      // Color only a literal provider-reported status; never infer host health.
      if (status === 'running' || status === 'online') result.classList.add('cockpit-status-running');
      if (status === 'stopped' || status === 'offline') result.classList.add('cockpit-status-stopped');
      return result;
    }
    function metric(label, input) {
      var result = element('div', undefined, 'pve-node-stat');
      result.append(element('span', label), element('strong', value(input)));
      return result;
    }
    function fields(rows) {
      var list = element('dl', undefined, 'pve-inventory-fields');
      rows.forEach(function (row) { list.append(element('dt', row[0]), element('dd', value(row[1]))); });
      return list;
    }
    function actionbar() {
      var bar = element('div', undefined, 'cockpit-actionbar');
      ['Power', 'Start', 'Stop', 'Reboot', 'Open shell', 'IP controls'].forEach(function (label) { bar.append(disabled(label)); });
      return bar;
    }
    function clearDetails() {
      if (activeButton) activeButton.setAttribute('aria-expanded', 'false');
      activeButton = null;
      var prompt = element('div', undefined, 'cockpit-detail-prompt');
      prompt.append(element('span', 'RESOURCE COCKPIT', 'cockpit-eyebrow'),
        element('h3', 'Select a node, VM or container'),
        element('p', 'Open a resource to inspect its reported configuration and available workspaces.'));
      details.replaceChildren(prompt);
    }
    function showDetails(trigger, name, rows, kind, entry) {
      if (!available()) return;
      if (activeButton) activeButton.setAttribute('aria-expanded', 'false');
      activeButton = trigger; trigger.setAttribute('aria-expanded', 'true');
      var head = element('div', undefined, 'cockpit-detail-head');
      var title = element('h3', name); title.tabIndex = -1;
      head.append(badge(kind.toUpperCase()), title, statusBadge(entry.status));
      var close = button('Close details', function () {
        clearDetails();
        if (trigger.isConnected && !trigger.closest('[hidden]')) trigger.focus();
      }, 'cockpit-detail-close'); head.append(close);
      var tabs = element('div', undefined, 'cockpit-tabs'), panel = element('div', undefined, 'cockpit-tab-panel');
      tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Resource details');
      panel.id = prefix + '-panel-' + (++nextId); panel.setAttribute('role', 'tabpanel'); panel.tabIndex = 0;
      var choices = [], names = ['Overview', 'Console', 'Network', 'Hardware', 'Snapshots', 'Backups'];
      function select(index, focus) {
        if (!available()) return;
        choices.forEach(function (tab, position) {
          tab.setAttribute('aria-selected', String(index === position)); tab.tabIndex = index === position ? 0 : -1;
        });
        var tab = choices[index], label = names[index];
        panel.setAttribute('aria-labelledby', tab.id);
        panel.replaceChildren();
        if (label === 'Overview') panel.append(fields(rows));
        else if (label === 'Hardware') {
          panel.append(fields([['CPU', entry.cpu], ['CPU count', entry.maxcpu], ['Memory', entry.memory], ['Disk', entry.disk]]),
            element('p', 'Hardware changes are unavailable.'), disabled('Edit hardware'));
        } else if (label === 'Network') {
          var addresses = Array.isArray(entry.addresses) && entry.addresses.length ? entry.addresses.join(', ') : null;
          panel.append(fields([['Reported addresses', addresses], ['Node', entry.node]]),
            element('p', 'Network configuration is unavailable.'), disabled('Edit network'));
        } else if (label === 'Console') {
          var terminal = element('div', undefined, 'cockpit-console');
          terminal.append(element('span', 'CONSOLE', 'cockpit-eyebrow'), element('p', 'No console session is connected.'));
          panel.append(terminal, disabled('Connect console'));
        } else {
          panel.append(element('h4', label), element('p', label + ' have not been read. This workspace is unavailable.'),
            disabled(label === 'Snapshots' ? 'Create snapshot' : 'Create backup'));
        }
        if (focus) tab.focus();
      }
      names.forEach(function (name, index) {
        var tab = button(name, function () { select(index, false); }, 'cockpit-tab');
        tab.id = prefix + '-tab-' + (++nextId); tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', panel.id);
        tab.addEventListener('keydown', function (event) {
          var target = event.key === 'ArrowRight' ? (index + 1) % names.length : event.key === 'ArrowLeft' ? (index + names.length - 1) % names.length : event.key === 'Home' ? 0 : event.key === 'End' ? names.length - 1 : null;
          if (target === null) return;
          event.preventDefault(); select(target, true);
        });
        choices.push(tab); tabs.append(tab);
      });
      details.replaceChildren(head, actionbar(), element('p', 'Power, shell and configuration actions are unavailable.', 'cockpit-unavailable'), tabs, panel);
      select(0, false); title.focus();
    }
    function detailButton(name, rows, kind, entry) {
      var trigger = button('Details for ' + name, function () { showDetails(trigger, name, rows, kind, entry); }, 'pve-inventory-details-button');
      trigger.setAttribute('aria-expanded', 'false');
      return trigger;
    }
    function rowSearch(values) { return values.map(function (input) { return input == null ? '' : String(input); }).join(' ').toLowerCase(); }
    function guestCard(host, guest) {
      var name = value(guest.name || guest.vmid), card = element('article', undefined, 'pve-workload-row cockpit-workload');
      card.dataset.inventoryKind = 'guest';
      card.dataset.inventorySearch = rowSearch([guest.name, guest.node, guest.vmid, guest.type]);
      var head = element('div', undefined, 'cockpit-workload-head');
      head.append(badge(guest.type === 'qemu' ? 'VM' : guest.type === 'lxc' ? 'LXC' : value(guest.type)), statusBadge(guest.status));
      if (guest.template === true) head.append(badge('Template'));
      var trigger = detailButton(name, [
        ['Source', host.label], ['Endpoint', host.endpoint], ['Guest', guest.name], ['ID', guest.vmid],
        ['Type', guest.type], ['Node', guest.node], ['Status', guest.status], ['CPU', guest.cpu],
        ['Memory', guest.memory], ['Disk', guest.disk], ['CPU count', guest.maxcpu], ['Uptime', guest.uptime],
        ['Observed', time(host.observedAt)]
      ], guest.type === 'lxc' ? 'container' : 'virtual machine', guest);
      trigger.classList.add('cockpit-resource-link');
      var identity = element('div', undefined, 'cockpit-workload-identity');
      identity.append(element('h4', name, 'pve-workload-name'), element('span', 'ID ' + value(guest.vmid) + ' · ' + value(guest.node)));
      var metrics = element('div', undefined, 'cockpit-workload-metrics');
      metrics.append(metric('CPU', guest.cpu), metric('MEMORY', guest.memory));
      var actions = element('div', undefined, 'cockpit-workload-actions');
      actions.append(trigger, disabled('Console'), disabled('Power'));
      card.append(head, identity, metrics, actions);
      return card;
    }
    function nodeGroup(host, entry, guests, orphanName) {
      var group = element('section', undefined, 'pve-group pve-expanded cockpit-node-group');
      group.dataset.cockpitNode = entry ? value(entry.node || entry.name) : '';
      if (!entry) group.dataset.cockpitOrphan = 'true';
      var shell = element('div', undefined, 'pve-node-shell'), main = element('div', undefined, 'pve-node-main');
      var name = entry ? value(entry.name || entry.node) : 'Unreported node: ' + value(orphanName);
      var identity = element('div', undefined, 'pve-node-id');
      identity.append(element('span', entry ? 'PVE NODE' : 'UNASSOCIATED GUESTS', 'cockpit-eyebrow'), element('h3', name));
      var meta = element('div', undefined, 'host-meta');
      meta.append(badge(host.label), entry ? statusBadge(entry.status) : badge('Metrics unavailable'));
      identity.append(meta); main.append(identity);
      if (entry) {
        shell.dataset.inventoryKind = 'node';
        shell.dataset.inventorySearch = rowSearch([entry.name, entry.node, entry.id]);
        var actions = element('div', undefined, 'pve-node-card-actions');
        actions.append(detailButton(value(entry.name || entry.node), [
          ['Source', host.label], ['Endpoint', host.endpoint], ['Node', entry.name || entry.node], ['ID', entry.id],
          ['Status', entry.status], ['CPU', entry.cpu], ['Memory', entry.memory], ['Disk', entry.disk],
          ['Uptime', entry.uptime], ['Observed', time(host.observedAt)]
        ], 'node', entry), disabled('Open shell'));
        main.append(actions);
      }
      var counts = element('div', undefined, 'pve-node-summary');
      counts.append(metric('GUEST ROWS', guests.length), metric('VIRTUAL MACHINES', guests.filter(function (guest) { return guest.type === 'qemu'; }).length),
        metric('CONTAINERS', guests.filter(function (guest) { return guest.type === 'lxc'; }).length));
      main.append(counts);
      var metrics = element('div', undefined, 'pve-node-metrics');
      ['cpu', 'memory', 'disk', 'uptime'].forEach(function (key) { metrics.append(metric(key.toUpperCase(), entry ? entry[key] : null)); });
      main.append(metrics); shell.append(main);
      var workloads = element('div', undefined, 'pve-vms'), grid = element('div', undefined, 'cockpit-workload-grid');
      workloads.id = prefix + '-guests-' + (++nextId);
      var toolbar = element('div', undefined, 'pve-node-actions');
      var toggle = button('Collapse guests for ' + name, function () {
        workloads.hidden = !workloads.hidden;
        toggle.setAttribute('aria-expanded', String(!workloads.hidden));
        toggle.textContent = (workloads.hidden ? 'Expand' : 'Collapse') + ' guests for ' + name;
        group.classList.toggle('pve-expanded', !workloads.hidden);
        if (workloads.hidden && activeButton && workloads.contains(activeButton)) clearDetails();
        applyFilter();
      }, 'pve-node-toggle');
      toggle.setAttribute('aria-expanded', 'true'); toggle.setAttribute('aria-controls', workloads.id);
      toolbar.append(toggle, element('span', 'Counts reflect returned source rows.', 'cockpit-muted'));
      var bar = element('div', undefined, 'pve-workload-bar');
      bar.append(element('span', 'Virtual machines & containers'), disabled('Create guest'));
      guests.forEach(function (guest) { grid.append(guestCard(host, guest)); });
      workloads.append(bar, grid);
      if (!guests.length) workloads.append(element('p', 'No guest rows were returned for this node.', 'cockpit-empty'));
      group.append(shell, toolbar, workloads);
      groups.push({root: group, shell: shell, workloads: workloads, toggle: toggle, name: name, source: rowSearch([host.label, host.endpoint]), entry: entry});
      return group;
    }
    function applyFilter(expand) {
      if (!available()) return;
      var query = filter.value.trim().toLowerCase(), shown = {node: 0, guest: 0}, total = {node: 0, guest: 0};
      groups.forEach(function (group) {
        var sourceMatch = group.source.includes(query), matched = false;
        if (query && expand) {
          group.workloads.hidden = false;
          group.toggle.setAttribute('aria-expanded', 'true');
          group.toggle.textContent = 'Collapse guests for ' + group.name;
          group.root.classList.add('pve-expanded');
        }
        group.root.querySelectorAll('[data-inventory-kind]').forEach(function (row) {
          var kind = row.dataset.inventoryKind;
          total[kind]++;
          row.hidden = !sourceMatch && !row.dataset.inventorySearch.includes(query);
          if (!row.hidden) { if (kind === 'node' || !group.workloads.hidden) shown[kind]++; matched = true; }
        });
        // Keep the observed node's header as context for matching guest cards.
        if (group.entry && matched && group.shell.hidden) { group.shell.hidden = false; shown.node++; }
        group.root.hidden = !!query && !matched;
      });
      if (activeButton && activeButton.closest('[hidden]')) clearDetails();
      filterSummary.textContent = total.node + total.guest === 0 ? 'No current inventory rows to filter. See the source status below.' :
        'Showing ' + shown.guest + ' of ' + total.guest + ' guest rows and ' + shown.node + ' of ' + total.node + ' node rows.' +
        (query && shown.node + shown.guest === 0 ? ' No inventory rows match this filter. Source status remains visible below.' : '');
    }
    function renderHosts(hosts, pending) {
      clearDetails(); groups = []; content.replaceChildren();
      hosts.forEach(function (host) {
        var box = element('section', undefined, 'pve-inventory-host cockpit-source');
        var head = element('div', undefined, 'cockpit-source-head');
        head.append(element('h3', value(host.label)), badge(pending ? 'Reading' : state(host.state)));
        box.append(head, element('p', 'Endpoint: ' + value(host.endpoint), 'cockpit-muted'));
        if (pending) box.append(element('p', 'Waiting for a current observation.'));
        else {
          box.append(element('p', 'Observed: ' + time(host.observedAt), 'cockpit-muted'));
          if (host.error) box.append(element('p', host.error, 'pve-inventory-error'));
          box.append(detailButton(value(host.label), [['Source', host.label], ['Endpoint', host.endpoint], ['Observation', state(host.state)], ['Observed', time(host.observedAt)]], 'source', host));
          var byNode = new Map();
          host.guests.forEach(function (guest) {
            var key = typeof guest.node === 'string' ? guest.node : '';
            if (!byNode.has(key)) byNode.set(key, []);
            byNode.get(key).push(guest);
          });
          host.nodes.forEach(function (entry) {
            var key = typeof entry.node === 'string' ? entry.node : entry.name;
            box.append(nodeGroup(host, entry, byNode.get(key) || [], null)); byNode.delete(key);
          });
          byNode.forEach(function (guests, name) { box.append(nodeGroup(host, null, guests, name)); });
          if (!host.nodes.length && !host.guests.length) box.append(element('p', host.state === 'observed' ? 'No node or guest rows were returned by this endpoint.' : 'Node and guest inventory is unavailable.', 'cockpit-empty'));
        }
        content.append(box);
      });
      applyFilter();
    }
    function validate(report) {
      if (!report || !['observed', 'partial', 'unavailable', 'unknown'].includes(report.state) || !Array.isArray(report.hosts)) throw Error('Invalid report');
      report.hosts.forEach(function (host) {
        if (!host || typeof host.id !== 'string' || typeof host.label !== 'string' || typeof host.endpoint !== 'string' ||
            !Array.isArray(host.nodes) || !Array.isArray(host.guests) ||
            !host.nodes.every(function (item) { return item && typeof item === 'object'; }) ||
            !host.guests.every(function (item) { return item && typeof item === 'object'; })) throw Error('Invalid host');
      });
      return report;
    }
    function failed() {
      refresh.disabled = false; section.setAttribute('aria-busy', 'false'); root.dataset.state = 'unavailable';
      summary.textContent = 'Inventory unavailable. Check the connection and refresh to try again. Previous observations have been cleared.';
      renderHosts(knownHosts.map(function (host) { return {id: host.id, label: host.label, endpoint: host.endpoint, state: 'unavailable', nodes: [], guests: []}; }), false);
    }
    function load() {
      if (!available()) return Promise.resolve();
      stop();
      var mine = ++generation, abort = new global.AbortController(); controller = abort;
      refresh.disabled = true; section.setAttribute('aria-busy', 'true'); root.dataset.state = 'loading';
      summary.textContent = 'Loading inventory. Previous observations have been cleared.';
      renderHosts(knownHosts, true);
      function owned() { return mine === generation && !abort.signal.aborted && available(); }
      timer = global.setTimeout(function () {
        if (!owned()) return;
        generation++; stop(); failed();
      }, 20000);
      return Promise.resolve().then(function () { if (owned()) return options.request(abort.signal); }).then(function (input) {
        if (!owned()) return;
        var report = validate(input);
        knownHosts = report.hosts.map(function (host) { return {id: host.id, label: host.label, endpoint: host.endpoint}; });
        stop(); refresh.disabled = false; section.setAttribute('aria-busy', 'false');
        root.dataset.state = report.state === 'observed' ? (report.hosts.length ? 'ready' : 'empty') : report.state === 'partial' ? 'partial' : 'unavailable';
        var copy = {observed: 'Inventory observed.', partial: 'Some inventory is unavailable. Available observations are shown below.', unavailable: 'Inventory unavailable. Configured endpoints are shown below.', unknown: 'Inventory status is unknown.'}[report.state];
        if (!report.hosts.length) copy = report.state === 'observed' ? 'No PVE endpoints are configured. Add a host to begin.' : 'Configured endpoints could not be read. Refresh to try again.';
        summary.textContent = copy + ' Observed: ' + time(report.observedAt) + '.';
        renderHosts(report.hosts, false);
      }).catch(function () { if (owned()) { stop(); failed(); } });
    }

    section.setAttribute('aria-label', 'PVE inventory');
    var header = element('div', undefined, 'pve-inventory-header');
    var title = element('div'); title.append(element('span', 'INFRASTRUCTURE / PVE', 'cockpit-eyebrow'), element('h2', 'PVE inventory'));
    header.append(title, refresh);
    if (options.mode === 'overview') {
      section.classList.add('cockpit-overview');
      if (typeof options.onNavigate === 'function') header.append(button('Open Fleet', function () { options.onNavigate('fleet'); }));
    }
    summary.setAttribute('role', 'status'); summary.setAttribute('aria-live', 'polite'); summary.setAttribute('aria-atomic', 'true');
    filterSummary.setAttribute('aria-live', 'polite');
    var filterLabel = element('label', 'Filter inventory', 'pve-inventory-filter');
    filter.type = 'search'; filter.placeholder = 'Source, node, guest name, VMID or type';
    filterLabel.append(filter); filter.addEventListener('input', applyFilter);
    details.dataset.inventoryDetail = ''; details.setAttribute('aria-label', 'Inventory details');
    clearDetails(); section.append(header, summary, filterLabel, filterSummary, details, content); root.append(section);
    return Object.freeze({load: load, dispose: dispose});
  }
  global.FreqPveInventory = Object.freeze({create: create});
})(globalThis);
