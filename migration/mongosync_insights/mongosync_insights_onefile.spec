# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for a single-file macOS executable.
Used by build_macos.sh — do not use for the Linux RPM (see mongosync_insights.spec).
"""
import os
import importlib

block_cipher = None

certifi_path = os.path.join(
    os.path.dirname(importlib.import_module("certifi").__file__), "cacert.pem"
)

a = Analysis(
    ["mongosync_insights.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("templates", "templates"),
        ("images", "images"),
        ("static", "static"),
        ("lib/error_patterns.json", "lib"),
        ("lib/mongosync_metrics.json", "lib"),
        (certifi_path, "certifi"),
    ],
    hiddenimports=[
        "blueprints",
        "blueprints.logs",
        "blueprints.live",
        "lib.session_support",
        "lib.logs_metrics",
        "lib.migration_verifier",
        "lib.otel_metrics",
        "lib.snapshot_store",
        "lib.log_store",
        "lib.log_store_registry",
        "lib.log_store_maintenance",
        "lib.file_decompressor",
        "lib.utils",
        "lib.app_config",
        "lib.connection_validator",
        "lib.plot_theme",
        "plotly",
        "narwhals",
        "engineio.async_drivers.threading",
        "dns.resolver",
        "dns.rdatatype",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="mongosync-insights",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
)
