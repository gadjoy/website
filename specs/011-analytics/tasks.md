---
description: "Task list for site measurement"
---

# Tasks: Site Measurement

> **Status: IN PROGRESS.** Collection is wired and guarded; creating the GA4 property and
> pasting its ID is the owner's one remaining step (T005).

**Input**: `specs/011-analytics/{spec,plan}.md` | **Constitution**: v2.0.0

---

- [x] T001 Tests first, confirmed RED: no analytics in the built site; DNT configured.
- [x] T002 Add the `privacy.googleAnalytics` block and document the ID as public by design.
- [x] T003 Positive test: injecting an ID via env emits the tag on a real build.
- [x] T004 Mutation-test both directions.
- [ ] T005 **OWNER ACTION** — create a GA4 property and paste its `G-XXXXXXX` into
      `services.googleAnalytics.id`. Nothing is collected until this happens, by design.

## Deferred

- [ ] D001 Cookie-consent UI, if the audience becomes substantially EU-based.
- [ ] D002 Search Console verification — complements analytics for "how are people finding us",
      and is also an owner action.
