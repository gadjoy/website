# Implementation Plan: Design System & Two Dead Pages

**Spec**: [spec.md](spec.md) | **Date**: 2026-10-31

## The dead pages first

They are defects a customer hits today, and neither depends on the token work.
`/services/` gets a real list layout; `_index.md`'s body gets rendered.

## Tokens, value-preserving

The 16 shadows and 7 radii are not 16 and 7 *intentions* — they are a handful of
intentions typed slightly differently. They collapse onto a small token set
chosen from the values already most used, so the rendered result is unchanged.

That constraint is the whole point. A token pass that also adjusts the look is a
redesign wearing a refactor's clothes, and nobody can review which half is which.
**The visual baselines are the proof**: if the diff is non-zero anywhere, the
substitution changed something it should not have, and the capture at the end of
this work is the check.

## What is deliberately NOT done

The working plan also lists one `page-hero.html`, one `.section-title`, one
`.gj-card`. Those are real improvements and they are large refactors of markup
that currently works, whose visible outcome is "identical, but tidier" — while
moving every baseline and risking regressions on a live business site for no
customer-facing gain.

Tokens first is the right order: they are what makes that refactor mechanical
and reviewable later. Recorded as deferred with a reason, not dropped.

## Open Graph

The shop's primary channel is WhatsApp, where a shared link currently renders as
a bare URL. This is the highest-value item in the spec and the cheapest.
