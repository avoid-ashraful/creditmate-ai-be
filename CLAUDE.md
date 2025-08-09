# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Environment

This is a Django-based AI-powered credit card discovery platform using Python 3.12, pipenv for dependency management, PostgreSQL 17 as the database, and Celery for background tasks.

**Required services:**
- PostgreSQL 17 (primary database)
- Redis (for Celery task queue)
- OpenAI API key for AI content parsing

## Essential Commands

### Environment Setup
```bash
# Install dependencies
pipenv install --dev

# Activate virtual environment
pipenv shell

# Database migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser
```

### Development Server
```bash
# Django development server
python manage.py runserver

# Celery worker (separate terminal)
celery -A credit_mate_ai worker --loglevel=info

# Celery beat scheduler (separate terminal)
celery -A credit_mate_ai beat --loglevel=info
```

### Testing
```bash
# Run all tests with pytest
pytest

# Run with coverage
pytest --cov=banks --cov=credit_cards --cov=common --cov-report=html

# Run Django tests
python manage.py test
```

### Code Quality
```bash
# Format code
black .

# Check imports
isort .

# Lint code
flake8
```

### Web Crawling
```bash
# Manual crawl all sources
python manage.py crawl_bank_data

# Crawl specific bank
python manage.py crawl_bank_data --bank-id 1

# Dry run
python manage.py crawl_bank_data --dry-run
```

## Architecture Overview

The application follows a Django REST API architecture with three main apps:

1. **banks** - Bank entities and data source management
   - Models: `Bank`, `BankDataSource`, `CrawledContent`
   - Services: Content extraction, LLM parsing, crawling orchestration
   - Background tasks for automated crawling

2. **credit_cards** - Credit card product management
   - Models: `CreditCard` with detailed financial attributes
   - REST API endpoints for search, filtering, comparison

3. **common** - Shared utilities and base models
   - Audit mixin for timestamp tracking

## Key Components

### AI Content Processing Pipeline
Located in `banks/services.py`:
- `ContentExtractor` - Extracts text from PDFs, webpages, images, CSV files
- `LLMContentParser` - Uses OpenAI GPT to parse content into structured data
- `CreditCardDataService` - Updates database with parsed credit card information
- `BankDataCrawlerService` - Orchestrates the entire crawling process

### Background Tasks
Celery tasks in `banks/tasks.py` handle:
- Scheduled weekly crawling of all data sources
- Individual data source processing
- Error handling and retry logic

### API Structure
REST endpoints follow `/api/v1/` pattern:
- Banks: `/api/v1/banks/`
- Credit cards: `/api/v1/credit-cards/`
- Comprehensive filtering, search, and comparison features

## Data Flow

1. **Data Sources** - URLs configured for each bank (PDFs, webpages, images, CSV)
2. **Content Extraction** - Extract text from various file formats
3. **AI Parsing** - OpenAI GPT converts unstructured text to structured JSON
4. **Database Update** - Credit card records created/updated with parsed data
5. **API Access** - REST endpoints serve processed data with advanced filtering

## Environment Variables

Required configuration in `.env`:
- `SECRET_KEY` - Django secret key
- `DATABASE_URL` - PostgreSQL 17 connection string
- `OPENAI_API_KEY` - For AI content parsing
- `CELERY_BROKER_URL` - Redis URL for task queue
- `DEBUG` - Development mode flag

## Testing Strategy

- **Models** - Validation and relationship testing
- **API** - REST endpoint testing with security checks
- **Services** - Business logic and external integration testing
- **Tasks** - Celery task execution testing
- **Integration** - End-to-end workflow testing

Test configuration uses pytest with Django integration, socket blocking for external calls, and comprehensive coverage reporting.

## Code Documentation Standards

All functions and methods follow **numpy-style docstring format** for consistency and automatic documentation generation:

```python
def extract_content(self, url, content_type):
    """Extract content from URL based on content type.

    Parameters
    ----------
    url : str
        The URL to extract content from
    content_type : str
        The type of content to extract (PDF, WEBPAGE, IMAGE, CSV)

    Returns
    -------
    tuple of (str, str)
        First element is raw content, second is extracted text content

    Raises
    ------
    NetworkError
        For network-related connection or timeout errors
    ContentExtractionError
        For HTTP errors or general extraction failures
    """
```

## Function and Method Naming Standards

All functions and methods follow these conventions:
- Use descriptive names that clearly indicate the function's purpose
- Avoid type hints in function signatures (use docstrings for type information)
- Use numpy-style docstrings for all public methods and functions
- Private methods (prefixed with `_`) should also include docstrings for complex logic

### Example Refactored Method:
```python
# Before refactoring
def _record_no_changes(self, data_source: BankDataSource, content_hash: str) -> None:
    """Record that content hasn't changed."""
    pass

# After refactoring
def _record_no_changes(self, data_source, content_hash):
    """Record that content hasn't changed.

    Parameters
    ----------
    data_source : BankDataSource
        The data source being processed
    content_hash : str
        SHA256 hash of the content for change detection

    Returns
    -------
    None
    """
    pass
```

## Git Workflow Instructions

**IMPORTANT**: Do not automatically create git commits unless explicitly requested by the user. Only commit when the user specifically asks for commits to be made.

**Code Standards**: All functions and methods must use numpy-style docstrings without type hints in signatures.
