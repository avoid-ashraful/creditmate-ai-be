# Development Setup and Guidelines

This document provides comprehensive setup instructions and development guidelines for Credit Mate AI.

## Quick Start Development Setup

### Prerequisites
- Python 3.12+
- Redis (for Celery task queue)
- OpenAI API Key
- Git

### 1. Clone and Setup
```bash
# Clone repository
git clone https://github.com/avoid-ashraful/creditmate-ai-be.git
cd creditmate-ai-be

# Install pipenv if not already installed
pip install pipenv

# Install dependencies
pipenv install --dev

# Activate virtual environment
pipenv shell
```

### 2. Environment Configuration
```bash
# Copy environment template
cp .env.example .env

# Edit .env with your configuration
# Minimum required:
export SECRET_KEY="your-super-secret-key"
export OPENAI_API_KEY="your-openai-api-key"
export DEBUG=True
export ENVIRONMENT=local
```

### 3. Database Setup
```bash
# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

### 4. Start Services
```bash
# Terminal 1: Django development server
python manage.py runserver

# Terminal 2: Celery worker
celery -A credit_mate_ai worker --loglevel=info

# Terminal 3: Celery beat scheduler
celery -A credit_mate_ai beat --loglevel=info
```

### 5. Access Application
- API: http://localhost:8000/api/v1/
- Admin: http://localhost:8000/admin/
- API Documentation: See [API docs](../api/)

## Docker Development Setup

### Using Docker Compose (Recommended)
```bash
# Development with Docker
docker-compose -f docker-compose.dev.yml up

# Run migrations in container
docker-compose -f docker-compose.dev.yml exec web python manage.py migrate

# Create superuser in container
docker-compose -f docker-compose.dev.yml exec web python manage.py createsuperuser
```

## Development Guidelines

### Code Style and Quality

#### Code Formatting
```bash
# Format code with Black
black .

# Sort imports with isort
isort .

# Lint code with Flake8
flake8
```

#### Pre-commit Hooks
```bash
# Install pre-commit hooks
pre-commit install

# Run pre-commit on all files
pre-commit run --all-files
```

### Testing

#### Running Tests
```bash
# Run all tests with pytest
pytest

# Run with coverage
pytest --cov=banks --cov=credit_cards --cov=common --cov-report=html

# Run specific test module
pytest banks/tests/test_api.py

# Run Django tests
python manage.py test
```

#### Test Coverage Standards
- Minimum 90% test coverage required
- All new features must include tests
- API endpoints must have comprehensive test coverage
- Edge cases and error scenarios must be tested

### Development Workflow

#### Branch Strategy
```bash
# Create feature branch
git checkout -b feature/amazing-feature

# Make changes and commit
git add .
git commit -m "Add amazing feature"

# Push to branch
git push origin feature/amazing-feature

# Open Pull Request
```

#### Commit Guidelines
- Use clear, descriptive commit messages
- Follow conventional commit format when possible
- Keep commits focused and atomic
- Include tests with feature commits

### API Development

#### Adding New Endpoints
1. **Create serializers** in `api/serializers.py`
2. **Add filters** in `api/filters.py`
3. **Implement views** in `api/views.py`
4. **Configure URLs** in `api/urls.py`
5. **Write tests** in `tests/test_api.py`
6. **Update documentation** in `docs/api/`

#### Rate Limiting
All endpoints automatically have rate limiting applied:
- Anonymous: 1000/hour
- Authenticated: 2000/hour
- Burst: 100/min

For custom rate limiting, implement custom throttle classes.

#### CORS Configuration
Development CORS is configured for common frontend ports:
- http://localhost:3000
- http://127.0.0.1:3000

To add more origins, update `CORS_ALLOWED_ORIGINS` in `.env`.

### Database Development

#### Migrations
```bash
# Create migrations for model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Check migration status
python manage.py showmigrations
```

#### Model Guidelines
- Use descriptive field names
- Add help_text for complex fields
- Include proper validation
- Use appropriate field types
- Add indexes for frequently queried fields

### Celery Development

#### Task Development
```bash
# Test tasks manually
python manage.py shell
>>> from banks.tasks import crawl_bank_data_source
>>> crawl_bank_data_source.delay(source_id=1)
```

#### Monitoring Tasks
```bash
# Check active tasks
celery -A credit_mate_ai inspect active

