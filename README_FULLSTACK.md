# CreditMate AI - Full Stack Application

Complete credit card comparison platform with Django REST API backend, Next.js frontend, ratings/reviews system, and Docker deployment.

## 🚀 Features

### Backend (Django REST API)
- ✅ Credit card CRUD with comprehensive filtering
- ✅ 10 benefit categories with MCC code alignment
- ✅ User ratings (1-5 stars) with duplicate prevention
- ✅ User reviews with pros/cons, helpful voting
- ✅ Admin moderation for reviews
- ✅ Celery background tasks for web crawling
- ✅ OpenRouter/Gemini AI for data parsing
- ✅ Comprehensive API with 20+ endpoints

### Frontend (Next.js 14 + TypeScript)
- 📋 Credit card listing with advanced filters
- 🔍 Search and sort functionality
- 📊 Side-by-side card comparison (up to 4 cards)
- ⭐ Rating and review submission
- 🏷️ Browse by benefit categories
- 📱 Responsive design with Tailwind CSS
- 🚀 Server-side rendering for SEO

### Infrastructure
- 🐳 Docker Compose for full stack deployment
- 🗄️ PostgreSQL 17 database
- 🔴 Redis for task queue
- 🔄 Celery for background tasks
- 🚀 Production-ready configuration

## 📦 Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 18+ (for local frontend development)
- Python 3.12+ (for local backend development)

### 1. Clone and Setup

```bash
cd /home/user/creditmate-ai-be

# Create .env file
cat > .env << EOF
SECRET_KEY=your-secret-key-here-change-in-production
DATABASE_URL=postgresql://postgres:postgres@db:5432/creditmate_ai
CELERY_BROKER_URL=redis://redis:6379/0
OPENROUTER_API_KEY=your-openrouter-key
GEMINI_API_KEY=your-gemini-key
ALLOWED_HOSTS=localhost,127.0.0.1,web,0.0.0.0
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
DEBUG=True
EOF
```

### 2. Create Next.js Frontend

```bash
# Create Next.js app
npx create-next-app@latest frontend --typescript --tailwind --app --src-dir --import-alias "@/*"

# Answer prompts:
# - TypeScript: Yes
# - ESLint: Yes
# - Tailwind CSS: Yes
# - `src/` directory: Yes
# - App Router: Yes
# - Import alias: @/*

cd frontend

# Install dependencies
npm install axios @tanstack/react-query zustand lucide-react class-variance-authority clsx tailwind-merge

# Create frontend Dockerfile
cat > Dockerfile << 'EOF'
FROM node:18-alpine AS base

# Install dependencies only when needed
FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ENV NEXT_TELEMETRY_DISABLED 1

RUN npm run build

# Production image, copy all the files and run next
FROM base AS runner
WORKDIR /app

ENV NODE_ENV production
ENV NEXT_TELEMETRY_DISABLED 1

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT 3000

CMD ["node", "server.js"]
EOF

# Create .env.local for frontend
cat > .env.local << EOF
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_APP_NAME=CreditMate AI
EOF

cd ..
```

### 3. Implement Frontend (See FRONTEND_IMPLEMENTATION.md for details)

The frontend implementation involves creating:
1. API client (`src/lib/api/`)
2. TypeScript types (`src/types/`)
3. React components (`src/components/`)
4. App Router pages (`src/app/`)
5. Custom hooks (`src/lib/hooks/`)

Refer to `FRONTEND_IMPLEMENTATION.md` for complete code examples.

### 4. Build and Run with Docker

```bash
# Build all services
docker-compose build

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Check running services
docker-compose ps
```

Services will be available at:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000/api/v1
- **Django Admin**: http://localhost:8000/admin
- **PostgreSQL**: localhost:5432
- **Redis**: localhost:6379

### 5. Initialize Database

```bash
# Run migrations
docker-compose exec web python manage.py migrate

# Create superuser
docker-compose exec web python manage.py createsuperuser

# Load initial data (benefit categories already seeded via migration)
```

## 🔧 Development

### Backend Development

```bash
# Install dependencies
uv sync --dev

# Start services locally
uv run python manage.py runserver
uv run celery -A credit_mate_ai worker --loglevel=info
uv run celery -A credit_mate_ai beat --loglevel=info

# Run tests
uv run pytest

# Run migrations
uv run python manage.py migrate

# Create migrations
uv run python manage.py makemigrations
```

### Frontend Development

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Start production server
npm start

