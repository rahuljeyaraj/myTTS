"""Entry point of myTTS.exe (PyInstaller needs a script, not a package's __main__)."""

import sys

from mytts.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
