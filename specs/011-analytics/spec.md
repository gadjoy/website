---
description: "Measure whether publishing actually brings customers in, without breaking the zero-cost, public-by-design setup"
status: in-progress
prs: [29]
---

# Feature Specification: Site Measurement

**Branch**: `feat/analytics` | **Date**: 2026-09-19 | **Constitution**: v2.0.0

## Problem

The site is about to receive eighteen months of backlog, and there is currently **no way to tell
whether any of it brings a single customer in.** `services.googleAnalytics.id` is empty, so no
measurement of any kind exists: not page views, not which repairs get read, not whether anyone
reaches the contact page.

That matters more than usual here. The whole publishing pipeline was built on the premise that
publishing repairs is worth doing. Without measurement that premise stays an assumption, and the
cheapest moment to start measuring is *before* the backlog lands, not after — a step change in
traffic is only visible if something was watching beforehand.

Two constraints from the move off WordPress must survive: **zero hosting cost** and
**public by design**. GA4 is free and client-side, so both hold.

## User Scenarios

### US1 — The owner can see whether publishing works (P1)
After the backlog publishes, it is answerable whether traffic rose, which repairs are read, and
whether readers reach the contact page.

### US2 — A visitor is not tracked by accident (P1)
With no measurement ID configured — the current state, and the state of any fork or local build
— **no analytics script is emitted at all**. Tracking is opt-in by configuration, never a
default that someone forgets to turn off.

### US3 — Do Not Track is honoured (P2)
A visitor who has asked not to be tracked is not tracked, without the owner having to configure
anything.

## Requirements

- **FR-001** Measurement MUST be enabled by a single config value
  (`services.googleAnalytics.id`) and MUST require no template changes — the theme already
  calls Hugo's internal analytics template.
- **FR-002** When that value is empty, the built output MUST contain **no** analytics script,
  tag, or third-party request. Not tracking must be the default.
- **FR-003** `privacy.googleAnalytics.respectDoNotTrack` MUST be `true`, so a visitor's DNT
  signal is honoured without further configuration.
- **FR-004** The measurement ID is **public by design** — it is visible in the page source of
  every site that uses one — and MUST be documented as such next to the value, exactly as
  `web3forms_key` is, so nobody later "fixes" it into a secret or panics on finding it.
- **FR-005** Adding the ID MUST NOT require any other change, so the owner's step is one line.

## Success Criteria

| ID | Criterion | Test coverage |
|---|---|---|
| SC-001 | With no ID configured, the built site emits no analytics script or third-party tag | ✅ `test_no_analytics_until_an_id_is_configured` (asserted on the built site, skips once an ID is set) |
| SC-002 | `respectDoNotTrack` is enabled in config | ✅ `test_do_not_track_is_respected` |
| SC-003 | Setting an ID emits the tag on a real built page | ✅ `test_configuring_an_id_actually_emits_the_tag` (real build, ID injected via env) |
| SC-004 | The config states that the ID is public by design | ✅ documented beside the value in `hugo.yaml` |

## Out of Scope

- **Choosing a vendor.** GA4 is free and the theme already supports it. A self-hosted
  alternative (Plausible, Umami) would reintroduce the hosting cost this stack exists to avoid.
- **Cookie-consent UI.** Worth revisiting if the audience becomes substantially EU-based; the
  shop's customers are in Bangalore, and DNT is honoured either way.
- **Creating the GA4 property.** That is an owner action — this makes it a one-line change.
- **Dashboards or reporting.** Collection first.

## The tradeoff, stated plainly

This adds a Google script to every page of a site whose owner deliberately chose a static,
public, zero-dependency stack. That is a real cost in principle, even though it is free in
money. It is worth it only because the alternative is publishing eighteen months of content
with no idea whether it works. If that trade is unwelcome, FR-002 means doing nothing leaves
the site exactly as it is today — untracked.
