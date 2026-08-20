"""Generator finalization under MicroPython.

Regression guard for the sprint 006 ticket 009 defect: `motion.drive()`
lands a neutral in a `finally`, and breaking out of a `for` loop does
NOT run it here, though it does on CPython. `MoveHandle.stop()` exists
precisely because this is true. If a future MicroPython makes `break`
close the generator promptly, `test_break_does_not_finalize` starts
failing -- that is a signal to revisit the API, not a test to delete.
"""

from _harness import check, check_eq, report


def _gen(log):
    try:
        for i in range(100):
            yield i
    finally:
        log.append("finally")


def test_break_does_not_finalize():
    log = []
    for x in _gen(log):
        if x == 3:
            break
    check("break alone does not run finally", log == [],
          "log=%r -- if this now runs, MoveHandle.stop() may be redundant" % (log,))


def test_gc_collect_does_not_finalize():
    log = []
    for x in _gen(log):
        if x == 3:
            break
    import gc
    gc.collect()
    check("gc.collect() does not run finally", log == [], "log=%r" % (log,))


def test_close_does_finalize():
    log = []
    g = _gen(log)
    next(g)
    g.close()
    check_eq("close() runs finally", log, ["finally"])


def test_close_is_idempotent():
    log = []
    g = _gen(log)
    next(g)
    g.close()
    g.close()
    check_eq("close() twice runs finally once", log, ["finally"])


def test_exhaustion_finalizes():
    log = []
    for _ in _gen(log):
        pass
    check_eq("running to completion runs finally", log, ["finally"])


def test_close_after_exhaustion_is_noop():
    log = []
    g = _gen(log)
    for _ in g:
        pass
    g.close()
    check_eq("close() after exhaustion does not re-run finally", log, ["finally"])


def test_wrapper_stop_pattern():
    """The MoveHandle shape: __iter__/__next__ delegate, stop() closes."""
    log = []

    class Handle:
        def __init__(self, gen):
            self._gen = gen
            self._stopped = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self._gen)

        def stop(self):
            if self._stopped:
                return
            self._stopped = True
            self._gen.close()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.stop()
            return False

    h = Handle(_gen(log))
    for x in h:
        if x == 3:
            h.stop()
            break
    check_eq("stop() lands the finally after break", log, ["finally"])

    log2 = []
    with Handle(_gen(log2)) as h2:
        for x in h2:
            if x == 3:
                break
    check_eq("with-block lands the finally on break", log2, ["finally"])

    log3 = []
    try:
        with Handle(_gen(log3)) as h3:
            for x in h3:
                if x == 3:
                    raise ValueError("boom")
    except ValueError:
        pass
    check_eq("with-block lands the finally on exception", log3, ["finally"])


test_break_does_not_finalize()
test_gc_collect_does_not_finalize()
test_close_does_finalize()
test_close_is_idempotent()
test_exhaustion_finalizes()
test_close_after_exhaustion_is_noop()
test_wrapper_stop_pattern()
report("generator_semantics")