# Run linter
npm run lint
```

## 📚 API Endpoints

### Credit Cards
- `GET /api/v1/credit-cards` - List all cards with filters
- `GET /api/v1/credit-cards/{id}` - Get card details
- `GET /api/v1/credit-cards/search_suggestions` - Get search suggestions

### Benefit Categories
- `GET /api/v1/benefit-categories` - List all categories
- `GET /api/v1/benefit-categories/{id}` - Get category details
- `GET /api/v1/benefit-categories/{id}/cards` - Get cards in category

### Ratings
- `GET /api/v1/ratings?credit_card=X` - List ratings for a card
- `POST /api/v1/ratings` - Submit a rating

### Reviews
- `GET /api/v1/reviews?credit_card=X` - List approved reviews
- `POST /api/v1/reviews` - Submit a review (requires admin approval)
- `POST /api/v1/reviews/{id}/mark_helpful` - Mark review as helpful

### Banks
- `GET /api/v1/banks` - List all banks
- `GET /api/v1/banks/{id}` - Get bank details

## 🎨 Frontend Structure

```
frontend/src/
├── app/                    # Next.js App Router pages
│   ├── page.tsx           # Homepage with featured cards
│   ├── cards/
│   │   ├── page.tsx       # Browse all cards
│   │   └── [id]/page.tsx  # Card detail with reviews
│   ├── categories/
│   │   ├── page.tsx       # Browse categories
│   │   └── [id]/page.tsx  # Category cards
│   ├── compare/
│   │   └── page.tsx       # Compare up to 4 cards
│   └── search/
│       └── page.tsx       # Advanced search
├── components/             # Reusable React components
│   ├── cards/             # Card components
│   ├── reviews/           # Review components
│   ├── layout/            # Layout components
│   └── ui/                # UI primitives
├── lib/
│   ├── api/               # API client
│   ├── hooks/             # Custom React hooks
│   └── utils.ts           # Helper functions
└── types/
    └── index.ts           # TypeScript types
```

## 🧪 Testing

### Backend Tests
```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov

# Run specific test file
uv run pytest credit_cards/tests/test_models.py

# Run Django tests
uv run python manage.py test
```

### Frontend Tests
```bash
cd frontend

# Run Jest tests
npm test

# Run E2E tests with Playwright
npm run test:e2e
```

## 🔒 Security

- HTTPS enforced in production
- CORS properly configured
- SQL injection protection via Django ORM
- XSS protection via React
- CSRF protection enabled
- Request size validation (10MB limit)
- Rate limiting on API endpoints
- Email verification for reviews

## 📈 Performance

- Database indexes on frequently queried fields
- Redis caching for API responses
- Server-side rendering for SEO
- Static asset optimization
- Image optimization with Next.js Image
- API pagination (20 items per page)
- Database query optimization with select_related

## 🚢 Deployment

### Production Checklist

1. **Environment Variables**
   - Change `SECRET_KEY` to a strong random key
   - Set `DEBUG=False`
   - Configure `ALLOWED_HOSTS`
   - Add production domain to `CORS_ALLOWED_ORIGINS`
   - Set API keys for OpenRouter/Gemini

2. **Database**
   - Use managed PostgreSQL (Railway, Heroku, AWS RDS)
   - Set up automated backups
   - Configure connection pooling

3. **Static Files**
   - Run `python manage.py collectstatic`
   - Serve via CDN or Nginx

4. **Monitoring**
   - Set up error tracking (Sentry)
   - Configure logging
   - Monitor Celery tasks

5. **SSL**
   - Configure HTTPS
   - Set `SECURE_SSL_REDIRECT=True`
   - Enable HSTS

### Railway Deployment

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Initialize project
railway init

# Add PostgreSQL
railway add

# Deploy
railway up

# Set environment variables
railway variables set SECRET_KEY=your-secret-key
railway variables set OPENROUTER_API_KEY=your-key
```

## 📝 License

MIT License - See LICENSE file for details

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## 📧 Support

For issues and questions:
- GitHub Issues: [github.com/avoid-ashraful/creditmate-ai-be/issues](https://github.com/avoid-ashraful/creditmate-ai-be/issues)
- Email: support@creditmate.ai

## 🎯 Roadmap

- [x] Backend API with ratings/reviews
- [x] Docker Compose setup
- [ ] Complete Next.js frontend
- [ ] User authentication system
- [ ] Email notifications
- [ ] Advanced analytics
- [ ] Mobile app (React Native)
- [ ] Admin dashboard enhancements
