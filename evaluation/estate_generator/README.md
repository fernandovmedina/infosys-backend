# Private estate-generator evaluation boundary

This directory is reserved for evaluator-only material: scenario attribution,
causal event provenance, held-out seed manifests, and expected findings.

It is deliberately outside `app/`. The deployed investigator must not import,
read, or receive this material. A future evaluation harness may use it to score
public estates, but the public generator package must not depend on it.

Generated private sidecars belong under `generated/` and are ignored by Git;
this document is the only versioned artifact in this boundary until evaluation
logic is implemented.
