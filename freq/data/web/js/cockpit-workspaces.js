(function (global) {
  'use strict';

  // Intended management surfaces only. Provider observations live in Fleet.
  // This module never fetches, invokes legacy handlers, or grants a write action.
  var sequence = 0;
  function create(options) {
    var root = options.root, doc = root.ownerDocument, disposed = false;
    var aliases = {network: 'topology', switch: 'topology', storage: 'nas', truenas: 'nas', 'pve-firewall': 'security', system: 'tools'};
    var view = aliases[options.view] || options.view;
    var prefix = 'cockpit-workspace-' + (++sequence);
    var shell = element('section', undefined, 'cockpit-workspace');
    var listeners = [];
    root.dataset.cockpitWorkspace = view;
    shell.dataset.workspace = view;

    function element(tag, text, className) {
      var item = doc.createElement(tag);
      if (text !== undefined) item.textContent = text;
      if (className) item.className = className;
      return item;
    }
    function dispose() {
      if (disposed) return;
      disposed = true;
      listeners.forEach(function (entry) { entry[0].removeEventListener('click', entry[1]); });
      listeners = [];
      if (shell.parentNode === root) shell.remove();
      if (root.dataset.cockpitWorkspace === view && !root.querySelector('.cockpit-workspace')) delete root.dataset.cockpitWorkspace;
    }
    function current() {
      var valid = !disposed;
      try { if (options.isCurrent) valid = valid && options.isCurrent() === true; } catch (_) { valid = false; }
      if (!valid) dispose();
      return valid;
    }
    function listen(target, action) {
      var handler = function () { if (current()) action(); };
      target.addEventListener('click', handler);
      listeners.push([target, handler]);
    }
    function action(label) {
      var button = element('button', label, 'fleet-btn cockpit-action');
      button.type = 'button';
      button.disabled = true;
      button.title = 'Not connected yet';
      button.dataset.actionUnavailable = 'true';
      button.setAttribute('aria-describedby', prefix + '-status');
      return button;
    }
    function actions(labels) {
      var bar = element('div', undefined, 'cockpit-actions');
      labels.forEach(function (label) { bar.append(action(label)); });
      return bar;
    }
    function panel(title, subtitle) {
      var box = element('section', undefined, 'section cockpit-panel');
      var heading = element('div', undefined, 'section-header');
      heading.append(element('h3', title));
      if (subtitle) heading.append(element('span', subtitle, 'cockpit-muted'));
      var body = element('div', undefined, 'section-body');
      box.append(heading, body);
      box.body = body;
      return box;
    }
    function grid() { return element('div', undefined, 'cards cockpit-grid'); }
    function fields(items) {
      var list = element('dl', undefined, 'cockpit-fields');
      items.forEach(function (label) { list.append(element('dt', label), element('dd', '— · Not observed')); });
      return list;
    }
    function table(title, headers, note, labels) {
      var box = panel(title, 'Not observed');
      if (labels) box.body.append(actions(labels));
      var wrap = element('div', undefined, 'cockpit-table-wrap');
      var result = element('table', undefined, 'cockpit-table');
      var caption = element('caption', note, 'cockpit-muted');
      var head = element('thead'), row = element('tr'), body = element('tbody');
      headers.forEach(function (label) { var th = element('th', label); th.scope = 'col'; row.append(th); });
      head.append(row);
      var empty = element('tr'), cell = element('td', '— ' + note, 'cockpit-empty');
      cell.colSpan = headers.length;
      empty.append(cell); body.append(empty); result.append(caption, head, body); wrap.append(result); box.body.append(wrap);
      return box;
    }
    function summary(labels) {
      var bar = element('div', undefined, 'stats cockpit-stats');
      labels.forEach(function (label) {
        var stat = element('div', undefined, 'st');
        stat.append(element('span', label, 'cockpit-stat-label'), element('strong', '—'), element('small', 'Not observed', 'cockpit-muted'));
        bar.append(stat);
      });
      return bar;
    }
    function controlPanel(title, description, labels, details) {
      var box = panel(title, 'Not connected yet');
      box.body.append(element('p', description, 'cockpit-muted'));
      if (details) box.body.append(fields(details));
      box.body.append(actions(labels));
      return box;
    }
    function terminal(title) {
      var box = panel(title, 'No session');
      box.body.append(element('pre', '› Awaiting a connected source\n— No output observed', 'cockpit-terminal'));
      box.body.append(actions(['Open shell', 'Run command', 'Clear output']));
      return box;
    }
    function topology(tab) {
      var content = element('div');
      content.append(summary(['Switches', 'Ports', 'VLANs', 'Links']));
      if (tab === 'Map' || tab === 'Overview') {
        var map = panel('Infrastructure map', 'Topology not observed');
        var surface = element('div', undefined, 'cockpit-map');
        surface.append(element('span', '◇', 'cockpit-map-symbol'), element('h4', 'Network topology'), element('p', 'Switches, hosts and links appear here when their relationships are observed.', 'cockpit-muted'));
        map.body.append(actions(['Discover links', 'Auto layout', 'Export map']), surface);
        content.append(map);
      }
      if (tab === 'Switches' || tab === 'Overview') {
        content.append(table('Switch inventory', ['Switch', 'Address', 'Model', 'Ports', 'State'], 'No switch inventory has been observed.', ['Add switch', 'Refresh switches']));
        var ports = panel('Port configuration', 'Select a connected switch');
        ports.body.append(fields(['Switch', 'Port', 'Link', 'Speed', 'Untagged VLAN', 'Tagged VLANs']), actions(['Enable port', 'Disable port', 'Set VLAN', 'Apply port configuration']));
        content.append(ports);
      }
      if (tab === 'VLANs') content.append(table('VLAN configuration', ['VLAN ID', 'Name', 'Tagged ports', 'Untagged ports', 'State'], 'VLAN membership has not been observed.', ['Create VLAN', 'Edit VLAN', 'Delete VLAN', 'Apply configuration']));
      if (tab === 'Interfaces') content.append(table('Interfaces & IP addresses', ['Interface', 'Node', 'Address', 'Gateway', 'Bridge', 'State'], 'No interface configuration has been observed.', ['Add interface', 'Assign IP', 'Edit bridge', 'Apply network changes']));
      return content;
    }
    function nas(tab) {
      var content = element('div');
      content.append(summary(['Pool capacity', 'Allocated', 'Snapshots', 'Shares']));
      if (tab === 'Pools' || tab === 'Overview') content.append(table('Storage pools', ['Pool', 'Layout', 'Capacity', 'Used', 'Available', 'State'], 'Storage pool information has not been observed.', ['Create pool', 'Import pool', 'Scrub pool']));
      if (tab === 'Datasets' || tab === 'Overview') content.append(table('Datasets & volumes', ['Dataset', 'Pool', 'Used', 'Quota', 'Compression', 'State'], 'No dataset inventory has been observed.', ['Create dataset', 'Create volume', 'Edit quota', 'Permissions']));
      if (tab === 'Shares') content.append(table('Network shares', ['Share', 'Protocol', 'Path', 'Clients', 'State'], 'SMB and NFS shares have not been observed.', ['Create SMB share', 'Create NFS share', 'Edit share', 'Stop share']));
      if (tab === 'Snapshots') content.append(table('Snapshots & replication', ['Snapshot', 'Dataset', 'Created', 'Retention', 'Replication'], 'No snapshot or replication history has been observed.', ['Take snapshot', 'Schedule snapshots', 'Replicate', 'Restore snapshot']));
      content.append(controlPanel('NAS connection', 'Connect a storage source to inspect capacity, datasets, shares and protection.', ['Connect NAS', 'Open NAS shell'], ['Endpoint', 'Connection', 'Last observation']));
      return content;
    }
    function security(tab) {
      var content = element('div');
      content.append(summary(['Firewall state', 'Rules', 'Interfaces', 'NAT entries']));
      if (tab === 'Rules' || tab === 'Overview') content.append(table('Firewall rules', ['Order', 'Action', 'Direction', 'Interface', 'Source', 'Destination', 'Protocol', 'State'], 'No firewall rules have been observed.', ['Add rule', 'Edit rule', 'Move rule', 'Delete rule', 'Apply rules']));
      if (tab === 'Interfaces' || tab === 'Overview') content.append(table('Firewall interfaces', ['Interface', 'Zone', 'Address', 'Policy', 'State'], 'No firewall interfaces have been observed.', ['Assign interface', 'Edit interface', 'Set policy']));
      if (tab === 'NAT') content.append(table('NAT & port forwarding', ['Rule', 'Interface', 'Protocol', 'External port', 'Destination', 'State'], 'NAT configuration has not been observed.', ['Add port forward', 'Edit NAT', 'Delete NAT', 'Apply NAT']));
      if (tab === 'Logs') content.append(terminal('Firewall event log'));
      content.append(controlPanel('Firewall controls', 'Rule changes require an accepted management connection.', ['Enable firewall', 'Disable firewall', 'Validate configuration', 'Export rules']));
      return content;
    }
    function services(tab, media) {
      var content = element('div');
      content.append(summary(media ? ['Media services', 'Libraries', 'Streams', 'Storage'] : ['Containers', 'Images', 'Volumes', 'Networks']));
      if (tab === 'Services' || tab === 'Overview') {
        var cards = grid();
        cards.append(controlPanel(media ? 'Media services' : 'Container services', 'Service names, state and resource use have not been observed.', ['Deploy service', 'Start service', 'Stop service', 'Restart service'], ['Service', 'Host', 'Image', 'State']));
        cards.append(controlPanel(media ? 'Library management' : 'Compose stacks', media ? 'Libraries and scan activity have not been observed.' : 'Compose projects and deployment history have not been observed.', media ? ['Add library', 'Scan library', 'Edit library'] : ['Create stack', 'Edit compose', 'Deploy stack'], media ? ['Library', 'Location', 'Last scan'] : ['Stack', 'Project directory', 'Last deployment']));
        content.append(cards);
      }
      if (tab === 'Containers' || tab === 'Overview') content.append(table('Containers', ['Container', 'Image', 'Host', 'Ports', 'State', 'Resources'], 'No container inventory has been observed.', ['Create container', 'Start', 'Stop', 'Restart', 'Open shell']));
      if (tab === 'Registry') content.append(table('Image registry', ['Image', 'Tag', 'Registry', 'Size', 'Updated'], 'Registry images have not been observed.', ['Add registry', 'Pull image', 'Prune images']));
      if (tab === 'Volumes') content.append(table('Volumes & networks', ['Resource', 'Type', 'Driver', 'Mount / subnet', 'Used by'], 'Container storage and networks have not been observed.', ['Create volume', 'Create network', 'Inspect resource']));
      if (tab === 'Logs') content.append(terminal(media ? 'Media service logs' : 'Container logs'));
      return content;
    }
    function tools(tab) {
      var content = element('div');
      if (tab === 'Automation' || tab === 'Overview') content.append(table('Automation & scheduled jobs', ['Job', 'Target', 'Schedule', 'Last run', 'Next run', 'State'], 'No automation schedules or results have been observed.', ['Create automation', 'Run now', 'Pause job', 'View run history']));
      if (tab === 'Diagnostics' || tab === 'Overview') {
        var cards = grid();
        cards.append(controlPanel('Connection diagnostics', 'Select a connected target before running diagnostics.', ['Ping target', 'Check DNS', 'Test port', 'Trace route'], ['Target', 'Address', 'Result']));
        cards.append(controlPanel('System operations', 'Management access and operation acceptance are pending.', ['Start guest', 'Stop guest', 'Reboot', 'Assign IP', 'Open shell'], ['Target', 'Power state', 'Address']));
        content.append(cards, terminal('Diagnostic console'));
      }
      if (tab === 'Activity') content.append(table('Activity & audit trail', ['Time', 'Actor', 'Target', 'Operation', 'Result'], 'No management activity has been observed.', ['Refresh activity', 'Export activity']));
      if (tab === 'Backups') content.append(table('Backup jobs', ['Job', 'Target', 'Destination', 'Schedule', 'Last result'], 'No backup jobs or restore points have been observed.', ['Create backup job', 'Run backup', 'Restore', 'Verify backup']));
      return content;
    }
    function vault(tab) {
      var content = element('div');
      if (tab === 'Credentials' || tab === 'Overview') content.append(table('Credential references', ['Reference', 'Provider', 'Scope', 'Updated', 'State'], 'Credential references have not been observed. Secret values are never displayed here.', ['Add credential reference', 'Rotate credential', 'Remove reference']));
      if (tab === 'Certificates' || tab === 'Overview') content.append(table('Certificates & trust', ['Certificate', 'Subject', 'Issuer', 'Expires', 'State'], 'No certificate inventory has been observed.', ['Import certificate', 'Renew certificate', 'Manage trust']));
      if (tab === 'Access') content.append(table('Access policies', ['Policy', 'Principal', 'Resource', 'Permission', 'State'], 'No vault access policies have been observed.', ['Create policy', 'Edit policy', 'Revoke access']));
      return content;
    }
    function settings(tab) {
      var content = element('div'), cards = grid();
      if (tab === 'Connections' || tab === 'Overview') {
        cards.append(controlPanel('Infrastructure connections', 'Use Fleet to view observed PVE inventory and the current source configuration workflow.', ['Connect storage', 'Connect switch', 'Connect firewall', 'Connect container host'], ['Storage source', 'Network source', 'Firewall source', 'Container source']));
        cards.append(controlPanel('Workspace preferences', 'Preference persistence is not connected yet.', ['Save preferences', 'Reset preferences'], ['Default workspace', 'Refresh policy', 'Time zone']));
      }
      if (tab === 'Users') cards.append(controlPanel('Users & roles', 'User and role management has not been connected to this workspace.', ['Invite user', 'Edit role', 'Revoke session'], ['Selected user', 'Role', 'Last sign-in']));
      if (tab === 'Notifications') cards.append(controlPanel('Notifications', 'Delivery channels and alert policies have not been observed.', ['Add channel', 'Test notification', 'Save alert policy'], ['Channel', 'Destination', 'Delivery state']));
      if (tab === 'About') cards.append(controlPanel('System information', 'Runtime version and service state have not been observed here.', ['Check for updates', 'Export diagnostics'], ['Version', 'Runtime', 'Last update']));
      content.append(cards);
      return content;
    }
    var definitions = {
      topology: ['Network & topology', 'Switches, ports, VLANs and infrastructure relationships.', ['Overview', 'Switches', 'VLANs', 'Interfaces', 'Map'], topology],
      nas: ['Storage & NAS', 'Pools, datasets, shares and data protection.', ['Overview', 'Pools', 'Datasets', 'Shares', 'Snapshots'], nas],
      security: ['Security & firewall', 'Interfaces, policy, firewall rules and NAT.', ['Overview', 'Rules', 'Interfaces', 'NAT', 'Logs'], security],
      docker: ['Docker & containers', 'Services, compose stacks and container resources.', ['Overview', 'Services', 'Containers', 'Registry', 'Volumes', 'Logs'], function (tab) { return services(tab, false); }],
      media: ['Media services', 'Service operations, libraries and container visibility.', ['Overview', 'Services', 'Containers', 'Registry', 'Logs'], function (tab) { return services(tab, true); }],
      tools: ['System & tools', 'Automation, diagnostics, backups and activity.', ['Overview', 'Automation', 'Diagnostics', 'Activity', 'Backups'], tools],
      vault: ['Vault', 'Credential references, certificates and access policy.', ['Overview', 'Credentials', 'Certificates', 'Access'], vault],
      settings: ['Settings', 'Connections, workspace preferences and administration.', ['Overview', 'Connections', 'Users', 'Notifications', 'About'], settings]
    };
    var definition = definitions[view] || definitions.tools;
    var header = element('header', undefined, 'cockpit-workspace-header');
    var titles = element('div');
    titles.append(element('h2', definition[0]), element('p', definition[1], 'cockpit-muted'));
    header.append(titles);
    if (typeof options.onNavigate === 'function') {
      var fleet = element('button', '← Fleet inventory', 'fleet-btn');
      fleet.type = 'button';
      listen(fleet, function () { options.onNavigate('fleet'); });
      header.append(fleet);
    }
    var status = element('p', 'Not connected yet · Management controls are unavailable. Values marked — have not been observed.', 'cockpit-workspace-status');
    status.id = prefix + '-status';
    var tabs = element('div', undefined, 'cockpit-tabs');
    tabs.setAttribute('role', 'group');
    tabs.setAttribute('aria-label', definition[0] + ' sections');
    var body = element('div', undefined, 'cockpit-workspace-content');
    var buttons = [];
    definition[2].forEach(function (label, index) {
      var button = element('button', label, 'fleet-btn cockpit-tab');
      button.type = 'button';
      button.setAttribute('aria-pressed', index === 0 ? 'true' : 'false');
      button.setAttribute('aria-controls', prefix + '-content');
      listen(button, function () {
        buttons.forEach(function (entry) { entry.setAttribute('aria-pressed', entry === button ? 'true' : 'false'); });
        body.replaceChildren(definition[3](label));
      });
      buttons.push(button); tabs.append(button);
    });
    body.id = prefix + '-content';
    body.append(definition[3](definition[2][0]));
    shell.append(header, status, tabs, body);
    if (current()) root.append(shell);
    return {dispose: dispose};
  }
  global.FreqCockpitWorkspaces = {create: create};
})(window);
