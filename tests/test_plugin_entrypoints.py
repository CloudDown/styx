from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

import styx  # noqa: E402
from styx.backend import cli, paths, supervisor  # noqa: E402


class PluginEntrypoints(unittest.TestCase):
    def context(self):
        ctx = Mock()
        ctx.get_config.return_value = False
        return ctx

    def test_plugin_root_still_contains_manifest_and_assets(self):
        self.assertEqual(paths.PLUGIN_ROOT, Path(__file__).resolve().parents[1])
        self.assertTrue((paths.PLUGIN_ROOT / "plugin.yaml").is_file())
        self.assertTrue((paths.PLUGIN_ROOT / "assets/login-background.jpg").is_file())

    def test_registration_preserves_hermes_cli_contract(self):
        ctx = self.context()
        styx.register(ctx)
        registration = ctx.register_cli_command.call_args.kwargs
        self.assertEqual(registration["name"], "styx")
        self.assertIs(registration["setup_fn"], cli.register_cli)
        self.assertIs(registration["handler_fn"], cli.styx_command)
        parser = argparse.ArgumentParser()
        registration["setup_fn"](parser)
        args = parser.parse_args(["start", "--no-wait", "--client-auth"])
        with patch.object(cli, "_start", return_value=0) as start:
            self.assertEqual(registration["handler_fn"](args), 0)
        start.assert_called_once_with(wait=False, client_auth=True)

    def test_slash_reports_status_without_the_address(self):
        ctx = self.context()
        styx.register(ctx)
        name, handler = ctx.register_command.call_args.args
        self.assertEqual(name, "styx")
        for running in (True, False):
            with self.subTest(running=running):
                with patch.object(
                    supervisor,
                    "status",
                    return_value={"running": running, "url": "sensitive-address"},
                ):
                    result = handler("")
                self.assertIn("up" if running else "down", result)
                self.assertNotIn("sensitive-address", result)

    def test_autostart_cannot_restart_the_hermes_gateway(self):
        with patch.object(supervisor, "start") as start:
            styx._autostart()
        start.assert_called_once_with(wait=False, may_restart_gateway=False)

    def test_relative_imports_work_under_a_hermes_package_alias(self):
        name = "_styx_layout_probe"
        spec = importlib.util.spec_from_file_location(
            name,
            paths.PLUGIN_ROOT / "__init__.py",
            submodule_search_locations=[str(paths.PLUGIN_ROOT)],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            ctx = self.context()
            module.register(ctx)
            parser = argparse.ArgumentParser()
            ctx.register_cli_command.call_args.kwargs["setup_fn"](parser)
            self.assertEqual(parser.parse_args(["doctor"]).styx_command, "doctor")
        finally:
            for key in list(sys.modules):
                if key == name or key.startswith(name + "."):
                    del sys.modules[key]

    @unittest.skipUnless(importlib.util.find_spec("fastapi"), "Dashboard needs FastAPI")
    def test_dashboard_backend_loads_without_a_package(self):
        spec = importlib.util.spec_from_file_location(
            "_styx_dashboard_probe", paths.PLUGIN_ROOT / "dashboard/plugin_api.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIs(module._supervisor(), supervisor)
        with patch.object(supervisor, "status", return_value={"running": False}):
            self.assertEqual(module.get_status(), {"running": False})
        with patch.object(supervisor, "start", return_value={"running": True}) as start:
            self.assertEqual(module.post_start(), {"running": True})
        start.assert_called_once_with(wait=True, client_auth=False)
        with patch.object(supervisor, "stop") as stop:
            with patch.object(supervisor, "status", return_value={"running": False}):
                self.assertEqual(module.post_stop(), {"running": False})
        stop.assert_called_once_with()
