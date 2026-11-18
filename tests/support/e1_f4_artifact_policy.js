const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const zlib = require('node:zlib');

const ZIP_LOCAL_FILE = 0x04034b50;
const ZIP_CENTRAL_FILE = 0x02014b50;
const ZIP_END = 0x06054b50;
const MAX_ZIP_ENTRY_BYTES = 128 * 1024 * 1024;

function filesUnder(root) {
  if (!root || !fs.existsSync(root)) return [];
  const result = [];
  const visit = candidate => {
    const stat = fs.lstatSync(candidate);
    if (stat.isSymbolicLink()) throw new Error('artifact policy refuses symlinks');
    if (stat.isDirectory()) {
      for (const child of fs.readdirSync(candidate)) visit(path.join(candidate, child));
    } else if (stat.isFile()) result.push(candidate);
  };
  visit(root);
  return result;
}

function readSecrets(secretFile) {
  if (!secretFile || !fs.existsSync(secretFile)) return [];
  const mode = fs.statSync(secretFile).mode & 0o777;
  if (mode !== 0o600) throw new Error('secret registry mode is not 0600');
  return fs.readFileSync(secretFile, 'utf8').split('\n').filter(Boolean);
}

function zipEntries(bytes) {
  const searchStart = Math.max(0, bytes.length - 65_557);
  let endOffset = -1;
  for (let offset = bytes.length - 22; offset >= searchStart; offset -= 1) {
    if (bytes.readUInt32LE(offset) === ZIP_END) { endOffset = offset; break; }
  }
  if (endOffset < 0) throw new Error('ZIP end record is missing');
  const entryCount = bytes.readUInt16LE(endOffset + 10);
  let centralOffset = bytes.readUInt32LE(endOffset + 16);
  const entries = [];
  for (let index = 0; index < entryCount; index += 1) {
    if (bytes.readUInt32LE(centralOffset) !== ZIP_CENTRAL_FILE) {
      throw new Error('ZIP central-directory entry is malformed');
    }
    const flags = bytes.readUInt16LE(centralOffset + 8);
    const method = bytes.readUInt16LE(centralOffset + 10);
    const compressedSize = bytes.readUInt32LE(centralOffset + 20);
    const uncompressedSize = bytes.readUInt32LE(centralOffset + 24);
    const nameLength = bytes.readUInt16LE(centralOffset + 28);
    const extraLength = bytes.readUInt16LE(centralOffset + 30);
    const commentLength = bytes.readUInt16LE(centralOffset + 32);
    const localOffset = bytes.readUInt32LE(centralOffset + 42);
    if (flags & 0x1) throw new Error('encrypted ZIP entries cannot be audited');
    if (compressedSize === 0xffffffff || uncompressedSize === 0xffffffff) {
      throw new Error('ZIP64 entries exceed the artifact audit contract');
    }
    if (uncompressedSize > MAX_ZIP_ENTRY_BYTES) throw new Error('ZIP entry exceeds audit size limit');
    if (bytes.readUInt32LE(localOffset) !== ZIP_LOCAL_FILE) throw new Error('ZIP local entry is malformed');
    const localNameLength = bytes.readUInt16LE(localOffset + 26);
    const localExtraLength = bytes.readUInt16LE(localOffset + 28);
    const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
    const compressed = bytes.subarray(dataOffset, dataOffset + compressedSize);
    let content;
    if (method === 0) content = Buffer.from(compressed);
    else if (method === 8) content = zlib.inflateRawSync(compressed, { maxOutputLength: MAX_ZIP_ENTRY_BYTES });
    else throw new Error(`unsupported ZIP compression method ${method}`);
    if (content.length !== uncompressedSize) throw new Error('ZIP entry size does not match its directory');
    entries.push(content);
    centralOffset += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

function buffersInArtifact(bytes) {
  const buffers = [bytes];
  if (bytes.length >= 4 && bytes.readUInt32LE(0) === ZIP_LOCAL_FILE) buffers.push(...zipEntries(bytes));
  return buffers;
}

function scanArtifacts(roots, secrets) {
  const leaks = [];
  for (const root of roots) {
    for (const file of filesUnder(root)) {
      const bytes = fs.readFileSync(file);
      const candidates = buffersInArtifact(bytes);
      if (secrets.some(secret => candidates.some(candidate => candidate.includes(Buffer.from(secret))))) {
        leaks.push(file);
      }
    }
  }
  return leaks;
}

function cleanup(paths) {
  for (const candidate of paths) {
    if (candidate && fs.existsSync(candidate)) fs.rmSync(candidate, { recursive: true, force: true });
  }
}

function selfTest() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pve-freq-f4-artifact-policy-'));
  fs.chmodSync(root, 0o700);
  const registry = path.join(root, 'secrets');
  const artifacts = path.join(root, 'artifacts');
  const planted = 'F4-Planted_Secret-Value';
  fs.mkdirSync(artifacts, { mode: 0o700 });
  fs.writeFileSync(registry, `${planted}\n`, { mode: 0o600, flag: 'wx' });
  const trace = path.join(artifacts, 'trace.zip');
  const python = process.env.PVE_FREQ_PYTHON || 'python3';
  const create = spawnSync(python, ['-c', [
    'import pathlib, sys, zipfile',
    'secret = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8").strip()',
    'with zipfile.ZipFile(sys.argv[1], "w", compression=zipfile.ZIP_DEFLATED) as archive:',
    '    archive.writestr("trace.network", ("prefix:" + secret + ":suffix") * 64)',
  ].join('\n'), trace, registry], { encoding: 'utf8' });
  if (create.status !== 0) throw new Error('could not create compressed planted trace fixture');
  if (fs.readFileSync(trace).includes(Buffer.from(planted))) {
    throw new Error('planted trace fixture did not compress the registered value');
  }
  const leaks = scanArtifacts([artifacts], readSecrets(registry));
  cleanup([artifacts, registry]);
  if (leaks.length !== 1 || fs.existsSync(artifacts) || fs.existsSync(registry)) {
    throw new Error('planted-secret artifact policy did not detect and clean exactly once');
  }
  fs.rmdirSync(root);
  process.stdout.write('PLANTED_SECRET_DETECTED_AND_CLEANED\n');
}

if (require.main === module) {
  if (process.argv[2] !== '--self-test') throw new Error('only --self-test is supported');
  selfTest();
}

module.exports = { cleanup, readSecrets, scanArtifacts };
