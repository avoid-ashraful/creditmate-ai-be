# 🚨 Incident Response Playbook

This playbook provides structured procedures for diagnosing and resolving incidents in the CreditMate AI backend. All procedures assume on-call support is available.

## Table of Contents

- [Quick Reference](#quick-reference)
- [Severity Levels](#severity-levels)
- [Common Incidents](#common-incidents)
- [Diagnostic Procedures](#diagnostic-procedures)
- [Communication Protocol](#communication-protocol)
- [Prevention & Post-Incident](#prevention--post-incident)

## Quick Reference

### Quick Restart (Most Common Fix)

```bash
# Restart all services
docker-compose -f docker-compose.yml restart

# Or with more control
docker-compose -f docker-compose.yml down
docker-compose -f docker-compose.yml up -d

# Verify services are healthy
curl -I https://api.yourdomain.com/api/v1/banks/
```

### Check System Status

```bash
# All containers running?
docker-compose ps

# All services healthy?
docker-compose logs --tail=20 web

# Database connected?
docker-compose exec web python manage.py dbshell

# Redis available?
docker-compose exec redis redis-cli ping
```

### Find Recent Errors

```bash
# Last 100 log lines
docker-compose logs --tail=100 web

# Errors only
docker-compose logs web | grep ERROR

# Last hour of logs
docker-compose logs --since 1h web
```

## Severity Levels

### P1 - Critical (SEV-1)
**Impact**: Service completely unavailable or data loss occurring
**Response Time**: Immediate (< 5 minutes)
**Examples**:
- API returning 503 for all requests
- Database connections failing
- Data corruption detected

**Action**: Follow [P1 Response](#p1-critical-response)

### P2 - High (SEV-2)
**Impact**: Service degraded, errors for majority of users
**Response Time**: Urgent (< 30 minutes)
**Examples**:
- API response time > 5 seconds
- Error rate > 10% of requests
- Celery tasks backed up in queue

**Action**: Follow [P2 Response](#p2-high-response)

### P3 - Medium (SEV-3)
**Impact**: Service partially degraded, some users affected
**Response Time**: Normal (within business hours)
**Examples**:
- Error rate 1-10% of requests
- Specific endpoints slow
- Rate limiting too restrictive

**Action**: Follow [P3 Response](#p3-medium-response)

### P4 - Low (SEV-4)
**Impact**: Minor issues, no user impact
**Response Time**: Routine (when convenient)
**Examples**:
- Documentation out of date
- Logs verbose/cluttered
- Minor performance optimization opportunity

**Action**: Create ticket for next sprint

## Common Incidents

### Incident: API Returning 503 Service Unavailable

**Severity**: P1 or P2
**Diagnosis**: Service cannot handle requests

#### Step 1: Immediate Diagnosis

```bash
# Are containers running?
docker-compose ps

# Output should show all services with "Up" status
# If not all "Up", container likely crashed

# Check recent error logs
docker-compose logs --tail=50 web | grep -i error

# Is database connected?
docker-compose exec web python manage.py dbshell
# Should connect without timeout

# Is Redis available?
docker-compose exec redis redis-cli ping
# Should respond: PONG
```

#### Step 2: Recovery Options

**Option A: Restart services** (often fixes transient issues)
```bash
docker-compose restart web
docker-compose restart celery
# Wait 30 seconds for services to stabilize
curl -I https://api.yourdomain.com/api/v1/banks/
```

**Option B: Check container logs for persistent errors**
```bash
# Get full error stack trace
docker-compose logs web

# Look for patterns:
# - "Connection refused" → database or Redis down
# - "Memory error" → service out of memory
# - "Timeout" → service taking too long
# - "Import error" → code deployment issue
```

**Option C: If database error**
```bash
# Verify database is running
docker ps | grep postgres

# Connect to database directly
docker-compose exec db psql -U postgres -c "SELECT version();"

# If database crashed, recovery procedure:
# 1. Stop application servers (docker-compose down)
# 2. Check database logs: docker-compose logs db
# 3. Restart database: docker-compose up db
# 4. Wait for recovery: docker-compose exec db pg_isready
# 5. Restart application: docker-compose up -d
```

**Option D: Full rollback if deployment related**
```bash
# See [Rollback Procedures](./DEPLOYMENT_RUNBOOKS.md#rollback-procedures)
# Contact deployment team if needed
```

#### Step 3: Communication

1. Notify stakeholders of incident
2. Provide status updates every 15 minutes
3. Share resolution when service restored

**Example message**:
```
INCIDENT: API Service Degradation
- Start: 14:23 UTC
- Status: Investigating database connection issues
- Impact: All API requests returning 503
- ETA for fix: 14:45 UTC
- Updates: [check status channel for updates]
```

---

### Incident: High Error Rate (>10%)

**Severity**: P2
**Diagnosis**: Application or external service errors

#### Step 1: Identify Error Type

```bash
# Sample recent errors
docker-compose logs --tail=200 web | grep ERROR | head -20

# Count error types
docker-compose logs --tail=500 web | grep -oP 'ERROR: \K[^:]+' | sort | uniq -c

# Filter by error type
docker-compose logs web | grep "timeout\|Connection\|authentication"
```

#### Step 2: Common Error Patterns

**OpenAI API Errors**
```bash
# Check for API key issues
grep "invalid_api_key\|authentication" docker-compose.logs

# Check for rate limit
grep "RateLimitError\|429" docker-compose.logs

# Remedy: Verify API key and account status
docker-compose exec web bash
echo $OPENAI_API_KEY  # Should show valid key
```

**Database Errors**
```bash
# Check for connection pool exhaustion
grep "FATAL.*too many connections" docker-compose.logs

# Remedy: Check active connections
docker-compose exec db psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"
# Should be < max_connections setting
```

**Memory Errors**
```bash
# Check for OOM errors
grep -i "memory\|oom" docker-compose.logs

# Check memory usage
docker stats
# Look for high memory usage by containers
```

**Task Queue Backlog**
```bash
# Check Celery queue size
docker-compose exec redis redis-cli LLEN celery

# If queue is huge (>1000), tasks may be failing
# Check task logs
docker-compose logs celery | grep ERROR

# Remedy: Scale up workers
# docker-compose up -d --scale celery=3
```

#### Step 3: Application Recovery

```bash
# For code errors, restart with fresh process
docker-compose restart web

# For external API errors, check system status
# OpenAI: https://status.openai.com

# For rate limiting, implement exponential backoff
# Code change needed - create hotfix PR

# Wait for error rate to drop
sleep 60
curl -s https://api.yourdomain.com/api/v1/banks/ > /dev/null && echo "OK" || echo "FAILED"
```

---

### Incident: Database Connection Pool Exhausted

**Severity**: P1
**Diagnosis**: "FATAL: too many connections" errors

#### Immediate Action

```bash
# Check current connections
docker-compose exec db psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"

# Check max connections setting
docker-compose exec db psql -U postgres -c "SHOW max_connections;"

# Identify long-running queries
docker-compose exec db psql -U postgres -c "
  SELECT pid, query, query_start, state
  FROM pg_stat_activity
  WHERE state != 'idle'
  ORDER BY query_start;"

# Kill idle connections if needed (carefully!)
docker-compose exec db psql -U postgres -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE state = 'idle'
  AND query_start < now() - interval '5 minutes';"
```

#### Recovery Steps

1. **Increase connection pool** (temporary, requires restart)
   ```bash
   # Edit docker-compose.yml
   # Increase POSTGRES_MAX_CONNECTIONS
   docker-compose down
   docker-compose up -d db
   docker-compose up -d web celery celery-beat
   ```

2. **Reduce application concurrency**
   ```bash
   # Temporarily reduce Gunicorn workers
   docker-compose stop web
   docker-compose exec web gunicorn \
     --workers 2 \
     --threads 1 \
     --bind 0.0.0.0:8000 \
     credit_mate_ai.wsgi:application
   ```

3. **Identify and fix query leaks**
   - Check logs for long-running queries
   - Look for code not closing connections properly
   - Review recent deployments for connection leak

---

### Incident: Celery Tasks Not Running

**Severity**: P2 or P3
**Diagnosis**: Background tasks queue building up

#### Diagnostic Checks

```bash
# Is Celery worker running?
docker-compose ps celery
# Should show "Up"

# Check worker status
docker-compose exec web celery -A credit_mate_ai inspect active
# Should list active workers

# Check task queue
docker-compose exec redis redis-cli LLEN celery
# Should be manageable number (< 1000)

# Check Celery logs for errors
docker-compose logs celery --tail=100
```

#### Recovery Procedures

**Option A: Restart Celery**
```bash
docker-compose restart celery celery-beat
sleep 10
docker-compose exec web celery -A credit_mate_ai inspect active
```

**Option B: Clear stuck tasks**
```bash
# WARNING: This deletes queued tasks
docker-compose exec redis redis-cli DEL celery

# Restart worker
docker-compose restart celery
```

**Option C: Scale up workers for backlog**
```bash
# Temporarily scale to 3 workers
docker-compose up -d --scale celery=3

# Monitor queue depth
watch "docker-compose exec redis redis-cli LLEN celery"

# Scale back down when caught up
docker-compose down
docker-compose up -d
```

---

### Incident: API Response Times Degraded (>2 seconds)

**Severity**: P2
**Diagnosis**: Performance issue or high load

#### Step 1: Check Load

```bash
# CPU usage
docker stats

# Memory usage
free -h

# Disk I/O
iostat -x 1 5

# Database query time
# Enable slow query log if available
docker-compose exec db psql -U postgres -c "SET log_min_duration_statement = 1000;"
```

#### Step 2: Database Query Optimization

```bash
# Check for slow queries
docker-compose logs db | grep "duration:"

# Identify problematic queries
docker-compose exec db psql -U postgres -c "
  SELECT mean_exec_time, query
  FROM pg_stat_statements
  ORDER BY mean_exec_time DESC
  LIMIT 10;"

# Add indexes if needed
docker-compose exec db psql -U postgres -c "
  CREATE INDEX idx_credit_cards_annual_fee
  ON credit_cards_creditcard(annual_fee);"
```

#### Step 3: Application Tuning

```bash
# Increase Gunicorn workers
# Edit docker-compose.yml: increase workers from 4 to 8
docker-compose restart web

# Check if caching is working
docker-compose exec web python manage.py shell
>>> from django.core.cache import cache
>>> cache.set('test', 'value', 60)
>>> cache.get('test')
'value'  # Should return value, not None

# Review API response caching headers
curl -v https://api.yourdomain.com/api/v1/banks/ 2>&1 | grep -i "cache"
```

#### Step 4: Monitor Recovery

```bash
# Track response time over time
for i in {1..10}; do
  time curl -s https://api.yourdomain.com/api/v1/banks/ > /dev/null
  sleep 5
done

# Should show decreasing response times
```

---

## Diagnostic Procedures

### Complete System Health Check

```bash
#!/bin/bash
# Save as health-check.sh

echo "=== Docker Status ==="
docker-compose ps

echo -e "\n=== Recent Errors ==="
docker-compose logs --tail=20 web | grep ERROR || echo "No errors"

echo -e "\n=== Database Connection ==="
docker-compose exec web python manage.py dbshell -c "SELECT 1" && echo "✓ Connected" || echo "✗ Failed"

echo -e "\n=== Redis Status ==="
docker-compose exec redis redis-cli ping || echo "✗ Failed"

echo -e "\n=== Celery Workers ==="
docker-compose exec web celery -A credit_mate_ai inspect active_queues || echo "✗ No workers"

echo -e "\n=== API Response ==="
curl -I https://api.yourdomain.com/api/v1/banks/ 2>/dev/null | head -1

echo -e "\n=== Memory Usage ==="
docker stats --no-stream

echo -e "\n=== Disk Usage ==="
df -h /

echo -e "\n=== Running Processes ==="
ps aux | grep -E "gunicorn|celery|postgres" | grep -v grep
```

### Log Analysis Template

```bash
# Find errors from specific time range
docker-compose logs --since 2024-10-13T14:00:00 --until 2024-10-13T15:00:00 web

# Count errors by type
docker-compose logs web | grep ERROR | grep -oP 'ERROR: \K[^:]+' | sort | uniq -c | sort -rn

# Timeline of events
docker-compose logs web | grep -E "ERROR|WARNING|INFO" | tail -50
```

---

## Communication Protocol

### Incident Declaration

When severity P1 or P2 detected:

```
INCIDENT DECLARED: [INCIDENT_NAME]
- Severity: P1/P2
- Time Declared: [UTC timestamp]
- Affected System: [API/Database/Queue]
- User Impact: [% of users affected]
- On-Call Lead: [Name]
- Status: Investigating
```

### Status Update Template (Every 15 minutes for P1, every 30 for P2)

```
INCIDENT UPDATE: [INCIDENT_NAME]
- Elapsed Time: [time since start]
- Status: [Investigating/Mitigating/Resolved]
- Root Cause: [If known] or [Under investigation]
- Actions Taken: [List of recovery steps]
- ETA for Resolution: [Estimate]
- Next Update: [UTC time]
```

### Resolution Message

```
INCIDENT RESOLVED: [INCIDENT_NAME]
- Resolution Time: [Total duration]
- Root Cause: [Brief explanation]
- Fix Applied: [What was changed]
- Verification: [How we confirmed fix works]
- Follow-up: [Ticket created for permanent fix if needed]
- Post-Mortem: [When will it be reviewed]
```

---

## Prevention & Post-Incident

### Create Post-Incident Ticket

After resolution, create ticket documenting:

```markdown
## Incident: [Name]
**Date**: [Date]
**Duration**: [How long]
**Severity**: P[1-4]

### Root Cause
[What actually failed]

### Immediate Fix
[What we did to recover]

### Permanent Fix
[What code/config change prevents recurrence]

### Changes Made
- [File 1: change description]
- [File 2: change description]

### Testing
- [Test added to prevent regression]

### Monitoring
- [Alert added to detect earlier]
```

### Permanent Prevention Actions

#### Code Changes
```bash
# Create feature branch for fix
git checkout -b fix/incident-name

# Make code changes
# Add tests to prevent regression
# Run full test suite
uv run pytest

# Commit with reference to incident
git commit -m "fix: prevent incident-name scenario

Adds defensive check for connection pool saturation.
See incident ticket for details."

# Push and create PR
git push origin fix/incident-name
```

#### Operational Changes
```bash
# Update monitoring thresholds
# Add alerting for similar conditions
# Update runbooks with lessons learned
# Document in post-mortem
```

### Monitoring Improvements

After every P1/P2 incident:

1. **Add alerting** for early detection
   - Error rate spike detection
   - Response time degradation alert
   - Queue backlog threshold alert
   - Connection pool saturation alert

2. **Add logging** for better diagnostics
   - Log slow queries (>1s)
   - Log external API retries
   - Log connection pool status
   - Log Celery task failures

3. **Add testing** for regression prevention
   - Test for the failure scenario
   - Test recovery procedure
   - Add load test if load-related

---

## Emergency Contacts

**⚠️ Note**: The following placeholders require actual contact information setup by operations team.

| Role | Primary | Secondary | Escalation |
|------|---------|-----------|-----------|
| On-Call Engineer | [Contact A] | [Contact B] | [Manager] |
| Database Admin | [Contact A] | [Contact B] | [CTO] |
| DevOps Lead | [Contact A] | [Contact B] | [VP Eng] |
| Incident Commander | [Contact A] | [Contact B] | [VP Eng] |

**Setup required by Operations**: Create actual contact list and link here.

---

## Incident Statistics (Template)

Use for post-mortem analysis:

```
Period: [Month/Quarter]

Incident Summary:
- Total Incidents: [N]
- P1 Incidents: [N] (avg duration: [time])
- P2 Incidents: [N] (avg duration: [time])
- P3+ Incidents: [N]

Top Causes:
1. [Cause] - [N] incidents
2. [Cause] - [N] incidents
3. [Cause] - [N] incidents

Trends:
- [Observation]
- [Observation]

Improvements:
- [Action taken]
- [Action taken]
```

---

**Questions?** See [LOCAL_DEVELOPMENT.md](./LOCAL_DEVELOPMENT.md) for setup help or [DEPLOYMENT_RUNBOOKS.md](./DEPLOYMENT_RUNBOOKS.md) for deployment procedures.
