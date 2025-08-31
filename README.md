# 💳 CreditMate AI

[![Tests](https://github.com/avoid-ashraful/creditmate-ai-be/workflows/Tests/badge.svg)](https://github.com/avoid-ashraful/creditmate-ai-be/actions)
[![Code Quality](https://github.com/avoid-ashraful/creditmate-ai-be/workflows/Code%20Quality/badge.svg)](https://github.com/avoid-ashraful/creditmate-ai-be/actions)
[![codecov](https://codecov.io/gh/avoid-ashraful/creditmate-ai-be/branch/master/graph/badge.svg)](https://codecov.io/gh/avoid-ashraful/creditmate-ai-be)

> 🚀 **AI-Powered Credit Card Discovery Platform** - Automatically crawl, analyze, and compare credit cards from banks across the web using advanced AI content parsing.

## 🚧 Development Status

**Current Phase**: Active Development
**Version**: 0.1.0-beta
**Status**: Not yet production-ready

This project is currently in active development phase. Core features are implemented and tested, but the system has not gone live yet. We welcome contributions and feedback from developers interested in financial technology and AI applications.

## ✨ Features

- 🤖 **AI-Powered Content Extraction** - Uses OpenAI GPT to parse credit card data from PDFs, webpages, images, and CSV files
- 🕷️ **Automated Web Crawling** - Celery-based scheduled crawling system with intelligent retry logic
- 🔍 **Advanced Search & Filtering** - REST API with comprehensive filtering, searching, and comparison capabilities
- 📊 **Smart Data Management** - Automatic deduplication, error tracking, and data quality monitoring
- 🛡️ **Security First** - Built-in protection against SQL injection, XSS, and other vulnerabilities
- 📱 **API-First Design** - Comprehensive REST API with Django REST Framework
- ⚡ **High Performance** - Optimized queries, caching, and scalable architecture
- 🎯 **Advanced Filtering** - Filter by multiple IDs, bank IDs, and comprehensive search parameters
- ✉️ **Environment-Based Email** - Smart email configuration that disables email in development

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │   REST API      │    │   AI Parsing    │
│   (External)    │◄──►│   Django REST   │◄──►│   OpenAI GPT    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Web Crawler   │◄──►│   Database      │◄──►│   Admin Panel   │
│   Celery Tasks  │    │   PostgreSQL    │    │   Django Admin  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🆕 Recent Improvements

### API Enhancements
- **Enhanced Filtering**: Added `ids` and `bank_ids` filters for flexible credit card selection
- **Streamlined Endpoints**: Removed redundant endpoints in favor of comprehensive filtering
- **Comprehensive Documentation**: Added detailed API documentation for both Banks and Credit Cards APIs

### Developer Experience
- **Environment-Based Configuration**: Email service automatically disabled in development/staging
- **Security Updates**: Updated dependencies to address security vulnerabilities (Pillow 11.3.0, urllib3 2.5.0)
- **Git Workflow**: Improved development workflow with better commit practices

### Performance & Security
- **Rate Limiting**: API throttling implemented across all endpoints (1000/hour anonymous, 2000/hour authenticated)
- **CORS Configuration**: Environment-based Cross-Origin Resource Sharing setup
- **Docker Support**: Complete containerization with development and production configurations
- **Optimized Queries**: Enhanced database queries for better performance
- **Security Hardening**: Comprehensive security testing and vulnerability protection
- **Test Coverage**: Extensive test coverage including edge cases and security scenarios

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Redis (for Celery task queue)
- OpenAI API Key

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/avoid-ashraful/creditmate-ai-be.git
   cd creditmate-ai-be
   ```

2. **Install dependencies**
   ```bash
   # Install uv if not already installed
   pip install uv

   # Install project dependencies
   uv sync --dev

   # Activate virtual environment (if not already activated)
   source .venv/bin/activate
   ```

3. **Environment setup**
   ```bash
   # Copy environment template
   cp .env.example .env

   # Edit .env with your configuration
   export SECRET_KEY="your-super-secret-key"
   export OPENAI_API_KEY="your-openai-api-key"
   export DEBUG=True
   export ENVIRONMENT=local  # Email service disabled for development
   ```

4. **Database setup**
   ```bash
   # Run migrations
   uv run python manage.py migrate

   # Create superuser
   uv run python manage.py createsuperuser
   ```

5. **Start Redis (required for Celery)**
   ```bash
   # macOS
   brew install redis && brew services start redis

   # Ubuntu
   sudo apt-get install redis-server && sudo systemctl start redis
   ```

6. **Run the development server**
   ```bash
   # Terminal 1: Django development server
   uv run python manage.py runserver

   # Terminal 2: Celery worker (in another terminal)
   uv run celery -A credit_mate_ai worker --loglevel=info

   # Terminal 3: Celery beat scheduler (in another terminal)
   uv run celery -A credit_mate_ai beat --loglevel=info
   ```

7. **Access the application**
   - API: http://localhost:8000/api/v1/
   - Admin: http://localhost:8000/admin/
   - API Documentation: See detailed documentation links below

## 📖 API Documentation

### Quick Reference

| Resource | Endpoints | Documentation |
|----------|-----------|---------------|
| **Banks** | `/api/v1/banks/` | [Banks API Docs](./docs/api/banks.md) |
| **Credit Cards** | `/api/v1/credit-cards/` | [Credit Cards API Docs](./docs/api/credit-cards.md) |
| **Usage Examples** | All endpoints | [API Examples](./docs/api/examples.md) |

### Key Endpoints

```http
# Banks
GET    /api/v1/banks/                    # List all banks
GET    /api/v1/banks/{id}/               # Get bank details

# Credit Cards
GET    /api/v1/credit-cards/              # List all credit cards
GET    /api/v1/credit-cards/{id}/         # Get credit card details
GET    /api/v1/credit-cards/search-suggestions/ # Get search suggestions
```

### Essential Query Parameters

```http
# Filter by specific credit cards (for comparison)
?ids=1,2,3,4

# Filter by specific banks
?bank_ids=1,3,5

# Advanced filtering
?annual_fee=0&has_lounge_access=true&credit_score_required=Good

# Search functionality
?search=travel rewards cashback

# Sorting and pagination
?ordering=annual_fee,-interest_rate&page=2&page_size=20
```

### Quick Examples

```bash
# No annual fee cards
curl "http://localhost:8000/api/v1/credit-cards/?annual_fee=0"

# Compare specific cards
curl "http://localhost:8000/api/v1/credit-cards/?ids=1,2,3,4"

# Travel cards from major banks
curl "http://localhost:8000/api/v1/credit-cards/?search=travel&bank_ids=1,2,3"
```

**📋 For comprehensive examples and detailed documentation, see:**
- **[API Examples](./docs/api/examples.md)** - Complete usage guide with integration examples
- **[Banks API Documentation](./docs/api/banks.md)** - Detailed Banks API reference
- **[Credit Cards API Documentation](./docs/api/credit-cards.md)** - Complete Credit Cards API guide

## 🕷️ Web Crawling System

### How It Works

1. **Data Sources** - Configure URLs for each bank (PDFs, webpages, images, CSV)
2. **Scheduled Crawling** - Celery automatically crawls sources weekly
3. **Content Extraction** - Extract text from various file formats
4. **AI Parsing** - OpenAI GPT parses content into structured data
5. **Data Update** - Updates credit card database with new information

### Managing Data Sources

```bash
# Add data sources via Django Admin or management command
uv run python manage.py shell
>>> from banks.models import Bank, BankDataSource
>>> bank = Bank.objects.get(name="Chase")
>>> BankDataSource.objects.create(
...     bank=bank,
...     url="https://www.chase.com/credit-cards",
...     content_type="webpage",
...     description="Chase credit cards main page"
... )
```

### Manual Crawling

```bash
# Crawl all active sources
uv run python manage.py crawl_bank_data

# Crawl specific bank
uv run python manage.py crawl_bank_data --bank-id 1

# Crawl specific data source
uv run python manage.py crawl_bank_data --source-id 5

# Dry run (test without making changes)
uv run python manage.py crawl_bank_data --dry-run
```

## 🧪 Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=banks --cov=credit_cards --cov=common --cov-report=html

# Run specific test module
uv run pytest banks/tests/test_api.py

# Run Django tests
uv run python manage.py test
```

### Test Coverage

- **Models** - Comprehensive model validation and relationship testing
- **API** - Full REST API endpoint testing with security checks
- **Services** - Business logic and external service integration testing
- **Tasks** - Celery task execution and error handling testing
- **Integration** - End-to-end workflow testing

## 🔧 Configuration

### Environment Variables

```bash
# Environment Configuration (local/staging/production)
ENVIRONMENT=local                      # Email service disabled for non-production

# Core Django Settings
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (PostgreSQL in production)
DATABASE_URL=postgresql://user:pass@localhost:5432/creditmate

# OpenAI Integration
OPENAI_API_KEY=your-openai-api-key

# Celery & Redis
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Email Configuration (Production only)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@domain.com
EMAIL_HOST_PASSWORD=your-email-password

# CORS Configuration
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://yourdomain.com
CORS_ALLOW_CREDENTIALS=True

# API Rate Limiting
THROTTLE_RATE_ANON=1000/hour
THROTTLE_RATE_USER=2000/hour
THROTTLE_RATE_BURST=100/min

```

### Celery Configuration

Customize crawling schedule in `credit_mate_ai/celery.py`:

```python
app.conf.beat_schedule = {
    "crawl-bank-data-weekly": {
        "task": "banks.tasks.crawl_all_bank_data",
        "schedule": crontab(hour=2, minute=0, day_of_week=1),  # Monday 2 AM
    },
}
```

## 🚀 Deployment

### Production Setup

1. **Use PostgreSQL instead of SQLite**
2. **Configure proper Redis instance**
3. **Set up reverse proxy (Nginx)**
4. **Use environment variables for secrets**
5. **Configure logging and monitoring**

### Docker Deployment

```bash
# Build and run with Docker Compose
docker-compose up -d

# Run migrations
docker-compose exec web python manage.py migrate

# Create superuser
docker-compose exec web python manage.py createsuperuser
```

### Recommended Production Stack

- **Web Server**: Nginx + Gunicorn
- **Database**: PostgreSQL
- **Cache/Queue**: Redis
- **Process Manager**: Supervisor or systemd

## 🛡️ Security Features

- **SQL Injection Protection** - Parameterized queries and ORM usage
- **XSS Prevention** - Content sanitization and proper escaping
- **CSRF Protection** - Django's built-in CSRF middleware
- **CORS Security** - Configurable Cross-Origin Resource Sharing with environment variables
- **Rate Limiting** - API throttling and abuse prevention (1000/hour anonymous, 2000/hour authenticated)
- **Input Validation** - Comprehensive data validation
- **Secure Headers** - Security headers for all responses

## 📊 Monitoring & Maintenance

### Health Checks

```bash
# Check system health
uv run python manage.py check

# Check database connectivity
uv run python manage.py dbshell

# Monitor Celery workers
uv run celery -A credit_mate_ai inspect active
```

### Maintenance Tasks

```bash
# Crawl bank data manually
uv run python manage.py crawl_bank_data

# Crawl specific bank
uv run python manage.py crawl_bank_data --bank-id 1

# View available management commands
uv run python manage.py help
```

## 🤝 Contributing

We welcome contributions! Please see our [Implementation Summary](./docs/development/implementation-summary.md) and [Crawler Guide](./docs/development/crawler-system.md) for technical details.

### Development Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`uv run pytest`)
5. Run code quality checks (`black . && flake8 && isort .`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

### Code Quality

We maintain high code quality standards:

- **Code Formatting**: Black
- **Linting**: Flake8
- **Import Sorting**: isort
- **Test Coverage**: Minimum 90%

## 📚 Documentation

**📋 [Complete Documentation Index](./docs/README.md)**

### API Documentation
- **[API Examples](./docs/api/examples.md)** - Comprehensive API usage guide with integration examples
- **[Banks API Reference](./docs/api/banks.md)** - Complete Banks API documentation
- **[Credit Cards API Reference](./docs/api/credit-cards.md)** - Detailed Credit Cards API guide

### Configuration & Setup
- **[Environment Variables](./docs/configuration/environment-variables.md)** - Complete configuration reference
- **[Email Configuration](./docs/configuration/email.md)** - Environment-based email setup
- **[CORS & Rate Limiting](./docs/configuration/cors-and-rate-limiting.md)** - Security configuration for APIs

### Development & Architecture
- **[Setup & Guidelines](./docs/development/setup-and-guidelines.md)** - Development environment and coding standards
- **[Crawler System](./docs/development/crawler-system.md)** - AI-powered web crawling system
- **[Implementation Summary](./docs/development/implementation-summary.md)** - Technical implementation details
- **[Project Guidelines](./CLAUDE.md)** - Claude development instructions

## 🐛 Troubleshooting

### Common Issues

1. **Celery tasks not running**
   - Check Redis connection: `redis-cli ping`
   - Verify worker is running: `uv run celery -A credit_mate_ai inspect active`

2. **OpenAI API errors**
   - Verify API key is set: `echo $OPENAI_API_KEY`
   - Check API usage limits on OpenAI dashboard

3. **Database connection errors**
   - Ensure database is running
   - Check connection settings in `.env`

## 📄 License

This project is licensed under the MIT License.

## 🙏 Acknowledgments

- **Django** - The web framework for perfectionists with deadlines
- **OpenAI** - AI-powered content parsing capabilities
- **Celery** - Distributed task queue system
- **Django REST Framework** - Powerful and flexible toolkit for building Web APIs
- **Redis** - In-memory data structure store for caching and task queuing

---

<div align="center">
  <p>Built with ❤️ by the CreditMate AI Team</p>
  <p>
  </p>
</div>
