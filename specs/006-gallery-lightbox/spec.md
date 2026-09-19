---
description: "Gallery as a before/after lightbox wall rather than blog-style thumbnails"
status: shipped
shipped: 2026-06-06
prs: [5]
backfilled: 2026-08-05
---

# Feature Specification: Before/After Gallery Wall

**Shipped**: 2026-06-06 via PR #5 | **Backfilled**: 2026-08-05 | **Constitution**: v2.0.0

> **Retrospective spec**, reconstructed from PR #5, commits `d8e33e51` and `cdb485f4`, and
> `layouts/_default/gallery.html`.

## Problem

The gallery rendered as a list of blog-like cards — the same treatment as `/blog/`, so it
duplicated the archive without adding anything. The repair photos are the strongest asset the
business has (genuine before/after pairs from the bench), and the card layout buried them at
thumbnail size behind titles and dates.

## User Scenarios

### US1 — A visitor scans a wall of real work (P1)
The gallery presents images at scale as a dense wall, not a paginated list of titled cards.

### US2 — A visitor inspects one repair closely (P1)
Clicking any image opens it full-size in a lightbox, dismissible without leaving the page.

### US3 — A visitor sees before and after together (P2)
Pairs read as pairs, so the transformation is legible rather than requiring the viewer to
reconstruct it.

## Requirements

- **FR-001** The gallery MUST render through `layouts/_default/gallery.html`, selected by
  `layout: gallery` in the page's front matter.
- **FR-002** Images MUST be laid out as a masonry/dense wall, visually distinct from the blog
  list treatment.
- **FR-003** Clicking an image MUST open a lightbox with the full-size asset; it MUST be
  closable by control and by keyboard.
- **FR-004** Lightbox behaviour MUST be implemented in the project's own JS
  (`layouts/partials/custom_headers.html`), not by adding a third-party dependency.
- **FR-005** Images MUST be lazy-loaded, and MUST use the optimised WebP assets produced by
  `008` — the gallery is the heaviest page on the site.
- **FR-006** No blog metadata (date, author, tags, sidebar) may appear on the gallery page.

## Success Criteria

| ID | Criterion | Test coverage |
|---|---|---|
| SC-001 | `/gallery/` returns 200 | ✅ `scripts/smoke.sh` |
| SC-002 | Renders the gallery layout, not the theme fallback | ✅ `test_page_uses_its_project_layout`; mutation-tested (first marker passed vacuously — see below) |
| SC-003 | Every gallery image reference resolves to a real asset | ✅ `test_internal_refs_resolve` |
| SC-004 | Lightbox opens and closes, including by keyboard | **OWED** (needs a browser) |
| SC-005 | Images are lazy-loaded and served as WebP | **OWED** |
| SC-006 | No published image exposes an IMEI, serial, MAC or owner name (FR-007) | ✅ `test_no_device_identifiers.py` — hash manifest + OCR for new/changed images |

## Out of Scope

- Captions or per-image case notes. The blog posts carry the write-ups; the gallery is visual.
- Filtering by device or repair type.
- Any image upload or admin flow — assets come from the migration and `008`.

## As Built

Two commits inside PR #5: `d8e33e51` created `layouts/_default/gallery.html` (45 lines) with the
grid and typography pass; `cdb485f4` rebuilt it as the before/after lightbox wall (+26/−…) and
added the lightbox JS to `custom_headers.html` (+27 lines).

