#!/usr/bin/env python3
"""
DDOT GIS Operations - end-to-end build of the submission deliverable.

Assembles <output-dir>/<First>_<MI>_<Last>_GIS/ and <First>_<MI>_<Last>_GIS.zip:

  1. Copies the deliverable scripts and README into the project folder.
  2. Runs 01_pull_and_process_data.py with this interpreter (needs geopandas).
  3. Runs 02_create_qgis_project.py with a PyQGIS-capable interpreter
     (auto-detected, or --qgis-python / $QGIS_PYTHON) to export one shapefile
     per PDF filter / question to shapefiles/, build and validate
     ddot_maintenance_operations.qgz and package the zip.
  4. Optionally opens the project in QGIS Desktop.

Examples:
    .venv/bin/python generate_and_launch_gis.py Jane_Q_Public
    .venv/bin/python generate_and_launch_gis.py Jane_Q_Public_GIS_V2      # versioned deliverable
    .venv/bin/python generate_and_launch_gis.py --first-name Jane --middle-initial Q --last-name Public
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

HERE = Path(__file__).resolve().parent
SOURCE_DIR = HERE  # the repository root is the deliverable source
SHIPPED_FILES = ("01_pull_and_process_data.py", "README.md")  # 02 is a working script, run from here
STEP1 = "01_pull_and_process_data.py"
STEP2 = "02_create_qgis_project.py"
QGZ_NAME = "ddot_maintenance_operations.qgz"
SHP_DIR = "shapefiles"


def _load_step2():
    """Import 02_create_qgis_project for its stdlib-only naming helper."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("create_qgis_project", SOURCE_DIR / STEP2)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clean_env(headless: bool = True) -> dict[str, str]:
    """Environment for a foreign interpreter: drop this venv's Python settings."""
    env = {k: v for k, v in os.environ.items() if k not in {"VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"}}
    venv_bin = os.environ.get("VIRTUAL_ENV")
    if venv_bin:
        prefix = str(Path(venv_bin) / ("Scripts" if os.name == "nt" else "bin"))
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p != prefix)
    if headless:
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return env


def qgis_python_candidates() -> list[str]:
    cands: list[str] = []
    if os.environ.get("QGIS_PYTHON"):
        cands.append(os.environ["QGIS_PYTHON"])
    cands.append(sys.executable)
    if sys.platform == "win32":
        for root in ("C:/Program Files/QGIS*", "C:/OSGeo4W*", "C:/Program Files/OSGeo4W*"):
            for d in sorted(glob.glob(root), reverse=True):
                cands += [f"{d}/bin/python-qgis-ltr.bat", f"{d}/bin/python-qgis.bat"]
    elif sys.platform == "darwin":
        for app in sorted(glob.glob("/Applications/QGIS*.app"), reverse=True):
            cands.append(f"{app}/Contents/MacOS/bin/python3")
    else:
        cands += ["/usr/bin/python3", "/usr/local/bin/python3"]
    seen, out = set(), []
    for c in cands:
        if c not in seen and (Path(c).exists() or shutil.which(c)):
            seen.add(c)
            out.append(c)
    return out


