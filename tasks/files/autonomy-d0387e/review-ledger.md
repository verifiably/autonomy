# Nested-policy research review ledger

Task: autonomy-d0387e. Review round 1 by codex/gpt-6-astra, frozen research
revision e8fdb3aa4e4435a91f869ff280af02168707b01b, base 2742a6f.
Full returned review: policy-review-report.md (task attachment).
Verdict: accept; Critical 0, Important 0, Minor 1. No corrective round required.

- Ruling: M1 fixed in b76482d9cee630ab3ef5d0ff206a2a882ee624d9: document citations use
  `{enabled?: boolean}`, allowing an empty object. Why: pinned
  `BetaCitationsConfigParam` declares the flag optional; the proposed subset follows
  that requirement. Cost: if wrong, an implementation could accept an unsupported
  empty configuration. This is wording only; no runtime behavior changed.
- Ruling: accept exclusion of provider acceptance/execution of synthetic keys at
  e8fdb3a. Why: the authorized investigation is offline; code acceptance and SDK
  shapes do not establish provider execution. Cost: exploitability remains unknown.
- Ruling: accept exclusion of provider support for selected compatibility switches
  at e8fdb3a. Why: the captured requests use synthetic model compatibility settings
  to exercise serializer branches, not live model support. Cost: live compatibility
  remains unverified and cannot be claimed from these captures.
- Ruling: accept exclusion of implemented enforcement and unchanged forwarding at
  e8fdb3a. Why: this task produces evidence and a proposed policy, with production
  code unchanged; autonomy-58799c carries the implementation acceptance obligations.
  Cost: existing validation gaps remain until that work lands.
- Ruling: accept exclusion of full provider semantics, future header semantics,
  prompt-mediated effects, accounting, response completion and namespace proof at
  e8fdb3a. Why: the task bounds nested request policy, and the brief explicitly
  separates these concerns and their existing tasks. Cost: this report establishes
  no assurance about those behaviors.

No minor (deferred) findings remain. The controller also clarified in b76482d that
the capture artifact preserves parsed request bodies, not byte-for-byte bodies.
No production code, approved spec, route schema or provider dependency changed.
