# CORS and Rate Limiting Configuration

## Overview

This guide explains how to configure Cross-Origin Resource Sharing (CORS) and API rate limiting in Credit Mate AI. Both features use environment variables following security best practices.

## CORS Configuration

### What is CORS?

Cross-Origin Resource Sharing (CORS) is a security feature that allows web applications running at one domain to access resources from another domain. This is essential for frontend applications that need to communicate with your API.

### Environment Variables

Configure CORS using these environment variables:

```bash
# Required: Comma-separated list of allowed origins
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://yourdomain.com

# Optional: Allow credentials in requests (default: True)
CORS_ALLOW_CREDENTIALS=True

# Development only: Allow all origins (NEVER use in production)
CORS_ALLOW_ALL_ORIGINS=False
```

### Configuration Examples

#### Production Setup
```bash
# Production environment
ENVIRONMENT=production
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com,https://app.yourdomain.com
CORS_ALLOW_CREDENTIALS=True
```

#### Development Setup
```bash
# Development environment
ENVIRONMENT=local
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080
CORS_ALLOW_CREDENTIALS=True

# For development convenience (use with caution)
# CORS_ALLOW_ALL_ORIGINS=True
```

#### Staging Setup
```bash
# Staging environment
ENVIRONMENT=staging
CORS_ALLOWED_ORIGINS=https://staging.yourdomain.com,https://dev.yourdomain.com
CORS_ALLOW_CREDENTIALS=True
```

### Security Best Practices

1. **Never use `CORS_ALLOW_ALL_ORIGINS=True` in production**
2. **Always specify exact origins** - avoid wildcards
3. **Use HTTPS in production** origins
4. **Keep the origins list minimal** - only include necessary domains
5. **Review origins regularly** - remove unused domains

### Allowed Headers

The following headers are automatically allowed:

- `accept`
- `accept-encoding`
- `authorization`
- `content-type`
- `dnt`
- `origin`
- `user-agent`
- `x-csrftoken`
- `x-requested-with`

## Rate Limiting Configuration

### Overview

Rate limiting prevents API abuse by limiting the number of requests from each client within a specific time window.

The implementation uses a custom `TrustedClientRateThrottle` class that applies three throttle policies in sequence:
1. **Burst throttle** - short-term burst protection (default 10/sec)
2. **Authenticated throttle** - for logged-in users (default 1000/min)
3. **Anonymous throttle** - for unauthenticated users (default 100/min)

All throttles use `REMOTE_ADDR` for identification (not `X-Forwarded-For`, which can be spoofed). Authenticated users are identified by user ID.

### Default Limits

- **Anonymous users**: 100 requests per minute
- **Authenticated users**: 1000 requests per minute
- **Burst protection**: 10 requests per second

### Environment Variables

Configure rate limiting using these environment variables:

```bash
# Anonymous user rate limit (requests per time period)
THROTTLE_RATE_ANON=100/min

# Authenticated user rate limit (requests per time period)
THROTTLE_RATE_USER=1000/min

# Burst rate limit (short-term protection)
THROTTLE_RATE_BURST=10/sec
```

### Rate Limit Formats

Rate limits use the format: `number/period`

**Supported periods:**
- `sec` - seconds
- `min` - minutes
- `hour` - hours
- `day` - days

**Examples:**
```bash
# 100 requests per minute
THROTTLE_RATE_ANON=100/min

# 50 requests per day
THROTTLE_RATE_ANON=50/day

# 10 requests per second
THROTTLE_RATE_ANON=10/sec
```

### Environment-Specific Configuration

#### Development
```bash
# Relaxed limits for development
THROTTLE_RATE_ANON=10000/hour
THROTTLE_RATE_USER=20000/hour
THROTTLE_RATE_BURST=1000/min
```

#### Production
```bash
# Strict limits for production
THROTTLE_RATE_ANON=100/min
THROTTLE_RATE_USER=1000/min
THROTTLE_RATE_BURST=10/sec
```

#### High-Traffic Production
```bash
# Higher limits for high-traffic applications
THROTTLE_RATE_ANON=5000/hour
THROTTLE_RATE_USER=10000/hour
THROTTLE_RATE_BURST=500/min
```

### Rate Limit Headers

When rate limiting is active, the API includes these response headers:

```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1609459200
```

### Rate Limit Responses

When limits are exceeded, the API returns:

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json

