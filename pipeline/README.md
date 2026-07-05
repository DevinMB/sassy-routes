# pipeline

Offline scoring/ingest pipeline — lands in **Phase 1** (curvature + elevation
precompute, fun-index scoring into CouchDB) and moves onto Kafka in **Phase 3**.

Nothing here runs yet. The scoring weights it will consume live in
[`../scoring.yaml`](../scoring.yaml), version-controlled from day one so model
changes stay reviewable.
