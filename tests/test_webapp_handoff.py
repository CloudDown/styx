from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import fast_webapp, gate, passwords, sessions, webapp_handoff as handoff  # noqa: E402
from test_gate_regressions import Chunks, Transport  # noqa: E402

TICKET = "t" * 43


class LaunchProtocol(unittest.TestCase):
    def test_public_cli_output_is_converted_without_exposing_credentials(self):
        result = handoff.parse_launch_output(
            "bundle ready\n  http://127.0.0.1:9120/webapp/launch#ticket=" + TICKET,
            "127.0.0.1", 9120,
        )
        self.assertEqual(result, {"ticket": TICKET, "query": ""})

    def test_wrong_origin_userinfo_path_and_ticket_are_rejected(self):
        for link in [
            f"http://example.invalid:9120/webapp/launch#ticket={TICKET}",
            f"http://127.0.0.1:9999/webapp/launch#ticket={TICKET}",
            f"http://user@127.0.0.1:9120/webapp/launch#ticket={TICKET}",
            f"http://127.0.0.1:9120/other#ticket={TICKET}",
            "http://127.0.0.1:9120/webapp/launch#ticket=short",
            f"http://127.0.0.1:9120/webapp/launch#ticket={TICKET}&ticket={TICKET}",
        ]:
            with self.subTest(link=link), self.assertRaises(handoff.HandoffError) as error:
                handoff.parse_launch_output(link, "127.0.0.1", 9120)
            self.assertNotIn(TICKET, str(error.exception))

    def test_explicit_additional_hermes_sign_in_is_not_bypassed(self):
        output = "Open the Webapp and sign in with your dashboard account: http://127.0.0.1:9120/"
        self.assertIsNone(handoff.parse_launch_output(output, "127.0.0.1", 9120))

    def test_host_cli_is_no_open_skip_build_and_uses_no_credential_arguments(self):
        with patch.object(handoff, "hermes_argv", return_value=["hermes"]):
            with patch.object(handoff.subprocess, "run", return_value=Mock(
                returncode=0, stdout=f"http://127.0.0.1:9120/webapp/launch#ticket={TICKET}",
            )) as run:
                handoff.request_launch("127.0.0.1", 9120)
        self.assertEqual(run.call_args.args[0], ["hermes", "webapp", "--no-open", "--skip-build"])
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_timeout_never_discloses_partial_output(self):
        error = subprocess.TimeoutExpired("hermes", 45, output=TICKET)
        with patch.object(handoff.subprocess, "run", side_effect=error):
            with self.assertRaises(handoff.HandoffError) as raised:
                handoff.request_launch("127.0.0.1", 9120)
        self.assertNotIn(TICKET, str(raised.exception))


class EntryPasses(unittest.IsolatedAsyncioTestCase):
    async def test_entry_is_one_use_and_bound_to_the_styx_session(self):
        flow = handoff.WebappHandoff("127.0.0.1", 9120)
        with patch.object(handoff, "request_launch", return_value={"ticket": TICKET, "query": ""}):
            url = await flow.launch("session-one", "session=chat")
        query = parse_qs(urlsplit(url).fragment)["query"][0]
        entry = parse_qs(query)[handoff.ENTRY_QUERY][0]
        self.assertFalse(flow.consume(entry, "session-two"))
        self.assertTrue(flow.consume(entry, "session-one"))
        self.assertFalse(flow.consume(entry, "session-one"))

    async def test_expired_entries_are_removed_and_budget_is_bounded(self):
        now = [100.0]
        flow = handoff.WebappHandoff("127.0.0.1", 9120)
        with patch.object(handoff, "time", types.SimpleNamespace(monotonic=lambda: now[0])):
            with patch.object(handoff, "_MAX_ENTRIES", 1):
                with patch.object(handoff, "request_launch", return_value={"ticket": TICKET, "query": ""}):
                    first = await flow.launch("session", "")
                    with self.assertRaises(handoff.HandoffError):
                        await flow.launch("session", "")
                    now[0] += 121
                    second = await flow.launch("session", "")
        self.assertNotEqual(first, second)
        self.assertEqual(len(flow._entries), 1)

    async def test_requested_navigation_and_native_profile_defaults_are_preserved(self):
        flow = handoff.WebappHandoff("127.0.0.1", 9120)
        with patch.object(handoff, "request_launch", return_value={"ticket": TICKET, "query": "?profile=default"}):
            target = await flow.launch("session", "profile=other&session=chat&_styx_entry=old")
        fragment = parse_qs(urlsplit(target).fragment)
        query = parse_qs(fragment["query"][0])
        self.assertEqual(query["profile"], ["other"])
        self.assertEqual(query["session"], ["chat"])
        self.assertNotEqual(query[handoff.ENTRY_QUERY], ["old"])
        self.assertEqual(handoff.strip_entry_query(fragment["query"][0]), "profile=other&session=chat")


