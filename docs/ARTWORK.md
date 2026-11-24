# Styx artwork

The Cerberus login background is a reproduction of Luca Giordano's fresco
*The Barque of Charon, the Sleep of Night and Morpheus* (1684–1686), in the
Palazzo Medici-Riccardi, Florence.

- Source: [Luca Giordano 009FXD.jpg on Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Luca_Giordano_009FXD.jpg).
- The Commons file page identifies the artwork and its reproduction as public domain.
- That reproduction derives from the Yorck Project image; the corrected version
  was uploaded by Pixel8tor in 2021. See the source page for its provenance and
  public-domain notices. Styx does not claim copyright over the fresco.

## Files

- `assets/login-background.jpg`: the original local painting, retained as the master.
- `assets/login/*.avif` and `assets/login/*.webp`: eight prebuilt, centered
  crops (portrait, tablet, landscape and wide) in AVIF and WebP. `<picture>`
  offers AVIF first and falls back to WebP; native media queries and width
  descriptors select by viewport aspect ratio, width and pixel density, capped
  at the largest candidate per crop. A phone downloads a 480/640-pixel-wide
  portrait, not the original landscape painting. AVIF is roughly 35–45 % smaller
  than the equivalent WebP. The crops have content-addressed, same-origin
  immutable URLs; the private form and CSRF token remain `no-store`. There is
  no request-time resizing, external image service or JavaScript. Narrow phone
  widths keep the portrait source while the keyboard shortens the viewport,
  avoiding an extra background download during password entry.
- `assets/login/preview.webp`: a tiny (48-pixel-wide) inline preview painted
  immediately with the form, while the selected detailed crop downloads.
- `docs/login.png`: the existing 1440 × 900 login-page screenshot used in the README
  and catalog gallery. It contains no browser chrome, address, entered password or session data.
- `docs/catalog-banner.jpg`: a 1200 × 600 crop of that same screenshot for the
  catalog's 2:1 card. No new artwork, labels or fabricated UI have been added.

The card can be reproduced from the repository root with ImageMagick:

```bash
magick docs/login.png -gravity center -crop 1440x720+0+0 +repage \
  -resize 1200x600 -strip -sampling-factor 4:4:4 -quality 90 docs/catalog-banner.jpg
```

The login page uses only local assets. Linking to this credit does not cause
the gate or login page to contact Wikimedia.

Rebuild the login crops with `python scripts/build_login_backgrounds.py` in a
development environment with Pillow, `avifenc` and the plugin dependencies
installed. Without an AVIF encoder the script rebuilds WebP and leaves AVIF
unchanged. The gate itself requires neither Pillow nor libavif.
