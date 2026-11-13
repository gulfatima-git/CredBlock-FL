# CredBlock-FL Phase 5 final acceptance v2

**Phase 5 data and rolling-graph validation: PASS.** The earlier graph-retention
gate is resolved by the new versioned runtime. This supersedes the conditional
v1 acceptance decision; it does not alter the frozen dataset or old reports.

| Verified scope | Result |
|---|---:|
| Controlled instances, including descriptive references | 513 |
| All-organization replay branches | 2,565 |
| Previously oracle-checked User/time labels | 3,454,398 |
| New graph unit tests | 20/20 |
| Real graph attack branches | 45, across all splits/seeds/organizations |
| Pure-background feature controls | 45 |
| As-of feature/edge/label checks | 315 |
| Real events aged out during checked replay hours | 18,025 |

The accepted API is `src.organization.rolling_graph_v1.OrganizationGraphRuntime`.
It initializes from bounded past observations, expires seven-day events and
structural edges, removes orphan nodes from active tensors, maintains ten-minute
features and supports verified checkpoint restart/resume. Trainer and detector
views read the same persistent state. Evaluator labels/masks are separate from
the observable PyG model packet. Integer counts/edges match the independent SQL
oracle exactly; float32 feature transforms use the documented tolerance.

The graph protocol was fixed at Sorg-family Sorg5/RIP=.50/Raccount=.50 for every
split/seed and all five organizations. It validates the reusable implementation
on 45 real branches and 45 background controls. It is not a claim that graph
features were replayed for all 2,565 branches, and it is not model performance.

Legacy modules remain unchanged for reproducing historical results. The new
files must be installed in the main project to adopt this accepted path; its
future GraphSAGE code must not call the old cumulative graph updater.

The event/label freeze is unchanged. Raccount coverage/intensity, Sorg
composition/volume, repeated-background dependence and three temporal blocks per
split remain documented limitations. Source flags do not certify benignness.
Optional fixed-total sensitivity data is not claimed. External Sheets was not
updated.

**Progress:** all four handover closeout milestones are validated. One-time source
installation remains before using the new API from the main project. Next is
Phase 6 GraphSAGE implementation; no model training, federation, formal privacy,
poisoning robustness or Fabric result is claimed here.
