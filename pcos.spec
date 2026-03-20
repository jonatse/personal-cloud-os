# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec file for Personal Cloud OS
#
# Build with:
#   cd /home/jonathan/project
#   pyinstaller pcos.spec
#
# Output: dist/pcos/  — complete self-contained directory
#         dist/pcos/pcos  — the executable
#
# See BUILD.md for full instructions.

import os
import sys

SRC = os.path.abspath('src')
VENDOR = os.path.join(SRC, 'vendor')
BIN = os.path.join(SRC, 'bin')

block_cipher = None

a = Analysis(
    [os.path.join(SRC, 'main.py')],
    pathex=[SRC, VENDOR],
    binaries=[
        # Bundle the i2pd binary into dist/pcos/bin/
        (os.path.join(BIN, 'i2pd'), 'bin'),
        # Vendored compiled extensions
        (os.path.join(VENDOR, 'cryptography', 'hazmat', 'bindings', '_rust.abi3.so'),
         'cryptography/hazmat/bindings'),
        (os.path.join(VENDOR, 'psutil', '_psutil_linux.abi3.so'), 'psutil'),
        (os.path.join(VENDOR, 'psutil', '_psutil_posix.abi3.so'), 'psutil'),
    ],
    datas=[
        # App source packages
        (os.path.join(SRC, 'core'),      'core'),
        (os.path.join(SRC, 'services'),  'services'),
        (os.path.join(SRC, 'cli'),       'cli'),
        (os.path.join(SRC, 'tray'),      'tray'),
        (os.path.join(SRC, 'container'), 'container'),
        (os.path.join(SRC, 'ui'),        'ui'),
        (os.path.join(SRC, 'shelf'),     'shelf'),
        # Vendor pure-Python packages (PyInstaller handles .so files via binaries above)
        (os.path.join(VENDOR, 'RNS'),    'RNS'),
        (os.path.join(VENDOR, 'serial'), 'serial'),
    ],
    hiddenimports=[
        # RNS interfaces loaded dynamically
        'RNS.Interfaces.AutoInterface',
        'RNS.Interfaces.TCPInterface',
        'RNS.Interfaces.UDPInterface',
        'RNS.Interfaces.I2PInterface',
        'RNS.Interfaces.LocalInterface',
        'RNS.Interfaces.SerialInterface',
        'RNS.Interfaces.Android',
        # RNS vendor deps
        'RNS.vendor.configobj',
        'RNS.vendor.platformutils',
        'RNS.vendor.umsgpack',
        'RNS.vendor.i2plib',
        # cryptography internals loaded via importlib
        'cryptography.hazmat.primitives.asymmetric.x25519',
        'cryptography.hazmat.primitives.asymmetric.ed25519',
        'cryptography.hazmat.backends.openssl',
        # stdlib modules that may be missed
        'curses',
        'curses.textpad',
        '_curses',
        'tkinter',
        'tkinter.ttk',
        'asyncio',
        'logging.handlers',
        'socket',
        'threading',
        'subprocess',
        'json',
        'hashlib',
        'platform',
        'uuid',
    ],
    excludes=[
        # Things we explicitly don't need
        'PIL',
        'Pillow',
        'pystray',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'PyQt5',
        'PyQt6',
        'wx',
        'gi',
        'gtk',
        'test',
        'unittest',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# .so files handled via datas + binaries in Analysis() above

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='pcos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,       # don't compress — UPX can cause false positive AV flags
    console=True,    # CLI app
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True,
    upx=False,
    upx_exclude=[],
    name='pcos',
)
