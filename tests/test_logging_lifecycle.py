"""Tests for metrics DB lifecycle — prove init/use/shutdown is clean.

Bug: freq/core/log.py opened a process-global SQLite connection for
perf/health data and never closed it, producing ResourceWarning noise
during test runs and potentially leaking connections in daemon mode.

Fix: Added shutdown() function + atexit registration.
"""
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

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

    def test_init_creates_db(self):
        """init() must create the SQLite DB file."""
        logger.init(self.log_file)
        db_path = os.path.join(self.tmpdir, "freq.db")
        self.assertTrue(os.path.isfile(db_path))

    def test_shutdown_closes_connection(self):
        """shutdown() must close the DB connection."""
        logger.init(self.log_file)
        self.assertIsNotNone(logger._db_conn)
        logger.shutdown()
        self.assertIsNone(logger._db_conn)

    def test_shutdown_is_idempotent(self):
        """shutdown() can be called multiple times without error."""
        logger.init(self.log_file)
        logger.shutdown()
        logger.shutdown()
        logger.shutdown()
        self.assertIsNone(logger._db_conn)

    def test_shutdown_before_init(self):
        """shutdown() before init() must not raise."""
        logger.shutdown()
        self.assertIsNone(logger._db_conn)

    def test_init_use_shutdown_cycle(self):
        """Full lifecycle: init → perf write → shutdown → no warnings."""
        logger.init(self.log_file)
        logger.perf("test_op", 0.123)
        logger.shutdown()
        self.assertIsNone(logger._db_conn)

    def test_reinit_after_shutdown(self):
        """After shutdown, re-init must reconnect cleanly."""
        logger.init(self.log_file)
        logger.perf("op1", 0.1)
        logger.shutdown()
        logger.init(self.log_file)
        logger.perf("op2", 0.2)
        self.assertIsNotNone(logger._db_conn)

    def test_no_resource_warning(self):
        """init/use/shutdown must not produce ResourceWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            logger.init(self.log_file)
            logger.perf("test_op", 0.5)
            logger.shutdown()
            resource_warnings = [x for x in w if issubclass(x.category, ResourceWarning)]
            self.assertEqual(len(resource_warnings), 0,
                             f"ResourceWarning detected: {resource_warnings}")

    def test_repeated_cycles(self):
        """Multiple init/shutdown cycles must work cleanly."""
        for i in range(5):
            logger.init(self.log_file)
            logger.perf(f"cycle_{i}", float(i))
            logger.shutdown()
        self.assertIsNone(logger._db_conn)


if __name__ == "__main__":
    unittest.main()
