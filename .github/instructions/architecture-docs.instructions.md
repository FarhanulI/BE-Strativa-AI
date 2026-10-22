---
description: "Use when editing product architecture, module maps, module specifications, phase plans, or domain-boundary documentation. Keep the docs aligned with the canonical architecture and modular-monolith contracts."
applyTo: "docs/**/*.md"
---

# Architecture Documentation Guidelines

- Treat `product-architecture.md` as canonical. Update `modules.md` and module specs to reflect it; do not make a conflicting design decision implicitly. If the architecture itself needs to change, state the decision and update the source of truth deliberately.
- Keep the module map's phase order coherent with dependencies. Distinguish a module's contract/design from the phase when its full integration becomes possible.
- Every module specification must cite the architecture sections it implements and cover: purpose, owned entities, schema/indexes, public interface, OpenAPI endpoints, events in/out, jobs, AI tasks, UI slice, authorization, invariants, acceptance criteria, and non-goals.
- Make ownership explicit. State which module owns each entity/table and require cross-module communication through public service interfaces or domain events; never document cross-module table access or internal imports as integration patterns.
- Preserve the canonical content flow: raw intelligence events -> signal synthesis -> strategic signals -> opportunities -> briefs -> channel execution -> creation -> publishing -> measurement -> learning. Trends are inputs, not direct content-generation triggers.
- Document tenant scope and authorization explicitly. Workspace resources require membership checks; global, workspace, and profile knowledge must retain explicit scope and retrieval boundaries.
- Keep human edits/version history, downstream invalidation, content lineage, and the distinction between human preference and audience performance visible wherever the relevant workflows are specified.
- Prefer concise links to canonical sections over copying large passages. Use consistent names for modules, entities, events, states, and AI tasks; mark unresolved choices as open decisions rather than presenting assumptions as settled facts.
- Include acceptance criteria that can be verified through tests or a demonstrated workflow, not vague outcomes.
