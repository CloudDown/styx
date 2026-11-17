from __future__ import annotations

import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

# The portable unit suite also runs without a full Hermes checkout. Missing
# Hermes operations must be explicitly mocked, never silently emulated.
try:
    import hermes_cli.config
except ModuleNotFoundError as exc:
    if exc.name not in {"hermes_cli", "hermes_cli.config"}:
        raise
    import types
    package = types.ModuleType("hermes_cli")
    config = types.ModuleType("hermes_cli.config")
    def unavailable(*args, **kwargs):
        raise AssertionError("test must mock the Hermes config API")
    config.load_config = config.load_config_readonly = config.save_config = unavailable
    package.config = config
    sys.modules["hermes_cli"] = package
    sys.modules["hermes_cli.config"] = config

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend.webapp_ensure import (  # noqa: E402
    _prepare_webapp, _wait_healthy, apply_webapp_enable, dashboard_port, ensure_upstream,
)


class WebappEnable(unittest.TestCase):
    def setUp(self):
        self.prepare = self.enterContext(patch("styx.backend.webapp_ensure._prepare_webapp"))
        self.healthy = self.enterContext(patch("styx.backend.webapp_ensure._wait_healthy"))
        self.wait_port = self.enterContext(patch("styx.backend.webapp_ensure.wait_port", return_value=False))

    def test_enables_empty_config(self):
        cfg, port, changed = apply_webapp_enable({})
        self.assertTrue(changed)
        self.assertEqual(port, 9120)
        self.assertEqual(cfg["webapp"]["enabled"], True)
        self.assertEqual(cfg["webapp"]["host"], "127.0.0.1")

    def test_idempotent_when_already_on(self):
        src = {"webapp": {"enabled": True, "host": "127.0.0.1", "port": 9120}}
        cfg, port, changed = apply_webapp_enable(src)
        self.assertFalse(changed)
        self.assertEqual(port, 9120)
        self.assertEqual(cfg["webapp"]["enabled"], True)

    def test_refuses_non_loopback_without_changing_config(self):
        src = {"webapp": {"enabled": False, "host": "0.0.0.0", "port": 9333}}
        with self.assertRaisesRegex(RuntimeError, "non-loopback"):
            apply_webapp_enable(src)
        self.assertFalse(src["webapp"]["enabled"])
        self.assertEqual(src["webapp"]["host"], "0.0.0.0")

    def test_keeps_custom_port_and_ipv6_loopback(self):
        cfg, port, changed = apply_webapp_enable(
            {"webapp": {"enabled": False, "host": "::1", "port": 9333}},
        )
        self.assertTrue(changed)
        self.assertEqual(port, 9333)
        self.assertEqual(cfg["webapp"]["host"], "::1")

    def test_refuses_public_dashboard_before_checking_port(self):
        with patch("hermes_cli.config.load_config_readonly", return_value={"dashboard": {"host": "0.0.0.0"}}):
            with patch("styx.backend.webapp_ensure.port_open") as probe:
                with self.assertRaisesRegex(RuntimeError, "non-loopback"):
                    ensure_upstream("dashboard")
                probe.assert_not_called()

    def test_autostart_never_restarts_gateway(self):
        with patch("hermes_cli.config.load_config_readonly", return_value={}):
            with patch("hermes_cli.config.load_config", return_value={}):
                with patch("hermes_cli.config.save_config") as save:
                    with patch("styx.backend.webapp_ensure.port_open", return_value=False):
                        with patch("styx.backend.webapp_ensure._bring_up_gateway") as restart:
                            with self.assertRaisesRegex(RuntimeError, "no listener"):
                                ensure_upstream("webapp", may_restart=False)
                            restart.assert_not_called()
                            self.assertTrue(save.call_args.args[0]["webapp"]["enabled"])

    def test_dashboard_port_default(self):
        self.assertEqual(dashboard_port({}), 9119)
        self.assertEqual(dashboard_port({"dashboard": {"port": 1900}}), 1900)

    def test_open_port_still_prepares_renderer_and_checks_http(self):
        cfg = {"webapp": {"enabled": True, "host": "127.0.0.1", "port": 9120}}
        with patch("hermes_cli.config.load_config_readonly", return_value=cfg):
            with patch("hermes_cli.config.load_config", return_value=cfg):
                with patch("styx.backend.webapp_ensure.port_open", return_value=True):
                    with patch("styx.backend.webapp_ensure._bring_up_gateway") as restart:
                        self.assertEqual(ensure_upstream("webapp"), ("127.0.0.1", 9120))
        self.prepare.assert_called_once_with(None)
        self.healthy.assert_called_once_with("127.0.0.1", 9120)
        restart.assert_not_called()

    def test_build_failure_does_not_report_success_or_restart_gateway(self):
        self.prepare.side_effect = RuntimeError("build failed")
        with patch("hermes_cli.config.load_config_readonly", return_value={}):
            with patch("hermes_cli.config.load_config", return_value={}):
                with patch("hermes_cli.config.save_config"):
                    with patch("styx.backend.webapp_ensure._bring_up_gateway") as restart:
                        with self.assertRaisesRegex(RuntimeError, "build failed"):
                            ensure_upstream("webapp")
        restart.assert_not_called()
        self.healthy.assert_not_called()

    def test_autostart_waits_for_listener_without_restarting_itself(self):
        self.wait_port.return_value = True
        with patch("hermes_cli.config.load_config_readonly", return_value={}):
            with patch("hermes_cli.config.load_config", return_value={}):
                with patch("hermes_cli.config.save_config"):
                    with patch("styx.backend.webapp_ensure.port_open", return_value=False):
                        with patch("styx.backend.webapp_ensure._bring_up_gateway") as restart:
                            ensure_upstream("webapp", may_restart=False)
        restart.assert_not_called()
        self.healthy.assert_called_once()


class RendererBuild(unittest.TestCase):
    def test_uses_public_build_only_cli_and_private_log(self):
        with tempfile.TemporaryDirectory() as raw:
            with patch("styx.backend.webapp_ensure.hermes_argv", return_value=["hermes"]):
                with patch("styx.backend.webapp_ensure.subprocess.run", return_value=Mock(returncode=0)) as run:
                    _prepare_webapp(Path(raw))
            self.assertTrue((Path(raw) / "logs/webapp-build.log").is_file())
        self.assertEqual(run.call_args.args[0], ["hermes", "webapp", "--build-only"])
        self.assertEqual(run.call_args.kwargs["timeout"], 900)

    def test_build_error_and_timeout_have_actionable_log_path(self):
        import subprocess
        for result in [Mock(returncode=1), subprocess.TimeoutExpired("hermes", 900)]:
            with self.subTest(result=result), tempfile.TemporaryDirectory() as raw:
                kwargs = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
                with patch("styx.backend.webapp_ensure.hermes_argv", return_value=["hermes"]):
                    with patch("styx.backend.webapp_ensure.subprocess.run", **kwargs):
                        with self.assertRaisesRegex(RuntimeError, "webapp-build.log"):
                            _prepare_webapp(Path(raw))

    def test_health_wait_rejects_a_persistent_error_page(self):
        with patch("styx.backend.webapp_ensure.upstream_health", return_value=(False, "interface missing")):
            with patch("styx.backend.webapp_ensure.time.monotonic", side_effect=[0, 21]):
                with self.assertRaisesRegex(RuntimeError, "interface missing"):
                    _wait_healthy("127.0.0.1", 9120)


if __name__ == "__main__":
    unittest.main()
