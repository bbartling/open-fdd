from __future__ import annotations

from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")
pytest.importorskip("nbclient")
pytest.importorskip("jupyter_client")
pytest.importorskip("matplotlib")
from nbclient import NotebookClient
from jupyter_client.kernelspec import KernelSpecManager


REPO_ROOT = Path(__file__).resolve().parents[3]


def _select_kernel_name() -> str:
    """Choose a usable kernel on CI/local; skip if none are installed."""
    ksm = KernelSpecManager()
    specs = ksm.find_kernel_specs()
    if "python3" in specs:
        return "python3"
    for candidate in ("python",):
        if candidate in specs:
            return candidate
    for name in specs:
        if "python" in name.lower():
            return name
    pytest.skip(f"No Jupyter kernel installed. Available kernels: {sorted(specs)}")


@pytest.mark.parametrize(
    "notebook_relpath",
    [
        "examples/RTU11/RTU11_engine_tutorial.ipynb",
        "examples/AHU7/run_and_viz_faults.ipynb",
        "examples/ML/ml_regression_fault_poc.ipynb",
    ],
)
def test_example_notebook_executes(notebook_relpath: str) -> None:
    """Regression check: example notebooks run from top to bottom."""
    nb_path = REPO_ROOT / notebook_relpath
    assert nb_path.exists(), f"Missing notebook: {nb_path}"

    with nb_path.open("r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)
    kernel_name = _select_kernel_name()

    # Normalize stale outputs before execution so old metadata doesn't break validation.
    for cell in nb.cells:
        if cell.get("cell_type") == "code":
            cell["execution_count"] = None
            cell["outputs"] = []

    client = NotebookClient(
        nb,
        timeout=300,
        kernel_name=kernel_name,
        resources={"metadata": {"path": str(REPO_ROOT)}},
    )
    client.execute()
