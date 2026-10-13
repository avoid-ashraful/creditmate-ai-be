# Backend deployment runbook

## Deployment artifacts and status

Infrastructure is maintained in the parent worktree `/home/ubuntu/credit-workers/task-8.2-devops`, not this backend checkout. Its `k8s/base/` and `k8s/overlays/{staging,production}/` are Kustomize resources for frontend, backend, Celery worker/Beat, services, ingress, HPA, PDB, config, and External Secrets. `k8s/README.md` lists prerequisites and placeholders. The staging overlay names `creditmate-staging` and `staging.creditmate.ai`; production names `creditmate-prod` and `creditmate.ai`. The manifests assume external PostgreSQL, Redis, and Elasticsearch. They do not run migrations. `docker-compose.staging.yml` is a single-host stack with Postgres 16, Redis 7, Elasticsearch 8.11, Gunicorn backend, Celery worker/Beat, and frontend. Only frontend/backend ports bind to loopback; put a TLS proxy in front. Compose secrets belong in ignored `.env.staging`.

These manifests describe intended infrastructure; their presence does not establish that an environment is deployed or reachable. `docs/PROJECT_STATUS.md` records remote staging and automation as unverified. Confirm image tags, secret store, cluster prerequisites, database targets, and change window with the environment owner before acting.

## Release sequence (Kubernetes)

1. Review the code change, tests, migration plan, and rollback compatibility. Build/publish immutable backend image tag (normally commit SHA) through the authorized release process.
2. Review/render the intended overlay from the DevOps checkout: `kubectl kustomize k8s/overlays/staging`. Check for any `REPLACE_ME` values; the DevOps README specifies a grep check. Confirm secrets resolve and every dependency points to that environment.
3. Take/verify a database backup. Apply the overlay using the team's approved deployment process (`kubectl apply -k k8s/overlays/staging` only after cluster/context confirmation). No automated CI deployment is assumed by this runbook.
4. Run migrations once as a controlled one-off job using the new image and environment configuration, before new code requires the schema. Record output and migration state. Do not run `migrate` independently in each replica.
5. Roll out backend and worker images, then frontend if applicable. Keep Celery Beat to one instance. Watch rollout and logs.
6. Verify `/api/healthz/`, `/api/readyz/`, API smoke paths, `/metrics` access from the authorized scraper, worker queue progress, and search status. Verify expected alerts are clear.

Commands below are examples and must be run from the DevOps checkout with a verified context/namespace:

```bash
kubectl config current-context
kubectl kustomize k8s/overlays/staging
kubectl -n creditmate-staging get deploy,pods,svc
kubectl -n creditmate-staging rollout status deployment/creditmate-backend
```

## Compose staging

From the DevOps checkout, follow the Compose file header: copy `.env.staging.example` to ignored `.env.staging`, supply all `REPLACE_ME` values and image references, inspect with `docker compose --env-file .env.staging -f docker-compose.staging.yml config -q`, then deploy via the environment owner's approved procedure. Do not expose database, Redis, or Elasticsearch ports publicly. Compose keeps state in named volumes; do not use `down -v` during routine deployment.

## Database migration and backup

Before schema changes, verify a recent, restorable PostgreSQL backup and sufficient disk space. Use the platform's managed backup/PITR mechanism where configured; otherwise take a consistent `pg_dump -Fc` and store it encrypted outside the host with restricted access. Capture database name, timestamp, image tag, and migration state. Test restores into an isolated database periodically. See [backup/restore](INCIDENT_RESPONSE.md#database-backup-and-restore).

Prefer expand-and-contract migrations compatible with the old and new application versions. Run migrations once, capture logs, and inspect `showmigrations`. Do not reverse a migration blindly after writes; assess data loss and forward-fix where safer.

## Rollback

1. Declare the incident and pause further releases/migrations. Save logs, alert details, image tags, and current migration state.
2. Roll the application deployments back to the last known good immutable image (`kubectl rollout undo deployment/creditmate-backend -n <namespace>`), and similarly worker/frontend if affected. For Compose, restore the previous image references in `.env.staging` and redeploy through the owner process.
3. Verify health/readiness, error rates, worker processing, and user-facing behavior.
4. If the release included a migration, determine compatibility first. Prefer rolling code forward/back while retaining additive schema. Restore a database backup only with incident lead approval and a documented data-loss window; restore to an isolated target first if possible. Coordinate API, workers, and Beat versions so old code does not consume incompatible jobs.
5. Record timeline, impact, recovery evidence, and follow-up actions.

## Post-deploy checklist

- [ ] Correct namespace/host and immutable image tag confirmed.
- [ ] Migration status recorded and no pending expected migration.
- [ ] Health and readiness succeed; `/metrics` is reachable only by authorized monitoring.
- [ ] API error/latency and infrastructure dashboards are normal.
- [ ] Celery worker active, queue draining, and only one Beat scheduler active.
- [ ] Elasticsearch healthy and indexing behavior verified when search is enabled.
- [ ] Release notes and incident/on-call handoff updated.
