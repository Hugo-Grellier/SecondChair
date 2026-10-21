# Editorial evaluation track

Reported only. It never gates v4 and sets no floor (GM decision 24, [#182](https://github.com/Hugo-Grellier/SecondChair/issues/182); design: [editorial-evaluation.md](../../design/editorial-evaluation.md)). Human scores sit beside the deterministic S0-S4 bench ([spec 10](../../spec/10-success-bench.md)), never inside it. No LLM critique is shipped before the first human round (decision 28).

| File | What |
|---|---|
| [rubric.md](rubric.md) | Nine-dimension rubric, evaluator instructions, evaluator sheet, disagreement record |
| [briefs.md](briefs.md) | Five fixed briefs on the public sample campaign |
| [exemplars.md](exemplars.md) | One exemplar per brief; agent-drafted, **to be edited by the GM** |
| [table-log.yaml](table-log.yaml) | Table-use log for one played session |
| `src/secondchair/bench/editorial.py` | Deterministic metrics per prep artifact, the abandoned-prep count, and `blind` (one template, provenance stripped, sealed key in a separate file; same seed gives the same letters) |

Reviewers: the GM plus one outside reader (decision 25). Editing effort is measured by diff size between the agent's draft and the version the GM adopted (decision 27).
