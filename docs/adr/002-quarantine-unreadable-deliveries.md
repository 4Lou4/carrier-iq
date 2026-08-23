# ADR-002: Quarantine unreadable deliveries instead of dropping or failing on them

*Status: accepted. Supersedes nothing. The move to PostgreSQL, foreseen in ADR-001,
becomes ADR-003: ADRs are numbered in the order decisions are taken, not planned.*

## Context

The raw layer is a faithful record of what arrived (ADR-001), so it holds whatever
upstream sent, including deliveries that cannot be read at all: no identifier, a
negative billable duration. Staging deduplicates and types, but until now it had no
answer for a row that is not merely incomplete but meaningless.

The distinction matters and is easy to blur. A missing purchase rate is **incomplete
but readable**: the row still describes a call that happened, so it flows through and
its coverage is watched by a merge-blocking gate. A row with no identifier is
**unreadable**: it cannot be deduplicated, therefore it cannot be counted once,
therefore nothing aggregated over it means anything.

## Options considered

**Let them through.** Cheapest, and wrong: a negative duration silently biases every
aggregate that touches it, and the failure surfaces weeks later as a number nobody can
explain.

**Fail the load.** Correct in principle, unusable in practice. One damaged delivery
stops a run that is otherwise fine. Teams respond to that by disabling the check, and
then there is no check.

**Set them aside, keep them, count them.** Chosen. The row is written to
`stg_call_events_quarantine` with the reason it was rejected, excluded from staging,
and its volume is asserted by a test.

## Decision

A dead letter queue, with three properties that are the actual decision:

1. **One definition of "unreadable"**, in the `quarantine_reason` macro, used by both
   the quarantine model and the staging exclusion. Written twice, the two would drift
   and a row would end up either counted twice or not at all.
2. **Rejected rows are kept, not deleted.** A quarantine you cannot query is a
   deletion with extra steps. When someone asks why yesterday's totals are short, the
   answer has to be a query.
3. **The volume is under test, on both sides.** Above 1% of deliveries the build
   fails, because a queue that grows silently converts a loud upstream failure into a
   quiet undercount. At exactly zero it also fails, because a queue that never holds
   anything is decoration — the same rule the coverage gate follows.

## The trade-off we accept

Staging now depends on a macro rather than reading the source directly. That is one
more indirection to follow when reading the model, bought in exchange for the two
definitions being unable to disagree.

## What we found while building it, and what it defers

The generator injects unreadable deliveries so the quarantine has something to catch.
A third defect belongs in that list and is deliberately absent: an event dated in the
future, which upstream clock skew genuinely produces.

It cannot be injected here, because **it would break the loader before the quarantine
ever saw it**. Loading is incremental on `occurred_at` and dlt keeps the maximum value
seen as a high-water mark. A single row dated 2036 moves that mark to 2036; every
later run then asks for events at or after 2036, finds none, reports success, and
loads nothing — indefinitely. A silent stop, dressed as a green pipeline.

The general form is worth stating plainly: **a validation placed after the cursor
cannot protect the cursor.** Fixing it means validating before the high-water mark
advances, which is orchestration work rather than generation work. It is deferred to
the DAG, and a test pins the defect as absent in the meantime so nobody adds it back
without reading this. The macro still checks for future dates, so a row arriving by
any other path is held back rather than counted.
