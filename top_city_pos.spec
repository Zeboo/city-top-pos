from pathlib import Path

project = Path(SPECPATH)
hiddenimports = ["app.database.database", "app.models.models", "app.services.pos_service"]

a = Analysis(
    [str(project / "app" / "main.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / "app" / "resources"), "app/resources")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TopCityPOS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None,
)
