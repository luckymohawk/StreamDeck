# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['source/streamdeck_driver.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('source/scripts', 'scripts'),
        ('browsebuttons/dist', 'browsebuttons/dist'),
        ('source/run.sh', '.')
    ],
    hiddenimports=[
        'flask', 
        'platformdirs', 
        'PIL', 
        'StreamDeck',
        'jaraco.text',
        'pkg_resources._vendor'
    ],
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
    name='Streamdeck Commander_internal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file='entitlements.plist'
)

# This COLLECT step explicitly creates a 'onedir' structure
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Streamdeck Commander'
)

app = BUNDLE(
    coll, # We now bundle the collected directory
    name='Streamdeck Commander.app',
    icon='source/icon.icns',
    bundle_identifier='com.luckymcnulty.streamdeckcommander',
    executable='run.sh' # Keep our custom launcher script
)