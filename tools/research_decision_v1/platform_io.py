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
            handle = kernel.CreateFileW(str(part), 0x80000000,
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


@contextmanager
def output_parent(path):
    """Create/open each parent without following redirects; retain publication authority."""
    path = Path(path).absolute()
    if ".." in path.parts: raise ValueError("output_symlink")
    if os.name != "nt":
        descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:]:
                try: os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError: pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor); descriptor = child
            yield descriptor
        finally: os.close(descriptor)
        return
    ctypes, kernel, FileInfo = _windows_api()
    if len(path.drive) != 2 or path.drive[1] != ":" or any(":" in part for part in path.parts[1:]):
        raise ValueError("unsafe_windows_output_path")
    handles = []
    try:
        for part in [*reversed(path.parents), path]:
            # Every previously visited ancestor is already held against rename
            # and reparse mutation. Check the new handle before descending.
            part.mkdir(exist_ok=True)
            handle = kernel.CreateFileW(str(part), 0x80000000, 1, None, 3, 0x02200000, None)
            if handle == ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle); info = FileInfo()
            if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & 0x400 or not info.attributes & 0x10:
                raise ValueError("output_symlink")
        yield None
    finally:
        for handle in reversed(handles): kernel.CloseHandle(handle)


@contextmanager
def output_existing_descriptor(path, parent_descriptor):
    if parent_descriptor is None:
        with input_descriptor(path) as descriptor: yield descriptor
    else:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_descriptor)
        try: yield descriptor
        finally: os.close(descriptor)


def publish_staged(temporary, path, parent_descriptor=None):
    if os.name == "nt":
        ctypes, kernel, _ = _windows_api()
        # WRITE_THROUGH, deliberately no REPLACE_EXISTING flag.
        if not kernel.MoveFileExW(str(temporary), str(path), 0x8):
            code = ctypes.get_last_error()
            if code in (80, 183): raise FileExistsError("immutable_target_exists")
            raise ctypes.WinError(code)
    else:
        # A renamed parent cannot redirect a write. Reject a changed pathname
        # too, so a successful return still names the verified directory.
        try:
            with _posix_descriptor(path.parent / ".") as checked:
                if (os.fstat(checked).st_dev, os.fstat(checked).st_ino) != (os.fstat(parent_descriptor).st_dev, os.fstat(parent_descriptor).st_ino):
                    raise ValueError("output_parent_changed")
        except OSError as exc: raise ValueError("output_parent_changed") from exc
        os.link(temporary.name, path.name, src_dir_fd=parent_descriptor, dst_dir_fd=parent_descriptor, follow_symlinks=False)


def sync_directory(path, descriptor=None):
    if os.name == "nt": return  # MoveFileExW above requested write-through.
    os.fsync(descriptor)
