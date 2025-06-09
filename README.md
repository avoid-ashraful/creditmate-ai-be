# Credit Mate AI - Backend

<div align="center">
  <h3>🚀 AI-Powered Financial Management Platform</h3>
  <p>A comprehensive Django-based backend for credit analysis, financial planning, and personalized recommendations</p>

  [![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
  [![Django](https://img.shields.io/badge/Django-4.2+-green.svg)](https://djangoproject.com)
  [![Django REST Framework](https://img.shields.io/badge/DRF-3.14+-red.svg)](https://django-rest-framework.org)
  [![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
</div>

## 📋 Table of Contents

- [About](#about)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [API Documentation](#api-documentation)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Development Guidelines](#development-guidelines)
- [Contributing](#contributing)
- [License](#license)
- [Support](#support)

## 🎯 About

Credit Mate AI is a sophisticated financial management platform that leverages artificial intelligence to provide users with comprehensive credit analysis, personalized financial planning tools, and actionable recommendations to improve their credit scores and overall financial health.

### Key Capabilities
- **AI-Powered Credit Analysis**: Advanced algorithms analyze credit patterns and provide insights
- **Financial Planning Tools**: Comprehensive suite of tools for budget management and financial goal setting
- **Personalized Recommendations**: Tailored advice based on individual financial profiles
- **Credit Score Improvement**: Strategic guidance to enhance credit ratings
- **Financial Health Monitoring**: Real-time tracking and assessment of financial wellness

## ✨ Features

### Core Features
- 🏦 **Bank Integration**: Connect and manage multiple bank accounts
- 💳 **Credit Card Management**: Track and analyze credit card usage patterns
- 📊 **Financial Analytics**: Detailed insights and reporting capabilities
- 🤖 **AI Recommendations**: Machine learning-powered financial advice
- 📈 **Credit Score Tracking**: Monitor credit score changes over time
- 🔒 **Secure Data Handling**: Enterprise-grade security for financial data

### API Features
- 🌐 **RESTful API Design**: Clean, intuitive API endpoints
- 🔐 **Authentication & Authorization**: Secure user management system
- 📋 **Comprehensive Filtering**: Advanced filtering and search capabilities
- 📄 **Pagination Support**: Efficient handling of large datasets
- ✅ **Data Validation**: Robust input validation and error handling

## 🛠 Tech Stack

### Backend Framework
- **Django 4.2+**: High-level Python web framework
- **Django REST Framework**: Powerful toolkit for building Web APIs
- **Python 3.11+**: Modern Python version with enhanced performance

### Database
- **SQLite**: Lightweight database for development
- **PostgreSQL**: Production database (configurable)

### Development Tools
- **Pipenv**: Python dependency management
- **Black**: Python code formatter
- **Flake8**: Code linting and style checking
- **isort**: Import statement sorting
- **pre-commit**: Git hooks for code quality

### Testing
- **Django Test Framework**: Built-in testing capabilities
- **pytest**: Advanced testing framework
- **Factory Boy**: Test data generation

## 📋 Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.11 or higher** - [Download Python](https://python.org/downloads/)
- **pip** - Python package installer (comes with Python)
- **pipenv** - Python dependency management tool
- **Git** - Version control system

### Installing Pipenv
```bash
pip install pipenv
```

## 🚀 Installation

### 1. Clone the Repository
```bash
git clone git@github.com:avoid-ashraful/creditmate-ai-be.git
cd creditmate-ai-be
```

### 2. Set Up Virtual Environment
```bash
# Install dependencies and create virtual environment
pipenv install --dev

# Activate virtual environment
pipenv shell
```

### 3. Database Setup
```bash
# Run database migrations
python manage.py migrate

# Create superuser (optional)
python manage.py createsuperuser
```

### 4. Load Initial Data (Optional)
```bash
# Load sample data for development
python manage.py loaddata fixtures/sample_data.json
```

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# Django Settings
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# Database Configuration
DATABASE_URL=sqlite:///db.sqlite3

# Email Configuration (optional)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend

# External API Keys (add as needed)
# CREDIT_BUREAU_API_KEY=your-api-key
# BANK_API_KEY=your-bank-api-key
```

### Django Settings

The project uses environment-based configuration. Key settings can be found in:
- `credit_mate_ai/settings.py` - Main settings file
- `.env` - Environment-specific variables

## 🏃‍♂️ Usage

### Development Server
```bash
# Start the development server
python manage.py runserver

# Server will be available at http://127.0.0.1:8000/
```

### Django Admin
Access the admin interface at `http://127.0.0.1:8000/admin/` using your superuser credentials.

### API Endpoints
The API is available at `http://127.0.0.1:8000/api/v1/`. Key endpoints include:

- `/api/v1/banks/` - Bank management
- `/api/v1/credit-cards/` - Credit card operations
- `/api/v1/users/` - User management
- `/api/v1/auth/` - Authentication endpoints

## 📚 API Documentation

### Authentication
The API uses token-based authentication. Include the token in your requests:

```bash
curl -H "Authorization: Token your-token-here" http://127.0.0.1:8000/api/v1/banks/
```

### Example API Calls

#### Get User's Banks
```bash
GET /api/v1/banks/
Authorization: Token your-token-here
```

#### Create Credit Card
```bash
POST /api/v1/credit-cards/
Authorization: Token your-token-here
Content-Type: application/json

{
  "name": "Chase Sapphire",
  "bank": 1,
  "credit_limit": 5000.00,
  "current_balance": 1250.00
}
```

For detailed API documentation, visit `/api/docs/` when running the development server.

## 🧪 Testing

### Running Tests
```bash
# Run all tests
python manage.py test

# Run tests for specific app
python manage.py test banks
python manage.py test credit_cards

# Run tests with coverage
pipenv install coverage
coverage run --source='.' manage.py test
coverage report
```

### Test Structure
```
app_name/
├── tests/
│   ├── test_api.py      # API endpoint tests
│   ├── test_models.py   # Model tests
│   └── test_services.py # Business logic tests
```

### Writing Tests
Follow Django testing best practices:
- Use `APITestCase` for API testing
- Use `TestCase` for model and utility testing
- Mock external services
- Test authentication and permissions

## 📁 Project Structure

```
credit-mate-ai/
├── credit_mate_ai/          # Django project settings
│   ├── settings.py          # Main configuration
│   ├── urls.py              # URL routing
│   └── wsgi.py              # WSGI configuration
├── banks/                   # Bank management app
│   ├── api/                 # API-related files
│   ├── tests/               # Test files
│   ├── models.py            # Database models
│   └── services.py          # Business logic
├── credit_cards/            # Credit card management app
│   ├── api/                 # API-related files
│   ├── tests/               # Test files
│   ├── models.py            # Database models
│   └── services.py          # Business logic
├── common/                  # Shared utilities
├── templates/               # Django templates
├── static/                  # Static files
├── requirements/            # Dependency files
├── docs/                    # Documentation
└── manage.py                # Django management script
```

## 🔧 Development Guidelines

### Code Style
- **Black**: Code formatting with 88-character line length
- **Flake8**: Linting and style checking
- **isort**: Import statement organization

```bash
# Format code
black .

# Check linting
flake8

# Sort imports
isort .

# Run all pre-commit hooks
pre-commit run --all-files
```

### Git Workflow
1. Create feature branch: `git checkout -b feat-your-feature`
2. Make changes and commit: `git commit -m "Add your feature"`
3. Push branch: `git push origin feat-your-feature`
4. Create Pull Request

### Commit Message Format
```
type(scope): description

Examples:
feat(banks): add bank account validation
fix(api): resolve credit card creation bug
docs(readme): update installation instructions
```

## 🤝 Contributing

We welcome contributions! Please follow these steps:

1. **Fork the repository**
2. **Create a feature branch** (`git checkout -b feat/amazing-feature`)
3. **Make your changes** following our coding standards
4. **Add tests** for new functionality
5. **Run the test suite** (`python manage.py test`)
6. **Commit your changes** (`git commit -m 'feat: add amazing feature'`)
7. **Push to the branch** (`git push origin feat/amazing-feature`)
8. **Open a Pull Request**

### Pull Request Guidelines
- Provide a clear description of the changes
- Include tests for new features
- Update documentation as needed
- Ensure all tests pass
- Follow the existing code style

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

### Getting Help
- **Documentation**: Check our [API Documentation](API_DOCUMENTATION.md)
- **Issues**: [GitHub Issues](https://github.com/avoid-ashraful/creditmate-ai-be/issues)
- **Discussions**: [GitHub Discussions](https://github.com/avoid-ashraful/creditmate-ai-be/discussions)

### Reporting Issues
When reporting issues, please include:
- Python version
- Django version
- Steps to reproduce
- Expected vs actual behavior
- Error messages or logs

### Development Setup Issues
If you encounter issues during setup:
1. Ensure Python 3.11+ is installed
2. Check that pipenv is properly installed
3. Verify virtual environment activation
4. Review error messages in terminal

---

<div align="center">
  <p>Built with ❤️ by <a href="https://github.com/avoid-ashraful">Ashraful Islam</a></p>
  <p>⭐ Star this repository if you find it helpful!</p>
</div>
