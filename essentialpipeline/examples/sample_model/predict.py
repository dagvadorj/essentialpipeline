"""
Sample EssentialPipeline model bundle: a tiny linear model.

Contract every bundle follows: read /io/input.json, write /io/output.json.
This one expects {"features": [x1, x2, ...]} and returns
{"prediction": <weighted sum + bias>}, using the weights in model.json
that ship inside the bundle.

Uses only the standard library - model execution runs with no network
access, so a bundle can't install anything at run time.
"""

import json
import os

with open(os.path.join(os.path.dirname(__file__), 'model.json')) as f:
    model = json.load(f)

with open('/io/input.json') as f:
    payload = json.load(f)

features = payload['features']
if len(features) != len(model['weights']):
    raise SystemExit(f"expected {len(model['weights'])} features, got {len(features)}")

prediction = sum(w * x for w, x in zip(model['weights'], features)) + model['bias']

with open('/io/output.json', 'w') as f:
    json.dump({'prediction': round(prediction, 6)}, f)

print(f"predicted {prediction:.6f}")
