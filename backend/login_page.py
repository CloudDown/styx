"""Minimal login page with viewport-selected, same-origin painting crops."""

from __future__ import annotations

import base64
import hashlib
import html as htmlmod
from functools import lru_cache

from .paths import PLUGIN_ROOT


# Prebuilt crops, not an unbounded request-time image resizing service. Widths
# cap transfer/decode cost even on high-DPR phones. Keep the original as master.
BACKGROUND_SIZES = {
    "portrait-480": (480, 1040),
    "portrait-640": (640, 1387),
    "tablet-640": (640, 854),
    "tablet-960": (960, 1280),
    "landscape-960": (960, 600),
    "landscape-1600": (1600, 1000),
    "wide-1280": (1280, 549),
    "wide-1920": (1920, 823),
}
BACKGROUND_GROUPS = (
    # Keep a narrow phone's selected crop stable when the keyboard shortens
    # its viewport: typing must not initiate a second background download.
    ("(max-width: 600px), (max-aspect-ratio: 3/5)", ("portrait-480", "portrait-640")),
    ("(max-aspect-ratio: 1/1)", ("tablet-640", "tablet-960")),
    ("(max-aspect-ratio: 2/1)", ("landscape-960", "landscape-1600")),
    ("", ("wide-1280", "wide-1920")),
)
_DEFAULT_BACKGROUND = "landscape-1600"


@lru_cache(maxsize=len(BACKGROUND_SIZES))
def background_bytes(variant: str = _DEFAULT_BACKGROUND) -> bytes:
    if variant not in BACKGROUND_SIZES:
        raise ValueError("unknown login background")
    image = PLUGIN_ROOT / "assets" / "login" / f"{variant}.webp"
    return image.read_bytes()


@lru_cache(maxsize=len(BACKGROUND_SIZES))
def background_url(variant: str = _DEFAULT_BACKGROUND) -> str:
    # Only the public painting is cacheable; never the form or its CSRF token.
    digest = hashlib.sha256(background_bytes(variant)).hexdigest()
    return f"/_styx/login-background-{variant}-{digest}.webp"


def _srcset(variants: tuple[str, ...]) -> str:
    return ", ".join(
        f"{background_url(variant)} {BACKGROUND_SIZES[variant][0]}w" for variant in variants
    )


@lru_cache(maxsize=1)
def _preview() -> str:
    image = (PLUGIN_ROOT / "assets" / "login" / "preview.webp").read_bytes()
    return "data:image/webp;base64," + base64.b64encode(image).decode("ascii")


def _painting() -> str:
    sources = "\n".join(
        f'<source media="{media}" srcset="{_srcset(variants)}" sizes="100vw">'
        for media, variants in BACKGROUND_GROUPS if media
    )
    fallback = BACKGROUND_GROUPS[-1][1]
    # No unconditional image preload: it would download the wrong crop as well
    # on mobile. The native picture/preload scanner chooses exactly one source.
    return f"""<picture class="painting" aria-hidden="true">
{sources}
<img src="{background_url(fallback[0])}" srcset="{_srcset(fallback)}"
     sizes="100vw" width="1280" height="549" alt=""
     fetchpriority="high" decoding="async" draggable="false">
</picture>"""


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
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content">
<meta name="color-scheme" content="dark">
<meta name="referrer" content="no-referrer">
<meta name="theme-color" content="#292a28">
<title>Styx</title>
<style>
  * {{ box-sizing: border-box; }}
  html {{
    background: #292a28;
    -webkit-text-size-adjust: 100%;
    -webkit-tap-highlight-color: transparent;
  }}
  body {{
    isolation: isolate;
    margin: 0;
    min-height: 100vh;
    min-height: 100svh;
    min-height: 100dvh;
    display: grid;
    place-items: center;
    padding: max(24px, env(safe-area-inset-top, 0px))
             max(24px, env(safe-area-inset-right, 0px))
             max(24px, env(safe-area-inset-bottom, 0px))
             max(24px, env(safe-area-inset-left, 0px));
    color: #fff;
    font-family: system-ui, sans-serif;
  }}
  .painting {{
    position: fixed;
    inset: 0;
    z-index: -1;
    pointer-events: none;
    background: url("{_preview()}") center / cover no-repeat;
  }}
  .painting img {{
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
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
    -webkit-user-select: none;
    user-select: none;
  }}
  @media (hover: hover) and (pointer: fine) {{
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
  @media (pointer: coarse) {{
    input {{ height: 48px; }}
    button {{ flex-basis: 48px; height: 48px; }}
  }}
  @media (pointer: coarse) and (max-width: 600px) {{
    body {{
      align-items: end;
      padding-bottom: calc(clamp(80px, 18dvh, 144px) + env(safe-area-inset-bottom, 0px));
    }}
    main {{ width: min(360px, 100%); }}
    #error {{
      top: auto;
      bottom: calc(100% + 12px);
      margin: 0;
    }}
  }}
  @media (pointer: coarse) and (max-height: 500px) {{
    body {{
      align-items: center;
      padding-bottom: max(24px, env(safe-area-inset-bottom, 0px));
    }}
  }}
</style>
</head>
<body>
{_painting()}
<main aria-label="Styx login">
  <form method="post" action="/login">
    <input type="hidden" name="csrf" value="{csrf_e}">
    <div class="field">
      <input id="password" name="password" type="password" required autofocus
             autocomplete="current-password" aria-label="Password"
             autocapitalize="none" autocorrect="off" spellcheck="false" enterkeyhint="go"
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
