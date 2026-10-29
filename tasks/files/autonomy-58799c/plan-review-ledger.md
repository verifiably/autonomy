# Closed messages policy review ledger

Task: autonomy-58799c.
Review source: plan-round-2-report.md, supplied through the user.
Reviewed revision: 10547f2b50b2cd60e1e294ef46535c545a04843f,
docs/plans/2026-10-29-closed-messages-policy.md.
Reviewer: claude-code/claude-opus-5-5 (identity supplied by the reviewer).
Controller: Codex, plan author. These Why/Cost assessments are the controller's
rulings, recorded here before revising the plan.

## Plan round 2 — revise, Important 2 / Minor 4

Ruling: I1 accepted; add a standalone acceptance case using the exact captured
__pi_deferred_placeholder__ tool in an otherwise plain request. Why: it appears
only in the inline capture, whose expected refusal cannot prove acceptance of
this tool. Confirmed against all four captured tool lists and decision 13's first
acceptance row. Cost: if unnecessary, one extra fixture-dependent positive test.
Source revision: 10547f2; revised revision recorded below after freezing.

Ruling: I2 accepted; require 400-digit integer tokens to pass at temperature and
top_p, both in parsed-body tests and through the fake upstream with HTTP 200.
Why: the spec permits finite integers without provider ranges; stdlib JSON parses
the token, while math.isfinite(int) raises OverflowError, which the existing
server catches as a 502/upstream-error. Cost: if this interpretation is wrong,
these acceptance tests would require a reviewed contract change; they deliberately
make no claim about real provider range acceptance. Source revision: 10547f2.

Ruling: M3 accepted and fixed in the plan; move the spec's implemented marker
out of Task 2 and after final whole-branch review and corrective rounds. Why:
passing tests alone does not fulfill the file map's review condition. Cost: if
unnecessary, one small metadata-only documentation commit after review.
Source revision: 10547f2.

Ruling: M4 accepted and fixed in the plan; add a body-level explicit-custom
acceptance case under an authorizing route plus its unlisted negative. Why:
route parsing and the existing refusal do not prove the authorized body path.
Cost: if redundant, one extra parameterized positive/negative test pair.
Source revision: 10547f2.

Ruling: M5 accepted and fixed in setup instructions; merge current local main,
rehydrate, then run the full baseline after human plan approval. Why: ecd5858
changed the same two test/fixture files, and an older-base baseline omits those
regressions. Ordinary merge preserves both frozen revisions; do not amend or
rebase them or merge main while the revised plan awaits review. Cost: if main
moves incompatibly, setup may require conflict resolution before the baseline.
Source revision: 10547f2; inspected main change: ecd5858.

Ruling: M6 accepted and fixed in the plan; consistently name the field test
test_undefined_fields_are_refused and name the tool/unused-operation tests
separately. Why: prose and example currently name the same field case differently.
Cost: if unnecessary, a naming-only plan edit. Source revision: 10547f2.

No minor (deferred) entries. No finding rejected or regraded.

## Author's decomposition decision

Keep the two dependent deliverables. The body policy shares the same parser,
operation and recursive context checks; splitting it creates an intermediate
partially enforced policy without an independent interface. The reviewer
explicitly left this choice to the author rather than filing a defect. Unit and
integration tests remain separate, named checks within Task 2. This is an author
choice, not a new user-approved decision.

## Gate and evidence

Review round 2 is dispositioned by these rulings; author may now revise the plan
into a new commit. Implementation, merging main and the full-suite baseline remain
stopped until the new frozen plan is reviewed. No production code changes made.

## Revised frozen plan and self-review

All six rulings above were applied in new frozen plan revision
f3d686d73445b2b905f7604319791f3b74aa7b7b,
docs/plans/2026-10-29-closed-messages-policy.md. Each ruling's revision pair is
10547f2 → f3d686d. The original frozen commit was neither amended nor rebased.

Plan round 3 is the author's self-review: accept, no findings; reviewer
codex/gpt-6.1-sol, identity freshly verified with relay (exit 0). This acceptance
records only self-review; the revised plan still requires human review.

Verification: all four Python examples parse; both document links resolve; the
pinned capture's SHA-256 matches; exact placeholder and 400-digit integer sample
construction were checked using standard-library operations. The math.isfinite
overflow was reproduced with stdlib JSON, not by running production code.
just check exits 0 with the two existing unlinked_step warnings (both sequential
deliverables tracked by this one task); git diff --check passes. No product tests
run, product code edited, main merge performed, live API used or desktop touched.
Full suite remains due at execution setup on the merged base.

No rulings rejected; no minor (deferred) entries. All I1/I2/M3/M4/M5/M6 are
addressed in the plan, not claims that the future implementation already passes.
