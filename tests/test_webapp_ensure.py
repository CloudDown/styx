from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.webapp_ensure import apply_webapp_enable, dashboard_port, ensure_upstream  # noqa: E402


class WebappEnable(unittest.TestCase):
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
            with patch("styx.webapp_ensure.port_open") as probe:
                with self.assertRaisesRegex(RuntimeError, "non-loopback"):
                    ensure_upstream("dashboard")
                probe.assert_not_called()

    def test_autostart_never_restarts_gateway(self):
        with patch("hermes_cli.config.load_config_readonly", return_value={}):
            with patch("hermes_cli.config.load_config", return_value={}):
                with patch("hermes_cli.config.save_config") as save:
                    with patch("styx.webapp_ensure.port_open", return_value=False):
                        with patch("styx.webapp_ensure._bring_up_gateway") as restart:
                            with self.assertRaisesRegex(RuntimeError, "no listener"):
                                ensure_upstream("webapp", may_restart=False)
                            restart.assert_not_called()
                            self.assertTrue(save.call_args.args[0]["webapp"]["enabled"])

    def test_dashboard_port_default(self):
        self.assertEqual(dashboard_port({}), 9119)
        self.assertEqual(dashboard_port({"dashboard": {"port": 1900}}), 1900)


if __name__ == "__main__":
    unittest.main()
