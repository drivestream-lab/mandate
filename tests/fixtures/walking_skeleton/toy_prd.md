# Toy PRD: a greeting

The toy service greets a caller by name.

## Requirement

The service offers one function that returns "Hello, <name>" for a non-empty name.

## Wave evidence

The wave that builds this is released only with run-signed evidence for exactly the protected
tests named here. The caller workflow, the test set and the test-set digest are fixed by this
document when it is signed, never read from the commit under test.

```wave-evidence
repository: drivestream-lab/mandate-sandbox-svc
caller_workflow: __CALLER_WORKFLOW__
test_set: [tests/unit]
expected_test_set_digest: __TEST_SET_DIGEST__
quarantine: []
plugins: []
```

Run: __RUN__
