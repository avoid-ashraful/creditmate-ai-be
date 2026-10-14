# Incident response and on-call

## Severity and escalation

Use the organization's incident commander/on-call process if configured; the repository does not define a staffed rotation. Prometheus Alertmanager template routes `critical` to PagerDuty and `warning` to Slack, but delivery requires real integrations and an active rotation.

- **SEV1 / critical:** broad outage, data loss/corruption, active security incident, or critical user flow unavailable. Page immediately; incident commander coordinates response and stakeholder updates.
- **SEV2 / high:** substantial degradation, repeated failures, or a major subsystem unavailable with workaround. Engage on-call promptly and update stakeholders regularly.
- **SEV3 / moderate:** limited impact or non-urgent degradation with workaround. Create/assign an issue and monitor.
- **SEV4 / low:** minor defect, question, or isolated data-quality issue. Track in normal work.

These severity labels are an operational guide, not configured alert severities. Alert rules use `critical` and `warning` labels.

## First 15 minutes

1. Acknowledge the page; note start time, affected service/environment, alert name, and reporter. Open the incident channel/bridge and name an incident lead for SEV1/2.
2. Assess user impact and scope. Check `/api/healthz/` (process liveness), `/api/readyz/` (dependency readiness), and `/metrics` from an authorized network/token context. Do not publish metrics output containing sensitive labels externally.
3. Inspect Prometheus/Grafana request rate, 5xx ratio, p99 latency, pod restarts/replicas, CPU/memory/disk, and dependency health. Check logs around the first failure and recent deploy/migration/config changes.
4. Stabilize safely: stop/rollback a harmful rollout, scale only within resource limits, or disable a failing optional integration using the approved change path. Avoid destructive data actions and unreviewed database rollback.
5. Communicate current impact, mitigation, owner, and next update time. Preserve timestamps, dashboard links, logs, and commands for the timeline.

## Dashboards and alerts

Check the Prometheus/Grafana overview and data-quality dashboards in the DevOps repository `monitoring/grafana/dashboards/`. Confirm scraper targets and alert routing. The backend registers `/api/healthz/`, `/api/readyz/`, and `/metrics` in `credit_mate_ai/urls.py`; metrics access requires `METRICS_TOKEN` or `METRICS_ALLOWED_IPS` configuration.

Prometheus rule names in parent `monitoring/prometheus/rules/` include `CreditmateHighErrorRate`, `CreditmateEndpointErrorRateHigh`, `CreditmateHighLatencyP99`, `CreditmateEndpointLatencyP99High`, `CreditmateTargetDown`, `CreditmateNodeDiskUsageHigh`, `CreditmateNodeDiskUsageCritical`, `CreditmateNodeCPUUtilizationHigh`, `CreditmateNodeCPUSaturated`, `CreditmateNodeMemoryPressure`, `CreditmatePodCrashLooping`, `CreditmateDeploymentReplicasUnavailable`, `CreditmateHPAAtMaxReplicas`, `CreditmateRedisDown`, `CreditmatePostgresDown`, `CreditmateElasticsearchRed`, `CreditmateDataQualityLowConfidence`, `CreditmateDataQualityLowSuccessRate`, `CreditmateBankDataQualityLowConfidence`, and `CreditmateBankDataQualityLowSuccessRate`. Consult live rule files before response; names/thresholds may change.

## Communications template

```text
Incident: [short name] | Severity: [SEV1-4] | Status: [investigating/mitigating/monitoring/resolved]
Started: [UTC time] | Affected: [service, environment, user impact]
What we know: [verified facts]
Mitigation: [action and outcome]
Owner: [incident lead] | Next update: [UTC time]
```

Use the approved incident channel and customer/status-page process. Do not include credentials, personal data, or speculative root causes. During active SEV1/2, update at the interval agreed by the incident lead (typically every 15–30 minutes) and at material changes.

## On-call basics

- Keep access to alerting, dashboards, deployment tooling, and secret-management channels current; use least privilege and MFA.
- Acknowledge promptly, assess impact before changing state, and hand off with current symptoms, actions, owners, and next check.
- Use runbook links from alert annotations and preserve an incident timeline. Do not paste secret values into chat or shell history.
- If an alert is noisy or a runbook is wrong, resolve the incident first and file a follow-up; never silently disable alerting.
- The repository does not prove PagerDuty/Slack endpoints or an on-call rotation are provisioned; verify them with operations.

## Database backup and restore

Backups must be managed by the platform/database owner. Prefer provider snapshots and point-in-time recovery where available. If using logical dumps, use `pg_dump -Fc` with an appropriately privileged account, encrypt at rest and in transit, store off-host with restricted access, and verify completion/retention. A backup is not proven until restored and checked in an isolated environment.

Example logical backup (run only with approved credentials and a protected destination):

```bash
pg_dump --format=custom --no-owner --file=/secure/backup/creditmate-YYYYMMDD-HHMM.dump "$DATABASE_URL"
```

Restore to a new isolated database first, inspect schema/data, then plan cutover with the incident lead. Example:

```bash
createdb creditmate_restore_check
pg_restore --no-owner --dbname=creditmate_restore_check /secure/backup/creditmate-YYYYMMDD-HHMM.dump
```

The Compose staging PostgreSQL volume is persistent but is not a backup. Never run `docker compose down -v` as a recovery step. Record restore point and expected data-loss window; production restore/cutover must follow the provider-specific procedure and approval chain.
