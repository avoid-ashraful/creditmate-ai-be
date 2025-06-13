# 💳 CreditMate AI

[![Tests](https://github.com/username/creditmate-ai-be/workflows/Tests/badge.svg)](https://github.com/username/creditmate-ai-be/actions)
[![Code Quality](https://github.com/username/creditmate-ai-be/workflows/Code%20Quality/badge.svg)](https://github.com/username/creditmate-ai-be/actions)
[![codecov](https://codecov.io/gh/username/creditmate-ai-be/branch/master/graph/badge.svg)](https://codecov.io/gh/username/creditmate-ai-be)

> 🚀 **AI-Powered Credit Card Discovery Platform** - Automatically crawl, analyze, and compare credit cards from banks across the web using advanced AI content parsing.

## ✨ Features

- 🤖 **AI-Powered Content Extraction** - Uses OpenAI GPT to parse credit card data from PDFs, webpages, images, and CSV files
- 🕷️ **Automated Web Crawling** - Celery-based scheduled crawling system with intelligent retry logic
- 🔍 **Advanced Search & Filtering** - REST API with comprehensive filtering, searching, and comparison capabilities
- 📊 **Smart Data Management** - Automatic deduplication, error tracking, and data quality monitoring
- 🛡️ **Security First** - Built-in protection against SQL injection, XSS, and other vulnerabilities
- 📱 **API-First Design** - Comprehensive REST API with Django REST Framework
- ⚡ **High Performance** - Optimized queries, caching, and scalable architecture

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

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Redis (for Celery task queue)
- OpenAI API Key

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/username/creditmate-ai-be.git
   cd creditmate-ai-be
   ```

2. **Install dependencies**
   ```bash
   # Install pipenv if not already installed
   pip install pipenv

   # Install project dependencies
   pipenv install --dev

   # Activate virtual environment
   pipenv shell
   ```

3. **Environment setup**
   ```bash
   # Copy environment template
   cp .env.example .env

   # Edit .env with your configuration
   export SECRET_KEY="your-super-secret-key"
   export OPENAI_API_KEY="your-openai-api-key"
   export DEBUG=True
   ```

4. **Database setup**
   ```bash
   # Run migrations
   python manage.py migrate

   # Create superuser
   python manage.py createsuperuser

   # Load sample data (optional)
   python manage.py loaddata fixtures/sample_data.json
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
   python manage.py runserver

   # Terminal 2: Celery worker (in another terminal)
   celery -A credit_mate_ai worker --loglevel=info

   # Terminal 3: Celery beat scheduler (in another terminal)
   celery -A credit_mate_ai beat --loglevel=info
   ```

7. **Access the application**
   - API: http://localhost:8000/api/v1/
   - Admin: http://localhost:8000/admin/
   - API Documentation: http://localhost:8000/api/v1/docs/

## 📖 API Documentation

### Banks Endpoints

```http
GET    /api/v1/banks/                    # List all banks
GET    /api/v1/banks/{id}/               # Get bank details
GET    /api/v1/banks/{id}/credit-cards/  # Get bank's credit cards
```

### Credit Cards Endpoints

```http
GET    /api/v1/credit-cards/              # List all credit cards
GET    /api/v1/credit-cards/{id}/         # Get credit card details
POST   /api/v1/credit-cards/compare/      # Compare multiple cards
GET    /api/v1/credit-cards/featured/     # Get featured cards
GET    /api/v1/credit-cards/no-annual-fee/ # Get cards with no annual fee
GET    /api/v1/credit-cards/premium/      # Get premium cards
GET    /api/v1/credit-cards/search-suggestions/ # Get search suggestions
```

### Query Parameters

```http
# Filtering
?bank=chase&has_lounge_access=true&annual_fee_max=200

# Searching
?search=travel rewards cashback

# Ordering
?ordering=annual_fee,-interest_rate

# Pagination
?page=2&page_size=20
```

### Example API Usage

```bash
# Get all Chase credit cards with no annual fee
curl "http://localhost:8000/api/v1/credit-cards/?bank__name=Chase&annual_fee=0"

# Compare two credit cards
curl -X POST "http://localhost:8000/api/v1/credit-cards/compare/" \
  -H "Content-Type: application/json" \
  -d '{"card_ids": [1, 2]}'

# Search for travel rewards cards
curl "http://localhost:8000/api/v1/credit-cards/?search=travel+rewards"
```

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
python manage.py shell
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
python manage.py crawl_bank_data

# Crawl specific bank
python manage.py crawl_bank_data --bank-id 1

# Crawl specific data source
python manage.py crawl_bank_data --source-id 5

# Dry run (test without making changes)
python manage.py crawl_bank_data --dry-run
```

## 🧪 Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=banks --cov=credit_cards --cov=common --cov-report=html

# Run specific test module
pytest banks/tests/test_api.py

# Run Django tests
python manage.py test
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

# Security
CORS_ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
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
- **Monitoring**: Sentry + Prometheus
- **Deployment**: Docker + Kubernetes

## 🛡️ Security Features

- **SQL Injection Protection** - Parameterized queries and ORM usage
- **XSS Prevention** - Content sanitization and proper escaping
- **CSRF Protection** - Django's built-in CSRF middleware
- **Rate Limiting** - API throttling and abuse prevention
- **Input Validation** - Comprehensive data validation
- **Secure Headers** - Security headers for all responses

## 📊 Monitoring & Maintenance

### Health Checks

```bash
# Check system health
python manage.py check

# Check database connectivity
python manage.py dbshell

# Monitor Celery workers
celery -A credit_mate_ai inspect active
```

### Maintenance Tasks

```bash
# Clean up old crawled content
python manage.py cleanup_old_content --days 30

# Reset failed data sources
python manage.py reset_failed_sources

# Generate performance reports
python manage.py performance_report
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](./documents/CONTRIBUTING.md) for details.

### Development Workflow

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`pytest`)
5. Run code quality checks (`black . && flake8 && isort .`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

### Code Quality

We maintain high code quality standards:

- **Code Formatting**: Black
- **Linting**: Flake8
- **Import Sorting**: isort
- **Type Hints**: MyPy (optional but encouraged)
- **Test Coverage**: Minimum 90%

## 📚 Documentation

- [API Documentation](./documents/API.md)
- [Crawler System Guide](./documents/CRAWLER_README.md)
- [Implementation Details](./documents/IMPLEMENTATION_SUMMARY.md)
- [Deployment Guide](./documents/DEPLOYMENT.md)
- [Contributing Guide](./documents/CONTRIBUTING.md)

## 🐛 Troubleshooting

### Common Issues

1. **Celery tasks not running**
   - Check Redis connection: `redis-cli ping`
   - Verify worker is running: `celery -A credit_mate_ai inspect active`

2. **OpenAI API errors**
   - Verify API key is set: `echo $OPENAI_API_KEY`
   - Check API usage limits on OpenAI dashboard

3. **Database connection errors**
   - Ensure database is running
   - Check connection settings in `.env`

### Getting Help

- 📧 **Email**: support@creditmate.ai
- 💬 **Issues**: [GitHub Issues](https://github.com/username/creditmate-ai-be/issues)
- 📖 **Wiki**: [Project Wiki](https://github.com/username/creditmate-ai-be/wiki)
- 💡 **Discussions**: [GitHub Discussions](https://github.com/username/creditmate-ai-be/discussions)

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

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
    <a href="https://github.com/username/creditmate-ai-be">⭐ Star us on GitHub</a> •
    <a href="https://twitter.com/creditmate_ai">🐦 Follow on Twitter</a> •
    <a href="https://creditmate.ai">🌐 Visit our Website</a>
  </p>
</div>
