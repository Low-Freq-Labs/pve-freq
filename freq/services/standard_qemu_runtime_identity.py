"""Retained original runtime identity observations, never read authority.

The original caller must retain this once-only attempt before run under its
owned source_read and original cutoff. It resolves only its captured configured
runtime name and current process IDs/groups. No account, group, permission,
credential, service or provider is changed or opened. NSS and other external
writers are outside the Python source gate: observations are refusal filters,
not atomicity, provenance, incarnation or a credential/view/provider grant.
"""
import grp
import math
import os
import pwd
import re
import threading
import time

from freq.core import read_source_epoch
from freq.core.config import is_managed_service_account_name


_NAME = re.compile(r'[a-z_][a-z0-9_-]{0,31}')


class RuntimeUnavailable(Exception):
    def __init__(self):
        super().__init__('Read runtime identity unavailable')


class RuntimeIdentityCapture:
    __slots__ = ('_context', '_end', '_service', '_thread', '_used',
                 '_stages', '_values', '_failure', '_state', '_result')

    def __init__(self, context, original_end, configured_runtime):
        if (type(context) is not read_source_epoch.source_read
                or type(original_end) not in (int, float)
                or not math.isfinite(original_end)
                or type(configured_runtime) is not str
                or configured_runtime != configured_runtime.strip().lower()
                or not is_managed_service_account_name(configured_runtime)):
            raise RuntimeUnavailable()
        self._context, self._end, self._service = context, original_end, configured_runtime
        self._thread = threading.current_thread()
        self._used = False
        self._stages = ['unused'] * 9
        self._values = [None] * 9
        self._failure = self._result = None
        self._state = 'prepared'

    def _current(self):
        c = self._context
        if (threading.current_thread() is not self._thread
                or c.thread is not self._thread or c.stage != 'captured'
                or c.rejected or not c._retained
                or read_source_epoch._readers.get(id(c)) is not c
                or read_source_epoch._epoch is not c.epoch
                or not time.monotonic() < self._end):
            raise RuntimeUnavailable()

    def _call(self, index, function, *args):
        self._current()
        self._stages[index] = 'pending'
        try:
            result = function(*args)
        except KeyError:
            self._stages[index] = 'absent'
            raise
        self._values[index] = result
        self._stages[index] = 'returned'
        self._current()
        return result

    def run(self):
        if self._used or threading.current_thread() is not self._thread:
            raise RuntimeUnavailable()
        self._used = True
        self._state = 'entered'
        try:
            uid = self._call(0, os.getuid)
            euid = self._call(1, os.geteuid)
            gid = self._call(2, os.getgid)
            egid = self._call(3, os.getegid)
            if (any(type(v) is not int or not 0 < v <= 4294967294
                    for v in (uid, euid, gid, egid)) or uid != euid or gid != egid):
                raise RuntimeUnavailable()
            named = self._call(4, pwd.getpwnam, self._service)
            current = self._call(5, pwd.getpwuid, euid)
            if (type(named) is not pwd.struct_passwd or type(current) is not pwd.struct_passwd
                    or any(row.pw_name != self._service or row.pw_uid != euid
                           or row.pw_gid != egid for row in (named, current))):
                raise RuntimeUnavailable()
            try:
                group = self._call(6, grp.getgrnam, self._service)
            except KeyError:
                # Exact original writer fallback when no service-named group
                # exists: use the current real primary group, never a guessed
                # group/name from the browser or a different configured user.
                group = self._call(7, grp.getgrgid, gid)
            groups = self._call(8, os.getgroups)
            if (type(group) is not grp.struct_group
                    or type(group.gr_name) is not str or not _NAME.fullmatch(group.gr_name)
                    or type(group.gr_gid) is not int or not 0 < group.gr_gid <= 4294967294
                    or type(groups) is not list or len(groups) > 1024
                    or any(type(v) is not int or not 0 <= v <= 4294967294 for v in groups)
                    or group.gr_gid != egid and group.gr_gid not in groups
                    or self._stages[6] == 'returned' and group.gr_name != self._service
                    or self._stages[7] == 'returned' and group.gr_gid != gid):
                raise RuntimeUnavailable()
            self._current()
            result = (self._service, euid, egid, group.gr_name, group.gr_gid)
        except BaseException as failure:
            self._failure = failure
            self._state = 'unsettled' if 'pending' in self._stages else 'closed'
            if not issubclass(type(failure), Exception) or issubclass(type(failure), MemoryError):
                raise failure from None
            raise RuntimeUnavailable() from None
        self._state = 'closed'
        self._result = result
        return result
