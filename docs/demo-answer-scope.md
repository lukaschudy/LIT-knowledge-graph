# One demo cluster, broad graph search

The demo answer scope is **GRIN2A/GRIN2B neurodevelopmental disorders**, focused on selected variants with published evidence of reduced NMDA-receptor function. Provisional cases and opposing-function controls remain distinct; the presence of a gene in the graph does not establish cluster membership.

- **Top search:** searches available graph indexes, including entities outside this cluster and outside the current view. The public deployment searches its published HGNC/GRIN snapshot; the local app can also search the larger harvested and resolved indexes. This does not claim that every harvested record is deployed or vector-indexed.
- **Ask Atlas:** retains the fixed demo scope. Searching, selecting another entity, or asking to change clusters cannot broaden its evidence set. Unsupported subjects receive a scope/coverage response, not an unrelated overview. HGNC identifiers for GRIN2A/GRIN2B resolve to their demo identities.
- **Local model:** the default app projects current claims/evidence onto the registered GRIN allowlist and searches the GRIN catalog only. The unrestricted catalog remains available to search. Recommendations from a different research request are not passed to the demo answer prompt. Explicit custom `--bundle` runs remain development workflows.
- **Hosted demo:** source annotation lookup stays limited to the published GRIN bundle. It does not claim to run the local model or search private/full harvested data.

Regression checks cover unrelated variant/asset questions, mixed outside-gene requests, global search followed by a cluster answer, HGNC identity mapping, retained citation scope, catalog cache separation, and finding/selecting an outside entity from the resolved view.