def find_qgis_python(explicit: str | None) -> str:
    candidates = [explicit] if explicit else qgis_python_candidates()
    for exe in candidates:
        try:
            r = subprocess.run(
                [exe, "-c", "import qgis.core"],
                env=_clean_env(), capture_output=True, timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0:
            return exe
    raise SystemExit(
        "Could not find a Python interpreter with PyQGIS. Tried: "
        + (", ".join(candidates) or "(none)")
        + ". Pass --qgis-python or set QGIS_PYTHON."
    )


def launch_qgis(qgz: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(qgz)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(qgz)])
        else:
            cmd = [shutil.which("qgis"), str(qgz)] if shutil.which("qgis") else ["xdg-open", str(qgz)]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, env=_clean_env(headless=False))
        print(f"Launched QGIS with {qgz}")
    except OSError as exc:
        print(f"Could not launch QGIS automatically ({exc}); open {qgz} manually.", file=sys.stderr)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?",
                    help="candidate name as First_M_Last, optionally ending in _GIS or _GIS_V<n>, e.g. Jane_Q_Public_GIS_V2")
    ap.add_argument("--first-name")
    ap.add_argument("--middle-initial")
    ap.add_argument("--last-name")
    ap.add_argument("--version-label", help="deliverable version suffix, e.g. V2 -> <First>_<MI>_<Last>_GIS_V2")
    ap.add_argument("--output-dir", type=Path, default=HERE / "build", help="default: ./build")
    ap.add_argument("--qgis-python", help="interpreter able to `import qgis.core` (default: auto-detect)")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="reuse the existing GeoPackage instead of re-running step 01")
    ap.add_argument("--no-launch", action="store_true", help="do not open QGIS at the end")
    ap.add_argument("--no-live-layers", action="store_true", help="omit live REST feeds from the project")
    ap.add_argument("--no-shapefiles", action="store_true", help="skip the per-filter shapefile export")
    ap.add_argument("--tolerance-ft", help="forwarded to step 01")
    ap.add_argument("--crs", help="forwarded to step 01")
    args = ap.parse_args(argv)

    flags = (args.first_name, args.middle_initial, args.last_name)
    if args.name:
        if any(flags):
            ap.error("give the name either positionally or with --first-name/--middle-initial/--last-name, not both")
        try:
            args.first_name, args.middle_initial, args.last_name, version = split_name(args.name)
        except ValueError as exc:
            ap.error(str(exc))
        if version and args.version_label and version.upper() != args.version_label.upper():
            ap.error(f"name says {version} but --version-label says {args.version_label}")
        args.version_label = args.version_label or version
    elif not all(flags):
        ap.error("a name is required: e.g. Jane_Q_Public, or --first-name, --middle-initial and --last-name")
    return args


def split_name(name: str) -> tuple[str, str, str, str | None]:
    """'jane_q_public' / 'Jane_Q_Public_GIS' / 'Jane_Q_Public_GIS_V2' -> (first, mi, last, version|None)."""
    parts = [p for p in name.strip().split("_") if p]
    version = None
    if len(parts) == 5 and parts[3].upper() == "GIS" and re.fullmatch(r"[Vv][1-9][0-9]*", parts[4]):
        parts, version = parts[:4], parts[4].upper()
    if len(parts) == 4 and parts[-1].upper() == "GIS":
        parts = parts[:3]
    if len(parts) != 3:
        raise ValueError(f"name {name!r} must look like First_M_Last (optionally ending in _GIS or _GIS_V<n>)")
    return parts[0], parts[1], parts[2], version


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        root_name = _load_step2().package_name(
            args.first_name, args.middle_initial, args.last_name, args.version_label
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    output_dir = args.output_dir.resolve()
    project_dir = output_dir / root_name
    project_dir.mkdir(parents=True, exist_ok=True)
    for name in SHIPPED_FILES:
        shutil.copy2(SOURCE_DIR / name, project_dir / name)

    if args.skip_fetch:
        if not (project_dir / "data" / "ddot_maintenance_operations.gpkg").exists():
            print("error: --skip-fetch given but no GeoPackage exists yet", file=sys.stderr)
            return 2
    else:
        cmd = [sys.executable, str(project_dir / STEP1), "--out-dir", str(project_dir)]
        if args.tolerance_ft:
            cmd += ["--tolerance-ft", args.tolerance_ft]
        if args.crs:
            cmd += ["--crs", args.crs]
        if subprocess.run(cmd).returncode != 0:
            print("error: step 01 failed - see logs/geoprocessing_history.log", file=sys.stderr)
            return 1

    qgis_python = find_qgis_python(args.qgis_python)
    print(f"Using PyQGIS interpreter: {qgis_python}", flush=True)
    cmd = [
        qgis_python, str(SOURCE_DIR / STEP2),
        "--project-dir", str(project_dir), "--zip-dir", str(output_dir),
        "--first-name", args.first_name, "--middle-initial", args.middle_initial, "--last-name", args.last_name,
    ]
    if args.version_label:
        cmd += ["--version-label", args.version_label]
    if args.no_live_layers:
        cmd.append("--no-live-layers")
    if args.no_shapefiles:
        cmd.append("--no-shapefiles")
    if subprocess.run(cmd, env=_clean_env()).returncode != 0:
        print("error: step 02 failed - see logs/geoprocessing_history.log", file=sys.stderr)
        return 1

    zip_path = output_dir / f"{root_name}.zip"
    print("=" * 72)
    print(f"Project folder : {project_dir}")
    if not args.no_shapefiles:
        print(f"Shapefiles     : {project_dir / SHP_DIR}")
    print(f"Deliverable    : {zip_path}")
    print("=" * 72)

    if not args.no_launch:
        launch_qgis(project_dir / QGZ_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
