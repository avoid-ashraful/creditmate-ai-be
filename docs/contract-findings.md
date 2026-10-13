# Task 5.4 contract findings

The added contract suite records these existing schema/behavior gaps without changing endpoint behavior:

- Several function-style/APIView operations are present in drf-spectacular output but have no JSON `content` schema or use an unconstrained generic object for successful responses (including account actions, review summary/helpful, alert preferences, and advanced-search operations). Runtime contract assertions cover these payloads; OpenAPI checks verify operation presence and check declared fields whenever the generator supplies properties. The generated schema should add explicit response serializers if consumers need typed payloads.
- The health/readiness probes and public alert unsubscribe route are not included in the generated schema. Their route behavior and response shapes are checked directly by the contract tests; adding schema annotations would make them discoverable to generated-schema consumers.
- `/metrics` is intentionally absent from OpenAPI and returns Prometheus text. The contract test checks its 403 and authorized 200 behavior and content type directly.
