"""Lifecycle-faithful unittest case-matrix execution."""

from __future__ import annotations

import unittest
from collections.abc import Sequence
from types import TracebackType
from typing import TypeAlias

ExcInfo: TypeAlias = tuple[type[BaseException], BaseException, TracebackType | None]


class _CaseResult(unittest.TestResult):
    """Capture the original outcome after ``TestCase.run`` finishes cleanup."""

    def __init__(self) -> None:
        super().__init__()
        self.outcomes: list[tuple[str, ExcInfo]] = []

    def addFailure(self, test: unittest.TestCase, err: ExcInfo) -> None:  # noqa: N802
        self.outcomes.append(("failure", err))
        super().addFailure(test, err)

    def addError(self, test: unittest.TestCase, err: ExcInfo) -> None:  # noqa: N802
        self.outcomes.append(("error", err))
        super().addError(test, err)

    def addSubTest(  # noqa: N802
        self,
        test: unittest.TestCase,
        subtest: unittest.TestCase,
        err: ExcInfo | None,
    ) -> None:
        if err is not None:
            kind = "failure" if issubclass(err[0], test.failureException) else "error"
            self.outcomes.append((kind, err))
        super().addSubTest(test, subtest, err)


def _propagate_case_outcome(result: _CaseResult, case_name: str) -> None:
    if result.outcomes:
        _kind, (_exc_type, exception, traceback) = result.outcomes[0]
        raise exception.with_traceback(traceback)
    if result.unexpectedSuccesses:
        raise AssertionError(f"{case_name}: unexpected success")
    if result.expectedFailures:
        raise unittest.SkipTest(f"{case_name}: expected failure")
    if result.skipped:
        reasons = "; ".join(reason for _test, reason in result.skipped)
        raise unittest.SkipTest(f"{case_name}: {reasons}")


def run_case_matrix(
    owner: unittest.TestCase,
    case_type: type[unittest.TestCase],
    case_names: Sequence[str],
) -> None:
    """Run every named case with its own full unittest lifecycle."""

    for case_name in case_names:
        with owner.subTest(case=case_name):
            result = _CaseResult()
            case_type(case_name).run(result)
            _propagate_case_outcome(result, case_name)
