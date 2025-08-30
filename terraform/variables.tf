variable "railway_token" {
  description = "Railway API token for authentication"
  type        = string
  sensitive   = true
  default     = null
}

variable "github_repo_url" {
  description = "GitHub repository URL for the Django backend"
  type        = string
  default     = "your-github-username/credit-mate-ai-backend"
}

variable "django_secret_key" {
  description = "Django SECRET_KEY for the application"
  type        = string
  sensitive   = true
}

variable "postgres_password" {
  description = "Password for PostgreSQL database"
  type        = string
  sensitive   = true
  default     = "secure-random-password-123"
}

variable "redis_password" {
  description = "Password for Redis cache"
  type        = string
  sensitive   = true
  default     = "redis-secure-password"
}

variable "openrouter_api_key" {
  description = "OpenRouter API key for AI content parsing"
  type        = string
  sensitive   = true
  default     = ""
}

variable "gemini_api_key" {
  description = "Google Gemini API key for AI content parsing"
  type        = string
  sensitive   = true
  default     = ""
}

variable "environment" {
  description = "Environment name (development, staging, production)"
  type        = string
  default     = "production"
  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "Environment must be one of: development, staging, production."
  }
}

variable "django_debug" {
  description = "Enable Django DEBUG mode"
  type        = bool
  default     = false
}

variable "allowed_hosts" {
  description = "Django ALLOWED_HOSTS setting"
  type        = list(string)
  default     = ["*"]
}
