"""Restricted SQLite schema and statement DATA, without a connector or IO.

No statement is executed here. The original connector must separately own and
verify schema, foreign-key enforcement, transactions, capacity and closure.
Supplied plans and rows are not authority, durability or issuance receipts.
"""
from dataclasses import dataclass

from freq.services import snippet_authoring_journal_encoding as codec


# Logical row/input bounds only, not reserved SQLite pages/disk/RSS capacity.
MAX_OPERATION_ROWS = 128
SCHEMA_STATEMENTS = (
    '''CREATE TABLE sj_heads (
        installation_id TEXT NOT NULL CHECK(typeof(installation_id)='text' AND length(installation_id) BETWEEN 1 AND 128),
        operation_id TEXT NOT NULL CHECK(typeof(operation_id)='text' AND length(operation_id) BETWEEN 1 AND 128),
        sequence INTEGER NOT NULL CHECK(typeof(sequence)='integer' AND sequence BETWEEN 1 AND 32),
        payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload) BETWEEN 1 AND 65536),
        PRIMARY KEY(installation_id, operation_id),
        FOREIGN KEY(installation_id, operation_id, sequence, payload)
          REFERENCES sj_history(installation_id, operation_id, sequence, payload)
          DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(installation_id, operation_id)
          REFERENCES sj_version_claims(installation_id, operation_id)
          DEFERRABLE INITIALLY DEFERRED
    ) WITHOUT ROWID''',
    '''CREATE TABLE sj_history (
        installation_id TEXT NOT NULL,
        operation_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK(typeof(sequence)='integer' AND sequence BETWEEN 1 AND 32),
        payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload) BETWEEN 1 AND 65536),
        PRIMARY KEY(installation_id, operation_id, sequence),
        UNIQUE(installation_id, operation_id, sequence, payload),
        FOREIGN KEY(installation_id, operation_id)
          REFERENCES sj_heads(installation_id, operation_id)
    ) WITHOUT ROWID''',
    '''CREATE TABLE sj_version_claims (
        installation_id TEXT NOT NULL,
        operation_id TEXT NOT NULL,
        estate_id TEXT NOT NULL,
        storage_id TEXT NOT NULL,
        storage_incarnation TEXT NOT NULL,
        volume_id TEXT NOT NULL,
        content_kind TEXT NOT NULL CHECK(content_kind IN ('user','vendor','meta','network')),
        revision TEXT NOT NULL,
        initial_payload BLOB NOT NULL CHECK(typeof(initial_payload)='blob' AND length(initial_payload) BETWEEN 1 AND 65536),
        PRIMARY KEY(installation_id, operation_id),
        UNIQUE(installation_id, estate_id, storage_id, storage_incarnation, volume_id, content_kind, revision),
        FOREIGN KEY(installation_id, operation_id)
          REFERENCES sj_heads(installation_id, operation_id),
        FOREIGN KEY(installation_id, operation_id, initial_payload)
          REFERENCES sj_registration_roots(installation_id, operation_id, payload)
          DEFERRABLE INITIALLY DEFERRED
    ) WITHOUT ROWID''',
    '''CREATE TABLE sj_registration_roots (
        installation_id TEXT NOT NULL,
        operation_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK(sequence=1),
        payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload) BETWEEN 1 AND 65536),
        PRIMARY KEY(installation_id, operation_id),
        UNIQUE(installation_id, operation_id, payload),
        FOREIGN KEY(installation_id, operation_id, sequence, payload)
          REFERENCES sj_history(installation_id, operation_id, sequence, payload),
        FOREIGN KEY(installation_id, operation_id)
          REFERENCES sj_heads(installation_id, operation_id)
    ) WITHOUT ROWID''',
    '''CREATE TRIGGER sj_head_insert BEFORE INSERT ON sj_heads
       WHEN NEW.sequence != 1 OR (SELECT count(*) FROM sj_heads) >= 128
       BEGIN SELECT RAISE(ABORT,'Private journal registration refused'); END''',
    '''CREATE TRIGGER sj_head_update BEFORE UPDATE ON sj_heads
       WHEN NEW.installation_id != OLD.installation_id OR NEW.operation_id != OLD.operation_id
         OR NEW.sequence != OLD.sequence + 1
       BEGIN SELECT RAISE(ABORT,'Private journal append refused'); END''',
    '''CREATE TRIGGER sj_history_insert BEFORE INSERT ON sj_history
       WHEN NOT EXISTS(SELECT 1 FROM sj_heads WHERE installation_id=NEW.installation_id
         AND operation_id=NEW.operation_id AND sequence=NEW.sequence AND payload=NEW.payload)
       BEGIN SELECT RAISE(ABORT,'Private journal history refused'); END''',
    *tuple('CREATE TRIGGER sj_' + table + '_' + action.lower() +
        ' BEFORE ' + action + ' ON sj_' + table +
        " BEGIN SELECT RAISE(ABORT,'Private journal retained rows immutable'); END"
        for table, actions in (('heads', ('DELETE',)), ('history', ('UPDATE','DELETE')),
            ('version_claims', ('UPDATE','DELETE')), ('registration_roots', ('UPDATE','DELETE')))
        for action in actions),
)

INSERT_HEAD = 'INSERT INTO sj_heads(installation_id,operation_id,sequence,payload) VALUES(?,?,?,?)'
INSERT_HISTORY = 'INSERT INTO sj_history(installation_id,operation_id,sequence,payload) VALUES(?,?,?,?)'
INSERT_CLAIM = '''INSERT INTO sj_version_claims(installation_id,operation_id,estate_id,storage_id,
    storage_incarnation,volume_id,content_kind,revision,initial_payload) VALUES(?,?,?,?,?,?,?,?,?)'''
INSERT_ROOT = 'INSERT INTO sj_registration_roots(installation_id,operation_id,sequence,payload) VALUES(?,?,?,?)'
COMPARE_APPEND_HEAD = '''UPDATE sj_heads SET sequence=?,payload=?
    WHERE installation_id=? AND operation_id=? AND sequence=? AND payload=?'''


@dataclass(frozen=True, slots=True, repr=False)
class PrivateJournalSQLPlanData:
    statements: tuple
    # Every statement must affect one row; the caller must verify each result
    # and commit the whole plan in one retained transaction, never autocommit.
    __hash__ = None

    def __reduce_ex__(self, protocol):
        raise TypeError('Private journal statement data cannot be serialized')


def prepare_registration_sql_data(value):
    payload = codec.encode_private_authoring_record(value)
    record = codec.decode_private_authoring_record(payload)
    if len(record.events) != 1 or record.events[0].event != 'registered':
        raise ValueError('Private journal registration refused') from None
    head = (record.installation_id, record.operation_id, 1, payload)
    v = record.version
    claim = (record.installation_id, record.operation_id, v.estate_id, v.storage_id,
        v.storage_incarnation, v.volume_id, v.content_kind, v.revision, payload)
    return PrivateJournalSQLPlanData(((INSERT_HEAD, head), (INSERT_HISTORY, head),
        (INSERT_ROOT, head), (INSERT_CLAIM, claim)))


def prepare_append_sql_data(previous, proposed):
    before = codec.encode_private_authoring_record(previous)
    after = codec.encode_private_authoring_record(proposed)
    record = codec.validate_private_encoded_append(before, after)
    sequence = len(record.events)
    return PrivateJournalSQLPlanData((
        (COMPARE_APPEND_HEAD, (sequence, after, record.installation_id,
            record.operation_id, sequence - 1, before)),
        (INSERT_HISTORY, (record.installation_id, record.operation_id, sequence, after)),
    ))
