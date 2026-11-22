"""Minimal login page with a same-origin, cacheable painting. No JavaScript."""

from __future__ import annotations

import hashlib
import html as htmlmod
from functools import lru_cache

from .paths import PLUGIN_ROOT


@lru_cache(maxsize=1)
def background_bytes() -> bytes:
    image = PLUGIN_ROOT / "assets" / "login-background.jpg"
    return image.read_bytes()


@lru_cache(maxsize=1)
def background_url() -> str:
    # Only the public painting is cacheable; never the form or its CSRF token.
    digest = hashlib.sha256(background_bytes()).hexdigest()
    return f"/_styx/login-background-{digest}.jpg"


def render(error: str = "", csrf: str = "") -> str:
    csrf_e = htmlmod.escape(csrf, quote=True)
    banner = (
        f'<p id="error" role="alert">{htmlmod.escape(error)}</p>' if error else ""
    )
    error_attrs = ' aria-invalid="true" aria-describedby="error"' if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="referrer" content="no-referrer">
<title>Styx</title>
<link rel="preload" as="image" href="{background_url()}" fetchpriority="high">
<style>
  * {{ box-sizing: border-box; }}
  html {{ background: #292a28; }}
  body {{
    margin: 0;
    min-height: 100vh;
    min-height: 100svh;
    display: grid;
    place-items: center;
    padding: 24px;
    color: #fff;
    font-family: system-ui, sans-serif;
    background-position: center;
    background-size: cover;
    background-repeat: no-repeat;
    background-image: url("{background_url()}");
  }}
  main {{ position: relative; width: min(320px, 100%); }}
  .field {{
    position: relative;
    isolation: isolate;
    display: flex;
    align-items: center;
    padding: 5px;
    border: 1px solid rgba(255, 255, 255, .35);
    border-radius: 999px;
  }}
  .field::before {{
    content: "";
    position: absolute;
    inset: 0;
    z-index: -1;
    border-radius: inherit;
    pointer-events: none;
    background: rgba(20, 24, 26, .38);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
  }}
  .field:focus-within {{ border-color: rgba(255, 255, 255, .85); }}
  input {{
    width: 100%;
    min-width: 0;
    height: 44px;
    border: 0;
    border-radius: 999px;
    outline: none;
    padding: 0 14px;
    background: transparent;
    color: #fff;
    font: inherit;
    font-size: 16px;
    caret-color: #fff;
  }}
  input::placeholder {{ color: rgba(255, 255, 255, .85); }}
  button {{
    display: grid;
    place-items: center;
    flex: 0 0 44px;
    height: 44px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: transparent;
    color: #fff;
    cursor: pointer;
    touch-action: manipulation;
  }}
  @media (hover: hover) {{
    button:hover {{ background: rgba(255, 255, 255, .15); }}
  }}
  button:active {{ background: rgba(255, 255, 255, .25); }}
  button:focus-visible {{ outline: 2px solid #fff; outline-offset: -2px; }}
  button svg {{ width: 20px; height: 20px; }}
  #error {{
    position: absolute;
    top: 100%;
    left: 0;
    width: 100%;
    margin: 12px 0 0;
    padding: 8px 12px;
    border-radius: 18px;
    background: rgba(20, 24, 26, .65);
    -webkit-backdrop-filter: blur(16px);
    backdrop-filter: blur(16px);
    text-align: center;
    font-size: 13px;
    line-height: 1.5;
  }}
</style>
</head>
<body>
<main aria-label="Styx login">
  <form method="post" action="/login">
    <input type="hidden" name="csrf" value="{csrf_e}">
    <div class="field">
      <input id="password" name="password" type="password" required autofocus
             autocomplete="current-password" aria-label="Password"
             placeholder="Password"{error_attrs}>
      <button type="submit" aria-label="Sign in">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
             aria-hidden="true">
          <path d="M5 12h14m-6-6 6 6-6 6"/>
        </svg>
      </button>
    </div>
    {banner}
  </form>
</main>
</body>
</html>
"""
