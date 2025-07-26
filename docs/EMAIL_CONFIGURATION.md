# Email Service Configuration

## Overview

The Credit Mate AI project implements environment-based email configuration that automatically disables email services in non-production environments to improve development experience and reduce configuration overhead.

## Environment-Based Configuration

### Environment Variable

The `ENVIRONMENT` variable controls email service behavior:

- **`local`** (default): Email service disabled
- **`staging`**: Email service disabled
- **`production`**: Email service enabled with SMTP configuration

### Configuration Behavior

| Environment | Email Backend | Description |
|-------------|---------------|-------------|
| `local` | `django.core.mail.backends.dummy.EmailBackend` | Emails are silently discarded |
| `staging` | `django.core.mail.backends.dummy.EmailBackend` | Emails are silently discarded |
| `production` | `django.core.mail.backends.smtp.EmailBackend` | Emails are sent via SMTP |

## Setup Instructions

### 1. Local/Staging Development

No email configuration needed! Just set:

```bash
ENVIRONMENT=local
# or
ENVIRONMENT=staging
```

The system will automatically disable email services.

### 2. Production Environment

Set the environment and configure SMTP settings:

```bash
# Environment
ENVIRONMENT=production

# SMTP Configuration
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@your-domain.com
EMAIL_HOST_PASSWORD=your-email-password
```

## Supported Email Providers

### Gmail
```bash
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password  # Use App Password, not regular password
```

### SendGrid
```bash
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=your-sendgrid-api-key
```

### Mailgun
```bash
EMAIL_HOST=smtp.mailgun.org
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-mailgun-smtp-username
EMAIL_HOST_PASSWORD=your-mailgun-smtp-password
```

## Usage in Code

### Testing Email Configuration

```python
from django.core.mail import send_mail
from django.conf import settings

# Check current configuration
print(f"Environment: {settings.ENVIRONMENT}")
print(f"Email Backend: {settings.EMAIL_BACKEND}")

# Send test email (only works in production)
send_mail(
    'Test Subject',
    'Test message body',
    'from@your-domain.com',
    ['recipient@example.com'],
    fail_silently=False,
)
```

### Future Email Features

The email service is configured for potential future features:

1. **Crawler Failure Notifications**: Alert administrators when data crawling fails
2. **System Health Monitoring**: Notify about system issues
3. **Admin Notifications**: Django admin password reset emails
4. **Error Reporting**: Critical system error notifications

## Benefits

### Development Benefits
- **No Configuration Required**: Works out-of-the-box for local development
- **No External Dependencies**: No need to set up SMTP servers for testing
- **Clean Logs**: No email-related errors in development

### Production Benefits
- **Reliable Email Delivery**: Full SMTP configuration in production
- **Provider Flexibility**: Support for multiple email providers
- **Security**: Email credentials only required in production

## Troubleshooting

### Issue: Emails not sending in production

**Check:**
1. `ENVIRONMENT=production` is set
2. SMTP credentials are correct
3. Email provider allows SMTP access
4. Firewall allows outbound connections on email port

### Issue: Email configuration errors

**Debug:**
```python
# Check current settings
from django.conf import settings
print(f"Environment: {settings.ENVIRONMENT}")
print(f"Email Backend: {settings.EMAIL_BACKEND}")

# Test email sending
from django.core.mail import send_mail
try:
    send_mail('Test', 'Test', 'from@test.com', ['to@test.com'])
    print("Email sent successfully")
except Exception as e:
    print(f"Email error: {e}")
```

## Migration from Previous Configuration

If you were previously using console or other email backends:

1. Remove old `EMAIL_BACKEND` from environment files
2. Set `ENVIRONMENT=local` for development
3. Configure SMTP settings only for production
4. Test the configuration with the debug commands above

## Security Notes

- Never commit SMTP credentials to version control
- Use environment variables for all sensitive email configuration
- Consider using app-specific passwords for Gmail
- Implement proper error handling for email failures in production code
