# validation conformance suite

Implementation-agnostic check that any service claiming to satisfy
[`contracts/openapi/validation.v1.yaml`](../../openapi/validation.v1.yaml)
actually does.

The suite uses [Schemathesis](https://schemathesis.readthedocs.io/) to
generate requests from the OpenAPI spec and verify that responses match
what the spec declares.

## Running against the OSS reference impl

```bash
docker compose up -d validation
```

```bash
cd contracts/conformance/validation
uv venv && source .venv/bin/activate
uv pip install -e .
pytest --service-url=http://localhost:8082 --service-token=$NEBULA_VALIDATION_TOKEN
```

## Running against your own implementation

```bash
pytest \
  --service-url=https://validation.your.example \
  --service-token=$YOUR_TOKEN
```

## What this checks

- Every documented status code is reachable with at least one request
  the contract considers valid.
- Response bodies match the schemas declared in the OpenAPI spec.
- Random invalid bodies don't produce undocumented 5xx.

## What this does NOT check

- That `terraform plan` actually produces accurate output for your
  modules.
- Cloud-provider authentication semantics.
- Performance or concurrent-request behavior.
