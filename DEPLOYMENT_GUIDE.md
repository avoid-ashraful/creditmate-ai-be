# CreditMate AI - Railway Deployment Guide

## Prerequisites
1. GitHub account
2. Railway account (sign up at railway.app)
3. Your API keys (OPENROUTER_API_KEY, GEMINI_API_KEY)

## Step-by-Step Deployment

### 1. Prepare Repository
Ensure all changes are committed and pushed to GitHub:
```bash
git add .
git commit -m "Prepare for Railway deployment"
git push origin main
```

### 2. Deploy to Railway

1. **Go to Railway**: https://railway.app
2. **Sign in** with GitHub
3. **New Project** → Deploy from GitHub repo
4. **Select** your repository: `creditmate-ai-be`
5. Railway will auto-detect Dockerfile

### 3. Add PostgreSQL Database

1. In your Railway project, click **"+ New"**
2. Select **"Database" → "PostgreSQL"**
3. Railway automatically sets DATABASE_URL for you

### 4. Add Redis

1. Click **"+ New"** again
2. Select **"Database" → "Redis"**
3. Railway automatically sets REDIS_URL

### 5. Configure Environment Variables

In your Railway project settings, add these variables:

```
SECRET_KEY=django-insecure-generate-a-new-one-here-make-it-long-and-random
DEBUG=False
ALLOWED_HOSTS=*.up.railway.app,*.railway.app
DATABASE_URL=(auto-set by Railway)
REDIS_URL=(auto-set by Railway)
OPENROUTER_API_KEY=your-actual-openrouter-api-key
GEMINI_API_KEY=your-actual-gemini-api-key
CELERY_BROKER_URL=$REDIS_URL
PORT=8000
```

### 6. Add Celery Worker Service

1. Click **"+ New" → "Empty Service"**
2. **Name it:** `celery-worker`
3. Connect it to your repository
4. **Custom Start Command:**
   ```
   celery -A credit_mate_ai worker --loglevel=info
   ```
5. Use the same environment variables as main app

### 7. Add Celery Beat Service (Optional)

For scheduled tasks:

1. Click **"+ New" → "Empty Service"**
2. **Name it:** `celery-beat`
3. Connect it to your repository
4. **Custom Start Command:**
   ```
   celery -A credit_mate_ai beat --loglevel=info
   ```

### 8. Deploy!

Railway will automatically:
- ✅ Build your Docker container
- ✅ Run migrations
- ✅ Start your Django app
- ✅ Give you a public URL

### 9. Access Your App

Your app will be available at:
```
https://your-app-name.up.railway.app
```

API endpoints:
- https://your-app-name.up.railway.app/api/v1/
- https://your-app-name.up.railway.app/api/v1/benefit-categories/
- https://your-app-name.up.railway.app/api/v1/credit-cards/
- https://your-app-name.up.railway.app/admin/

## Post-Deployment

### Create Superuser

Using Railway CLI:
```bash
railway login
railway run python manage.py createsuperuser
```

Or use Railway's built-in shell.

### Run Initial Data Migration

```bash
railway run python manage.py migrate
```

## Monitoring

Railway provides:
- Real-time logs
- Resource usage metrics
- Deployment history
- Environment variable management

## Troubleshooting

### Check Logs
In Railway dashboard → Click your service → "Deployments" → View logs

### Database Connection Issues
Make sure DATABASE_URL is set by PostgreSQL service

### Celery Not Working
Verify REDIS_URL is correctly set and worker service is running

## Cost Estimation

**Free Tier:**
- $5 monthly credit
- Suitable for development/testing

**Production:**
- Web service: ~$5/month
- PostgreSQL: ~$5/month  
- Redis: ~$3/month
- Celery workers: ~$5/month each
- **Total:** ~$18-25/month

## Support

If you encounter issues:
1. Check Railway logs
2. Review environment variables
3. Ensure all services are running
4. Check Railway community docs

---

Happy deploying! 🚀
