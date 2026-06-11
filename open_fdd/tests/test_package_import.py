from __future__ import annotations


def test_core_imports_without_pandas():
    import open_fdd
    from open_fdd.arrow_runtime import run_arrow_rule
    from open_fdd.playground.sandbox import lint_python

    assert open_fdd.__version__
    assert callable(run_arrow_rule)
    assert callable(lint_python)
