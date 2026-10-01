# Third-party software

The portable app bundles official CPython 3.14.7 x64 and matching Tcl/Tk components from the signed Python 3.14.7 Windows distribution. Python's license is `runtime/LICENSE.txt`. Tcl/Tk license/copyright notices remain in the included library archives/components.

All 18 versions in `requirements.lock` are unpacked from matching wheels. `.dist-info` metadata, license files, native-library folders and vendored-library notices are retained. They include NumPy, pandas, SciPy, scikit-learn, joblib, threadpoolctl, requests, urllib3, Beautiful Soup, Soup Sieve, lxml, python-dateutil, six, typing-extensions, certifi, charset-normalizer, idna and tzdata. Their licenses differ from the project's MIT license; included metadata and notices are authoritative.

`BUILD_INFO.json` records runtime and wheel hashes plus Tcl/Tk file hashes. `PACKAGE_MANIFEST.json` inventories the entire distribution. Build-only Zig 0.15.2 compiles the MIT-licensed native launcher and is not shipped as a compiler. The launcher uses Windows system libraries and requires no .NET installation.

Developer setup scripts are in the source archive instead of the portable top level. Do not remove license files or required `.libs`/DLL folders while trimming. Dataset rights remain separate: see `DATA_NOTICE.md`. Bundling dependencies does not clear dataset redistribution rights.
