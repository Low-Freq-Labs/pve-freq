"""Tests for metrics DB lifecycle — prove init/use/shutdown is clean.

Bug: freq/core/log.py opened a process-global SQLite connection for
perf/health data and never closed it, producing ResourceWarning noise
during test runs and potentially leaking connections in daemon mode.

Fix: Added shutdown() function + atexit registration.
"""
import concurrent.futures
import os
import sqlite3
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix  # noqa: E402, I001

from freq.core import log as logger


class TestMetricsDbLifecycle(unittest.TestCase):
    """The metrics DB connection must be closeable without errors."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmpdir, "freq.log")

    def tearDown(self):
        logger.shutdown()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _case_init_creates_db(self):
        """init() must create the SQLite DB file."""
        logger.init(self.log_file)
        db_path = os.path.join(self.tmpdir, "freq.db")
        self.assertTrue(os.path.isfile(db_path))

    def _case_shutdown_closes_connection(self):
        """shutdown() must close the DB connection."""
        logger.init(self.log_file)
        self.assertIsNotNone(logger._db_conn)
        logger.shutdown()
        self.assertIsNone(logger._db_conn)

    def _case_shutdown_is_idempotent(self):
        """shutdown() can be called multiple times without error."""
        logger.init(self.log_file)
        logger.shutdown()
        logger.shutdown()
        logger.shutdown()
        self.assertIsNone(logger._db_conn)

    def _case_shutdown_before_init(self):
        """shutdown() before init() must not raise."""
        logger.shutdown()
        self.assertIsNone(logger._db_conn)

    def _case_init_use_shutdown_cycle(self):
        """Full lifecycle: init → perf write → shutdown → no warnings."""
        logger.init(self.log_file)
        logger.perf("test_op", 0.123)
        logger.shutdown()
        self.assertIsNone(logger._db_conn)

    def _case_reinit_after_shutdown(self):
        """After shutdown, re-init must reconnect cleanly."""
        logger.init(self.log_file)
        logger.perf("op1", 0.1)
        logger.shutdown()
        logger.init(self.log_file)
        logger.perf("op2", 0.2)
        self.assertIsNotNone(logger._db_conn)

    def _case_reinit_closes_the_previous_connection_before_replacement(self):
        """Repeated CLI entry must not orphan the prior process-global connection."""
        logger.init(self.log_file)
        previous = logger._db_conn
        self.assertIsNotNone(previous)

        logger.init(os.path.join(self.tmpdir, "replacement.log"))

        self.assertIsNot(logger._db_conn, previous)
        with self.assertRaises(sqlite3.ProgrammingError):
            previous.execute("SELECT 1")

    def _case_no_resource_warning(self):
        """init/use/shutdown must not produce ResourceWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            logger.init(self.log_file)
            logger.perf("test_op", 0.5)
            logger.shutdown()
            resource_warnings = [x for x in w if issubclass(x.category, ResourceWarning)]
            self.assertEqual(len(resource_warnings), 0,
                             f"ResourceWarning detected: {resource_warnings}")

    def _case_repeated_cycles(self):
        """Multiple init/shutdown cycles must work cleanly."""
        for i in range(5):
            logger.init(self.log_file)
            logger.perf(f"cycle_{i}", float(i))
            logger.shutdown()
        self.assertIsNone(logger._db_conn)

    def _case_parallel_perf_writes_are_serialized(self):
        """Fleet worker threads must not concurrently drive one SQLite connection."""
        logger.init(self.log_file)

        def write_metric(index):
            logger.perf("ssh", index / 1000, host=str(index), ok=False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(write_metric, range(1000)))

        self.assertEqual(len(logger.read_perf()), 1000)


METRICS_DB_LIFECYCLE_CASES = (
    "_case_init_creates_db",
    "_case_shutdown_closes_connection",
    "_case_shutdown_is_idempotent",
    "_case_shutdown_before_init",
    "_case_init_use_shutdown_cycle",
    "_case_reinit_after_shutdown",
    "_case_reinit_closes_the_previous_connection_before_replacement",
    "_case_no_resource_warning",
    "_case_repeated_cycles",
    "_case_parallel_perf_writes_are_serialized",
)


class TestMetricsDbLifecycleMatrix(unittest.TestCase):
    def test_metrics_db_lifecycle_matrix(self):
        run_case_matrix(self, TestMetricsDbLifecycle, METRICS_DB_LIFECYCLE_CASES)


if __name__ == "__main__":
    unittest.main()
