/**
 * Styx — dashboard tab. Plain IIFE, window.__HERMES_PLUGIN_SDK__.
 */
(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  const REG = window.__HERMES_PLUGINS__;
  if (!SDK || !REG) return;

  const { React } = SDK;
  const h = React.createElement;
  const { Card, CardContent, Badge, Button } = SDK.components;
  const { useState, useEffect, useCallback } = SDK.hooks;

  function StyxTab() {
    const [st, setSt] = useState(null);
    const [err, setErr] = useState("");
    const [busy, setBusy] = useState(false);

    const refresh = useCallback(function () {
      return SDK.fetchJSON("/api/plugins/styx/status")
        .then(function (data) { setSt(data); setErr(""); })
        .catch(function (e) { setErr(String(e && e.message ? e.message : e)); });
    }, []);

    useEffect(function () {
      refresh();
      const id = setInterval(refresh, 5000);
      return function () { clearInterval(id); };
    }, [refresh]);

    function act(path) {
      setBusy(true);
      SDK.fetchJSON("/api/plugins/styx" + path, { method: "POST", body: "{}" })
        .then(function (data) { setSt(data); setErr(""); })
        .catch(function (e) { setErr(String(e && e.message ? e.message : e)); })
        .finally(function () { setBusy(false); });
    }

    function copyUrl() {
      if (!st || !st.url) return;
      if (navigator.clipboard) navigator.clipboard.writeText(st.url);
    }

    const running = !!(st && st.running);
    return h("div", { style: { padding: "1.25rem", maxWidth: "40rem" } },
      h("h1", { style: { fontSize: "1.4rem", margin: "0 0 .35rem" } }, "Styx"),
      h("p", { style: { opacity: 0.7, margin: "0 0 1rem" } },
        "Cerbère garde le passage. The onion URL is a secret — open it in Tor Browser."),
      err ? h("p", { style: { color: "#e85d4c" } }, err) : null,
      h(Card, null,
        h(CardContent, { style: { display: "flex", flexDirection: "column", gap: "0.75rem" } },
          h("div", { style: { display: "flex", alignItems: "center", gap: "0.5rem" } },
            h(Badge, null, running ? "up" : "down"),
            st ? h("span", null, st.target + " → " + st.upstream_host + ":" + st.upstream_port) : null
          ),
          h("div", { style: { fontFamily: "ui-monospace, monospace", fontSize: "0.85rem", wordBreak: "break-all" } },
            (st && st.url) ? st.url : "—"),
          h("div", { style: { display: "flex", gap: "0.5rem", flexWrap: "wrap" } },
            h(Button, { disabled: busy || running, onClick: function () { act("/start"); } }, "Start"),
            h(Button, { disabled: busy || !running, onClick: function () { act("/stop"); } }, "Stop"),
            h(Button, { disabled: !(st && st.url), onClick: copyUrl }, "Copy URL"),
            h(Button, { disabled: busy, onClick: refresh }, "Refresh")
          ),
          h("p", { style: { opacity: 0.6, fontSize: "0.8rem", margin: 0 } },
            "Passphrase: hermes styx passwd · Client auth: hermes styx client-auth")
        )
      )
    );
  }

  REG.register("styx", StyxTab);
})();
