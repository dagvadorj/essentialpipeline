# Sample Model

A minimal model bundle for EssentialPipeline - upload it as a version of a
model, then run it with `{"features": [1, 2, 3]}` (expected output:
`{"prediction": 4.75}`, since 0.5*1 - 1.25*2 + 2.0*3 + 0.75 = 4.75).

## The bundle contract

- A zip with `predict.py` at its root.
- `predict.py` reads `/io/input.json` and writes `/io/output.json`.
- It runs inside a container with **no network access** and the bundle
  mounted **read-only**, so it must be self-contained (standard library only,
  or vendor whatever it needs into the zip).
