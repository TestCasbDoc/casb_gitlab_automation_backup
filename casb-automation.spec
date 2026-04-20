# casb-automation.spec
# PyInstaller spec file for CASB Automation Framework
# Build: pyinstaller casb-automation.spec

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect all app yaml files and package data
added_files = [
    ("apps", "apps"),
    ("core", "core"),
    ("config.py", "."),
]

# Collect playwright data files
try:
    added_files += collect_data_files("playwright")
except Exception:
    pass

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        # Core deps
        "paramiko",
        "paramiko.transport",
        "paramiko.auth_handler",
        "paramiko.channel",
        "paramiko.client",
        "paramiko.config",
        "paramiko.dsskey",
        "paramiko.ecdsakey",
        "paramiko.ed25519key",
        "paramiko.rsakey",
        "paramiko.sftp",
        "paramiko.sftp_client",
        "paramiko.ssh_exception",
        # pywinauto
        "pywinauto",
        "pywinauto.application",
        "pywinauto.desktop",
        "pywinauto.findwindows",
        # Playwright
        "playwright",
        "playwright.sync_api",
        "playwright._impl._sync_base",
        # YAML
        "yaml",
        # Crypto
        "cryptography",
        "OpenSSL",
        "OpenSSL.SSL",
        # Standard lib
        "email.mime.multipart",
        "email.mime.text",
        "email.mime.base",
        "smtplib",
        "zipfile",
        "tempfile",
        "threading",
        "subprocess",
        "json",
        "socket",
        "ssl",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "flask",
        "waitress",
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="casb-automation",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,           # Keep console open — needed for log output
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
