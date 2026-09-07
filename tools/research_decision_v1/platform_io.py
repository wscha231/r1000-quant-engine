"""Local-file handles on POSIX and Windows; never follow reparse points."""
from contextlib import contextmanager
import os
from pathlib import Path


def is_redirect(path):
    path = Path(path)
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


@contextmanager
def _posix_descriptor(path):
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    descriptor = None
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory); directory = child
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        yield descriptor
    finally:
        if descriptor is not None: os.close(descriptor)
        os.close(directory)


def _windows_api():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    class FileInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
                    ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    kernel.MoveFileExW.restype = wintypes.BOOL
    return ctypes, kernel, FileInfo


@contextmanager
def _windows_descriptor(path):
    import msvcrt
    ctypes, kernel, FileInfo = _windows_api()
    # Restrict to ordinary local drive paths, excluding device/UNC/ADS names.
    if len(path.drive) != 2 or path.drive[1] != ":" or any(":" in part for part in path.parts[1:]):
        raise ValueError("unsafe_windows_input_path")
    handles, descriptor = [], None
    try:
        # Keep all parents open without WRITE/DELETE sharing until the bounded
        # read finishes. Reparse processing is disabled and attributes checked.
        for part in [*reversed(path.parents), path]:
            directory = part != path
            handle = kernel.CreateFileW(str(part), 0x80 if directory else 0x80000000,
                                        1, None, 3, 0x00200000 | (0x02000000 if directory else 0), None)
            if handle == ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            info = FileInfo()
            if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
                raise ValueError("unsafe_windows_reparse_or_type")
        descriptor = msvcrt.open_osfhandle(handles[-1], os.O_RDONLY | os.O_BINARY)
        handles.pop()  # CRT descriptor now owns the final Windows handle.
        yield descriptor
    finally:
        if descriptor is not None: os.close(descriptor)
        for handle in reversed(handles): kernel.CloseHandle(handle)


def input_descriptor(path):
    return _windows_descriptor(path) if os.name == "nt" else _posix_descriptor(path)


def publish_staged(temporary, path):
    if os.name == "nt":
        ctypes, kernel, _ = _windows_api()
        # WRITE_THROUGH, deliberately no REPLACE_EXISTING flag.
        if not kernel.MoveFileExW(str(temporary), str(path), 0x8):
            code = ctypes.get_last_error()
            if code in (80, 183): raise FileExistsError("immutable_target_exists")
            raise ctypes.WinError(code)
    else:
        os.link(temporary, path)


def sync_directory(path):
    if os.name == "nt": return  # MoveFileExW above requested write-through.
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
