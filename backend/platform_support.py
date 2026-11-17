"""The few OS-specific operations Styx needs; no service-manager assumptions."""

from __future__ import annotations

import errno
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import psutil

IS_WINDOWS = sys.platform == "win32"


def detached_process_options() -> dict:
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    return {"start_new_session": True}


def lock_exclusive(fd: int) -> None:
    """Non-blocking lock, including between threads in this process."""
    if IS_WINDOWS:
        import msvcrt

        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise BlockingIOError("Styx operation already locked") from exc
            raise
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if IS_WINDOWS:
        _windows_private_acl(path)
    else:
        path.chmod(0o700)
    return path


@lru_cache(maxsize=1)
def _windows_user_sid() -> str:
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    lookup = api.LookupAccountNameW
    lookup.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR,
                       ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    lookup.restype = wintypes.BOOL
    size, domain_size, kind = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
    account = psutil.Process().username()
    lookup(None, account, None, ctypes.byref(size), None, ctypes.byref(domain_size), ctypes.byref(kind))
    if not size.value:
        raise ctypes.WinError(ctypes.get_last_error())
    sid = ctypes.create_string_buffer(size.value)
    domain = ctypes.create_unicode_buffer(max(1, domain_size.value))
    if not lookup(None, account, sid, ctypes.byref(size), domain, ctypes.byref(domain_size), ctypes.byref(kind)):
        raise ctypes.WinError(ctypes.get_last_error())
    convert = api.ConvertSidToStringSidW
    convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    convert.restype = wintypes.BOOL
    text = wintypes.LPWSTR()
    if not convert(sid, ctypes.byref(text)):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return text.value
    finally:
        kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def _windows_private_acl(path: Path) -> None:
    """Protect the tree with an inheritable user/SYSTEM DACL, not Windows chmod."""
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    convert = api.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                        ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    descriptor = ctypes.c_void_p()
    sddl = f"D:P(A;OICI;FA;;;{_windows_user_sid()})(A;OICI;FA;;;SY)"
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        get_dacl = api.GetSecurityDescriptorDacl
        get_dacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
        get_dacl.restype = wintypes.BOOL
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        set_security = api.SetNamedSecurityInfoW
        set_security.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
                                 ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        set_security.restype = wintypes.DWORD
        # DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION.
        error = set_security(str(path), 1, 0x80000004, None, None, dacl, None)
        if error:
            raise ctypes.WinError(error)
    finally:
        kernel.LocalFree(descriptor)