# Check scheduled tasks
celery -A credit_mate_ai inspect scheduled

# Monitor task execution
celery -A credit_mate_ai events
```

### AI Content Processing

#### Testing OpenAI Integration
```bash
# Test content extraction
python manage.py shell
>>> from banks.services import ContentExtractor
>>> extractor = ContentExtractor()
>>> content = extractor.extract_from_url("https://example.com")
```

#### LLM Testing
- Test with various content types (PDF, webpage, CSV)
- Verify structured data output
- Handle API errors gracefully
- Monitor token usage

### Project Structure

```
credit-mate-ai/
├── banks/                  # Bank data and crawling
│   ├── api/               # REST API (views, serializers, filters)
│   ├── management/        # Django management commands
│   ├── tests/            # Test files
│   ├── models.py         # Data models
│   ├── services.py       # Business logic
│   └── tasks.py          # Celery tasks
├── credit_cards/          # Credit card models and API
│   ├── api/              # REST API
│   ├── tests/            # Test files
│   └── models.py         # Credit card models
├── common/                # Shared utilities
├── credit_mate_ai/        # Django project settings
├── docs/                  # Documentation
│   ├── api/              # API documentation
│   ├── configuration/    # Configuration guides
│   └── development/      # Development docs
└── requirements files     # Pipfile, Pipfile.lock
```

### Essential Commands Reference

#### Development Commands
```bash
# Start development server
python manage.py runserver

# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Django shell
python manage.py shell

# Check project configuration
python manage.py check
```

#### Celery Commands
```bash
# Start worker
celery -A credit_mate_ai worker --loglevel=info

# Start beat scheduler
celery -A credit_mate_ai beat --loglevel=info

# Monitor tasks
celery -A credit_mate_ai inspect active

# Purge all tasks
celery -A credit_mate_ai purge
```

#### Crawling Commands
```bash
# Crawl all data sources
python manage.py crawl_bank_data

# Crawl specific bank
python manage.py crawl_bank_data --bank-id 1

# Dry run
python manage.py crawl_bank_data --dry-run
```

### Troubleshooting

#### Common Development Issues

##### Redis Connection Issues
```bash
# Check Redis is running
redis-cli ping

# Start Redis (macOS)
brew services start redis

# Start Redis (Ubuntu)
sudo systemctl start redis
```

##### Database Issues
```bash
# Reset database
rm db.sqlite3
python manage.py migrate
python manage.py createsuperuser
```

##### Import Errors
```bash
# Check Python path
python -c "import sys; print('\n'.join(sys.path))"

# Reinstall dependencies
pipenv install --dev
```

##### OpenAI API Issues
```bash
# Verify API key
echo $OPENAI_API_KEY

# Test API connection
python -c "import openai; print('API key is valid')"
```

### Performance Guidelines

#### Database Optimization
- Use `select_related()` for foreign keys
- Use `prefetch_related()` for many-to-many relationships
- Add database indexes for frequently queried fields
- Use `only()` and `defer()` for large models

#### API Optimization
- Implement proper pagination
- Use appropriate serializer fields
- Cache expensive operations
- Monitor API response times

#### Celery Optimization
- Keep tasks idempotent
- Use appropriate task routing
- Monitor memory usage
- Implement proper error handling

For detailed guides on specific topics, see:
- [Crawler System](./crawler-system.md)
- [Implementation Summary](./implementation-summary.md)
- [Project Guidelines (CLAUDE.md)](../../CLAUDE.md)
