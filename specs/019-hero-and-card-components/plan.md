# Implementation Plan: Hero & Card Components

**Spec**: [spec.md](spec.md) | **Date**: 2026-11-07

## Two kinds of change, kept apart

**Refactors that must not change a pixel** — the hero partial (FR-001) and the
shared card surface (FR-002). The visual baselines are the proof, exactly as for
the token pass in spec 017.

**Fixes that are meant to change pixels** — styling the bare cards (FR-003) and
the single underline (FR-004).

Kept in separate commits so the baselines can attribute every moved pixel. If a
page that should be identical moves, the refactor was not value-preserving and
gets fixed rather than re-baselined.

## The card surface

One rule lists every card class and declares background, border and shadow once.
It sits before the per-card rules, at the same specificity, so the per-card rules
still win for what they override — `.svc-card` keeps its larger radius that way.

## The guard that was missing

FR-005 is the one that matters most going forward: two pages shipped with cards
styled by classes that do not exist, and every gate stayed green. A class
referenced in markup with no rule in the stylesheet is now a failing test.
