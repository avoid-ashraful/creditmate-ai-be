# 📚 Credit Mate AI Documentation

Welcome to the comprehensive documentation for Credit Mate AI - an AI-powered credit card discovery platform.

## 📖 Documentation Overview

This documentation is organized into four main categories:

### 🔌 API Documentation
Complete guides for using the Credit Mate AI REST API.

| Document | Description |
|----------|-------------|
| **[Banks API](./api/banks.md)** | Banks endpoint documentation with filtering and search |
| **[Credit Cards API](./api/credit-cards.md)** | Complete credit cards API reference with advanced filtering |
| **[API Examples](./api/examples.md)** | Comprehensive usage examples and integration patterns |

### ⚙️ Configuration
Setup and configuration guides for different environments.

| Document | Description |
|----------|-------------|
| **[Environment Variables](./configuration/environment-variables.md)** | Complete environment variable reference |
| **[Email Configuration](./configuration/email.md)** | Environment-based email setup |
| **[CORS & Rate Limiting](./configuration/cors-and-rate-limiting.md)** | Security configuration for APIs |

### 🛠️ Development
Development setup, guidelines, and architecture documentation.

| Document | Description |
|----------|-------------|
| **[Setup & Guidelines](./development/setup-and-guidelines.md)** | Development environment setup and coding standards |
| **[Crawler System](./development/crawler-system.md)** | AI-powered web crawling system documentation |
| **[Implementation Summary](./development/implementation-summary.md)** | Technical implementation details and architecture |

### 📖 User Guides
Plain-language how-to guides for credit card users (also rendered at the frontend `/guides` route).

| Document | Description |
|----------|-------------|
| **[User Guides Index](./user/README.md)** | Guide list, editorial rules, source and readability checks |
| **[Choosing your first credit card](./user/choosing-your-first-credit-card.md)** | Eligibility, costs, key terms and cardholder rights |
| **[Understanding annual fee waivers](./user/understanding-annual-fee-waivers.md)** | What an annual fee is and how to get one waived |
| **[Maximizing lounge access benefits](./user/maximizing-lounge-access-benefits.md)** | Airport lounge perks, limits and what to check |
| **[Credit card vs debit card](./user/credit-card-vs-debit-card.md)** | Side-by-side comparison for Bangladesh |

## 🚀 Quick Start

### For API Users
1. Start with **[API Examples](./api/examples.md)** for usage patterns
2. Reference **[Banks API](./api/banks.md)** and **[Credit Cards API](./api/credit-cards.md)** for detailed endpoints
3. Configure CORS using **[CORS & Rate Limiting](./configuration/cors-and-rate-limiting.md)**

### For Developers
1. Follow **[Setup & Guidelines](./development/setup-and-guidelines.md)** for environment setup
2. Configure environment variables using **[Environment Variables](./configuration/environment-variables.md)**
3. Review **[Implementation Summary](./development/implementation-summary.md)** for architecture understanding

### For System Administrators
1. Configure production environment using **[Environment Variables](./configuration/environment-variables.md)**
2. Set up email services with **[Email Configuration](./configuration/email.md)**
3. Configure security with **[CORS & Rate Limiting](./configuration/cors-and-rate-limiting.md)**

## 📊 API Quick Reference

### Base URL
```
http://localhost:8000/api/v1/
```

### Key Endpoints
```http
GET /api/v1/banks/                    # List banks
GET /api/v1/credit-cards/             # List credit cards
GET /api/v1/credit-cards/search-suggestions/  # Search suggestions
```

### Authentication
Currently public API (no authentication required for MVP).

### Rate Limits
- **Anonymous users**: 1000 requests/hour
- **Authenticated users**: 2000 requests/hour
- **Burst protection**: 100 requests/minute

## 🔧 Configuration Quick Reference

### Essential Environment Variables
```bash
# Required
SECRET_KEY=your-secret-key
OPENAI_API_KEY=your-openai-api-key

# Environment
ENVIRONMENT=local  # local/staging/production

# CORS (for frontend integration)
CORS_ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com

# Services
CELERY_BROKER_URL=redis://localhost:6379/0
```

## 🐛 Common Issues & Solutions

### API Issues
- **CORS errors**: Check [CORS configuration](./configuration/cors-and-rate-limiting.md#cors-configuration)
- **Rate limiting**: Review [rate limit settings](./configuration/cors-and-rate-limiting.md#rate-limiting-configuration)
- **404 errors**: Verify endpoints in [API documentation](./api/)

### Development Issues
- **Setup problems**: Follow [development setup](./development/setup-and-guidelines.md#quick-start-development-setup)
- **Environment variables**: Check [environment reference](./configuration/environment-variables.md)
- **Celery issues**: See [troubleshooting guide](./development/setup-and-guidelines.md#troubleshooting)

## 📋 Documentation Standards

This documentation follows these principles:

- **Comprehensive**: Complete coverage of all features
- **Practical**: Real-world examples and use cases
- **Current**: Kept up-to-date with latest changes
- **Accessible**: Clear structure and easy navigation

## 🤝 Contributing to Documentation

When contributing to the project:

1. **Update documentation** when adding new features
2. **Include examples** for new API endpoints
3. **Update configuration guides** for new environment variables
4. **Follow the existing structure** and formatting

## 📞 Getting Help

If you can't find what you're looking for:

1. **Search this documentation** using your browser's search (Ctrl/Cmd + F)
2. **Check the specific API documentation** for endpoint details
3. **Review configuration guides** for setup issues
4. **Check the main README** for general project information

## 🔗 External Resources

- **Main Project**: [README.md](../README.md)
- **Project Guidelines**: [CLAUDE.md](../CLAUDE.md)
- **Environment Template**: [.env.example](../.env.example)
- **GitHub Repository**: [Credit Mate AI Backend](https://github.com/avoid-ashraful/creditmate-ai-be)

---

**Note**: This documentation is for the backend API. For frontend documentation, check the respective frontend repository.
