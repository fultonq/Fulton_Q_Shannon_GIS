"""Local-only tests for the 02_create_qgis_project.py working script (not part of the deliverable)."""
import os
import subprocess
import sys
import zipfile

import pytest

from conftest import ROOT, _load

STEP2 = ROOT / "02_create_qgis_project.py"
pytestmark = pytest.mark.skipif(not STEP2.exists(), reason="local working script not present")


@pytest.fixture(scope="module")
def project():
    return _load("create_qgis_project", STEP2)


@pytest.mark.parametrize(
    "parts, expected",
    [
        (("Jane", "q", "Public"), "Jane_Q_Public_GIS"),
        (("Mary-Ann", "B", "O'Neil"), "Mary-Ann_B_ONeil_GIS"),
        (("fulton", "q", "shannon"), "Fulton_Q_Shannon_GIS"),
    ],
)
def test_package_name(project, parts, expected):
    assert project.package_name(*parts) == expected


@pytest.mark.parametrize("parts", [("", "Q", "X"), ("Jane", "QR", "X"), ("Jane", "Q", "../etc"), ("J4ne", "Q", "X")])
def test_package_name_rejects_bad_input(project, parts):
    with pytest.raises(ValueError):
        project.package_name(*parts)


def test_package_project_layout_and_exclusions(project, tmp_path):
    proj = tmp_path / "work"
    (proj / "data").mkdir(parents=True)
    (proj / "logs").mkdir()
    (proj / "data" / "ddot_maintenance_operations.gpkg").write_bytes(b"gpkg")
    (proj / "data" / "ddot_maintenance_operations.gpkg-wal").write_bytes(b"x")
    (proj / "data" / ".ddot_maintenance_operations.tmp.gpkg").write_bytes(b"x")
    (proj / "__pycache__").mkdir()
    (proj / "__pycache__" / "m.cpython-313.pyc").write_bytes(b"x")
    (proj / "ddot_maintenance_operations.qgz").write_bytes(b"qgz")
    (proj / "ddot_maintenance_operations.qgz~").write_bytes(b"backup")
    (proj / "README.md").write_text("r")
    (proj / "logs" / "geoprocessing_history.log").write_text("l")

    out = tmp_path / "Jane_Q_Public_GIS.zip"
    names = project.package_project(proj, out, "Jane_Q_Public_GIS")

    assert sorted(names) == [
        "Jane_Q_Public_GIS/README.md",
        "Jane_Q_Public_GIS/data/ddot_maintenance_operations.gpkg",
        "Jane_Q_Public_GIS/ddot_maintenance_operations.qgz",
        "Jane_Q_Public_GIS/logs/geoprocessing_history.log",
    ]
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None
    assert oct(out.stat().st_mode & 0o777) == "0o644"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".pkg-")] == []


def test_package_refuses_zip_inside_project(project, tmp_path):
    with pytest.raises(ValueError):
        project.package_project(tmp_path, tmp_path / "x.zip", "X_Y_Z_GIS")


def test_step02_reports_missing_pyqgis(project, tmp_path):
    """Run under this (QGIS-less) interpreter: must fail with a clear message, not a traceback."""
    try:
        import qgis.core  # noqa: F401
        pytest.skip("PyQGIS is importable here")
    except ImportError:
        pass
    r = subprocess.run(
        [sys.executable, project.__file__, "--project-dir", str(tmp_path), "--no-package"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0 and "PyQGIS is not importable" in r.stderr


def test_package_name_with_version(project):
    assert project.package_name("fulton", "q", "shannon", "v2") == "Fulton_Q_Shannon_GIS_V2"
    with pytest.raises(ValueError):
        project.package_name("fulton", "q", "shannon", "2")


def test_package_excludes_repo_tooling(project, tmp_path):
    repo = tmp_path / "repo"
    for rel in (".git/config", ".venv/bin/python", "tests/test_x.py", "build/x.zip", ".idea/misc.xml",
                "build_tool.py", "02_create_qgis_project.py", "requirements.txt", "requirements-dev.txt", "pytest.ini",
                ".gitignore", "README.md", "01_pull_and_process_data.py", "data/ddot_maintenance_operations.gpkg"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x")
    names = project.package_project(repo, tmp_path / "out.zip", "N_Q_X_GIS_V2")
    assert sorted(names) == [
        "N_Q_X_GIS_V2/01_pull_and_process_data.py",
        "N_Q_X_GIS_V2/README.md",
        "N_Q_X_GIS_V2/data/ddot_maintenance_operations.gpkg",
    ]


def test_shapefile_exports_fit_dbf_limits(project):
    stems = [stem for stem, *_ in project.SHAPEFILE_EXPORTS]
    assert len(stems) == len(set(stems)) == 6
    for stem, _display, _layer, _subset, field_map, _answers in project.SHAPEFILE_EXPORTS:
        names = [dst for _, dst in field_map]
        assert all(1 <= len(n) <= 10 for n in names), stem
        assert len({n.upper() for n in names}) == len(names), f"duplicate DBF field in {stem}"


def test_package_ships_shapefiles_but_not_interrupted_export(project, tmp_path):
    proj = tmp_path / "work"
    for rel in ("shapefiles/permits_filtered_snapped.shp", "shapefiles/field_crosswalk.csv",
                ".shp-abc123/permits_filtered_snapped.shp"):
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text("x")
    names = project.package_project(proj, tmp_path / "out.zip", "N_Q_X_GIS")
    assert sorted(names) == [
        "N_Q_X_GIS/shapefiles/field_crosswalk.csv",
        "N_Q_X_GIS/shapefiles/permits_filtered_snapped.shp",
    ]
