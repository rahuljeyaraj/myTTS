# Third-party notices

myTTS 0.1.0 for Windows (the installer and myTTS.exe) includes the software below. The license texts are in the `licenses` folder next to myTTS.exe (`%LOCALAPPDATA%\Programs\mytts\licenses` by default).

## How myTTS is licensed

- The myTTS source code is MIT licensed (`myTTS-LICENSE.txt`, and https://github.com/rahuljeyaraj/myTTS).
- The program as distributed includes eSpeak NG and phonemizer, which are GPL-3.0-or-later. So the installer and myTTS.exe as a whole are distributed under the terms of the GNU GPL version 3 (`GPL-3.0.txt`). The MIT license is compatible with the GPL, and each part keeps its own license.
- The complete source of myTTS for each release is the matching tag in the repository. The eSpeak NG source of the version it bundles is attached to each release.
- The voice model (Kokoro-82M, Apache-2.0) is not part of the installer: setup downloads it.

## Components

| Component | Version | License | What it is |
|---|---|---|---|
| [cffi](https://github.com/python-cffi/cffi) | 2.1.1 | MIT-0 | Python package |
| [cloudpickle](https://github.com/cloudpipe/cloudpickle) | 3.1.2 | BSD-3-Clause | Python package |
| [dlinfo](https://github.com/fphammerle/python-dlinfo) | 2.0.0 | MIT | Python package |
| [espeakng-loader](https://github.com/thewh1teagle/espeakng-loader) | 0.2.4 | MIT | Python package |
| [joblib](https://joblib.readthedocs.io) | 1.6.0 | BSD-3-Clause | Python package |
| [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | 0.6.1 | MIT | Python package |
| [numpy](https://numpy.org) | 2.2.6 | BSD-3-Clause (bundled OpenBLAS: BSD-3-Clause; see its license files) | Python package |
| [onnxruntime](https://onnxruntime.ai) | 1.23.2 | MIT License | Python package |
| [phonemizer](https://github.com/bootphon/phonemizer) | 3.6.0 | GPL-3.0-or-later | Python package |
| [pyreadline3](https://github.com/pyreadline3/pyreadline3) | 3.5.6 | BSD | Python package |
| [PySide6_Essentials](https://pyside.org) | 6.12.0 | LGPL-3.0-only (used under the LGPL) | Python package |
| [shiboken6](https://pyside.org) | 6.12.0 | LGPL-3.0-only (used under the LGPL) | Python package |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice/) | 0.5.6 | MIT | Python package |
| [typing_extensions](https://github.com/python/typing_extensions) | 4.16.0 | PSF-2.0 | Python package |
| [Python](https://www.python.org/) | 3.10.11 | PSF-2.0 | the Python runtime (python310.dll and the standard library), with the libraries it bundles: OpenSSL 1.1, libffi, bzip2, xz, zlib, expat and mpdecimal |
| [Qt](https://www.qt.io/) | 6.12.0 | LGPL-3.0-only | Qt6Core, Qt6Gui, Qt6Network and Qt6Widgets and the Windows platform plugin, through PySide6 |
| [eSpeak NG](https://github.com/espeak-ng/espeak-ng) | 1.52.0 | GPL-3.0-or-later | espeak-ng.dll and espeak-ng-data (turns text into phonemes), from espeakng-loader |
| [PortAudio](https://www.portaudio.com/) | PortAudio V19.7.0-devel, revision unknown | MIT | libportaudio64bit.dll (audio output), from sounddevice |
| [PyInstaller bootloader](https://pyinstaller.org/) | 6.22.3 | GPL-2.0-or-later WITH Bootloader-exception | the start-up code in myTTS.exe |

## Details

### cffi 2.1.1

- License: MIT-0
- Project: https://github.com/python-cffi/cffi
- License files: `cffi/LICENSE`

### cloudpickle 3.1.2

- License: BSD-3-Clause
- Project: https://github.com/cloudpipe/cloudpickle
- License files: `cloudpickle/LICENSE`

### dlinfo 2.0.0

- License: MIT
- Project: https://github.com/fphammerle/python-dlinfo
- License files: `dlinfo/LICENSE`

### espeakng-loader 0.2.4

- License: MIT
- Project: https://github.com/thewh1teagle/espeakng-loader
- License files: `espeakng-loader/LICENSE`

### joblib 1.6.0

- License: BSD-3-Clause
- Project: https://joblib.readthedocs.io
- License files: `joblib/LICENSE.txt`

### kokoro-onnx 0.6.1

- License: MIT
- Project: https://github.com/thewh1teagle/kokoro-onnx
- License files: `kokoro-onnx/LICENSE`

### numpy 2.2.6

- License: BSD-3-Clause (bundled OpenBLAS: BSD-3-Clause; see its license files)
- Project: https://numpy.org
- License files: `numpy/LICENSE.txt`, `numpy/numpy-_core-include-numpy-random-LICENSE.txt`, `numpy/numpy-ma-LICENSE`, `numpy/numpy-random-LICENSE.md`

### onnxruntime 1.23.2

- License: MIT License
- Project: https://onnxruntime.ai
- License files: `onnxruntime/onnxruntime-LICENSE`, `onnxruntime/onnxruntime-ThirdPartyNotices.txt`

### phonemizer 3.6.0

- License: GPL-3.0-or-later
- Project: https://github.com/bootphon/phonemizer
- License files: `phonemizer/LICENSE`

### pyreadline3 3.5.6

- License: BSD
- Project: https://github.com/pyreadline3/pyreadline3
- License files: `pyreadline3/LICENSE.md`

### PySide6_Essentials 6.12.0

- License: LGPL-3.0-only (used under the LGPL)
- Project: https://pyside.org
- License files: `LGPL-3.0.txt`

### shiboken6 6.12.0

- License: LGPL-3.0-only (used under the LGPL)
- Project: https://pyside.org
- License files: `LGPL-3.0.txt`

### sounddevice 0.5.6

- License: MIT
- Project: https://github.com/spatialaudio/python-sounddevice/
- License files: `sounddevice/LICENSE`

### typing_extensions 4.16.0

- License: PSF-2.0
- Project: https://github.com/python/typing_extensions
- License files: `typing_extensions/LICENSE`

### Python 3.10.11

- License: PSF-2.0
- Project: https://www.python.org/
- License files: `Python/LICENSE.txt`

### Qt 6.12.0

- License: LGPL-3.0-only
- Project: https://www.qt.io/
- License files: `LGPL-3.0.txt`, `GPL-3.0.txt`
- The Qt libraries are separate DLLs in the _internal\PySide6 folder, so you can replace them with your own build of the same Qt version. Third-party code inside Qt and its licenses: https://doc.qt.io/qt-6/licenses-used-in-qt.html

### eSpeak NG 1.52.0

- License: GPL-3.0-or-later
- Project: https://github.com/espeak-ng/espeak-ng
- License files: `GPL-3.0.txt`
- Built without changes from the upstream tag 1.52.0 (commit 4870adfa25b1a32b4361592f1be8a40337c58d6c). The source is at https://github.com/espeak-ng/espeak-ng/tree/1.52.0 and is attached to every myTTS release.

### PortAudio PortAudio V19.7.0-devel, revision unknown

- License: MIT
- Project: https://www.portaudio.com/
- License files: `PortAudio.txt`

### PyInstaller bootloader 6.22.3

- License: GPL-2.0-or-later WITH Bootloader-exception
- Project: https://pyinstaller.org/
- License files: `PyInstaller/COPYING.txt`
- The bootloader exception allows distributing programs built with PyInstaller under any license.

## Downloaded by setup (not in the installer)

### Kokoro-82M voice model

- License: Apache-2.0 (`Apache-2.0.txt`)
- Model: https://huggingface.co/hexgrad/Kokoro-82M, by hexgrad
- The ONNX files `kokoro-v1.0.onnx` and `voices-v1.0.bin` come from the kokoro-onnx project (https://github.com/thewh1teagle/kokoro-onnx, release model-files-v1.1). Setup checks their SHA-256.

## Microsoft runtime files

`vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140*.dll`, `ucrtbase.dll` and the `api-ms-win-*.dll` files are Microsoft Visual C++ and Universal C runtime files, redistributed as Microsoft allows.
