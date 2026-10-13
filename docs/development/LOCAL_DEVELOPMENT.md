# 🚀 Local Development Setup Guide

This guide provides step-by-step instructions for setting up the CreditMate AI backend for local development, with both traditional and Docker-based approaches.

## Table of Contents

- [System Requirements](#system-requirements)
- [Traditional Local Setup](#traditional-local-setup)
- [Docker-Based Development](#docker-based-development)
- [Environment Configuration](#environment-configuration)
- [Database Setup](#database-setup)
- [Running the Application](#running-the-application)
- [Code Quality Tools](#code-quality-tools)
- [Troubleshooting](#troubleshooting)

## System Requirements

### Minimum Requirements
- **Python**: 3.12 or higher
- **PostgreSQL**: 17 (for production-like database)
- **Redis**: 7.0 or higher
- **Git**: Latest version

### Optional
- **Docker**: 20.10+ and Docker Compose 2.0+ (for containerized development)
- **uv**: Latest version (Python package manager - installed via pip)

## Traditional Local Setup

### Step 1: Clone the Repository

```bash
git clone https://github.com/avoid-ashraful/creditmate-ai-be.git
cd creditmate-ai-be
```

### Step 2: Install Python Dependencies

```bash
# Install uv if not already installed
pip install uv

# Install project dependencies (including dev dependencies)
uv sync --dev

# Activate the virtual environment (optional, uv handles this)
source .venv/bin/activate
```

### Step 3: Install System Services

#### macOS (using Homebrew)
```bash
# Install PostgreSQL
brew install postgresql@17
brew services start postgresql@17

# Install Redis
brew install redis
brew services start redis

# Verify installations
psql --version
redis-cli ping
```

#### Ubuntu/Debian
```bash
# Install PostgreSQL
sudo apt-get update
sudo apt-get install -y postgresql-17 postgresql-contrib-17
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Install Redis
sudo apt-get install -y redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Verify installations
psql --version
redis-cli ping
```

### Step 4: Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your local configuration
nano .env
```

**Essential variables for local development:**

```bash
# Django settings
SECRET_KEY=django-insecure-dev-key-only-for-development
DEBUG=True
ENVIRONMENT=local
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (PostgreSQL)
DB_NAME=creditmate_db
DB_USER=postgres
DB_PASSWORD=postgres  # Change this to your password
DB_HOST=localhost
DB_PORT=5432

# OpenAI Integration (required for crawling)
OPENAI_API_KEY=sk-your-actual-openai-api-key

# Redis/Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
REDIS_CACHE_URL=redis://localhost:6379/1

# CORS (for frontend development)
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Rate limiting (permissive for development)
THROTTLE_RATE_ANON=10000/hour
THROTTLE_RATE_USER=20000/hour
```

### Step 5: Create Database

```bash
# Create PostgreSQL database and user
sudo -u postgres psql <<EOF
CREATE DATABASE creditmate_db;
CREATE USER creditmate_user WITH PASSWORD 'your_secure_password';
ALTER ROLE creditmate_user SET client_encoding TO 'utf8';
ALTER ROLE creditmate_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE creditmate_user SET default_transaction_deferrable TO on;
ALTER ROLE creditmate_user SET default_transaction_read_committed TO 'read committed';
GRANT ALL PRIVILEGES ON DATABASE creditmate_db TO creditmate_user;
EOF

# Or update .env with PostgreSQL credentials
DB_USER=creditmate_user
DB_PASSWORD=your_secure_password
```

### Step 6: Run Database Migrations

```bash
# Run all migrations
uv run python manage.py migrate

# Verify migrations
uv run python manage.py migrate --check
```

### Step 7: Create Superuser

```bash
# Create Django superuser for admin access
uv run python manage.py createsuperuser

# You'll be prompted for:
# - Username
# - Email
# - Password (twice)
```

## Docker-Based Development

### Quick Start with Docker Compose

```bash
# Copy environment file
cp .env.example .env

# Update .env with your OpenAI API key
# OPENAI_API_KEY=sk-your-actual-key

# Build and start containers
docker-compose -f docker-compose.dev.yml up -d

# Run migrations
docker-compose -f docker-compose.dev.yml exec web uv run python manage.py migrate

# Create superuser
docker-compose -f docker-compose.dev.yml exec web uv run python manage.py createsuperuser

# View logs
docker-compose -f docker-compose.dev.yml logs -f
```

### Docker Compose Services (Development)

The `docker-compose.dev.yml` includes:

| Service | Port | Purpose |
|---------|------|---------|
| `redis` | 6379 | Message broker for Celery |
| `web` | 8000 | Django development server |
| `celery` | - | Background task worker |
| `celery-beat` | - | Scheduled task scheduler |

### Access Development Environment

**Django Application**
```
http://localhost:8000/
```

**Django Admin**
```
http://localhost:8000/admin/
```

**API Documentation**
```
http://localhost:8000/api/v1/
```

**Redis CLI** (from inside container)
```bash
docker-compose -f docker-compose.dev.yml exec redis redis-cli
```

## Environment Configuration

### Required Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `SECRET_KEY` | Django secret key | `django-insecure-...` |
| `DEBUG` | Debug mode (local only) | `True` |
| `ENVIRONMENT` | Environment type | `local`, `staging`, `production` |
| `DB_NAME` | Database name | `creditmate_db` |
| `DB_USER` | Database user | `postgres` |
| `DB_PASSWORD` | Database password | `secure_password` |
| `DB_HOST` | Database host | `localhost` or `db` |
| `DB_PORT` | Database port | `5432` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-...` |
| `CELERY_BROKER_URL` | Redis broker URL | `redis://localhost:6379/0` |

### Optional Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ALLOWED_HOSTS` | Allowed host names | `localhost,127.0.0.1` |
| `CORS_ALLOWED_ORIGINS` | Allowed CORS origins | `http://localhost:3000` |
| `CACHE_BACKEND` | Cache backend | `redis` |
| `SENTRY_DSN` | Sentry error tracking | Disabled if not set |

**See [Environment Variables Reference](../configuration/environment-variables.md) for complete list.**

## Database Setup

### Manual Database Creation

```bash
# As PostgreSQL superuser
sudo -u postgres createdb creditmate_db
sudo -u postgres createuser creditmate_user -P

# Grant privileges
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE creditmate_db TO creditmate_user;"
```

### Load Sample Data (Optional)

```bash
# Create fixtures directory if needed
mkdir -p banks/fixtures

# Load initial banks data
uv run python manage.py loaddata banks/fixtures/initial_banks.json

# Verify data load
uv run python manage.py shell
>>> from banks.models import Bank
>>> Bank.objects.count()
```

### Database Inspection

```bash
# Connect to database
psql -U postgres -d creditmate_db

# List tables
\dt

# Describe table structure
\d banks_bank

# Exit
\q
```

## Running the Application

### Terminal 1: Django Development Server

```bash
# Start Django development server (hot reload enabled)
uv run python manage.py runserver

# Accessible at: http://localhost:8000/
```

### Terminal 2: Celery Worker

```bash
# Start Celery worker for background tasks
uv run celery -A credit_mate_ai worker --loglevel=info

# Shows task execution in real-time
```

### Terminal 3: Celery Beat Scheduler

```bash
# Start Celery Beat for scheduled tasks
uv run celery -A credit_mate_ai beat --loglevel=info

# Scheduled tasks run automatically on defined schedules
```

### With Docker Compose

```bash
# Start all services in background
docker-compose -f docker-compose.dev.yml up -d

# View logs from all services
docker-compose -f docker-compose.dev.yml logs -f

# View logs from specific service
docker-compose -f docker-compose.dev.yml logs -f web

# Stop all services
docker-compose -f docker-compose.dev.yml down

# Stop and remove data volumes (clean reset)
docker-compose -f docker-compose.dev.yml down -v
```

## Code Quality Tools

### Code Formatting

```bash
# Format code with Black
uv run black .

# Format with isort (import sorting)
uv run isort .

# Format all code at once
uv run black . && uv run isort .
```

### Linting

```bash
# Check code quality with Flake8
uv run flake8

# Show statistics
uv run flake8 --statistics

# Specific directory
uv run flake8 banks/ credit_cards/
```

### Type Checking

```bash
# Check types with mypy
uv run mypy .

# Check specific module
uv run mypy banks/
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov=banks --cov=credit_cards --cov=common --cov-report=html

# Run specific test file
uv run pytest banks/tests/test_api.py

# Run specific test function
uv run pytest banks/tests/test_api.py::TestBanksAPI::test_list_banks

# Run with verbose output
uv run pytest -v

# Stop on first failure
uv run pytest -x

# Show print statements
uv run pytest -s
```

### Pre-commit Hooks (Optional)

```bash
# Install pre-commit hooks
pre-commit install

# Run pre-commit on all files
pre-commit run --all-files

# Skip hooks on commit
git commit --no-verify
```

## System Health Checks

### Check Django Configuration

```bash
# Verify Django setup
uv run python manage.py check

# Expected output: System check identified no issues (0 silenced).
```

### Verify Database Connection

```bash
# Open Django shell and test connection
uv run python manage.py shell

# In Python shell:
>>> from django.db import connection
>>> connection.ensure_connection()
>>> print("Database connected!")
```

### Monitor Redis Connection

```bash
# Test Redis connectivity
redis-cli ping
# Expected output: PONG

# Check Redis info
redis-cli info
```

### Check Celery Workers

```bash
# List active workers
uv run celery -A credit_mate_ai inspect active

# Check task stats
uv run celery -A credit_mate_ai inspect stats

# Revoke all tasks (use with caution)
uv run celery -A credit_mate_ai purge
```

## Troubleshooting

### PostgreSQL Connection Issues

**Problem**: "could not connect to server"

**Solutions**:
```bash
# Verify PostgreSQL is running
sudo systemctl status postgresql  # Linux
brew services list               # macOS

# Test connection
psql -U postgres -h localhost -d postgres

# Check connection string in .env
echo $DB_HOST  # Should be 'localhost' for local setup
```

### Redis Connection Issues

**Problem**: "Connection refused" when starting Celery

**Solutions**:
```bash
# Verify Redis is running
redis-cli ping

# Start Redis (if stopped)
sudo systemctl start redis-server  # Linux
brew services start redis          # macOS

# Check Redis configuration
redis-cli CONFIG GET port
```

### Database Migration Errors

**Problem**: "Error during migration"

**Solutions**:
```bash
# Check migration status
uv run python manage.py migrate --plan

# Show SQL for migration
uv run python manage.py sqlmigrate banks 0001

# Revert migration (dangerous - data loss)
uv run python manage.py migrate banks 0000

# Create new migration after model changes
uv run python manage.py makemigrations
```

### Docker Port Conflicts

**Problem**: "bind: address already in use"

**Solutions**:
```bash
# Stop conflicting services
docker-compose -f docker-compose.dev.yml down

# Find process using port
lsof -i :8000  # Linux/macOS
netstat -ano | findstr :8000  # Windows

# Kill process (use with caution)
kill -9 <PID>

# Use different port
docker-compose -f docker-compose.dev.yml up -d -p 8001:8000
```

### Celery Tasks Not Running

**Problem**: Tasks submitted but not executing

**Solutions**:
```bash
# Verify Celery worker is running
uv run celery -A credit_mate_ai inspect active

# Verify Celery Beat is running
ps aux | grep celery

# Check task queue
redis-cli LLEN celery  # Check celery queue length

# Clear task queue (if needed)
redis-cli DEL celery

# Check worker logs for errors
uv run celery -A credit_mate_ai worker --loglevel=debug
```

### OpenAI API Issues

**Problem**: "Invalid API key" or "Rate limit exceeded"

**Solutions**:
```bash
# Verify API key is set
echo $OPENAI_API_KEY

# Test API connectivity
uv run python manage.py shell
>>> import openai
>>> openai.api_key = "your-key"
>>> openai.Model.list()  # Test call

# Check OpenAI account limits on https://platform.openai.com/account/billing/usage
```

### Memory/Resource Issues

**Problem**: Application running slowly or crashing

**Solutions**:
```bash
# Check available memory
free -h  # Linux
vm_stat | grep "Pages free"  # macOS

# Check disk space
df -h

# Check running processes
top  # Interactive
htop  # Better version (if installed)

# Reduce Celery concurrency if needed
uv run celery -A credit_mate_ai worker -c 2  # 2 concurrent tasks
```

## Development Best Practices

### Commit Code
```bash
# Follow conventional commits
git commit -m "feat(banks): add multi-source validation"
git commit -m "fix(api): resolve rate limit calculation"

# For detailed instructions, see: CLAUDE.md
```

### Create Feature Branches

```bash
# Follow consistent naming
git checkout -b feature/description
git checkout -b fix/bug-description
git checkout -b refactor/component-name
```

### Test Before Pushing

```bash
# Run full test suite
uv run pytest

# Check code quality
uv run black . && uv run isort . && uv run flake8

# Verify migrations
uv run python manage.py migrate --check
```

## Next Steps

- **[Environment Variables Reference](../configuration/environment-variables.md)** - Complete env var documentation
- **[Architecture Guide](./ARCHITECTURE.md)** - System architecture and data flow
- **[Coding Standards](./setup-and-guidelines.md)** - Development conventions and standards
- **[Testing Guide](./setup-and-guidelines.md#testing)** - Comprehensive testing documentation

---

**Need help?** See the [Troubleshooting](#troubleshooting) section above or check [setup-and-guidelines.md](./setup-and-guidelines.md#troubleshooting) for more common issues.
