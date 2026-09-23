from pathlib import Path

project = Path(SPECPATH)
a = Analysis(
    [str(project / "app/offline_web_client_legacy.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[
        (str(project / "app/web"), "app/web"),
        (str(project / "app/resources"), "app/resources"),
    ],
    hiddenimports=["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                   "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["psycopg"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TopCityPOSOffline",
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TopCityPOSOffline")
