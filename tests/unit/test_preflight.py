import pytest

from qlnes.io.errors import QlnesError
from qlnes.io.preflight import Preflight


def test_run_with_no_checks_is_noop():
    Preflight().run()


def test_check_runs_in_added_order():
    seen: list[str] = []
    pf = Preflight()
    pf.add("first", lambda: seen.append("first"))
    pf.add("second", lambda: seen.append("second"))
    pf.add("third", lambda: seen.append("third"))
    pf.run()
    assert seen == ["first", "second", "third"]


def test_qlneserror_propagates():
    pf = Preflight()
    pf.add("bad_rom_check", lambda: (_ for _ in ()).throw(QlnesError("bad_rom", "not iNES")))
    with pytest.raises(QlnesError) as exc:
        pf.run()
    assert exc.value.cls == "bad_rom"


def test_unknown_exception_wraps_to_internal_error():
    pf = Preflight()
    pf.add("buggy_check", lambda: (_ for _ in ()).throw(RuntimeError("oops")))
    with pytest.raises(QlnesError) as exc:
        pf.run()
    assert exc.value.cls == "internal_error"
    assert "buggy_check" in exc.value.reason
    assert exc.value.extra["check"] == "buggy_check"


def test_first_failing_check_short_circuits():
    seen: list[str] = []

    def fail():
        seen.append("ran-fail")
        raise QlnesError("bad_rom", "x")

    def after():
        seen.append("ran-after")

    pf = Preflight()
    pf.add("ok", lambda: seen.append("ran-ok"))
    pf.add("fail", fail)
    pf.add("after", after)
    with pytest.raises(QlnesError):
        pf.run()
    assert seen == ["ran-ok", "ran-fail"]
