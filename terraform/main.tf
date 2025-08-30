terraform {
  required_providers {
    railway = {
      source  = "terraform-community-providers/railway"
      version = "~> 0.3.0"
    }
  }
}

# Configure the Railway Provider
provider "railway" {
  # Railway token should be set via RAILWAY_TOKEN environment variable
}

# Create a new Railway project for Credit Mate AI Backend
resource "railway_project" "credit_mate_backend" {
  name        = "credit-mate-ai-backend"
  description = "Django backend for Credit Mate AI application"
}

# PostgreSQL Database Service
resource "railway_service" "postgres" {
  project_id = railway_project.credit_mate_backend.id
  name       = "postgres-db"

  # Railway automatically provisions PostgreSQL when using this configuration
  source_repo    = ""
  source_image   = "postgres:17"

  # Configure PostgreSQL environment
  variables = {
    POSTGRES_DB       = "credit_mate_ai"
    POSTGRES_USER     = "credit_mate_user"
    POSTGRES_PASSWORD = "secure-random-password-123"
  }
}

# Django Web Service
resource "railway_service" "django_web" {
  project_id = railway_project.credit_mate_backend.id
  name       = "django-web"

  # Connect to your GitHub repository
  source_repo   = "your-github-username/credit-mate-ai-backend"
  source_branch = "main"

  # Railway will automatically detect Django and use Gunicorn
  build_command = "pip install -r requirements.txt"
  start_command = "gunicorn credit_mate_ai.wsgi:application --bind 0.0.0.0:$PORT"

  # Environment variables for Django
  variables = {
    # Django Configuration
    DJANGO_SETTINGS_MODULE = "credit_mate_ai.settings"
    SECRET_KEY            = "your-django-secret-key-here"
    DEBUG                 = "False"
    ALLOWED_HOSTS         = "*"

    # Database Configuration (Railway auto-injects these)
    DATABASE_URL = "postgresql://${{Postgres.POSTGRES_USER}}:${{Postgres.POSTGRES_PASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.POSTGRES_DB}}"

    # Celery Configuration
    CELERY_BROKER_URL    = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND = "redis://redis:6379/0"

    # AI API Keys (Set these manually in Railway dashboard for security)
    OPENROUTER_API_KEY = "set-this-in-railway-dashboard"
    GEMINI_API_KEY     = "set-this-in-railway-dashboard"

    # Other Configuration
    PORT = "8000"
  }

  # Health check endpoint
  healthcheck_path = "/api/v1/"

  depends_on = [railway_service.postgres]
}

# Redis Service for Celery
resource "railway_service" "redis" {
  project_id = railway_project.credit_mate_backend.id
  name       = "redis-cache"

  source_image = "redis:7-alpine"

  variables = {
    REDIS_PASSWORD = "redis-secure-password"
  }
}

# Celery Worker Service
resource "railway_service" "celery_worker" {
  project_id = railway_project.credit_mate_backend.id
  name       = "celery-worker"

  # Same repository as Django web service
  source_repo   = "your-github-username/credit-mate-ai-backend"
  source_branch = "main"

  # Override the start command for Celery worker
  build_command = "pip install -r requirements.txt"
  start_command = "celery -A credit_mate_ai worker --loglevel=info"

  # Same environment variables as Django web service
  variables = {
    DJANGO_SETTINGS_MODULE = "credit_mate_ai.settings"
    SECRET_KEY            = "your-django-secret-key-here"
    DEBUG                 = "False"

    DATABASE_URL = "postgresql://${{Postgres.POSTGRES_USER}}:${{Postgres.POSTGRES_PASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.POSTGRES_DB}}"

    CELERY_BROKER_URL    = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND = "redis://redis:6379/0"

    OPENROUTER_API_KEY = "set-this-in-railway-dashboard"
    GEMINI_API_KEY     = "set-this-in-railway-dashboard"
  }

  depends_on = [railway_service.redis, railway_service.django_web]
}

# Celery Beat Service (Scheduler)
resource "railway_service" "celery_beat" {
  project_id = railway_project.credit_mate_backend.id
  name       = "celery-beat"

  source_repo   = "your-github-username/credit-mate-ai-backend"
  source_branch = "main"

  build_command = "pip install -r requirements.txt"
  start_command = "celery -A credit_mate_ai beat --loglevel=info"

  variables = {
    DJANGO_SETTINGS_MODULE = "credit_mate_ai.settings"
    SECRET_KEY            = "your-django-secret-key-here"
    DEBUG                 = "False"

    DATABASE_URL = "postgresql://${{Postgres.POSTGRES_USER}}:${{Postgres.POSTGRES_PASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.POSTGRES_DB}}"

    CELERY_BROKER_URL    = "redis://redis:6379/0"
    CELERY_RESULT_BACKEND = "redis://redis:6379/0"

    OPENROUTER_API_KEY = "set-this-in-railway-dashboard"
    GEMINI_API_KEY     = "set-this-in-railway-dashboard"
  }

  depends_on = [railway_service.redis, railway_service.django_web]
}

# Output important values
output "project_id" {
  description = "Railway project ID"
  value       = railway_project.credit_mate_backend.id
}

output "django_web_url" {
  description = "Django web service URL"
  value       = railway_service.django_web.domain
}

output "postgres_connection_info" {
  description = "PostgreSQL connection details"
  value = {
    host     = railway_service.postgres.domain
    database = railway_service.postgres.variables.POSTGRES_DB
    user     = railway_service.postgres.variables.POSTGRES_USER
  }
  sensitive = true
}
