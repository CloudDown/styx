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

- `assets/login-background.jpg`: the local painting embedded in the login page.
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
