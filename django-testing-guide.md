# Django Testing Guide with pytest

A comprehensive guide to implementing a robust testing suite for Django applications using pytest instead of Django's TestCase.

## Table of Contents
1. [Testing Configuration](#testing-configuration)
2. [Test Structure & Organization](#test-structure--organization)
3. [Base Test Classes & Mixins](#base-test-classes--mixins)
4. [Factory Pattern for Test Data](#factory-pattern-for-test-data)
5. [API Testing Patterns](#api-testing-patterns)
6. [Service Layer Testing](#service-layer-testing)
7. [Model Testing](#model-testing)
8. [Authentication & Permissions Testing](#authentication--permissions-testing)
9. [Mock Patterns](#mock-patterns)
10. [Performance & Query Optimization Testing](#performance--query-optimization-testing)
11. [Docker Integration](#docker-integration)

## Testing Configuration

### Core Configuration Files

#### `pytest.ini`
```ini
[pytest]
addopts = --reuse-db --nomigrations --show-capture=no --pdbcls=IPython.terminal.debugger:TerminalPdb --disable-socket -vv --ds=config.settings.test
markers =
    api: tests which require http calls to apis
filterwarnings =
    ignore::DeprecationWarning
timeout = 500
```

**Key Configuration Options:**
- `--reuse-db`: Significantly speeds up test execution by reusing database between runs
- `--nomigrations`: Skips migrations during testing for faster setup
- `--disable-socket`: Prevents external network calls during testing
- `--ds=config.settings.test`: Uses dedicated test settings
- `-vv`: Verbose output for better debugging

#### `setup.cfg` (Testing Section)
```ini
[coverage:run]
omit =
    */migrations/*
    */tests/*
    */venv/*
    manage.py
    */settings/*
    */conftest.py

[flake8]
per-file-ignores =
    */tests/*.py:D103,D102,D101,CFQ002
    */test_*.py:D103,D102,D101,CFQ002
```

### Global Test Configuration (`conftest.py`)

```python
import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

@pytest.fixture(scope="session", autouse=True)
def django_db_setup(django_db_setup, django_db_blocker):
    """Load essential test data once per test session."""
    with django_db_blocker.unblock():
        call_command("loaddata",
                    "sl_grade_years", "groups", "year",
                    "user_boolean_types", "academic_terms")
        call_command("create_global_data_sets")

@pytest.fixture()
def api_client():
    """Django REST Framework API test client."""
    return APIClient()

@pytest.fixture()
def authed_api_client(api_client):
    """Authenticated API client factory."""
    def _api_client_authenticator(user):
        api_client.credentials(HTTP_AUTHORIZATION="bearer " + user.jwt)
        return api_client
    return _api_client_authenticator

@pytest.fixture(scope="function", autouse=True)
def isolate_cacheops_within_session(worker_id):
    """Override cache key prefix for test isolation."""
    prefix = f"{worker_id}:{uuid.uuid4()}:"
    with override_settings(CACHEOPS_PREFIX=lambda q: prefix):
        yield
```

## Test Structure & Organization

### Standard App Structure
```
app_name/
├── tests/
│   ├── __init__.py
│   ├── test_api/
│   │   ├── __init__.py
│   │   ├── test_*_viewset.py
│   │   └── test_*_view.py
│   ├── test_models.py
│   ├── test_selectors.py
│   ├── test_services.py
│   ├── test_tasks.py
│   ├── test_admin.py
│   └── test_querysets.py
├── factories/
│   └── __init__.py
└── conftest.py (if app-specific fixtures needed)
```

### Test File Naming Conventions
- **ViewSets**: `test_*_viewset.py`
- **Services**: `test_services.py`
- **Models**: `test_models.py`
- **Selectors**: `test_selectors.py`
- **Admin**: `test_admin.py`
- **Tasks (Celery)**: `test_tasks.py`

## Base Test Classes & Mixins

### Primary Base Test Class with pytest
```python
import pytest
from rest_framework.test import APIClient

@pytest.mark.django_db
class BaseAPITestCase:
    """Base test case for API testing with pytest and authentication helpers."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up test data before each test method."""
        self.client = APIClient()
        self.district = DistrictFactory()
        self.k12_admin = self.create_k12_admin()
        self.student = StudentFactory()

    def api_authentication(self, user):
        """Authenticate API client with given user."""
        self.client.credentials(HTTP_AUTHORIZATION="bearer " + user.jwt)

    @classmethod
    def create_k12_admin(cls, district=None, student=None, capabilities=()):
        """Create K12Admin with proper district access."""
        district = district or (student.district if student else DistrictFactory())
        k12_admin = K12AdminFactory(district=district)

        # Add capabilities
        for cap in capabilities:
            k12_admin.role.user_capabilities.add(
                UserCapabilityFactory(name=cap)
            )
        return k12_admin
```

### Authentication Helpers for pytest
```python
# In conftest.py or test files
def api_authentication(client, user):
    """Authenticate API client with given user."""
    client.credentials(HTTP_AUTHORIZATION="bearer " + user.jwt)

def create_k12_admin(district=None, student=None, capabilities=()):
    """Create K12Admin with proper district access."""
    district = district or (student.district if student else DistrictFactory())
    k12_admin = K12AdminFactory(district=district)

    # Add capabilities
    for cap in capabilities:
        k12_admin.role.user_capabilities.add(
            UserCapabilityFactory(name=cap)
        )
    return k12_admin
```

## Factory Pattern for Test Data

### Basic Factory Structure
```python
import factory
from django.contrib.auth.signals import user_logged_in

@factory.django.mute_signals(signals.post_save)
class UserFactory(factory.django.DjangoModelFactory):
    """Factory for creating User instances."""

    email = factory.LazyAttribute(lambda _: f"{uuid.uuid4()}@testscenario.com")
    password = factory.PostGenerationMethodCall("set_password", "123456")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    is_active = True

    class Meta:
        model = "sl_users.User"
        django_get_or_create = ("email",)

@factory.django.mute_signals(signals.post_save, signals.pre_save)
class StudentFactory(factory.django.DjangoModelFactory):
    """Factory for creating Student instances."""

    user = factory.SubFactory(UserFactory)
    school = factory.SubFactory("sl_schools.factories.K12SchoolFactory")
    grade_year = factory.SubFactory(GradeYearFactory)

    class Meta:
        model = "sl_users.Student"
```

### Advanced Factory Patterns
```python
class ActivityCommentFactory(factory.django.DjangoModelFactory):
    """Factory for Activity comments with entity relationships."""

    created_by = factory.SubFactory(UserFactory)
    comment = factory.Faker("sentence", nb_words=10)
    entity = factory.SubFactory(FinalListItemFactory)

    class Meta:
        model = "activity.Activity"

    @factory.post_generation
    def scope(self, create, extracted, **kwargs):
        """Create appropriate scope based on entity."""
        if not create:
            return
        if extracted:
            self.scope = extracted
        else:
            self.scope = StudentScopeFactory(
                district=self.entity.student.district
            )
```

## API Testing Patterns

### ViewSet Testing Structure with pytest
```python
@pytest.mark.django_db
class TestActivityViewSet:
    """Test the endpoints of ActivityViewSet work as expected."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Set up testing environment."""
        self.client = APIClient()
        self.student = StudentFactory()
        self.k12_admin = create_k12_admin(student=self.student)
        self.external_k12_admin = create_k12_admin()
        self.guardian = create_guardian(student=self.student)

    def test_create_returns_expected_response_with_valid_data(self):
        """Test that activity is properly created through the post endpoint."""
        api_authentication(self.client, self.k12_admin.user)

        data = {
            "app": "activity",
            "model": "ActivityEntity",
            "id": self.activity_entity.id,
            "comment": "Test comment for testing."
        }

        response = self.client.post(self.create_url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert Activity.objects.filter(
            created_by=self.k12_admin.user,
            comment=data["comment"]
        ).exists()

    def test_entity_level_permissions(self):
        """Ensure entity level permissions work as expected."""
        test_cases = [
            (self.k12_admin.user, self.activity_entity, True),
            (self.student.user, self.activity_entity, True),
            (self.guardian.user, self.activity_entity, True),
            (self.external_k12_admin.user, self.activity_entity, False),
        ]

        for user, entity, has_permission in test_cases:
            api_authentication(self.client, user)
            data = self.get_comment_data(entity)

            response = self.client.post(self.create_url, data)
            expected_status = (
                status.HTTP_201_CREATED if has_permission
                else status.HTTP_403_FORBIDDEN
            )
            assert response.status_code == expected_status
```

### Authentication Testing
```python
def test_authentication_required(self):
    """Test that authentication is required for protected endpoints."""
    # Test without authentication
    response = self.client.get(self.list_url)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # Test with authentication
    api_authentication(self.client, self.k12_admin.user)
    response = self.client.get(self.list_url)
    assert response.status_code == status.HTTP_200_OK

@pytest.mark.parametrize("user_type,expected_status", [
    ("k12_admin", status.HTTP_200_OK),
    ("student", status.HTTP_403_FORBIDDEN),
    ("guardian", status.HTTP_403_FORBIDDEN),
])
def test_role_based_access(self, user_type, expected_status):
    """Test role-based access control."""
    user = getattr(self, user_type).user
    api_authentication(self.client, user)

    response = self.client.get(self.admin_only_url)
    assert response.status_code == expected_status
```

## Service Layer Testing

### Service Function Testing
```python
@pytest.mark.django_db
class TestFinalListServices:
    """Test final list service functions."""

    def setup_method(self, method):
        """Create common test data."""
        self.district = DistrictFactory()
        self.student = StudentFactory(school__district=self.district)
        self.he_school = HESchoolFactory()

    def test_is_last_designation_created_by_k12_admin_not_exist(self):
        """Test if there is no existing designations."""
        final_list_item = FinalListItemFactory(
            he_school=self.he_school,
            student=self.student,
        )

        result = is_last_designation_created_by_k12_admin(final_list_item)
        assert not result

    def test_is_last_designation_created_by_k12_admin_exist_admin(self):
        """Test if last designation is created by k12 admin user."""
        k12_admin = K12AdminFactory()
        final_list_item = FinalListItemFactory(
            he_school=self.he_school,
            student=self.student,
        )
        FinalListItemDesignationFactory(
            final_list_item=final_list_item,
            user=k12_admin.user
        )

        result = is_last_designation_created_by_k12_admin(final_list_item)
        assert result

    @pytest.mark.parametrize("gpa,initial_designation,updated_designation", [
        (3.8, "rule1", "rule2"),
        (3.9, "fallback", "fallback"),
    ])
    def test_re_designation_if_district_admission_rules_updates(
        self, gpa, initial_designation, updated_designation
    ):
        """Test re-designation if admission rules updates."""
        final_list_item = FinalListItemFactory(
            he_school=self.he_school,
            student=self.student
        )

        rule = AdmissionRuleFactory(
            district=self.district,
            designation_name="rule1",
            conditions={"gpa": {"gte": gpa}},
        )
        rule.he_schools.add(self.he_school)

        assert final_list_item.last_designation.name == initial_designation

        rule.designation_name = "rule2"
        rule.save()

        final_list_item.refresh_from_db()
        assert final_list_item.last_designation.name == updated_designation
```

## Model Testing

### Model Method Testing
```python
@pytest.mark.django_db
class TestActivityModel:
    """Test Activity model methods and properties."""

    def setup_method(self, method):
        self.user = UserFactory()
        self.entity = FinalListItemFactory()

    def test_str_representation(self):
        """Test string representation of Activity."""
        activity = ActivityCommentFactory(
            created_by=self.user,
            comment="Test comment"
        )
        expected = f"Comment by {self.user.email}: Test comment"
        assert str(activity) == expected

    def test_is_comment_property(self):
        """Test is_comment property."""
        comment_activity = ActivityCommentFactory()
        action_activity = ActivityActionFactory()

        assert comment_activity.is_comment
        assert not action_activity.is_comment

    def test_soft_delete(self):
        """Test soft delete functionality."""
        activity = ActivityCommentFactory()
        activity_id = activity.id

        activity.delete()

        # Should still exist in database but marked as inactive
        activity.refresh_from_db()
        assert not activity.is_active
        assert Activity.objects.filter(id=activity_id).exists()
        assert not Activity.objects.viewable_comments().filter(id=activity_id).exists()
```

### Model Validation Testing
```python
def test_model_validation(self):
    """Test model field validation."""
    with pytest.raises(ValidationError):
        activity = Activity(
            created_by=self.user,
            entity=self.entity,
            # Both comment and action are None - should fail validation
        )
        activity.full_clean()

def test_unique_constraints(self):
    """Test unique constraints."""
    ActivityLikeFactory(
        activity=self.activity,
        created_by=self.user
    )

    # Creating duplicate like should raise IntegrityError
    with pytest.raises(IntegrityError):
        ActivityLikeFactory(
            activity=self.activity,
            created_by=self.user
        )
```

## Authentication & Permissions Testing

### JWT Authentication Testing
```python
def test_jwt_authentication(self):
    """Test JWT token-based authentication."""
    user = UserFactory()
    token = jwt_encode_handler({"user_id": user.id})

    self.client.credentials(HTTP_AUTHORIZATION=f"bearer {token}")
    response = self.client.get(self.protected_url)
    assert response.status_code == status.HTTP_200_OK

def test_invalid_jwt_token(self):
    """Test invalid JWT token handling."""
    self.client.credentials(HTTP_AUTHORIZATION="bearer invalid_token")
    response = self.client.get(self.protected_url)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
```

### Permission Testing
```python
def test_capability_based_permissions(self):
    """Test capability-based permission system."""
    # User without capability
    user_without_capability = K12AdminFactory()

    # User with capability
    user_with_capability = K12AdminFactory()
    user_with_capability.role.user_capabilities.add(
        UserCapabilityFactory(name=CAPABILITY_PROGRAM_MANAGEMENT)
    )

    test_cases = [
        (user_without_capability.user, status.HTTP_403_FORBIDDEN),
        (user_with_capability.user, status.HTTP_200_OK),
    ]

    for user, expected_status in test_cases:
        self.api_authentication(user)
        response = self.client.get(self.capability_protected_url)
        assert response.status_code == expected_status
```

## Mock Patterns

### External Service Mocking
```python
from unittest.mock import patch, MagicMock

class TestExternalServiceIntegration:
    """Test integration with external services."""

    @patch('utils.slack.get_client')
    def test_slack_notification_sent(self, mock_slack_client):
        """Test that Slack notification is sent."""
        mock_client = MagicMock()
        mock_slack_client.return_value = mock_client

        # Trigger action that should send Slack notification
        activity = ActivityCommentFactory()
        send_activity_notification(activity)

        # Verify Slack client was called
        mock_client.chat_postMessage.assert_called_once()

    @patch('common.services.send_email')
    def test_email_notification(self, mock_send_email):
        """Test email notification sending."""
        user = UserFactory(email="test@example.com")

        send_welcome_email(user)

        mock_send_email.assert_called_once_with(
            to=["test@example.com"],
            subject="Welcome!",
            template="emails/welcome.html",
            context={"user": user}
        )

    @patch('django.db.transaction.on_commit')
    def test_transaction_commit_hooks(self, mock_on_commit):
        """Test that functions are called after transaction commit."""
        def mock_run_on_commit(func, using=None):
            func()

        mock_on_commit.side_effect = mock_run_on_commit

        # Action that should trigger post-commit hook
        ActivityCommentFactory()

        mock_on_commit.assert_called()
```

### Database Transaction Mocking
```python
@pytest.fixture()
def run_transaction_on_commit():
    """Fixture to immediately run transaction.on_commit callbacks."""
    def run_on_commit(func, using=None):
        func()

    with mock.patch("django.db.transaction.on_commit", side_effect=run_on_commit):
        yield
```

## Performance & Query Optimization Testing

### Query Count Testing
```python
def test_query_optimization(self, django_assert_max_num_queries):
    """Test that queries are optimized."""
    ActivityCommentFactory.create_batch(10)

    with django_assert_max_num_queries(3):
        # Should use select_related/prefetch_related to minimize queries
        activities = Activity.objects.select_related('created_by').all()
        list(activities)  # Force evaluation

def test_n_plus_one_prevention(self, django_assert_num_queries):
    """Test prevention of N+1 query problems."""
    activities = ActivityCommentFactory.create_batch(5)

    with django_assert_num_queries(2):  # One for activities, one for users
        serializer_data = ActivitySerializer(
            Activity.objects.select_related('created_by'),
            many=True
        ).data
        # Accessing user data shouldn't trigger additional queries
        for activity in serializer_data:
            activity['created_by']['email']
```

### Object Creation Assertion
```python
def test_object_creation_count(self, assert_num_objects_created):
    """Test exact number of objects created."""
    expected_objects = {
        Activity: 1,
        StudentScope: 1,
    }

    with assert_num_objects_created(expected_objects):
        ActivityCommentFactory()
```

## Docker Integration

### Docker Test Configuration
```yaml
# docker-compose.test.yml
version: '3.8'
services:
  django:
    build: .
    command: pytest
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.test
    depends_on:
      - db
      - redis
    volumes:
      - .:/app

  db:
    image: mysql:8.0
    environment:
      MYSQL_DATABASE: test_schoolinks
      MYSQL_ROOT_PASSWORD: test_password
```

### Running Tests in Docker
```bash
# Run all tests
docker-compose -f docker-compose.test.yml run django pytest

# Run specific test file
docker-compose -f docker-compose.test.yml run django pytest app/tests/test_models.py

# Run with coverage
docker-compose -f docker-compose.test.yml run django pytest --cov=app

# Run specific test method
docker-compose -f docker-compose.test.yml run django pytest app/tests/test_models.py::TestModel::test_method
```

## Advanced Testing Patterns

### Parametrized Testing
```python
@pytest.mark.parametrize("user_type,entity_type,expected_access", [
    ("k12_admin", "student_profile", True),
    ("student", "student_profile", True),
    ("guardian", "student_profile", True),
    ("external_k12_admin", "student_profile", False),
    ("member", "member_profile", True),
    ("student", "member_profile", False),
])
def test_entity_access_permissions(self, user_type, entity_type, expected_access):
    """Test entity access permissions across different user types."""
    user = getattr(self, user_type).user
    entity = getattr(self, entity_type)

    self.api_authentication(user)
    response = self.client.post(self.create_url, self.get_comment_data(entity))

    expected_status = (
        status.HTTP_201_CREATED if expected_access
        else status.HTTP_403_FORBIDDEN
    )
    assert response.status_code == expected_status
```

### Fixture Isolation
```python
@pytest.fixture(scope="function")
def isolate_notifications():
    """Clear and reset notifications registry for test isolation."""
    original_registry = notification_types.get_classes()
    notification_types.clear()
    try:
        yield
    finally:
        notification_types.set_registry(original_registry)
```

## Best Practices Summary

### Test Organization
1. **Separation of Concerns**: Separate tests by functionality (API, services, models)
2. **Descriptive Naming**: Use clear, descriptive test method names
3. **Setup Methods**: Use `setUpTestData` for class-level data, `setup_method` for method-level data
4. **Factory Usage**: Use factories for all test data creation

### Performance Optimization
1. **Database Reuse**: Use `--reuse-db` flag for faster test execution
2. **Query Optimization**: Always test for N+1 queries with `django_assert_max_num_queries`
3. **Fixture Scope**: Use appropriate fixture scopes (session, class, function)
4. **Batch Creation**: Use `create_batch` for creating multiple objects

### Testing Standards
1. **Use pytest**: All tests should use pytest with `@pytest.mark.django_db` for database access
2. **Authentication**: Test both authenticated and unauthenticated access
3. **Permissions**: Test all permission levels and edge cases
4. **Validation**: Test model validation and constraints
5. **Error Handling**: Test error conditions and edge cases
6. **Mocking**: Mock external services and expensive operations

### Code Quality
1. **Coverage**: Aim for high test coverage (>90%)
2. **Isolation**: Tests should be independent and not rely on other tests
3. **Documentation**: Document complex test scenarios
4. **Maintenance**: Keep tests updated with code changes

This testing guide provides a comprehensive foundation for implementing robust testing in Django applications, ensuring code quality, reliability, and maintainability.
