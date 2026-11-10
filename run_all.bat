@echo off
rem Rebuild everything: download -> geoprocess -> validate -> project -> previews
rem Requires QGIS (OSGeo4W) - adjust QGIS_BIN if QGIS is installed elsewhere.
set QGIS_BIN=X:\QGIS\bin
cd /d "%~dp0scripts"
rem delete cached REST pages so the data is re-downloaded fresh
if exist "..\data\raw" rmdir /s /q "..\data\raw"
call "%QGIS_BIN%\python-qgis.bat" -u 01_download.py || goto :err
call "%QGIS_BIN%\python-qgis.bat" -u 02_process.py || goto :err
call "%QGIS_BIN%\python-qgis.bat" -u 03_validate.py || goto :err
call "%QGIS_BIN%\python-qgis.bat" -u 04_build_project.py || goto :err
call "%QGIS_BIN%\python-qgis.bat" -u 05_render_preview.py || goto :err
echo Done. Open CS12_Roadway_Enrichment.qgz in QGIS.
exit /b 0
:err
echo FAILED - see messages above.
exit /b 1
