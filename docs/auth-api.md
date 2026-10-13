# Authentication API Reference

Base path: `/api/v1/auth/`

All endpoints return JSON. All error responses use the format:
```json
{"detail": "Error message", "code": "error_code"}
```
or field-specific errors:
```json
{"field_name": ["Error message"]}
```

---

## POST /register/

Register a new user. Returns a generic success message (no tokens) to support email verification flow.

### Request
```json
{
  "email": "user@example.com",
  "password": "securepass123",
  "password_confirm": "securepass123",
  "first_name": "John",
  "last_name": "Doe",
  "email_opt_in": true
}
```
- `email` (required): Email address, becomes username
- `password` (required): Min 8 chars, passes Django validators
- `password_confirm` (required): Must match password
- `first_name` (optional): Max 150 chars
- `last_name` (optional): Max 150 chars
- `email_opt_in` (optional, default false): Marketing consent

### Response (201 Created)
```json
{"detail": "Registration successful. Please check your email to verify your account."}
```

### Errors
- 400: Validation errors (email exists, password mismatch, weak password)
- 429: Rate limited (auth_burst scope)

---

## POST /login/

Authenticate user and return JWT access/refresh tokens.

### Request
```json
{
  "email": "user@example.com",
  "password": "securepass123"
}
```

### Response (200 OK)
```json
{
  "access": "eyJhbGciOiJIUzI1NiIs...",
  "refresh": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "id": 1,
    "username": "user@example.com",
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "profile": {
      "email_verified": true,
      "email_opt_in": false,
      "preferences": {}
    }
  }
}
```

### Errors
- 400: Invalid credentials (generic message, no enumeration)
- 400: Account inactive
- 429: Rate limited (auth_burst scope)

---

## POST /logout/

Blacklist the refresh token. Requires authentication.

### Request
```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIs..."
}
```

### Response (200 OK)
```json
{"detail": "Successfully logged out."}
```

### Errors
- 400: Invalid/expired refresh token
- 401: Not authenticated
- 429: Rate limited (auth_user scope)

---

## POST /token/refresh/

Rotate refresh token and return new access token.

### Request
```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIs..."
}
```

### Response (200 OK)
```json
{"access": "eyJhbGciOiJIUzI1NiIs..."}
```

### Errors
- 400: Invalid/expired/blacklisted refresh token (reuse detection)
- 429: Rate limited (auth_burst scope)

---

## POST /password-reset/

Request password reset email. Non-enumerating (same response regardless of user existence).

### Request
```json
{
  "email": "user@example.com"
}
```

### Response (200 OK)
```json
{"detail": "If an account exists, a password reset email has been sent."}
```

### Errors
- 400: Invalid email format
- 429: Rate limited (auth_burst scope)

---

## POST /password-reset/confirm/

Confirm password reset using token from email. Single-use token (Django's default_token_generator).

### Request
```json
{
  "uid": "MQ",
  "token": "abc123-def456",
  "new_password": "newsecurepass123",
  "new_password_confirm": "newsecurepass123"
}
```
- `uid` (required): Base36-encoded user ID from token generator
- `token` (required): One-time token from Django's default_token_generator
- `new_password` (required): Min 8 chars, passes validators
- `new_password_confirm` (required): Must match new_password

### Response (200 OK)
```json
{"detail": "Password has been reset successfully."}
```

**Side effects:** All outstanding refresh tokens for the user are blacklisted.

### Errors
- 400: Invalid/expired token, user not found, password mismatch, weak password
- 429: Rate limited (auth_burst scope)

---

## POST /verify-email/

Verify email address using token from registration email.

### Request
```json
{
  "token": "signed_email_token"
}
```

### Response (200 OK)
```json
{"detail": "Email verified successfully."}
```

### Errors
- 400: Invalid/expired token, email already verified
- 429: Rate limited (auth_burst scope)

---

## GET /me/

Get current user's profile. Requires authentication.

### Response (200 OK)
```json
{
  "id": 1,
  "username": "user@example.com",
  "email": "user@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "profile": {
    "email_verified": true,
    "email_opt_in": false,
    "preferences": {}
  }
}
```

### Errors
- 401: Not authenticated
- 429: Rate limited (auth_user scope)

---

## PATCH /me/

Update current user's profile. Requires authentication.

### Request
```json
{
  "first_name": "Jane",
  "last_name": "Smith",
  "profile": {
    "email_opt_in": true,
    "preferences": {"theme": "dark"}
  }
}
```
**Note:** `email` and `username` cannot be changed via this endpoint. Email changes require re-verification (not implemented). Staff/superusers may use admin.

### Response (200 OK)
```json
{
  "id": 1,
  "username": "user@example.com",
  "email": "user@example.com",
  "first_name": "Jane",
  "last_name": "Smith",
  "profile": {
    "email_verified": true,
    "email_opt_in": true,
    "preferences": {"theme": "dark"}
  }
}
```

### Errors
- 400: Validation errors
- 401: Not authenticated
- 429: Rate limited (auth_user scope)

---

## POST /change-password/

Change password while authenticated. Requires current password.

### Request
```json
{
  "old_password": "currentpass123",
  "new_password": "newsecurepass123",
  "new_password_confirm": "newsecurepass123"
}
```

### Response (200 OK)
```json
{"detail": "Password changed successfully."}
```

**Side effects:** All outstanding refresh tokens for the user are blacklisted (password change invalidates tokens).

### Errors
- 400: Wrong old password, new password same as old, password mismatch, weak password
- 401: Not authenticated
- 429: Rate limited (auth_user scope)

---

## Rate Limiting Scopes

| Scope | Default Rate | Endpoints |
|-------|-------------|-----------|
| auth_burst | 20/min | register, login, token/refresh, password-reset, password-reset/confirm, verify-email |
| auth_anon | 30/min | (currently unused, reserved) |
| auth_user | 100/min | logout, me (GET/PATCH), change-password |

---

## Token Lifetimes

| Token Type | Lifetime |
|------------|----------|
| Access | 15 minutes (configurable via SIMPLE_JWT.ACCESS_TOKEN_LIFETIME) |
| Refresh | 7 days (configurable via SIMPLE_JWT.REFRESH_TOKEN_LIFETIME) |

Rotation enabled: `ROTATE_REFRESH_TOKENS = True`, `BLACKLIST_AFTER_ROTATION = True`
