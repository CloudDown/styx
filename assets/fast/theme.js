'use strict';

// Desktop BUILTIN_THEMES, in paletteFor(light/dark) order. Only the ten
// paint slots used here travel with Fast; no theme CSS or font downloads.
const skins = {
  nous: ['ffffff 1f2328 0053fd f6f8fa f6f8fa ffffff d0d7de dae7fd cf222e 656d76','0d1117 e6edf3 4a84fe 010409 010409 0d1117 30363d 07162c f85149 7d8590'],
  github: ['ffffff 1f2328 196d31 f6f8fa f6f8fa ffffff d0d7de dbe7e2 cf222e 656d76','0d1117 e6edf3 4f9e5e 010409 010409 0d1117 30363d 0f2018 f85149 7d8590'],
  catppuccin: ['eff1f5 4c4f69 6d2ebf e6e9ef e6e9ef ccd0da acb0be d7d3e9 d20f39 4c4f69','1e1e2e cdd6f4 cba6f7 181825 181825 313244 585b70 38324b f38ba8 cdd6f4'],
  everforest: ['fdf6e3 5c6a72 586b35 fdf6e3 fdf6e3 fdf6e3 fdf6e3 e9e5ce f1706f 939f91','2d353b d3c6aa a7c080 2d353b 2d353b 2d353b 2d353b 434e47 da6362 859289'],
  solarized: ['fdf6e3 1f1f1f 675e34 eee8d5 d3cbb7 ddd6c1 ddd6c1 c6bea7 e25563 9ca8a6','002b36 839496 6ea1c4 001f26 002b36 073642 234751 144050 e35957 586e75'],
  'nous-alt': ['f8faff 17171a 0053fd f3f7ff ffffff 0053fd4d 0053fd38 f0f5ff c72e4d 666678','0d2f86 ffe6cb 0053fd 09286f 12378f 0b2566 3158ad 143b91 c0473a b5c7f3'],
  classic: ['f5f5f5 2b2109 825d02 f3f2f2 f0f0ef f5f5f5 cd7f32 e7e3d8 c62828 b8860b','1a1a2e fff8dc ffbf00 1f1e31 232335 1a1a2e cd7f32 433826 ef5350 b8860b'],
  midnight: ['ffffff 161616 8b80e8 f4f4f9 ffffff d2d0e6 deddee f3f2fd b94a3a 706e83','08081c ddd6ff 8b80e8 06061a 0d0d28 1e1e52 1e1e52 14143a b03060 7c7ab0'],
  ember: ['ffffff 161616 d97316 f8f3ef ffffff e0cec1 e9dbd1 fbf1e8 b94a3a 7d6c62','160800 ffd8b0 d97316 100600 1e0e04 3a1c08 3a1c08 2a1000 c43010 aa7a56'],
  mono: ['ffffff 161616 9a9a9a f5f5f5 ffffff d5d5d8 e1e1e3 f5f5f5 b94a3a 737377','0e0e0e eaeaea 9a9a9a 0a0a0a 141414 2a2a2a 2a2a2a 1a1a1a a84040 808080'],
  slate: ['ffffff 161616 58a6ff f2f6fa ffffff c9d7eb d7e2f1 eef6ff b94a3a 687487','0d1117 c9d1d9 58a6ff 090d13 161b22 30363d 30363d 1e2a38 cf4848 8b949e'],
  cyberpunk: ['ffffff 161616 00ff41 eefaf1 ffffff b9e7c8 cbefd7 e6ffec b94a3a 5a8368','000a00 00ff41 00ff41 000600 001200 003000 003000 001400 ff003c 1a8a30'],
};
const systemDark = matchMedia('(prefers-color-scheme: dark)');
let themePrefs = {};
const APPEARANCE = 'styx-fast-appearance';
let appearance = '';
try { appearance = localStorage.getItem(APPEARANCE) || ''; } catch {}
if (!['light','dark'].includes(appearance)) appearance = '';
// Ease a real appearance change; never animate the first paint (it would
// flash from the default palette to the stored one).
let themePainted = false, themeTimer = 0;
function paintTheme() {
  const root = document.documentElement;
  if (themePainted) {
    root.classList.add('theming');
    clearTimeout(themeTimer);
    themeTimer = setTimeout(() => root.classList.remove('theming'), 320);
  }
  themePainted = true;
  const pref = key => {
    if (Object.hasOwn(themePrefs, key)) return themePrefs[key];
    try { return localStorage.getItem(key); } catch { return null; }
  };
  const record = key => { try { return JSON.parse(pref(key)) || {}; } catch { return {}; } };
  const key = profile || 'default';
  const name = appearance ? 'nous' : record('hermes-desktop-profile-themes-v1')[key] || pref('hermes-desktop-theme-v2') || 'nous';
  const mode = appearance || record('hermes-desktop-profile-modes-v1')[key] || pref('hermes-desktop-mode-v1');
  let dark = mode === 'dark' || (mode !== 'light' && systemDark.matches);
  const builtin = (Object.hasOwn(skins,name) ? skins[name] : skins.nous)[+dark].split(' ').map(v => '#' + v);
  const custom = Object.hasOwn(skins,name) ? null : record('hermes-desktop-user-themes-v1')[name]
    || record('hermes-desktop-backend-themes-v1')[name];
  const colors = (dark && custom?.darkColors) || custom?.colors || {};
  const slots = ['background','foreground','midground','sidebarBackground','card','input','border','userBubble','destructive','mutedForeground'];
  const [bg,ink,accent,rail,card,input,border,bubble,alert,muted] = slots.map((slot,i) => {
    const v = colors[slot] ?? (slot === 'midground' ? colors.primary : null);
    return /^#[\da-f]{6}([\da-f]{2})?$/i.test(v) ? v : builtin[i];
  });
  const rgb = [1,3,5].map(i => parseInt(bg.slice(i,i+2),16));
  dark = .2126*rgb[0] + .7152*rgb[1] + .0722*rgb[2] < 127.5;
  const mix = (a,n,b) => `color-mix(in srgb, ${a} ${n}%, ${b})`;
  const scale = Number(pref('hermes.desktop.chat-text-scale.v1'));
  const style = document.documentElement.style;
  style.colorScheme = dark ? 'dark' : 'light';
  for (const [k,v] of Object.entries({
    ground: mix(bg,dark?74:92,dark?'#0d0d0e':'#f3f3f3'), rail, ink, accent, input, border, alert,
    muted, card: mix(card,dark?38:22,dark?'#161618':'#fcfcfc'),
    bubble: dark ? mix(bubble,46,'#161618') : '#fcfcfc', wordmark: dark ? mix(ink,90,bg) : accent,
    ring: mix(accent,dark?23:18,input), 'chat-scale': [90,100,110,125,150,175].includes(scale) ? scale/100 : 1.1,
  })) style.setProperty('--'+k,v);
  document.documentElement.dataset.skin = name;
  for (const meta of document.querySelectorAll('meta[name="theme-color"]')) meta.content = bg;
}
