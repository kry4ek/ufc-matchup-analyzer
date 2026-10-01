# Build the portable Windows folder

Build on Windows x64. End users need none of these tools. Use Python 3.14.7, the locked wheels, matching official runtime/Tk components, and build-only Zig 0.15.2.

## Verified inputs

- Embed: `https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip`, SHA-256 `d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15`.
- Tcl/Tk: `https://www.python.org/ftp/python/3.14.7/amd64/tcltk.msi`, SHA-256 `4ae542ab046b3a1b2f10e6c1ee91a215cb4d0638aae373d6e0687472eb7170bd`. Its Authenticode signature was validated against the Python Software Foundation signer.
- Full installer: `https://www.python.org/ftp/python/3.14.7/python-3.14.7-amd64.exe`, SHA-256 `9d9eb2709ef81bf5cd30db3c2096bdbc4ea10087c22e62f27d356b36f6ae9649`.
- Build compiler wheel: `ziglang-0.15.2-py3-none-win_amd64.whl`, SHA-256 `ca80dc9c70dbdfdd9ee51d000de3501a95d33d9782ab9ab9b56f700484ebcd83`, checked against its PyPI release metadata.

Administratively extract the signed Tcl/Tk MSI into the build directory. This extracts files without installing/changing system Python:

```bat
msiexec /a "build-inputs\tcltk.msi" /qn TARGETDIR="C:\Build\tk-3.14.7"
.venv\Scripts\python.exe -m pip download --only-binary=:all: -r requirements.lock -d build-inputs\wheels
.venv\Scripts\python.exe -m zipfile -e build-inputs\ziglang-0.15.2-py3-none-win_amd64.whl build-inputs\zig
```

The actual matching 3.14.7 package contains Tcl/Tk **9.0.4**. Do not copy older developer-installation DLLs into the build. Explicit `_pth` entries isolate the interpreter from system Python; GUI components load from the packaged directory.

## Build, package, verify

From the source root with the matching snapshot installed:

```bat
.venv\Scripts\python.exe tools\build_portable.py --python-zip build-inputs\python-3.14.7-embed-amd64.zip --tk-root C:\Build\tk-3.14.7 --wheels build-inputs\wheels --zig build-inputs\zig\ziglang\zig.exe --out "dist\UFC Matchup Analyzer"
.venv\Scripts\python.exe tools\package_release.py --portable-folder "dist\UFC Matchup Analyzer" --out-dir release-assets
.venv\Scripts\python.exe tools\verify_archives.py --directory release-assets
```

The builder refuses existing output folders and uses wheel files rather than copying a virtual environment. The native launcher uses the Windows subsystem and system DLLs, without .NET. The review EXE is unsigned. No compiler, pip or developer environment is shipped to users.

Vendor test/example/benchmark directories are omitted; required code, native libraries, metadata and license notices remain. `BUILD_INFO.json` records input/launcher hashes and `PACKAGE_MANIFEST.json` inventories every file. Packaging verifies snapshot hashes and excludes live runtime state/caches.

Extract the actual ZIP into a new folder and use its bundled interpreter:

```bat
"dist\UFC Matchup Analyzer\runtime\python.exe" tools\check_portable.py --target men --full --offline --out verification\men\report.json
"dist\UFC Matchup Analyzer\runtime\python.exe" tools\check_portable.py --target women --full --offline --out verification\women\report.json
"dist\UFC Matchup Analyzer\UFC Matchup Analyzer.exe" --smoke-report verification\launcher.json
```

The GUI test covers real workers/models, historical filters, reversed order, clipboard and exports. Add `--screenshots docs\images` to capture its own window. The private `--smoke-report` option constructs the real window, checks components/datasets, records its result and closes automatically.

Run `tools\check_layout.py` with the bundled interpreter and `--out verification\layout.json` for simulated 100/125/150/200% Tk scaling and focus traversal. This does not replace tests at actual Windows display scales. Windows worker temporary files use an ASCII short path, or a temporary local DOS-device alias when short names are unavailable, while staying inside the app folder. Startup removes stale aliases from interrupted workers.

Use `tools\check_native_save.py --fixture verification\men\men-forward.json --out verification\save\report.json` with the bundled interpreter on an English Windows test machine. It operates only dialogs owned by its own process and writes to a new, empty QA folder; it tests the actual default filename, UTF-8 export, Save cancellation and declined overwrite.

For v0.3 also run `tools\check_usability_portable.py --out verification\usability\report.json` through the freshly extracted runtime. It checks real statistics-only operations, exact reuse, preview arrival, cancellation after preparation, disabled history and full offline HTML exports. Run `tools\benchmark_validation.py --out verification\validation-profile.json` from the source root to compare a single-pass hash/schema scan prototype with the existing separate scans. Full semantic validation remains mandatory.

Use `tools\check_native_html_save.py --fixture verification\men\men-forward.json --out verification\html-save\report.json` to verify the actual HTML Save action and `.html` default. `tools\check_history_gui.py --fixture verification\men\men-forward.json --out verification\history\report.json` checks opening history while training, retained cancellation previews, Delete/Clear actions and preservation of displayed results after a real maintenance failure.

Run `python -m unittest discover -s tests -v` and the men's sampled feature-parity tool. The CI workflow runs source safety checks with Python 3.14.7 on Windows, macOS and Linux; missing graphical displays/data are explicitly skipped in source-only CI. Those jobs do not establish portable or model readiness.

Also verify clean Windows 10/11 machines without Python/development tools. A developer-machine success is not clean-machine evidence. Record OS, versions, commands, timings, memory and unverified checks. The standard fully verified release gate requires documented dataset rights and every required check. The owner-requested experimental publication is recorded separately and does not mark the gate as passed; see [publishing](PUBLISHING.md).
