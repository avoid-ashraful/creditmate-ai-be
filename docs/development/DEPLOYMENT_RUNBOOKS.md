# 📋 Deployment Runbooks

This guide provides safe, step-by-step procedures for deploying CreditMate AI backend to production and staging environments. All procedures assume a pre-configured deployment infrastructure.

## Table of Contents

- [Pre-Deployment Checklist](#pre-deployment-checklist)
- [Production Deployment](#production-deployment)
- [Staging Deployment](#staging-deployment)
- [Database Migrations](#database-migrations)
- [Rollback Procedures](#rollback-procedures)
- [Post-Deployment Verification](#post-deployment-verification)
- [Infrastructure Prerequisites](#infrastructure-prerequisites)

## Pre-Deployment Checklist

**⚠️ IMPORTANT**: All items below are **external prerequisites** that MUST be confirmed by your operations team BEFORE executing deployment procedures. This runbook is a **template**; you must verify all infrastructure details against your actual deployment environment.

### Prerequisites (Operations Team) — VERIFY ALL BEFORE STARTING

**Database Configuration:**
- [ ] **CONFIRM** actual PostgreSQL version in use (compose files use **PostgreSQL 15**; adjust if your infrastructure differs)
- [ ] **CONFIRM** database is provisioned with backup configured
- [ ] **CONFIRM** SSL enabled for production connections

**Message Queue & Cache:**
- [ ] **CONFIRM** Redis version in use (compose files use **Redis 7-alpine**)
- [ ] **CONFIRM** Redis cluster/replication configured if needed

**External Services:**
- [ ] **CONFIRM** API keys (OpenAI, Gemini, etc.) provisioned and tested
- [ ] **CONFIRM** Credentials NOT stored in source code

**Infrastructure & Networking:**
- [ ] **CONFIRM** Staging/production infrastructure deployed and accessible
- [ ] **CONFIRM** Correct deployment branch (NOT assumed to be `master`)
- [ ] **CONFIRM** Environment variables configured in your deployment system
- [ ] **CONFIRM** SSL certificates installed and valid (production only)
- [ ] **CONFIRM** Load balancer configured (if applicable)
- [ ] **CONFIRM** Log aggregation configured (if applicable)
- [ ] **CONFIRM** Monitoring/alerting configured (if applicable)
- [ ] **CONFIRM** Docker registry configured (if using Docker)

**Deployment Automation (If Applicable):**
- [ ] **⚠️ CI/CD Status**: GitHub Actions are configured for testing. Remote CI/deployment automation is **PENDING** and must be explicitly set up by your team.
- [ ] **CONFIRM** Actual CI/CD trigger branch (do not assume `master`)
- [ ] **CONFIRM** CI/CD deployment procedure documented separately

### Code Review & Testing (Development Team)
- [ ] Code changes reviewed and merged to **[YOUR_DEPLOYMENT_BRANCH]** (typically `master` or `main`)
- [ ] All tests passing locally (`uv run pytest`)
- [ ] Code quality checks passing (`black`, `flake8`, `isort`)
- [ ] Database migrations created and tested locally
- [ ] No uncommitted changes in working directory
- [ ] Latest changes pulled from **[YOUR_REMOTE_NAME]** (typically `origin`)

### Deployment Configuration (Operations Team)
- [ ] `.env` file configured for deployment environment
- [ ] OPENAI_API_KEY set and validated
- [ ] Database URL pointing to correct database
- [ ] CELERY_BROKER_URL pointing to Redis
- [ ] CORS_ALLOWED_ORIGINS configured for frontend domains
- [ ] SECRET_KEY set to secure value (production only)
- [ ] DEBUG=False in production
- [ ] ENVIRONMENT=production in production

## Production Deployment

### Step 1: Pre-Deployment Verification

**BEFORE RUNNING**: Confirm your actual deployment branch name with your operations team.

```bash
# Verify you're on the correct branch
git branch
# Output should show: * [YOUR_DEPLOYMENT_BRANCH]
# Example: * master (if that is your deployment branch)
# Replace [YOUR_DEPLOYMENT_BRANCH] with your actual branch name

# Verify latest commits
git log --oneline -5

# Check for uncommitted changes
git status
# Output should show: On branch [YOUR_DEPLOYMENT_BRANCH], nothing to commit

# Verify tests pass
uv run pytest
# All tests should pass

# Verify code quality
uv run black . --check && uv run isort . --check && uv run flake8
# No formatting issues should be reported
```

### Step 2: Database Backup (Operations Responsibility)

```bash
# This step is performed by operations team
# Creates backup of production database before deployment
# Contact: [Operations Team - see INCIDENT_RESPONSE.md]

# Verify backup exists and is recent
# Database: pg_dump should complete successfully
# Retention: Keep 7 daily backups + 4 weekly backups
```

### Step 3: Build Application Image

**Option A: CI/CD Pipeline (If Configured)**
```bash
# ⚠️ DEPLOYMENT AUTOMATION STATUS
# GitHub Actions are set up for testing. Remote CI/CD deployment automation
# must be explicitly verified and configured by your operations team.
#
# Ask your ops team:
# 1. Is deployment automation configured? (currently PENDING)
# 2. What branch does CI/CD watch? (do not assume "master")
# 3. What registry/deployment system is used?
# 4. What manual steps remain after CI/CD triggers?
#
# If CI/CD exists, typical flow:
# 1. Code pushed to [YOUR_DEPLOYMENT_BRANCH]
# 2. CI pipeline runs tests and code quality checks
# 3. Docker image built from Dockerfile (if automated)
# 4. Image tagged with git commit SHA
# 5. Image pushed to registry (if automated)
#
# Verify with your ops team before proceeding
```

**Option B: Manual Build**
```bash
# Build Docker image locally or on deployment server
docker build -t creditmate-ai-be:latest .
```

**Option C: Direct Deployment (Without Docker)**
```bash
# On deployment server
cd /app/creditmate-ai-be

# BEFORE: Verify branch with ops team
git pull [YOUR_REMOTE] [YOUR_DEPLOYMENT_BRANCH]
# Example: git pull origin master (replace with your actual branch)

uv sync --frozen  # Install locked dependencies
```

### Step 4: Review Database Migrations

```bash
# Show what migrations will be applied
uv run python manage.py migrate --plan

# Expected output:
#   Planned operations:
#   banks.0002_add_validation
#   credit_cards.0001_initial
# 
# Verify no unexpected migrations

# Check migration status
uv run python manage.py migrate --list
# Shows all migrations and their applied status
```

### Step 5: Apply Database Migrations

**⚠️ PRODUCTION DATABASE OPERATIONS - Requires careful coordination**

```bash
# Step 5a: Create migration backup (Operations responsibility)
# Database backup MUST be created BEFORE applying migrations
# Retention: Keep until rollback window expires (24 hours minimum)

# Step 5b: Apply migrations in maintenance window
# **Coordinate with infrastructure team for timing**
# Maintenance window timing is UNVERIFIED and must be set up by operations team
# Suggested approach: Pick low-traffic time or use zero-downtime migration strategies
# See "Zero-Downtime Migrations" section in this runbook

# Apply migrations (from project root or container)
uv run python manage.py migrate

# Verify all migrations applied
uv run python manage.py migrate --check
# Expected output: System check identified no issues (0 silenced).
```

### Step 6: Collect Static Files

```bash
# Collect static files for web server
uv run python manage.py collectstatic --noinput

# Verify files collected
ls -la staticfiles/
# Should contain CSS, JS, fonts, etc.
```

### Step 7: Deploy Application

**Docker-based deployment** (most common):
```bash
# Stop running containers
docker-compose -f docker-compose.yml down

# Pull latest images (if using registry)
docker-compose -f docker-compose.yml pull

# Start services with new image
docker-compose -f docker-compose.yml up -d

# Verify services started
docker-compose -f docker-compose.yml ps
# All services should show "Up"
```

**Direct deployment** (on-premises):
```bash
# Restart application server
sudo systemctl stop creditmate-api
sudo systemctl start creditmate-api

# Restart Celery worker
sudo systemctl stop creditmate-celery
sudo systemctl start creditmate-celery

# Restart Celery Beat
sudo systemctl stop creditmate-beat
sudo systemctl start creditmate-beat

# Verify services running
sudo systemctl status creditmate-*
```

### Step 8: Verify Deployment

```bash
# Check API is responding
curl -I https://api.yourdomain.com/api/v1/banks/
# Expected: HTTP 200

# Check admin interface
curl -I https://api.yourdomain.com/admin/
# Expected: HTTP 301 (redirect) or HTTP 200

# Verify database connected
uv run python manage.py dbshell
# Should connect without errors

# Check Celery workers active
uv run celery -A credit_mate_ai inspect active
# Should list active worker processes
```

**See [Post-Deployment Verification](#post-deployment-verification) for comprehensive checks.**

### Step 9: Monitor for Errors

```bash
# Watch logs in real-time
docker-compose -f docker-compose.yml logs -f web

# Or with systemd
journalctl -u creditmate-api -f

# Check for error spikes
# - Monitor error rate in logging system
# - Check Sentry dashboard if configured
# - Verify API response times normal
```

## Staging Deployment

Staging deployments are lower-risk and can be performed without maintenance windows.

**BEFORE STARTING**: Confirm your staging branch and remote with your ops team.

### Quick Staging Deploy

```bash
# Verify tests and code quality
uv run pytest && uv run black . --check && uv run flake8

# Pull latest code from [YOUR_REMOTE] [YOUR_STAGING_BRANCH]
# Example: git pull origin staging (or your actual branch)
git pull [YOUR_REMOTE] [YOUR_STAGING_BRANCH]

# Update dependencies
uv sync --frozen

# Apply migrations
uv run python manage.py migrate

# Collect static files
uv run python manage.py collectstatic --noinput

# Restart services (Docker)
# Verify your actual docker-compose filename below
docker-compose -f docker-compose.yml down
docker-compose -f docker-compose.yml up -d

# Verify deployment
# Replace with your actual staging domain
curl -I https://staging-api.yourdomain.com/api/v1/banks/
```

## Database Migrations

### Safe Migration Procedures

#### Before Deployment

```bash
# Test migrations locally
uv run python manage.py migrate

# Show plan
uv run python manage.py migrate --plan

# Verify no model conflicts
uv run python manage.py check

# Dry-run migrations (if database supports it)
uv run python manage.py migrate --fake --dry-run
```

#### Zero-Downtime Migrations

For changes to production database:

```bash
# Strategy 1: Add non-blocking columns first
# - Create new column with NULL default
# - Deploy code that reads both old and new columns
# - In second deployment, migrate data and switch reads
# - Remove old column in third deployment

# Strategy 2: Expand then contract
# 1. Expand phase: Add new schema elements, keep old
# 2. Dual-write phase: Application writes to both old and new
# 3. Backfill phase: Copy data from old to new
# 4. Dual-read phase: Application reads from new, write to both
# 5. Cleanup phase: Remove old schema elements
```

#### Rollback Migrations

**⚠️ Only perform rollback if data loss is acceptable**

```bash
# Show migration plan
uv run python manage.py migrate --plan

# Rollback to specific migration
uv run python manage.py migrate banks 0001_initial

# Verify rollback
uv run python manage.py migrate --check
```

### Custom Migration Best Practices

```python
# Bad - Contains business logic that can fail
def migrate_data(apps, schema_editor):
    CreditCard = apps.get_model('credit_cards', 'CreditCard')
    for card in CreditCard.objects.all():
        card.annual_fee = complex_calculation(card)  # Don't do this
        card.save()

# Good - Atomic, with proper error handling
def migrate_data(apps, schema_editor):
    # Use raw SQL for bulk operations
    schema_editor.execute("""
        UPDATE credit_cards_creditcard
        SET annual_fee = CASE 
            WHEN has_premium THEN 99
            ELSE 0
        END
    """)
```

## Rollback Procedures

### Immediate Rollback (Critical Issues)

If deployment causes critical issues:

```bash
# Rollback to previous Docker image
docker-compose -f docker-compose.yml down
export PREVIOUS_IMAGE_TAG="v1.2.0"  # Set to previous working version
docker image pull registry.yourdomain.com/creditmate-ai-be:${PREVIOUS_IMAGE_TAG}
sed -i "s/image:.*/image: registry.yourdomain.com\/creditmate-ai-be:${PREVIOUS_IMAGE_TAG}/" docker-compose.yml
docker-compose -f docker-compose.yml up -d

# Verify rollback
curl -I https://api.yourdomain.com/api/v1/banks/
```

### Code Rollback

```bash
# Revert to previous commit
git checkout HEAD~1  # Or specific commit SHA

# Redeploy with reverted code
# Replace [YOUR_REMOTE] and [YOUR_DEPLOYMENT_BRANCH] with your actual values
git pull [YOUR_REMOTE] [YOUR_DEPLOYMENT_BRANCH]
# Example: git pull origin master

uv sync --frozen
uv run python manage.py migrate  # Re-apply migrations if needed
# ... redeploy via Step 7 above
```

### Database Rollback (Operations Responsibility)

```bash
# Restore from backup
# (Performed by operations team with database expertise)
# Contact: [Operations Team]
# 
# Procedure:
# 1. Stop application servers
# 2. Restore database from backup
# 3. Verify data integrity
# 4. Restart application servers
# 5. Verify application functionality
```

## Post-Deployment Verification

### Health Checks

```bash
# API Endpoint Health
curl -v https://api.yourdomain.com/api/v1/banks/
# Expected: HTTP 200, valid JSON response

# Admin Interface
curl -I https://api.yourdomain.com/admin/
# Expected: HTTP 200 or HTTP 301 redirect

# Database Connection
uv run python manage.py dbshell
# Should connect successfully
```

### Functional Testing

```bash
# List banks
curl https://api.yourdomain.com/api/v1/banks/ | jq .

# List credit cards
curl https://api.yourdomain.com/api/v1/credit-cards/ | jq .

# Search functionality
curl 'https://api.yourdomain.com/api/v1/credit-cards/?search=travel' | jq .

# Verify data is accessible
# Check that credit cards from latest crawl are present
```

### Performance Verification

```bash
# Check API response time
time curl https://api.yourdomain.com/api/v1/credit-cards/

# Verify background tasks running
uv run celery -A credit_mate_ai inspect active
# Should list active workers

# Check Celery queue lengths
redis-cli LLEN celery
# Should process tasks normally
```

### Log Analysis

```bash
# Check for error spikes
docker-compose logs web | grep ERROR | wc -l

# Sample error logs
docker-compose logs web | grep ERROR | head -20

# Check for warnings
docker-compose logs web | grep WARNING

# If using centralized logging
# Review logs in your logging platform (Datadog, Splunk, etc.)
```

## Infrastructure Prerequisites

### Required Services (Operations Setup)

#### PostgreSQL Database
- **Version**: PostgreSQL 15 (as configured in compose files; adjust if your infrastructure differs)
  - **If using different version**: Update all references and test thoroughly before production
- Configuration:
  - `max_connections`: 200+ (for Gunicorn + Celery workers)
  - `shared_buffers`: 25% of available RAM
  - `effective_cache_size`: 75% of available RAM
  - SSL enabled for production
- Backups: Daily full + hourly WAL backups
- High availability: Streaming replication recommended

#### Redis Cache & Queue
- **Version**: Redis 7-alpine (as configured in compose files; adjust if your infrastructure differs)
  - **If using different version**: Update all references and test thoroughly before production
- Configuration:
  - `maxmemory-policy`: `allkeys-lru` (evict oldest keys)
  - `appendonly`: `yes` (persistence)
  - `appendfsync`: `everysec` (balance durability vs performance)
- Backups: RDB snapshots + AOF logs
- Clustering: Optional for high-volume environments

#### Application Server
- Python 3.12+
- Gunicorn with:
  - Workers: 2 * CPU cores + 1
  - Threads per worker: 1-4 (depends on workload)
  - Timeout: 60+ seconds
  - Keepalive: 5 seconds

#### Celery Workers
- 1+ worker processes
- Concurrency: 4-8 tasks per worker (depends on system resources)
- Task timeout: 3600 seconds (1 hour) for crawling tasks
- Beat scheduler: 1 instance for scheduled tasks

#### Web Server / Load Balancer
- Nginx or similar
- Configuration:
  - SSL/TLS termination
  - Gzip compression enabled
  - Upstream to Gunicorn workers
  - Health check endpoint: `/api/v1/banks/` (simple endpoint)

### Required Environment Variables (Operations Configuration)

```bash
# Security (generate new values for each environment)
SECRET_KEY=<generate-secure-random-string>
DEBUG=False  # MUST be False in production

# Environment identification
ENVIRONMENT=production
ALLOWED_HOSTS=api.yourdomain.com,www.yourdomain.com

# Database
DB_ENGINE=django.db.backends.postgresql
DB_NAME=creditmate_production
DB_USER=creditmate_user
DB_PASSWORD=<secure-password>
DB_HOST=db.yourdomain.internal
DB_PORT=5432

# Cache
REDIS_CACHE_URL=redis://redis.yourdomain.internal:6379/1
CACHE_BACKEND=redis

# Celery
CELERY_BROKER_URL=redis://redis.yourdomain.internal:6379/0
CELERY_RESULT_BACKEND=redis://redis.yourdomain.internal:6379/0

# External APIs
OPENAI_API_KEY=sk-<your-actual-key>

# CORS (frontend domains)
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# Optional: Error Tracking
SENTRY_DSN=https://key@sentry.io/project-id
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1
```

### Monitoring & Alerting Setup

```
Configure alerting for:
✓ API response time > 500ms
✓ Error rate > 1% of requests
✓ Celery worker count < 1
✓ Redis memory > 80%
✓ PostgreSQL connections > 150
✓ Disk usage > 80%
✓ CPU usage > 80% (sustained)
✓ Database query time > 1s
✓ Failed database backups
```

See [INCIDENT_RESPONSE.md](./INCIDENT_RESPONSE.md) for alerting procedures.

## Deployment Troubleshooting

### Services Won't Start

```bash
# Check error logs
docker-compose logs web

# Verify environment variables
docker-compose config | grep -A50 environment

# Test database connection
docker-compose exec web python manage.py dbshell

# Restart with verbose output
docker-compose up --no-detach web
```

### Migrations Fail

```bash
# Show current migration status
docker-compose exec web python manage.py migrate --list

# Check for migration conflicts
docker-compose exec web python manage.py migrate --plan

# Review migration file for syntax errors
docker-compose exec web python manage.py showmigrations --plan
```

### API Returns 503 Service Unavailable

```bash
# Check if services are running
docker-compose ps

# Check logs for errors
docker-compose logs --tail=100 web

# Restart services
docker-compose restart
```

### Database Connection Errors

```bash
# Verify database is running
docker-compose exec db psql -U postgres -c "SELECT 1"

# Check connection string
echo $DB_HOST $DB_PORT $DB_NAME

# Test connection manually
docker-compose exec web python -c "from django.db import connection; connection.ensure_connection()"
```

---

**Need help?** See [INCIDENT_RESPONSE.md](./INCIDENT_RESPONSE.md) for emergency procedures or contact the operations team.
