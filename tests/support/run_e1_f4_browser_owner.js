const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { cleanup, readSecrets, scanArtifacts } = require('./e1_f4_artifact_policy');

const evidenceRoot = process.env.PVE_FREQ_F4_EVIDENCE_ROOT || path.resolve(__dirname, '../../test-results');

function boundedEvidenceFile(candidate) {
  if (!candidate || !path.isAbsolute(candidate)) {
    throw new Error('PVE_FREQ_F4_EVIDENCE_XML must be an absolute path');
  }
  const realRoot = fs.realpathSync(evidenceRoot);
  const realParent = fs.realpathSync(path.dirname(candidate));
  if (realParent !== realRoot) {
    throw new Error('PVE_FREQ_F4_EVIDENCE_XML must be a direct file under the evidence root');
  }
  const status = fs.lstatSync(candidate, { throwIfNoEntry: false });
  if (status) {
    if (status.isSymbolicLink() || !status.isFile()) {
      throw new Error('PVE_FREQ_F4_EVIDENCE_XML must name a regular non-symlink file');
    }
  }
  return candidate;
}

function unlinkEvidenceFile(candidate) {
  const status = fs.lstatSync(candidate, { throwIfNoEntry: false });
  if (!status) return;
  if (status.isSymbolicLink() || !status.isFile()) {
    throw new Error('refusing to unlink a non-regular evidence destination');
  }
  fs.unlinkSync(candidate);
}
const evidenceXml = boundedEvidenceFile(process.env.PVE_FREQ_F4_EVIDENCE_XML);
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pve-freq-f4-browser-owner-'));
fs.chmodSync(root, 0o700);
const artifactDir = path.join(root, 'artifacts');
const secretFile = path.join(root, 'registered-secrets');
fs.mkdirSync(artifactDir, { mode: 0o700 });
fs.writeFileSync(secretFile, '', { mode: 0o600, flag: 'wx' });
const junit = path.join(root, 'browser-owner.xml');
const executable = path.resolve('node_modules/.bin/playwright');
const args = [
  'test',
  'tests/e2e/e1-f4-first-admin-claim.spec.js',
  '--config=playwright.f4-owner.config.js',
  '--project=chromium'
];
let result;
let leaks = [];
let retainEvidence = false;
unlinkEvidenceFile(evidenceXml);
try {
  result = spawnSync(executable, args, {
    cwd: process.cwd(),
    env: {
      ...process.env,
      PVE_FREQ_F4_ARTIFACT_DIR: artifactDir,
      PVE_FREQ_F4_SECRET_AUDIT_FILE: secretFile,
      PLAYWRIGHT_JUNIT_OUTPUT_NAME: junit,
    },
    encoding: 'utf8',
  });
  const secrets = readSecrets(secretFile);
  leaks = scanArtifacts([artifactDir, junit], secrets);
  if (secrets.some(secret => (result.stdout || '').includes(secret) || (result.stderr || '').includes(secret))) {
    leaks.push('captured process output');
  }
  if (!leaks.length) {
    fs.copyFileSync(junit, evidenceXml);
    fs.chmodSync(evidenceXml, 0o644);
    leaks = scanArtifacts([evidenceXml], secrets);
    retainEvidence = leaks.length === 0;
  }
} finally {
  cleanup([artifactDir, junit, secretFile]);
  if (!retainEvidence) unlinkEvidenceFile(evidenceXml);
  fs.rmdirSync(root);
}
if (leaks.length) {
  process.stderr.write(`F4_ARTIFACT_SECRET_SCAN BLOCKED ${leaks.length} artifact(s); cleaned\n`);
  process.exit(2);
}
if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);
process.stdout.write('F4_ARTIFACT_SECRET_SCAN CLEAN; temporary artifacts removed\n');
process.exit(result.status === null ? 3 : result.status);
