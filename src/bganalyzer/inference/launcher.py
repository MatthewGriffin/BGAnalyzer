"""Linux child launcher: terminate owned runtime if the GUI process dies."""

import ctypes
import os
import signal
import sys


def main():
    parent = int(sys.argv[1])
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Could not configure runtime parent-death signal")
    if os.getppid() != parent:
        return
    os.execv(sys.argv[2], sys.argv[2:])


if __name__ == "__main__":
    main()
