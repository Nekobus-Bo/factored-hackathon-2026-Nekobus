# data/raw

Immutable copy of what was delivered, untransformed.

**The dataset provided by the organization is not versioned in this repository.**
It is the organization's material and redistributing it is not ours to decide.

To add the delivered dataset, copy it to `data/raw/factored/` and run
`make ingest SOURCE=factored && make seed`. Without it, the system uses the
bundled synthetic sample, which is enough for the demo and for replay mode.
The synthetic demo identities are always loaded, and loaded first
(docs/adr/0011-hybrid-seed-dataset-ingest.md).