FR-005's dependency on `008` is real and was satisfied in the other order: the gallery shipped
first (PR #5, 21:07) and the WebP conversion landed later the same evening (PR #8, 22:57), so
for about 100 minutes the gallery was serving unoptimised originals from a 1.49 GB artifact.

### Privacy constraint discovered later, recorded here

A related decision from the portfolio work applies to this feature and belongs in its spec:
repair photographs must not publish customer-identifying data. Cards showing **IMEIs and
serial numbers** were identified on the live site and flagged for removal — those are
identifiers used in device fraud, and the customers did not consent to publication.

**FR-007** — no gallery or post image may display an IMEI, serial number, MAC address, or other
device/customer identifier. Where a photo carries one, the identifier is **redacted, not the
photo deleted**: the repair shot is legitimate evidence of the work, and only the identifier
block has to go.

Resolved 2026-08-06 (see As Built → Redaction), and now enforced at build time.

### Redaction: FR-007 resolved (2026-08-06)

The identifiers were found and obfuscated rather than deleted.

**What was exposed — far more than the two images originally reported.** The original report
named two ("Dipti's A03", "Sheikh's iPad"). An OCR sweep of all 2,711 upload images found
**241 flagged, of which 229 are on repair posts** — i.e. genuine device screens. The remaining
12 are false positives on `code`/`build` posts, where a Python console printed a long float
(`3529411764705883` is 60÷17) that pattern-matches an IMEI.

Verified examples:

| Image | Exposed |
|---|---|
| `2023/02/image-53/54.webp` (Galaxy A03 Core) | Serial `R9ZT…`, IMEI slot 1 + slot 2 |
| `2023/05/image-4.webp` (Galaxy On Nxt) | Serial `RZ8J…`, IMEI `357956…483` / `357957…481` |
| `2022/05/image-34.webp`, `2022/08/image-10.webp` | Wi-Fi/Bluetooth MAC addresses |

62 images yielded a full identifier **value** to OCR; the other 167 were caught on labels
("IMEI", "Serial number") where the digits were legible to a human but not cleanly machine-read
— which makes them no less exposed. Many appear in slot-1/slot-2 pairs, the signature of a
dual-SIM About screen.

The earliest dates from 2021-12 and the most recent from 2025-01, so this ran the full life of
the blog. Calling the practice "systematic" was accurate: photographing the About screen was
evidently the shop's standard way of recording which device came in.

**How it was fixed.** `migration/scripts/redact_device_identifiers.py` applies a coarse mosaic
plus blur to the three value regions, in place, preserving filename and format. Deliberately
*not* a light pixelation: a fine mosaic over known-format text (15 digits, fixed glyph set) is
in principle attackable by rendering candidates and comparing blocks, so each region is
collapsed to a handful of blocks and then blurred, which destroys the glyphs outright.

The **labels are left readable** — "Serial number", "IMEI (slot 1)", "IMEI (slot 2)" still show
above grey bands. A visible redaction is honest about what was removed, and the photo still
reads as proof of the repair, which is the whole reason for keeping it.

Verified by re-running OCR on the saved files: no 14–16 digit run and no serial fragment is
recoverable, while the surrounding text ("Galaxy A03 Core", "Model number SM-A032F/DS", the
Status paragraph) is untouched.

**Sweep.** All 2,711 upload images were OCR-swept rather than trusting the two known cases — the
original report described the practice as systematic.

**A redaction pass that looked finished and was not.** The first automated pass swept the band
*below* each identifier label, which is where the value sits on newer Samsung/Android About
screens. It ran over 226 images with zero errors and zero refusals — and left
`2023/05/image-4.webp` with its serial `RZ8J50WTJRR` **fully legible**, because that device uses
a two-column layout with the value to the *right* of the label, not beneath it. Caught by opening
the image after the "successful" batch.

Each label now gets one band from the label to the right edge of the frame, tall enough to
include the following line, covering both layouts. The cost is over-redaction — the label text
goes too, along with boilerplate like *"View the SIM card status, IMEI, and other information"* —
which is the right direction to err, bounded by a `MAX_REDACT_FRACTION` ceiling that refuses to
write rather than destroying the photo.

Two process points worth keeping:

- **A batch reporting 226/226 success is not evidence the work is correct.** It only proved no
  exceptions were raised. The geometry was wrong for a whole class of layout and the exit codes
  could not see it.
- **Re-running the fix required restoring the originals from git first.** Redaction is not
  idempotent for detection purposes: OCR cannot find a label it has already mosaiced, so a
  second pass over redacted files finds nothing and silently leaves the gaps in place.

## Tests Owed

SC-002 is closed by the table-driven check in `test_site_output.py`. Worth knowing why the
first attempt did not work: the obvious marker (`gj-lightbox`) also appears in
`custom_headers.html` as a JS selector, so it survived in the built HTML with the gallery
layout deleted and the guard passed vacuously. `gadjoy-gallery-intro` is emitted only by the
layout. SC-005 is a cheap output
assertion (`loading=lazy` present, `.webp` extensions).

FR-007 is **no longer owed** — `migration/tests/test_no_device_identifiers.py` enforces it at
build time. It was previously listed as un-automatable; that was wrong. What made it tractable
is keying on **content hash**: the manifest records every image already OCR-reviewed, so the
build OCRs only new or modified files (none in steady state), and restoring a pre-redaction
original is caught by hash alone even without OCR available.
