# Bank Data Crawler System

This document describes the bank data crawler system that automatically fetches and updates credit card information from various bank sources using AI-powered content parsing.

## Overview

The crawler system consists of several components:

1. **BankDataSource Model**: Stores URLs and metadata for bank data sources
2. **CrawledContent Model**: Stores extracted and parsed content from crawls
3. **Crawler Services**: Extract content from various file types (PDF, webpage, image, CSV)
4. **LLM Parser**: Uses OpenAI GPT to parse extracted content into structured data
5. **Celery Tasks**: Automated crawling tasks that run on a schedule
6. **Management Commands**: Manual crawling tools for testing and troubleshooting

## Models

### BankDataSource
- Stores URLs to crawl for each bank
- Tracks content type (PDF, webpage, image, CSV)
- Manages failed attempt counts and active status
- Automatically deactivates sources after 5 failed attempts

### CrawledContent
- Stores raw content, extracted text, and parsed JSON
- Links to the data source and optionally to specific credit cards
- Tracks processing status and error messages

## Usage

### Setting up Data Sources

1. Go to Django Admin → Bank Data Sources
2. Add URLs for each bank with appropriate content types
3. Set descriptions to help identify what each URL contains

### Manual Crawling

Use the management command to test crawling:

```bash
# Crawl all active data sources
python manage.py crawl_bank_data

# Crawl specific bank
python manage.py crawl_bank_data --bank-id 1

# Crawl specific data source
python manage.py crawl_bank_data --source-id 5

# Dry run to see what would be crawled
python manage.py crawl_bank_data --dry-run
```

### Automated Crawling

The system uses Celery for automated crawling:

1. **Install Redis** (required for Celery broker):
   ```bash
   brew install redis  # macOS
   sudo apt-get install redis-server  # Ubuntu
   ```

2. **Install Python dependencies**:
   ```bash
   pipenv install
   ```

3. **Start Redis**:
   ```bash
   redis-server
   ```

4. **Start Celery Worker**:
   ```bash
   celery -A credit_mate_ai worker --loglevel=info
   ```

5. **Start Celery Beat** (for scheduled tasks):
   ```bash
   celery -A credit_mate_ai beat --loglevel=info
   ```

### Configuration

#### OpenAI API Key
Set your OpenAI API key in environment variables or Django settings:

```bash
export OPENAI_API_KEY="your-api-key-here"
```

Or add to `settings.py`:
```python
OPENAI_API_KEY = "your-api-key-here"
```

#### Celery Settings
The system is configured to run weekly crawls. You can modify the schedule in `credit_mate_ai/celery.py`:

```python
app.conf.beat_schedule = {
    "crawl-bank-data-weekly": {
        "task": "banks.tasks.crawl_all_bank_data",
        "schedule": 604800.0,  # 7 days in seconds
    },
}
```

## Celery Tasks

### Available Tasks

1. **crawl_bank_data_source(data_source_id)**: Crawl a single data source
2. **crawl_all_bank_data()**: Crawl all active data sources (scheduled weekly)
3. **crawl_bank_data_sources_by_bank(bank_id)**: Crawl all sources for a bank
4. **cleanup_old_crawled_content(days_to_keep=30)**: Clean up old crawled content

### Manual Task Execution

You can also trigger tasks manually from Django shell:

```python
from banks.tasks import crawl_bank_data_source, crawl_all_bank_data

# Trigger single source crawl
crawl_bank_data_source.delay(1)

# Trigger full crawl
crawl_all_bank_data.delay()
```

## Content Extraction

The system can extract content from various file types:

### PDF Files
Uses PyPDF2 to extract text content from PDF documents.

### Web Pages
Uses BeautifulSoup to extract clean text content from HTML pages.

### Images
Uses Tesseract OCR (pytesseract) to extract text from images.

### CSV Files
Uses pandas to read and convert CSV data to text format.

## AI Parsing

The system uses OpenAI GPT-3.5-turbo to parse extracted content into structured credit card data. The LLM is prompted to extract:

- Credit card name
- Annual fee
- Interest rate (APR)
- Lounge access details
- Fees information
- Reward points policy
- Additional features

## Error Handling

### Failed Attempts
- Each data source tracks failed crawl attempts
- After 5 failed attempts, the source is automatically deactivated
- Failed attempts are reset after a successful crawl

### Retry Logic
- Celery tasks include retry logic with exponential backoff
- Network errors and temporary failures are retried automatically

### Error Monitoring
- All errors are logged and stored in CrawledContent records
- Admin interface provides visibility into failures
- Email notifications can be configured for persistent failures

## Admin Interface

The Django admin provides management interfaces for:

### Banks
- View bank information and metadata
- See count of credit cards and data sources

### Bank Data Sources
- Manage URLs and content types
- Monitor crawl status and failed attempts
- Bulk actions for resetting failures and activating/deactivating sources

### Crawled Content
- View raw and extracted content
- Monitor parsing results and errors
- Browse historical crawl data

## Testing

The system includes comprehensive tests:

```bash
# Run all crawler tests
python manage.py test banks.tests.test_services
python manage.py test banks.tests.test_tasks
python manage.py test banks.tests.test_models

# Run with coverage
pytest --cov=banks
```

## Monitoring and Maintenance

### Regular Tasks
1. Monitor failed data sources and fix broken URLs
2. Review parsing results and adjust LLM prompts if needed
3. Clean up old crawled content periodically
4. Update data sources as banks change their websites

### Performance Optimization
1. Use database indexes on frequently queried fields
2. Implement caching for expensive operations
3. Monitor Celery queue sizes and worker performance
4. Optimize LLM token usage to reduce costs

## Security Considerations

1. **API Keys**: Never commit OpenAI API keys to version control
2. **URL Validation**: All URLs are validated before crawling
3. **Content Filtering**: Implement content filtering to avoid malicious data
4. **Rate Limiting**: Respect website rate limits and robots.txt
5. **Data Privacy**: Ensure crawled data complies with privacy regulations

## Troubleshooting

### Common Issues

1. **Celery tasks not running**: Check Redis connection and Celery worker status
2. **Content extraction failures**: Verify URL accessibility and content type
3. **LLM parsing errors**: Check OpenAI API key and rate limits
4. **Database errors**: Ensure migrations are applied

### Debugging

1. Check Django logs for detailed error information
2. Use `--dry-run` flag to test crawling without side effects
3. Monitor Celery logs for task execution details
4. Use Django shell to test individual components

### Getting Help

1. Check the error messages in CrawledContent records
2. Review Celery worker logs for task failures
3. Use the management command with `-v 2` for verbose output
4. Test individual services in Django shell for debugging
