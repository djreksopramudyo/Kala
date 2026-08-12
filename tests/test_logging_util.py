"""Shared-logger tests: a swallowed data-path error must leave a trace."""

import logging

from kala import logging_util


def test_get_logger_is_singleton_and_named():
    a = logging_util.get_logger()
    b = logging_util.get_logger()
    assert a is b
    assert a.name == "kala"


def test_log_swallowed_writes_a_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="kala"):
        # the logger doesn't propagate (own file handler), so attach caplog's
        logging_util.get_logger().addHandler(caplog.handler)
        try:
            raise ValueError("boom")
        except ValueError as e:
            logging_util.log_swallowed("unit_test_context", e)
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "unit_test_context" in msgs
    assert "ValueError" in msgs
    assert "boom" in msgs


def test_log_swallowed_never_raises():
    # even with a nonsense context/exc it must be safe (logging can't break a run)
    logging_util.log_swallowed("ctx", RuntimeError("x"))
