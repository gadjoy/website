---
description: "Implementation plan for site measurement"
---

# Implementation Plan: Site Measurement

**Branch**: `feat/analytics` | **Date**: 2026-09-19 | **Spec**: `./spec.md`

## Summary

Config plus tests. The theme already calls Hugo's internal analytics template, so there is no
template work: the entire change is a privacy block, a documented empty ID, and guards that
prove nothing is emitted until someone sets it.

## Constitution Check (v2.0.0)

- **X. Public claims trace to a source**: PASS — nothing user-visible is claimed.
- **VIII. Gates in CI**: PASS — the "no ID means no tracking" property is asserted against the
  built site, not assumed from config.
- **I. Test-First**: PASS.

No violations → Complexity Tracking empty.

## Approach

`hugo.yaml` gains a `privacy.googleAnalytics.respectDoNotTrack: true` block and a comment
stating the ID is public by design, mirroring how `web3forms_key` is documented.

The interesting test is the negative one: **build the site and assert no analytics tag exists**.
That is the property that protects visitors today and in every fork, and it is the one that
would silently break if someone pasted an ID into the wrong place. The positive case is proven
by building with an ID injected via `HUGO_SERVICES_GOOGLEANALYTICS_ID`, so the test does not
depend on committing a real property ID.

## Validation

Both directions are mutation-tested: setting an ID must make the negative test fail, and
removing the privacy block must make the DNT test fail. A test that only ever runs in the
"nothing configured" state cannot tell a working integration from a broken one.

## Phases

- **A**: spec, then tests (RED)
- **B**: config
- **C**: mutation-test both directions
