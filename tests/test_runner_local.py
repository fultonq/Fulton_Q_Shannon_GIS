"""Local-only tests for the build runner (not part of the deliverable)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import ROOT, _load  # noqa: E402

RUNNER = ROOT / "generate_and_launch_gis.py"
pytestmark = pytest.mark.skipif(not RUNNER.exists(), reason="local build runner not present")


@pytest.fixture(scope="module")
def project():
    return _load("create_qgis_project", ROOT / "02_create_qgis_project.py")


@pytest.fixture(scope="module")
def runner():
    return _load("generate_and_launch_gis", RUNNER)


def test_runner_requires_names(runner):
    with pytest.raises(SystemExit):
        runner.parse_args([])


@pytest.mark.parametrize("name", ["fulton_q_shannon_gis", "Fulton_Q_Shannon", "fulton_q_shannon_GIS"])
def test_runner_accepts_positional_name(runner, project, name):
    args = runner.parse_args([name])
    assert project.package_name(args.first_name, args.middle_initial, args.last_name) == "Fulton_Q_Shannon_GIS"


@pytest.mark.parametrize("argv", [["fulton_shannon"], ["a_b_c_d_e"], ["Jane_Q_Public", "--first-name", "X"]])
def test_runner_rejects_ambiguous_names(runner, argv):
    with pytest.raises(SystemExit):
        runner.parse_args(argv)


def test_runner_rejects_invalid_name(runner, capsys):
    assert runner.main(["--first-name", "J4ne", "--middle-initial", "Q", "--last-name", "P", "--no-launch"]) == 2


def test_clean_env_strips_venv(runner, monkeypatch):
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setenv("VIRTUAL_ENV", "/v")
    monkeypatch.setenv("PYTHONPATH", "/p")
    monkeypatch.setenv("PATH", os.pathsep.join(["/v/bin", "/usr/bin"]))
    env = runner._clean_env()
    assert "VIRTUAL_ENV" not in env and "PYTHONPATH" not in env
    assert env["PATH"] == "/usr/bin" and env["QT_QPA_PLATFORM"] == "offscreen"
    assert "QT_QPA_PLATFORM" not in runner._clean_env(headless=False)


@pytest.mark.parametrize("name, version", [("fulton_q_shannon_gis_v2", "V2"), ("Fulton_Q_Shannon_GIS_V10", "V10"),
                                           ("fulton_q_shannon", None)])
def test_runner_parses_version_from_name(runner, name, version):
    args = runner.parse_args([name])
    assert args.version_label == version and args.last_name.lower() == "shannon"


def test_runner_rejects_conflicting_version(runner):
    with pytest.raises(SystemExit):
        runner.parse_args(["fulton_q_shannon_gis_v2", "--version-label", "V3"])


def test_runner_accepts_no_shapefiles(runner):
    assert runner.parse_args(["Jane_Q_Public", "--no-shapefiles"]).no_shapefiles
    assert not runner.parse_args(["Jane_Q_Public"]).no_shapefiles
