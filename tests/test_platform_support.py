from __future__ import annotations

import errno
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import platform_support as platform  # noqa: E402
from styx.backend import tor_supervisor as tor


class PlatformSupport(unittest.TestCase):
    def test_windows_spawn_is_detached_without_posix_session_flag(self):
        with patch.object(platform, "IS_WINDOWS", True):
            with patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True):
                with patch.object(subprocess, "DETACHED_PROCESS", 8, create=True):
                    self.assertEqual(platform.detached_process_options(), {"creationflags": 520})

    def test_posix_spawn_uses_new_session(self):
        with patch.object(platform, "IS_WINDOWS", False):
            self.assertEqual(platform.detached_process_options(), {"start_new_session": True})

    def test_windows_lock_seeks_and_locks_one_byte(self):
        fake = types.SimpleNamespace(LK_NBLCK=2, locking=Mock())
        with tempfile.TemporaryFile() as file:
            with patch.object(platform, "IS_WINDOWS", True):
                with patch.dict(sys.modules, {"msvcrt": fake}):
                    platform.lock_exclusive(file.fileno())
            self.assertEqual(os.fstat(file.fileno()).st_size, 1)
            fake.locking.assert_called_once_with(file.fileno(), 2, 1)

    def test_windows_lock_contention_maps_to_busy(self):
        fake = types.SimpleNamespace(
            LK_NBLCK=2, locking=Mock(side_effect=OSError(errno.EACCES, "busy"))
        )
        with tempfile.TemporaryFile() as file:
            with patch.object(platform, "IS_WINDOWS", True):
                with patch.dict(sys.modules, {"msvcrt": fake}):
                    with self.assertRaises(BlockingIOError):
                        platform.lock_exclusive(file.fileno())

    def test_private_directory_uses_real_os_permissions(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = platform.private_dir(Path(raw) / "private")
            self.assertTrue(folder.is_dir())
            if not platform.IS_WINDOWS:
                self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
            else:
                # Also executes the real Win32 ACL implementation on Windows CI.
                self.assertTrue(platform._windows_user_sid().startswith("S-1-"))

    @unittest.skipUnless(sys.platform == "win32", "Native Windows DACL check")
    def test_windows_private_directory_has_protected_non_null_dacl(self):
        import ctypes
        from ctypes import wintypes

        with tempfile.TemporaryDirectory() as raw:
            folder = platform.private_dir(Path(raw) / "private")
            api = ctypes.WinDLL("advapi32", use_last_error=True)
            read = api.GetFileSecurityW
            read.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
            ]
            read.restype = wintypes.BOOL
            size = wintypes.DWORD()
            read(str(folder), 4, None, 0, ctypes.byref(size))
            self.assertGreater(size.value, 0)
            descriptor = ctypes.create_string_buffer(size.value)
            self.assertTrue(read(str(folder), 4, descriptor, size, ctypes.byref(size)))
            get_control = api.GetSecurityDescriptorControl
            get_control.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.WORD),
                ctypes.POINTER(wintypes.DWORD),
            ]
            get_control.restype = wintypes.BOOL
            control, revision = wintypes.WORD(), wintypes.DWORD()
            self.assertTrue(get_control(descriptor, ctypes.byref(control), ctypes.byref(revision)))
            self.assertTrue(control.value & 0x1000)  # SE_DACL_PROTECTED
            get_dacl = api.GetSecurityDescriptorDacl
            get_dacl.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.BOOL),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(wintypes.BOOL),
            ]
            get_dacl.restype = wintypes.BOOL
            present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
            self.assertTrue(
                get_dacl(
                    descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
                )
            )
            self.assertTrue(present.value and dacl.value)

    def test_portable_identity_checks_user_profile_and_creation_time(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "gate.pid"
            process = Mock()
            process.username.return_value = "user"
            process.status.return_value = psutil.STATUS_RUNNING
            process.cmdline.return_value = ["python", "-m", "styx.gate", "--data-dir", raw]
            process.is_running.return_value = True
            process.create_time.return_value = 123.5
            with patch.object(tor.psutil, "Process", return_value=process):
                self.assertEqual(
                    tor._portable_process_info(42, path),
                    {"pid": 42, "username": "user", "create_time": 123.5},
                )
                process.cmdline.return_value = ["python", "-m", "hermes_cli.main", "gateway"]
                self.assertIsNone(tor._portable_process_info(42, path))

    def test_portable_stop_never_signals_a_reused_pid(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "gate.pid"
            path.write_text("42")
            process = Mock()
            with patch.object(tor.psutil, "Process", return_value=process):
                with patch.object(tor, "read_pid", return_value=None):
                    tor._stop_portable(path, 42, "gate")
            process.terminate.assert_not_called()
            process.kill.assert_not_called()

    def test_portable_stop_waits_and_escalates_only_the_owned_process(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "gate.pid"
            path.write_text("42")
            process = Mock()
            process.wait.side_effect = [psutil.TimeoutExpired(4), 0]
            with patch.object(tor.psutil, "Process", return_value=process):
                with patch.object(tor, "read_pid", return_value=42):
                    tor._stop_portable(path, 42, "gate")
            process.terminate.assert_called_once()
            process.kill.assert_called_once()
            self.assertFalse(path.exists())
