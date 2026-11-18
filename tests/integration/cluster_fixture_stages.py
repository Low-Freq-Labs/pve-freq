"""Fixture-only bounded stage log and one consumed release marker.

Not imported by the frozen initial three-shape package. No product debug route.
"""
import json
from pathlib import Path
import threading
import time


STAGES = frozenset(('read_entered', 'publication_admitted', 'headers_ended', 'headers_failed',
                    'body_write_completed', 'body_write_failed'))


class StageController:
    def __init__(self, log_path, release_marker, hold_stage):
        if hold_stage not in ('read_entered', 'publication_admitted'):
            raise ValueError('invalid hold stage')
        self.log_path = Path(log_path)
        self.release_marker = Path(release_marker)
        if self.release_marker.exists() or self.release_marker.is_symlink():
            raise ValueError('release marker already exists')
        self.hold_stage = hold_stage
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self._sequence = 0
        self._held = False
        self._consumed = False
        with self.log_path.open('x', encoding='utf-8'):
            pass

    def observe(self, stage, *, admitted=False, deadline=None):
        if stage not in STAGES or type(admitted) is not bool:
            raise ValueError('invalid stage')
        hold = False
        with self._lock:
            if self._sequence >= 16:
                raise RuntimeError('stage census limit')
            self._sequence += 1
            record = dict(schema=1, sequence=self._sequence, stage=stage, admitted=admitted)
            with self.log_path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, separators=(',', ':')) + '\n')
            if stage == self.hold_stage and not self._held:
                self._held = True
                hold = True
        if not hold:
            return
        stop = time.monotonic() + 8.0
        if deadline is not None:
            stop = min(stop, deadline)
        while not self._abort.is_set():
            if time.monotonic() >= stop:
                raise TimeoutError('fixture hold deadline')
            if self.release_marker.exists():
                if self.release_marker.is_symlink() or not self.release_marker.is_file():
                    raise ValueError('invalid release marker')
                with self.release_marker.open('rb') as stream:
                    marker = stream.read(9)
                if marker != b'release\n':
                    raise ValueError('invalid release marker contents')
                with self._lock:
                    if self._consumed:
                        raise RuntimeError('release already consumed')
                    self._consumed = True
                return
            self._abort.wait(0.01)
        raise RuntimeError('fixture stage retired')

    def retire(self):
        self._abort.set()

    def snapshot(self):
        with self._lock:
            return dict(records=self._sequence, held=self._held,
                        release_consumed=self._consumed, retired=self._abort.is_set())
