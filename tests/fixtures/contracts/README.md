# Checkpoint schema contracts

`model-schema-hashes.json` was captured from the working tree immediately before
the named-value refactor on 2026-11-07, with the locked Pydantic 2.14.2.
It contains no source materials or model output.

Each digest is SHA-256 of `json.dumps(Model.model_json_schema(), sort_keys=True)`
encoded as UTF-8, matching the schema serialization used in checkpoint identity.
Ordering inside enum arrays, titles, defaults and `$defs` are significant.

These expectations deliberately do not derive from the new enums or aliases.
A schema change needs an explicit compatibility decision; do not regenerate the
file merely to make a refactor pass. New models can be added when their persisted
checkpoint contract needs this protection; the test does not fix a model count.
