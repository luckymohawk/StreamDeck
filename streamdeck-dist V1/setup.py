from setuptools import setup
import glob

APP_NAME = "Streamdeck Commander"
APP_SCRIPT = 'source/streamdeck_driver.py'

# Data files are copied into the .app bundle's Contents/Resources directory
DATA_FILES = [
    ('scripts', glob.glob('source/scripts/*.applescript')),
    ('browsebuttons/dist', glob.glob('source/browsebuttons/dist/*.*')),
    ('browsebuttons/dist/assets', glob.glob('source/browsebuttons/dist/assets/*.*')),
    ('', ['source/streamdeck_db.py', 'source/icon.icns'])
]

OPTIONS = {
    'iconfile': 'source/icon.icns',
    # Entitlements are applied via the `codesign` command in the build-dmg.sh script,
    # which is the more reliable method for modern macOS.
    'plist': {
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': APP_NAME,
        'CFBundleIdentifier': "com.luckymcnulty.streamdeckcommander",
        'CFBundleVersion': "1.0.0",
        'LSUIElement': True,  # Runs as a background agent without a Dock icon
    },
    'packages': ['flask', 'flask_cors', 'PIL', 'StreamDeck', 'setuptools'],
    'includes': ['six', 'packaging', 'shlex', 'threading'],
}

setup(
    app=[APP_SCRIPT],
    name=APP_NAME,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
