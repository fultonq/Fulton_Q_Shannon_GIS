import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DELIVERABLE = ROOT


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def process():
    return _load("pull_and_process_data", DELIVERABLE / "01_pull_and_process_data.py")


@pytest.fixture(scope="session")
def project():
    return _load("create_qgis_project", DELIVERABLE / "02_create_qgis_project.py")


@pytest.fixture(scope="session")
def runner():
    return _load("generate_and_launch_gis", ROOT / "generate_and_launch_gis.py")
