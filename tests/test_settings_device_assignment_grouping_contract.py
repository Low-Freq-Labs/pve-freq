from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = (ROOT / "freq/data/web/app.html").read_text()
APP_JS = (ROOT / "freq/data/web/js/app.js").read_text()
APP_CSS = (ROOT / "freq/data/web/css/app.css").read_text()


def test_device_assignment_owns_admin_mount():
    device_idx = APP_HTML.index("<h3>Device Assignment</h3>")
    mount_idx = APP_HTML.index('id="device-admin-mount"')
    api_idx = APP_HTML.index("<h3>API</h3>")
    assert device_idx < mount_idx < api_idx
    assert "Classify hosts and existing VMs as PROD, LAB, TEMP, or OOC." in APP_HTML


def test_fleet_admin_moves_into_device_assignment_not_settings_sibling():
    assert "device-admin-mount" in APP_JS
    assert "mount.appendChild(sec)" in APP_JS
    assert "insertAdjacentElement('afterend',sec)" not in APP_JS


def test_device_assignment_is_the_single_editing_table():
    assert 'class="device-assignment-table"' in APP_JS
    assert "<th>Assignment</th><th>Host Properties</th><th>Management</th><th>Permissions</th><th>Save</th>" in APP_JS
    assert "saveDeviceAssignmentRow" in APP_JS


def test_old_subpanel_labels_do_not_render_under_device_assignment():
    assert "device-admin-panel" not in APP_JS
    assert "HOST PROPERTIES</h4>" not in APP_JS
    assert "VM CATEGORIES</h4>" not in APP_JS
    assert "PERMISSIONS</h4>" not in APP_JS
    assert "VM CATEGORIES & PERMISSIONS" not in APP_JS
    assert "PERMISSION TIERS" not in APP_JS


def test_assignment_choices_are_prod_lab_temp_ooc_without_sandbox():
    assert "{value:'prod',label:'PROD'}" in APP_JS
    assert "{value:'lab',label:'LAB'}" in APP_JS
    assert "{value:'template',label:'TEMP'}" in APP_JS
    assert "{value:'ooc',label:'OOC'}" in APP_JS
    options_block = APP_JS.split("var DEVICE_ASSIGNMENT_OPTIONS=", 1)[1].split("];", 1)[0]
    assert "sandbox" not in options_block.lower()


def test_fleet_admin_wrapper_is_flattened_inside_device_assignment():
    assert ".device-assignment-admin > .section-header { display: none; }" in APP_CSS
    assert ".device-assignment-table" in APP_CSS


def test_cost_sections_live_at_bottom_of_system_not_settings():
    settings_start = APP_HTML.index('id="settings-view"')
    settings_end = APP_HTML.index("</div><!-- close settings-view -->", settings_start)
    tools_start = APP_HTML.index('id="tools-view"')
    tools_end = APP_HTML.index("</div><!-- close tools-view -->", tools_start)
    settings = APP_HTML[settings_start:settings_end]
    tools = APP_HTML[tools_start:tools_end]

    assert "<h3>Fleet Costs</h3>" not in settings
    assert "<h3>Cost Analysis</h3>" not in settings
    host_compare_idx = tools.index("<h3>Host Compare</h3>")
    fleet_cost_idx = tools.index("<h3>Fleet Costs</h3>")
    cost_analysis_idx = tools.index("<h3>Cost Analysis</h3>")
    assert host_compare_idx < fleet_cost_idx < cost_analysis_idx


def test_system_loader_owns_cost_refresh_not_settings_loader():
    assert "function loadToolsPage(){_populateHostDropdowns();_populateCompareDropdowns();loadCosts();}" in APP_JS
    assert "function loadSettingsPage(){loadFederation();_loadSettingsPrefs();_loadLabAssignments();_ensureFleetAdminInSettings();loadFleetAdmin();}" in APP_JS
