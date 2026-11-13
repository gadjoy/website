# Implementation Plan: Self-Hosted Fonts

**Spec**: [spec.md](spec.md) | **Date**: 2026-11-13

## Two commits, kept apart

**Step 1 must not change a pixel.** The files are the ones Google serves for the
site's own request — same bytes, same `unicode-range` subsets — so the only
difference is the host. The proof is the existing e2e screenshot comparison
running against the **unchanged** baselines on the step-1 commit. The fingerprint
probe keeps loading Google's copy in step 1 so it still matches the committed
fingerprint; moving it would skip every comparison and prove nothing.

**Step 2 is meant to change pixels**: buttons and stat captions move from Roboto
to Inter, the Roboto link goes, and the probe renders the self-hosted files.
Baselines are recaptured on CI's image and inspected before commit.

## Where the faces are declared

`static/css/fonts.css`, linked from `headers.html` immediately before
`custom.css`. Not an `@import` inside `custom.css`: an import chain serialises
two requests, and an `@import` below a rule is silently ignored (spec 017).

## Why every subset is carried

Browsers download a subset only when a page uses a character in its range, so
the cyrillic, greek and vietnamese files cost nothing on an English page and keep
names like "Đức" from falling back mid-word.

## Overriding Roboto

The theme names Roboto on class selectors (`.btn`, `.label`, `.breadcrumb`,
`.pagination`, …) that out-rank `custom.css`'s element selectors. One rule in
`custom.css` lists them at equal specificity, later in the cascade. The e2e test
reads computed style, so a selector missed here fails there.
