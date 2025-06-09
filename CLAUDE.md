# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Credit Mate AI is a financial management application built with Django. The platform provides AI-powered credit analysis, financial planning tools, and personalized recommendations for users to improve their credit scores and financial health.

## Development Commands

### Environment Setup
```bash
# Setup environment
pipenv install --dev
pipenv shell

# Copy environment configuration
cp .env.example .env
# Edit .env file with your configuration values

# Run Django commands
python manage.py migrate
python manage.py runserver
python manage.py shell
python manage.py test
```

### Package Management
```bash
# Install new packages with specific versions (recommended)
pipenv install django~=5.2.3

# Install development packages
pipenv install --dev pytest~=8.4.0

# Update Pipfile.lock after changes
pipenv lock

# Check for security vulnerabilities
pipenv check
```

### Testing
```bash
# Run all tests with Django test runner
python manage.py test

# Run all tests with pytest (recommended)
pytest

# Run specific app tests
python manage.py test app_name
pytest app_name/

# Run single test case
python manage.py test app.tests.TestClass.test_method
pytest app_name/tests/test_file.py::TestClass::test_method

# Run with verbose output
pytest -v
```

### Code Quality
```bash
# Run pre-commit hooks (linting, formatting, security)
pre-commit run --all-files

# Format code (Black with 90 char line length)
black .

# Lint code
flake8

# Import sorting
isort
```

## Architecture Overview

### Core Design Patterns
- **Modular Django Apps**: Apps organized by business domain
- **Service/Selector Pattern**: Business logic separated into services (writes) and selectors (reads)
- **API-First Design**: RESTful APIs with Django REST Framework
- **Domain-Driven Design**: Apps organized around business domains rather than technical layers

### Database Architecture
- **SQLite** for development (simple file-based database)
- **Audit trails** with comprehensive change tracking
- **Data validation** at model and API levels

### Key Technology Stack
- **Django** with Django REST Framework
- **SQLite** as development database
- **Python 3.11+**


## Django Development Guidelines

### Model Organization
Follow this order for model classes:
1. Database fields
2. Custom manager attributes
3. `class Meta`
4. `def __str__()`
5. `def save()`
6. Cached properties (`@cached_property`)
7. Plain properties (`@property`)
8. Public methods
9. Class methods
10. Private methods

### Business Logic Separation
- **Services** (`services.py`): Handle writes, complex business logic, external API calls
- **Selectors** (`selectors.py`): Handle reads, data fetching, filtering logic
- **Querysets** (`querysets.py`): Database-level query abstractions
- Keep business logic OUT of views and models

### Model Patterns
- Add timestamp fields for created/modified tracking
- Use logical deletion patterns when needed
- Enum fields should use Django's `TextChoices`/`IntegerChoices`

### API Design
- Use specific viewsets (not always `ModelViewSet`)
- Version APIs consistently (`/api/v1/`)
- Keep serializers to max 2 levels of nesting
- Avoid passing context to serializers when possible

### Query Optimization
- Always use `select_related()` for foreign keys
- Use `prefetch_related()` for many-to-many and reverse foreign keys
- Abstract complex queries into QuerySet methods

### Testing Standards
- **Pytest is preferred** over Django's built-in TestCase
- Use pytest classes with `setup_method()` for test initialization
- The `setup_method()` is automatically called via global autouse fixture in `conftest.py`
- Mock external services for unit tests
- Use `APITestCase` for API testing when needed
- Test authentication and permissions thoroughly

### Pytest Configuration
- **Auto-setup**: `setup_method()` is automatically called for all test classes (no need for `@pytest.fixture(autouse=True)`)
- **Database access**: Use `@pytest.mark.django_db` decorator for tests that need database
- **Parametrized tests**: Use `@pytest.mark.parametrize` for testing multiple scenarios
- **Fixtures**: Global fixtures available in `conftest.py` (api_client, authed_api_client)

### File Naming Conventions
- `CharField` fields: default="", blank=True
- `DateField` fields: suffix with `_date`
- `TimeField` fields: suffix with `_time`
- `DateTimeField` fields: suffix with `_datetime`
- Foreign key serializer fields: suffix with `_id`

### App Structure
```
app_name/
├── api/
│   ├── serializers.py
│   ├── views.py
│   └── urls.py
├── tests/
│   ├── test_apis/
│   └── test_models/
├── models.py
├── services.py
├── selectors.py
├── admin.py
├── enums.py
└── constants.py
```

## Git Workflow

### Branch Naming
- Features: `feat-description`
- Bugs: `bug-description`
- Enhancements: `enh-description`

### Commit Messages
- Be descriptive and concise
- Max 72 characters for title

## Common Development Tasks

### Adding New Models
1. Create model in appropriate app's `models.py`
2. Add timestamp fields for tracking
3. Add to `admin.py` if admin interface needed
4. Create migration: `python manage.py makemigrations`
5. Run migration: `python manage.py migrate`

### Adding API Endpoints
1. Create serializer in `api/serializers.py`
2. Create view in `api/views.py`
3. Add URL route in `api/urls.py`
4. Add business logic to `services.py` or `selectors.py`
5. Write tests in `tests/test_apis/`

## Performance Considerations

- Use database indexing for frequently queried fields
- Implement caching for expensive operations
- Use `@cache_page` decorator for cacheable endpoints
- Monitor query performance and optimize as needed

## Environment Configuration

### Setup
1. Copy `.env.example` to `.env`: `cp .env.example .env`
2. Update `.env` with your configuration values
3. Install python-dotenv: `pipenv install python-dotenv` (optional, gracefully handled if missing)

### Available Environment Variables
- **SECRET_KEY**: Django secret key for cryptographic signing
- **DEBUG**: Enable/disable debug mode (True/False)
- **ALLOWED_HOSTS**: Comma-separated list of allowed host/domain names
- **OPENAI_API_KEY**: OpenAI API key for LLM-powered content parsing
- **DB_ENGINE**, **DB_NAME**, **DB_USER**, etc.: Database configuration
- **CELERY_BROKER_URL**: Redis URL for Celery task queue
- **EMAIL_HOST**, **EMAIL_PORT**, etc.: Email configuration

### Development vs Production
- Development: Use `.env` file with default SQLite database
- Production: Set environment variables directly with proper database (PostgreSQL/MySQL)

## Dependency Management Best Practices

### Package Versioning
- **Use specific versions** instead of `*` in `Pipfile` (e.g., `django = "~=5.2.3"`)
- **Compatible release operator `~=`**: Allows patch-level updates but prevents breaking changes
- **Example**: `django = "~=5.2.3"` allows `5.2.4`, `5.2.5` but not `5.3.0`

### Version Pinning Strategy
- **Production packages**: Use `~=` for stable compatibility with security updates
- **Development packages**: Use `~=` for consistent development environment
- **Security critical packages**: Pin exact versions if needed with `==`

### Maintenance
- **Regular updates**: `pipenv update` to get latest compatible versions
- **Security scanning**: `pipenv check` to identify vulnerabilities
- **Lock file**: Always commit `Pipfile.lock` for reproducible builds

## Security Guidelines

- Never commit secrets or API keys (`.env` is gitignored)
- Use Django's built-in permission system
- Validate all user inputs
- Use parameterized queries (Django ORM handles this)
- Implement proper authentication on all endpoints
- Use HTTPS in production environments
