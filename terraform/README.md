# Credit Mate AI Backend - Railway Deployment with Terraform

This directory contains Terraform configurations to deploy the Credit Mate AI Django backend to Railway.

## Architecture

The deployment creates a complete Django application with:
- **Django Web Service**: Main API server with Gunicorn
- **PostgreSQL Database**: Managed PostgreSQL 17 database
- **Redis Cache**: For Celery message broker
- **Celery Worker**: Background task processing
- **Celery Beat**: Scheduled task management

## Prerequisites

1. **Railway Account**: Sign up at [railway.app](https://railway.app)
2. **Railway Token**: Generate at [railway.app/account/tokens](https://railway.app/account/tokens)
3. **Terraform**: Install from [terraform.io](https://terraform.io)
4. **GitHub Repository**: Your Django code must be in a GitHub repository

## Quick Start

1. **Clone and Navigate**:
   ```bash
   cd PycharmProjects/credit-mate-ai/terraform
   ```

2. **Configure Variables**:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars with your values
   ```

3. **Set Railway Token**:
   ```bash
   export RAILWAY_TOKEN="your-railway-token-here"
   ```

4. **Deploy**:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

## Configuration Files

### Required Files
- `main.tf` - Main Terraform configuration
- `variables.tf` - Variable definitions
- `terraform.tfvars` - Your secret values (gitignored)
- `railway.json` - Railway deployment configuration
- `requirements.txt` - Python dependencies

### Environment Variables

The deployment automatically sets these environment variables:

**Django Configuration**:
- `DJANGO_SETTINGS_MODULE=credit_mate_ai.settings`
- `SECRET_KEY` - From your tfvars
- `DEBUG=False`
- `ALLOWED_HOSTS=*`

**Database Configuration**:
- `DATABASE_URL` - Auto-injected by Railway PostgreSQL service

**Celery Configuration**:
- `CELERY_BROKER_URL=redis://redis:6379/0`
- `CELERY_RESULT_BACKEND=redis://redis:6379/0`

**AI API Keys**:
- `OPENROUTER_API_KEY` - For OpenRouter AI API
- `GEMINI_API_KEY` - For Google Gemini API

## Manual Steps After Deployment

1. **Update GitHub Repository URL**:
   - Update `github_repo_url` in `terraform.tfvars`
   - Ensure your repository is public or Railway has access

2. **Set API Keys Securely**:
   - Go to Railway dashboard
   - Navigate to your project services
   - Add sensitive API keys through Railway's web interface

3. **Run Database Migrations**:
   - Railway automatically runs migrations on deployment
   - Check logs to ensure migrations completed successfully

4. **Create Superuser** (optional):
   ```bash
   railway run python manage.py createsuperuser
   ```

## Monitoring and Logs

- **Railway Dashboard**: View service status, logs, and metrics
- **Health Checks**: Configured on `/api/v1/` endpoint
- **Auto-restart**: Services restart on failure (max 3 retries)

## Scaling

To scale services:
```hcl
# In main.tf, add to service configuration:
replicas = 2  # Scale to 2 instances
```

## Troubleshooting

### Common Issues

1. **Build Failures**:
   - Check `requirements.txt` includes all dependencies
   - Verify Python version compatibility

2. **Database Connection Issues**:
   - Ensure PostgreSQL service is running
   - Check environment variable injection

3. **Static Files Not Loading**:
   - Verify `collectstatic` runs in start command
   - Check `whitenoise` configuration in Django settings

### Useful Commands

```bash
# View deployment status
terraform show

# Update deployment
terraform plan
terraform apply

# Destroy deployment
terraform destroy

# Railway CLI (alternative management)
railway login
railway status
railway logs
```

## Security Notes

- Never commit `terraform.tfvars` to version control
- Use strong, random passwords for databases
- Set `DEBUG=False` in production
- Configure proper `ALLOWED_HOSTS` for your domain

## Cost Optimization

Railway pricing is based on usage:
- **Hobby Plan**: $5/month for basic apps
- **Pro Plan**: $20/month with more resources
- **Pay-per-use**: For CPU/memory/storage usage

Monitor your usage in the Railway dashboard to optimize costs.

## Next Steps

After successful deployment:
1. Configure custom domain in Railway dashboard
2. Set up monitoring and alerts
3. Configure CI/CD pipeline for automatic deployments
4. Set up backup strategies for your database
