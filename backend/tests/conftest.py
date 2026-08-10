"""Shared pytest configuration for the standalone backend."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from support.detectors.blocking_io import BlockingIOProbe, detect_blocking_io

sys.path.insert(0, str(Path(__file__).parent.parent))

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_blocking_io_probe = BlockingIOProbe(_BACKEND_ROOT)
_BLOCKING_IO_DETECTOR_ATTR = "_blocking_io_detector"


@pytest.fixture()
def blocking_io_detector():
    """Fail a focused test if blocking calls run on the event loop thread."""
    with detect_blocking_io(fail_on_exit=True) as detector:
        yield detector


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("blocking-io")
    group.addoption(
        "--detect-blocking-io",
        action="store_true",
        default=False,
        help="Report blocking calls made while an asyncio event loop is running.",
    )
    group.addoption(
        "--detect-blocking-io-fail",
        action="store_true",
        default=False,
        help="Fail when --detect-blocking-io records violations.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "no_blocking_io_probe: skip the optional blocking IO probe"
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    if _blocking_io_probe_enabled(session.config):
        _blocking_io_probe.clear()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item):
    if not _blocking_io_probe_enabled(item.config) or _blocking_io_probe_skipped(item):
        yield
        return

    detector = detect_blocking_io(fail_on_exit=False, stack_limit=18)
    detector.__enter__()
    setattr(item, _BLOCKING_IO_DETECTOR_ATTR, detector)
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item: pytest.Item):
    yield
    detector = getattr(item, _BLOCKING_IO_DETECTOR_ATTR, None)
    if detector is None:
        return
    try:
        detector.__exit__(None, None, None)
        _blocking_io_probe.record(item.nodeid, detector.violations)
    finally:
        delattr(item, _BLOCKING_IO_DETECTOR_ATTR)


def pytest_sessionfinish(session: pytest.Session) -> None:
    if (
        _blocking_io_fail_enabled(session.config)
        and _blocking_io_probe.violation_count
        and session.exitstatus == pytest.ExitCode.OK
    ):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    if not _blocking_io_probe_enabled(terminalreporter.config):
        return
    header, *details = _blocking_io_probe.format_summary().splitlines()
    terminalreporter.write_sep("=", header)
    for line in details:
        terminalreporter.write_line(line)


def _blocking_io_probe_enabled(config: pytest.Config) -> bool:
    return bool(
        config.getoption("--detect-blocking-io")
        or config.getoption("--detect-blocking-io-fail")
    )


def _blocking_io_fail_enabled(config: pytest.Config) -> bool:
    return bool(config.getoption("--detect-blocking-io-fail"))


def _blocking_io_probe_skipped(item: pytest.Item) -> bool:
    return item.get_closest_marker("no_blocking_io_probe") is not None