class GateHandoff(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secret = b"x" * 32
        passwords.write_hash(self.root / "passwd", "test-password")
        self.native_token = "n" * 43
        self.tickets = set()
        self.upstream_calls = []
        self.issue = self.enterContext(patch.object(handoff, "request_launch", side_effect=self.issue_ticket))
        self.enterContext(patch.object(gate, "_LOGIN_DELAY", 0))
        client_type = httpx.AsyncClient
        with patch.object(gate.httpx, "AsyncClient", side_effect=lambda **kw: client_type(
            transport=Transport(self.upstream), **kw,
        )):
            self.app = gate.build_app(
                data_dir=self.root, upstream_host="127.0.0.1", upstream_port=9120,
                secret=self.secret, webapp_handoff=True,
            )
        await self.enterAsyncContext(self.app.router.lifespan_context(self.app))
        self.browser = client_type(transport=httpx.ASGITransport(app=self.app), base_url="http://test.local")
        self.addAsyncCleanup(self.browser.aclose)

    def issue_ticket(self, host, port):
        ticket = secrets.token_urlsafe(32)
        self.tickets.add(ticket)
        return {"ticket": ticket, "query": ""}

    def upstream(self, request):
        self.upstream_calls.append(request)
        headers = {"content-type": "text/html"}
        status = 200
        if request.url.path == "/webapp/launch":
            body = b"native launch page"
        elif request.url.path == "/webapp/window-session":
            ticket = request.headers.get("X-Hermes-Window-Ticket")
            self.assertEqual(request.headers.get("Origin"), "http://127.0.0.1:9120")
            self.assertEqual(request.headers.get("Host"), "127.0.0.1:9120")
            headers = {"content-type": "application/json", "cache-control": "no-store"}
            if ticket in self.tickets:
                self.tickets.remove(ticket)
                body = ('{"token":"' + self.native_token + '"}').encode()
            else:
                status, body = 403, b'{"detail":"expired"}'
        elif request.url.path == "/api/profiles":
            headers = {"content-type": "application/json"}
            status = 200 if request.headers.get("X-Hermes-Session-Token") == self.native_token else 401
            body = b'{"profiles":[]}'
        else:
            self.assertNotIn(handoff.ENTRY_QUERY, request.url.params)
            body = b"<html>Hermes workspace</html>"
        return httpx.Response(status, headers=headers, stream=Chunks(body))

    async def login(self, *, next_path="/api/profiles", expected_status=303):
        await self.browser.get("/login")
        csrf = self.browser.cookies[sessions.CSRF_COOKIE]
        response = await self.browser.post("/login", params={"next": next_path},
                                           data={"csrf": csrf, "password": "test-password"})
        self.assertEqual(response.status_code, expected_status)
        return response

    async def complete(self, response):
        self.assertEqual(response.status_code, 303)
        link = urlsplit(response.headers["location"])
        self.assertEqual(link.path, "/webapp/launch")
        self.assertEqual(link.netloc, "")
        self.assertEqual(response.headers["cache-control"], "no-store")
        fragment = parse_qs(link.fragment)
        native_page = await self.browser.get(link.path)
        self.assertEqual(native_page.status_code, 200)
        exchange = await self.browser.post("/webapp/window-session", headers={
            "X-Hermes-Window-Ticket": fragment["ticket"][0],
        })
        self.assertEqual(exchange.status_code, 200)
        entry_url = "/?" + fragment["query"][0]
        workspace = await self.browser.get(entry_url)
        self.assertEqual(workspace.status_code, 200)
        return exchange.json()["token"], entry_url

    async def test_no_cli_launch_or_native_exchange_before_cerberus_authentication(self):
        self.assertEqual((await self.browser.get("/")).status_code, 303)
        self.assertEqual((await self.browser.post("/webapp/window-session")).status_code, 303)
        self.issue.assert_not_called()
        self.assertFalse(self.upstream_calls)

    async def test_fast_shell_and_connect_are_unavailable_before_cerberus(self):
        fast_webapp.write_mode(self.root, "fast")
        for path in (fast_webapp.FAST, fast_webapp.MARKDOWN, fast_webapp.FAST + "/connect", "/?_styx_view=fast"):
            self.assertEqual((await self.browser.get(path)).status_code, 303)
        self.issue.assert_not_called()
        self.assertFalse(self.upstream_calls)

    async def test_fast_shows_shell_before_cli_and_reuses_native_grant_on_reload(self):
        fast_webapp.write_mode(self.root, "fast")
        response = await self.login(next_path="/?profile=main")
        self.assertEqual(response.headers["location"], fast_webapp.FAST + "?profile=main")
        shell = await self.browser.get(response.headers["location"], headers={"Accept-Encoding": "gzip"})
        self.assertIn("Chat with Hermes", shell.text)
        self.assertEqual(shell.headers["cache-control"], "private, no-cache")
        self.assertEqual(shell.headers["content-encoding"], "gzip")
        self.assertIn("frame-ancestors 'none'", shell.headers["content-security-policy"])
        # Budget, not a target: the shell stays ~40x below the official Webapp's
        # ~1.15 MB (gzip) because it ships no framework, and reloads revalidate
        # to a 304 instead of re-downloading it.
        self.assertLess(int(shell.headers["content-length"]), 26_000)
        warm = await self.browser.get(shell.request.url, headers={
            "Accept-Encoding": "gzip", "If-None-Match": shell.headers["etag"]})
        self.assertEqual(warm.status_code, 304)
        self.assertEqual(await warm.aread(), b"")
        lexer = await self.browser.get(fast_webapp.MARKDOWN, headers={"Accept-Encoding": "gzip"})
        self.assertEqual(lexer.status_code, 200)
        self.assertEqual(lexer.headers["content-encoding"], "gzip")
        integrity = base64.b64encode(hashlib.sha256(lexer.content).digest()).decode()
        self.assertIn("sha256-" + integrity, shell.text)
        self.assertEqual((await self.browser.head(fast_webapp.FAST + "/connect")).status_code, 405)
        self.issue.assert_not_called()
        no_native = await self.browser.get("/api/profiles")
        self.assertEqual(no_native.status_code, 401)

        launch = await self.browser.get(fast_webapp.FAST + "/connect?profile=main")
        link = urlsplit(launch.headers["location"])
        self.assertEqual(link.path, "/webapp/launch")
        fragment = parse_qs(link.fragment)
        self.assertEqual((await self.browser.get(link.path)).status_code, 200)
        exchange = await self.browser.post("/webapp/window-session", headers={
            "X-Hermes-Window-Ticket": fragment["ticket"][0],
        })
        self.assertEqual(exchange.status_code, 200)
        final = await self.browser.get("/?" + fragment["query"][0])
        self.assertEqual(final.status_code, 200)
        self.assertIn("Styx Fast", final.text)
        self.assertEqual((await self.browser.get("/?" + fragment["query"][0])).status_code, 303)
        self.assertEqual((await self.browser.get(fast_webapp.FAST + "?profile=main")).status_code, 200)
        self.assertEqual(self.issue.call_count, 1)

    async def test_fast_default_can_open_unmodified_official_webapp(self):
        await self.login()
        fast_webapp.write_mode(self.root, "fast")
        self.assertEqual((await self.browser.get("/")).headers["location"], fast_webapp.FAST)
        token, _ = await self.complete(await self.browser.get("/?_styx_view=hermes&profile=main"))
        self.assertEqual(token, self.native_token)
        self.assertEqual(dict(self.upstream_calls[-1].url.params), {"profile": "main"})
        fast_webapp.write_mode(self.root, "hermes")
        self.assertEqual(urlsplit((await self.browser.get("/")).headers["location"]).path, "/webapp/launch")

    async def test_fast_respects_extra_provider_and_password_rotation(self):
        await self.login()
        self.issue.side_effect = None
        self.issue.return_value = None
        response = await self.browser.get(fast_webapp.FAST + "/connect")
        self.assertEqual(response.headers["location"], "/?_styx_view=hermes")
        self.assertEqual((await self.browser.get(response.headers["location"])).status_code, 200)
        passwords.write_hash(self.root / "passwd", "replacement")
        self.assertEqual((await self.browser.get(fast_webapp.FAST)).status_code, 303)

    async def test_unconfigured_or_invalid_mode_opens_native_hermes(self):
        mode_file = self.root / "webapp-mode"
        self.assertFalse(mode_file.exists())
        self.assertEqual(fast_webapp.read_mode(self.root), "hermes")
        first = await self.login(next_path="/")
        self.assertEqual(urlsplit(first.headers["location"]).path, "/webapp/launch")
        token, _ = await self.complete(first)
        self.assertEqual(token, self.native_token)

        for invalid in (b"unknown\n", b"\xff"):
            with self.subTest(mode=invalid):
                mode_file.write_bytes(invalid)
                self.assertEqual(fast_webapp.read_mode(self.root), "hermes")
                reopened = await self.browser.get("/")
                self.assertEqual(urlsplit(reopened.headers["location"]).path, "/webapp/launch")

    async def test_password_login_native_exchange_workspace_and_authenticated_api(self):
        response = await self.login(next_path="/?profile=other&session=chat")
        self.assertIn("styx-launch;dur=", response.headers["server-timing"])
        token, entry = await self.complete(response)
        self.assertEqual(parse_qs(urlsplit(entry).query)["profile"], ["other"])
        self.assertEqual(parse_qs(urlsplit(entry).query)["session"], ["chat"])
        response = await self.browser.get("/api/profiles", headers={"X-Hermes-Session-Token": token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.issue.call_count, 1)
        self.assertNotIn("styx_session", self.upstream_calls[-1].headers.get("Cookie", ""))

    async def test_login_failure_does_not_request_a_native_ticket(self):
        await self.browser.get("/login")
        response = await self.browser.post("/login", data={
            "csrf": self.browser.cookies[sessions.CSRF_COOKIE], "password": "wrong",
        })
        self.assertEqual(response.status_code, 401)
        self.issue.assert_not_called()

    async def test_password_replaced_during_direct_launch_does_not_issue_a_session(self):
        def changed(host, port):
            passwords.write_hash(self.root / "passwd", "replacement")
            return {"ticket": TICKET, "query": ""}
        self.issue.side_effect = changed
        response = await self.login(next_path="/", expected_status=401)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(sessions.COOKIE, self.browser.cookies)
        self.assertNotIn(TICKET, str(response.headers))

    async def test_direct_login_respects_extra_hermes_provider_and_closed_failure(self):
        self.issue.side_effect = None
        self.issue.return_value = None
        response = await self.login(next_path="/")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")
        self.issue.side_effect = handoff.HandoffError("Hermes browser launch unavailable.")
        self.browser.cookies.clear()
        response = await self.login(next_path="/", expected_status=503)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertFalse(self.upstream_calls)

    async def test_reload_issues_a_new_native_grant_instead_of_looping(self):
        await self.login()
        _, entry = await self.complete(await self.browser.get("/"))
        await self.complete(await self.browser.get(entry))
        self.assertEqual(self.issue.call_count, 2)

    async def test_two_tabs_have_distinct_entry_passes_without_cookie_races(self):
        await self.login()
        responses = await asyncio.gather(self.browser.get("/?tab=one"), self.browser.get("/?tab=two"))
        first, second = await self.complete(responses[0]), await self.complete(responses[1])
        self.assertNotEqual(first[1], second[1])
        self.assertEqual(self.issue.call_count, 2)

    async def test_host_launch_failure_is_closed_and_does_not_proxy_the_workspace(self):
        await self.login()
        self.issue.side_effect = handoff.HandoffError("Hermes browser launch unavailable.")
        response = await self.browser.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(self.upstream_calls)

    async def test_additional_hermes_sign_in_provider_is_preserved(self):
        await self.login()
        self.issue.side_effect = None
        self.issue.return_value = None
        self.assertEqual((await self.browser.get("/")).status_code, 200)
        self.assertEqual((await self.browser.get("/api/profiles")).status_code, 401)

    async def test_password_change_during_launch_does_not_disclose_the_ticket(self):
        await self.login()
        def changed(host, port):
            passwords.write_hash(self.root / "passwd", "replacement")
            return {"ticket": TICKET, "query": ""}
        self.issue.side_effect = changed
        response = await self.browser.get("/")
        self.assertEqual(response.headers["location"], "/login")
        self.assertNotIn(TICKET, str(response.headers))
