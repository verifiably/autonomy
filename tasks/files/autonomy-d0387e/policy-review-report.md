What this change does: autonomy-d0387e records the current validator gaps, verifies relevant shapes against pinned SDK declarations, and recommends a finite policy for autonomy-58799c to scope. **Ready to merge as bounded research**, with one nonblocking Minor clarification. This review approves neither a contract amendment nor an implementation.

Reviewed repository `.worktrees/egress-policy`, base `2742a6f`, frozen head `e8fdb3aa4e4435a91f869ff280af02168707b01b`. Reviewer identity: **codex/gpt-6-astra**, freshly verified with the requested command, exit 0.

**Critical: none. Important: none. Minor: one.**

1. **Document citations’ optional flag is presented as required.**  
   Reference: `.worktrees/egress-policy/docs/notes/2026-10-18-egress-proof-gaps-brief.md:254`.

   The recommendation says citations accept only `{enabled: boolean}`, while pinned `BetaCitationsConfigParam` declares `enabled?: boolean` at `messages.d.ts:1297`. The surrounding policy says SDK required fields and nullability govern the supported shapes. Consequently, an implementer could reject a document’s `citations: {}` while believing that refusal follows the pinned declaration.

   Change this to `{enabled?: boolean}`, or explicitly record requiring the flag as intentional narrowing. If left unchanged, this creates a small compatibility ambiguity for implementation; it does not leave an unchecked control position.

The substantive conclusions are supported:

- The current validator and route parser match the characterization: message keys, extra block keys and nested configuration remain unchecked; inline `tool_addition` is already excluded from the supported block vocabulary.
- The recommendation closes the declared control-object boundaries through finite keys, discriminants, primitive checks and recursive content validation. It also closes operator configuration’s escape hatch by rejecting fields and tool types without defined shapes.
- Refusing fallback configuration is justified by both the server-selected `"default"` variant and per-attempt overrides. Checking only fallback model names would not establish equivalent closure.
- Client `input_schema` and `tool_use.input` remain explicitly opaque. The research does not mistake model-, source- or tool-looking keys inside those regions for provider controls.
- Decision 13’s broader operator permissions remain visible as intended capability. The brief correctly identifies their proposed removal as requiring reviewed amendment, rather than claiming the current contract already requires this subset.
- The acceptance matrix clearly separates current verdicts from proposed outcomes and names the additional implementation checks. Passing characterization cases are not presented as evidence of a fix.

Evidence review covered the full branch diff, task and attachments, validator and route parser, relevant existing tests, README, decision 13, pinned declarations, and pi serializer. All **five source hashes matched**, including SDK **0.129.0** and pi-ai **1.1.0**. The named validator, route, README and design inputs are unchanged between `7097495` and the reviewed head.

I inspected the recorded **67-case passing output** and its assertions. The **791-test baseline and fast results** remain controller/task-reported evidence; I did not rerun tests or regenerate captures under this read-only assignment.

Behaviors declined to judge:

- **Provider acceptance or execution of synthetic keys:** offline declarations and local validation cannot establish this; no live API was used.
- **Provider support for selected compatibility switches:** serializer output proves the emitted shape, not model support.
- **Implemented enforcement or unchanged forwarded bytes:** production code is unchanged; those remain acceptance obligations for autonomy-58799c.
- **Full provider semantic validity, future header semantics, prompt-mediated effects, accounting, response completion and namespace proof:** outside this bounded research assignment and explicitly separated in the brief.

**Verdict: Ship the research result.** The controller should record the Minor disposition and wake autonomy-58799c before merge as the task requires.

No files, task notes or branches were changed; nothing was pushed. No processes remain running from this review. The branch remains unmerged in `.worktrees/egress-policy`; integration belongs to the controller after its closeout steps.