{
    "detail": "Request was throttled. Expected available in 3600 seconds."
}
```

### Retry-After Behavior

The `CeilingRetryAfterThrottle` base class rounds fractional retry periods up to whole seconds for the `Retry-After` header, ensuring clients never wait less than advertised.

## Implementation Details

### CORS Implementation

CORS is implemented using `django-cors-headers`:

1. **Middleware**: `corsheaders.middleware.CorsMiddleware` (positioned early in MIDDLEWARE)
2. **Settings**: Environment-based configuration in `credit_mate_ai/settings.py`
3. **Security**: Whitelist-based origin control via `CORS_ALLOWED_ORIGINS`

### Rate Limiting Implementation

Rate limiting uses Django REST Framework's throttling framework with custom classes:

1. **`TrustedClientRateThrottle`** - Main throttle combining all three policies
2. **`AnonymousThrottle`** - Limits unauthenticated clients by IP (`REMOTE_ADDR`)
3. **`AuthenticatedThrottle`** - Limits authenticated clients by user ID
4. **`BurstThrottle`** - Limits short bursts for both anonymous and authenticated clients
5. **`CeilingRetryAfterThrottle`** - Base class rounding retry times up to whole seconds

All throttles inherit from `SimpleRateThrottle` and use Django's cache framework for storage.

### Throttle Scope Mapping

| Throttle Class | Scope | Default Rate |
|----------------|-------|--------------|
| `AnonymousThrottle` | `anon` | `THROTTLE_RATE_ANON` (100/min) |
| `AuthenticatedThrottle` | `user` | `THROTTLE_RATE_USER` (1000/min) |
| `BurstThrottle` | `burst` | `THROTTLE_RATE_BURST` (10/sec) |

### Configuration in Settings

The throttles are configured in `REST_FRAMEWORK` settings:

```python
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [
        "credit_mate_ai.throttling.TrustedClientRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.getenv("THROTTLE_RATE_ANON", "100/min"),
        "user": os.getenv("THROTTLE_RATE_USER", "1000/min"),
        "burst": os.getenv("THROTTLE_RATE_BURST", "10/sec"),
    },
}
```

## Testing

### Testing CORS

```bash
# Test CORS preflight request
curl -H "Origin: http://localhost:3000" \
     -H "Access-Control-Request-Method: GET" \
     -H "Access-Control-Request-Headers: Content-Type" \
     -X OPTIONS \
     http://localhost:8000/api/v1/credit-cards/

# Test actual CORS request
curl -H "Origin: http://localhost:3000" \
     -X GET \
     http://localhost:8000/api/v1/credit-cards/
```

### Testing Rate Limiting

```bash
# Test rate limiting with rapid requests
for i in {1..10}; do
  curl -w "Status: %{http_code}\n" \
       http://localhost:8000/api/v1/credit-cards/ \
       -o /dev/null -s
  sleep 0.1
done

# Test with authentication (if available)
for i in {1..10}; do
  curl -H "Authorization: Bearer <token>" \
       -w "Status: %{http_code}\n" \
       http://localhost:8000/api/v1/credit-cards/ \
       -o /dev/null -s
  sleep 0.1
done
```

## Monitoring

### CORS Monitoring

Monitor CORS issues by:

1. **Browser console errors** - Check for CORS-related errors
2. **Server logs** - Monitor failed CORS requests
3. **Network tab** - Verify preflight requests succeed

### Rate Limiting Monitoring

Monitor rate limiting by:

1. **Response headers** - Check rate limit headers in responses
2. **429 status codes** - Monitor throttled requests
3. **User feedback** - Users reporting "too many requests" errors

## Troubleshooting

### Common CORS Issues

#### Issue: "CORS policy: No 'Access-Control-Allow-Origin' header"
**Solution:** Add your frontend domain to `CORS_ALLOWED_ORIGINS`

#### Issue: "CORS policy: The request client is not a secure context"
**Solution:** Use HTTPS for production origins

#### Issue: Credentials not being sent
**Solution:** Ensure `CORS_ALLOW_CREDENTIALS=True` and frontend sends credentials (`credentials: 'include'`)

### Common Rate Limiting Issues

#### Issue: Getting 429 errors unexpectedly
**Solution:** Check if rate limits are too restrictive for your use case

#### Issue: Rate limiting not working
**Solution:** 
- Verify `TrustedClientRateThrottle` is in `DEFAULT_THROTTLE_CLASSES`
- Check cache backend is working (Redis required for production)
- Ensure `REST_FRAMEWORK.DEFAULT_THROTTLE_RATES` has the correct scopes

#### Issue: Different limits for different endpoints
**Solution:** Rate limiting is global by default; implement custom throttle classes for specific endpoints

## Advanced Configuration

### Custom Rate Limiting per Endpoint

To implement different rate limits for specific endpoints, create custom throttle classes:

```python
# In your views.py
from rest_framework.throttling import UserRateThrottle

class BurstRateThrottle(UserRateThrottle):
    scope = 'burst'

class CreditCardViewSet(viewsets.ModelViewSet):
    throttle_classes = [BurstRateThrottle]
    # ... rest of your view
```

### CORS for Specific Views

To configure CORS for specific views only:

```python
# In your views.py
from corsheaders.decorators import cors_allow_all

@cors_allow_all
def my_view(request):
    # This view allows all CORS requests
    pass
```

## Security Considerations

### CORS Security
- Never use `CORS_ALLOW_ALL_ORIGINS=True` in production
- Regularly audit allowed origins
- Use specific subdomains rather than wildcards
- Monitor for unauthorized cross-origin requests

### Rate Limiting Security
- Set conservative limits initially, then adjust based on usage
- Implement different limits for different user tiers
- Monitor for distributed attacks that might bypass IP-based limiting
- Consider implementing user-based rate limiting for authenticated endpoints
- The `TrustedClientRateThrottle` applies burst → authenticated → anonymous in sequence, so burst limits protect against credential stuffing

## Production Checklist

### CORS Production Checklist
- [ ] `CORS_ALLOWED_ORIGINS` contains only production domains
- [ ] All origins use HTTPS
- [ ] `CORS_ALLOW_ALL_ORIGINS` is `False` or not set
- [ ] Origins list is minimal and necessary
- [ ] CORS headers are being sent correctly

### Rate Limiting Production Checklist
- [ ] Rate limits are appropriate for expected traffic
- [ ] Burst protection is enabled
- [ ] Monitoring is in place for 429 responses
- [ ] Rate limit headers are being sent
- [ ] Different limits configured for anonymous vs authenticated users
- [ ] Redis cache backend is configured and accessible
- [ ] Throttle classes are in `DEFAULT_THROTTLE_CLASSES`
