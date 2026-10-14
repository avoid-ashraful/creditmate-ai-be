# API smoke findings

The end-to-end smoke run completed with all 11 grouped checks passing against a freshly migrated PostgreSQL database seeded with 3 banks and 12 cards. No backend behavior required a code change.

The run exercises alert unsubscribe through authenticated `DELETE /api/v1/alerts/subscriptions/{id}/`. The public signed-token unsubscribe route is intended for links in alert emails; the subscription API response does not expose that token, so the HTTP smoke cannot obtain a public token without reading email or database state.

The schema endpoint returned HTTP 200. drf-spectacular emitted existing warnings about APIView serializer inference and operation ID collisions while generating the schema; these did not fail the endpoint or smoke check.
