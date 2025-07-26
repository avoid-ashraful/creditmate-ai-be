# Environment Variables Configuration

This document provides a comprehensive reference for all environment variables used in Credit Mate AI.

## Quick Reference

For a complete example configuration, see [.env.example](../../.env.example) in the project root.

## Core Django Settings

### Required Settings
```bash
# Django secret key for cryptographic signing
SECRET_KEY=your-super-secret-key-here

# Debug mode (True for development, False for production)
DEBUG=True

# Comma-separated list of allowed hosts
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Environment Configuration
```bash
# Environment type: local, staging, or production
# This affects email backend and other environment-specific settings
ENVIRONMENT=local
```

## Database Configuration

### SQLite (Default for Development)
```bash
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=db.sqlite3
```

### PostgreSQL (Recommended for Production)
```bash
DB_ENGINE=django.db.backends.postgresql
DB_NAME=creditmate_ai
DB_USER=postgres
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432
```

## External Services

### OpenAI API (Required for AI Content Parsing)
```bash
# OpenAI API key for GPT-based content parsing
OPENAI_API_KEY=sk-your-openai-api-key-here
```

### Celery & Redis (Required for Background Tasks)
```bash
# Redis URL for Celery message broker
CELERY_BROKER_URL=redis://localhost:6379/0

# Redis URL for Celery result backend
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

## Security Configuration

### CORS (Cross-Origin Resource Sharing)
```bash
# Comma-separated list of allowed frontend origins
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://yourdomain.com

# Allow credentials in CORS requests
CORS_ALLOW_CREDENTIALS=True

# Development only - allows all origins (NEVER use in production)
CORS_ALLOW_ALL_ORIGINS=False
```

### API Rate Limiting
```bash
# Rate limit for anonymous users (requests per time period)
THROTTLE_RATE_ANON=1000/hour

# Rate limit for authenticated users (requests per time period)
THROTTLE_RATE_USER=2000/hour

# Burst protection rate limit (requests per minute)
THROTTLE_RATE_BURST=100/min
```

### HTTPS/SSL Security (Production)
```bash
# Force HTTPS redirects
SECURE_SSL_REDIRECT=True

# HTTP Strict Transport Security
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True

# Secure cookies
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

## Email Configuration

Email configuration is environment-dependent:

### Local/Staging (Email Disabled)
```bash
ENVIRONMENT=local
# No email configuration needed - uses dummy backend
```

### Production (SMTP Required)
```bash
ENVIRONMENT=production

# Email backend configuration
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@domain.com
EMAIL_HOST_PASSWORD=your-email-password
```

## Environment-Specific Examples

### Local Development
```bash
# Basic local development setup
SECRET_KEY=django-insecure-dev-key-only-for-development
DEBUG=True
ENVIRONMENT=local
ALLOWED_HOSTS=localhost,127.0.0.1

# OpenAI API (required)
OPENAI_API_KEY=sk-your-openai-api-key-here

# Redis for Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# CORS for frontend development
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Relaxed rate limiting for development
THROTTLE_RATE_ANON=10000/hour
THROTTLE_RATE_USER=20000/hour
```

### Staging Environment
```bash
# Staging configuration
SECRET_KEY=your-staging-secret-key
DEBUG=False
ENVIRONMENT=staging
ALLOWED_HOSTS=staging.yourdomain.com

# PostgreSQL database
DB_ENGINE=django.db.backends.postgresql
DB_NAME=creditmate_staging
DB_USER=postgres
DB_PASSWORD=your-db-password
DB_HOST=staging-db.yourdomain.com
DB_PORT=5432

# Production-like services
OPENAI_API_KEY=sk-your-openai-api-key-here
CELERY_BROKER_URL=redis://staging-redis.yourdomain.com:6379/0

# Staging CORS
CORS_ALLOWED_ORIGINS=https://staging.yourdomain.com,https://staging-app.yourdomain.com

# Standard rate limiting
THROTTLE_RATE_ANON=1000/hour
THROTTLE_RATE_USER=2000/hour
```

### Production Environment
```bash
# Production configuration
SECRET_KEY=your-production-secret-key
DEBUG=False
ENVIRONMENT=production
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# PostgreSQL database
DB_ENGINE=django.db.backends.postgresql
DB_NAME=creditmate_production
DB_USER=postgres
DB_PASSWORD=your-secure-db-password
DB_HOST=prod-db.yourdomain.com
DB_PORT=5432

# Production services
OPENAI_API_KEY=sk-your-production-openai-api-key
CELERY_BROKER_URL=redis://prod-redis.yourdomain.com:6379/0

# Production CORS (strict)
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com,https://app.yourdomain.com
CORS_ALLOW_CREDENTIALS=True

# Production rate limiting
THROTTLE_RATE_ANON=1000/hour
THROTTLE_RATE_USER=2000/hour
THROTTLE_RATE_BURST=100/min

# HTTPS security
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# Email configuration
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.yourdomain.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=noreply@yourdomain.com
EMAIL_HOST_PASSWORD=your-email-password
```

## Validation and Testing

### Required Variables
These variables must be set for the application to function:
- `SECRET_KEY`
- `OPENAI_API_KEY`
- `CELERY_BROKER_URL`

### Optional Variables
These have sensible defaults but can be customized:
- `DEBUG` (defaults to True)
- `ENVIRONMENT` (defaults to "local")
- `THROTTLE_RATE_*` (have default rate limits)
- `CORS_*` (have default CORS settings)

### Testing Configuration
```bash
# Test your configuration
python manage.py check

# Test database connection
python manage.py migrate --dry-run

# Test Celery connection
celery -A credit_mate_ai inspect ping

# Test Redis connection
redis-cli ping
```

## Security Best Practices

1. **Never commit secrets to version control**
2. **Use different SECRET_KEY for each environment**
3. **Use strong, unique passwords for databases**
4. **Rotate API keys regularly**
5. **Use HTTPS in production**
6. **Keep CORS origins minimal and specific**
7. **Monitor rate limiting logs**
8. **Use environment-specific rate limits**

## Troubleshooting

### Common Issues

#### Secret Key Errors
```bash
# Error: SECRET_KEY must be set
# Solution: Set SECRET_KEY environment variable
export SECRET_KEY="your-secret-key-here"
```

#### Database Connection Issues
```bash
# Error: Database connection failed
# Solution: Check database settings and connectivity
python manage.py dbshell
```

#### Redis Connection Issues
```bash
# Error: Celery broker connection failed
# Solution: Check Redis is running and accessible
redis-cli ping
```

#### CORS Issues
```bash
# Error: CORS policy blocks request
# Solution: Add frontend domain to CORS_ALLOWED_ORIGINS
CORS_ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
```

For detailed configuration guides, see:
- [Email Configuration](./email.md)
- [CORS and Rate Limiting](./cors-and-rate-limiting.md)
