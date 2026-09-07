---
id: autonomy-82f2dc
title: Create the public verifiably/autonomy repo and push
status: todo
priority: 2
size: s
created: 2026-09-07T12:08:25Z
updated: 2026-09-07T12:08:25Z
depends: []
tags: [hygiene]
---

The autonomy checkout has commits but no git remote at all, and no verifiably/autonomy repository exists. It is the top layer of the five-layer stack (atoms, nodes, beliefs, science, autonomy) and the only one with nowhere to push.

Create it public under the verifiably org, matching beliefs and nodes, and push main. Public also means GitHub Actions on standard runners is free here (see the CI decision in beliefs AGENTS.md).

Same precondition as making any repo public: audit the whole history for secrets, credentials and home-directory paths before the first push, since the initial push publishes every commit at once.
