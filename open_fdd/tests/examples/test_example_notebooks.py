from __future__ import annotations

from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")
pytest.importorskip("nbclient")
pytest.importorskip("matplotlib")
from nbclient import NotebookClient


REPO_ROOT = Path(__file__).resolve().parents[3]


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

    # Normalize stale outputs before execution so old metadata doesn't break validation.
    for cell in nb.cells:
        if cell.get("cell_type") == "code":
            cell["execution_count"] = None
            cell["outputs"] = []

    client = NotebookClient(
        nb,
        timeout=300,
        kernel_name="python3",
        resources={"metadata": {"path": str(REPO_ROOT)}},
    )
    client.execute()
