# terraform/sentry.tf
# Manages the Sentry project, metric alerts, and dashboard via Terraform.
# Phase 10 — Tabbed Calculation Detail.
#
# Provider: https://registry.terraform.io/providers/jianyuan/sentry/latest
#
# Apply:
#   cd terraform
#   terraform init
#   terraform apply -var="sentry_auth_token=$SENTRY_AUTH_TOKEN"
#
# The alert rules mirror sentry/alert-rules.json 1:1 (same source of truth —
# prefer editing BOTH, or treat sentry/alert-rules.json as the spec and this
# file as the executable form).

terraform {
  required_providers {
    sentry = {
      source  = "jianyuan/sentry"
      version = "~> 0.12"
    }
  }
}

provider "sentry" {
  token = var.sentry_auth_token
}

# ─── Project ────────────────────────────────────────────────────────
resource "sentry_project" "calculation_detail" {
  organization = var.sentry_org
  team         = var.sentry_team
  name         = "calculation-detail-frontend"
  platform     = "javascript-react"
  slug         = "calculation-detail-frontend"
}

# ─── Metric Alert: Map Init Time ────────────────────────────────────
# Backed by `measurements.map-init` (WorkspaceTab lazy chunk load).
resource "sentry_metric_alert" "map_init_time" {
  organization      = var.sentry_org
  project           = sentry_project.calculation_detail.id
  name              = "Map Init Time > 3s (p75)"
  dataset           = "transactions"
  query             = "event.type:transaction transaction.op:pageload"
  aggregate         = "p75(measurements.map-init)"
  time_window       = 30
  threshold_type    = 0 # Above threshold
  resolve_threshold = 2500

  trigger {
    label           = "critical"
    alert_threshold = 3000
    resolve_threshold = 2500

    action {
      type              = "slack"
      target_type       = "specific"
      target_identifier = "#alerts-performance"
      integration_id    = var.sentry_slack_integration_id
    }

    action {
      type              = "pagerduty"
      target_type       = "specific"
      target_identifier = var.pagerduty_service_id
      integration_id    = var.sentry_pagerduty_integration_id
    }
  }

  trigger {
    label           = "warning"
    alert_threshold = 2000
    resolve_threshold = 1500

    action {
      type              = "slack"
      target_type       = "specific"
      target_identifier = "#alerts-performance"
      integration_id    = var.sentry_slack_integration_id
    }
  }
}

# ─── Metric Alert: Tab Switch ───────────────────────────────────────
# Backed by `measurements.tab-switch` (useTabSwitchTiming).
resource "sentry_metric_alert" "tab_switch" {
  organization      = var.sentry_org
  project           = sentry_project.calculation_detail.id
  name              = "Tab Switch > 100ms (p95)"
  dataset           = "transactions"
  query             = "event.type:transaction transaction.op:ui.action"
  aggregate         = "p95(measurements.tab-switch)"
  time_window       = 15
  threshold_type    = 0
  resolve_threshold = 80

  trigger {
    label           = "warning"
    alert_threshold = 100
    resolve_threshold = 80

    action {
      type              = "slack"
      target_type       = "specific"
      target_identifier = "#alerts-ux"
      integration_id    = var.sentry_slack_integration_id
    }
  }
}

# ─── Metric Alert: LCP ──────────────────────────────────────────────
# Backed by Sentry browser-tracing Web Vitals (`measurements.lcp`).
resource "sentry_metric_alert" "lcp" {
  organization      = var.sentry_org
  project           = sentry_project.calculation_detail.id
  name              = "LCP > 2.5s (p75)"
  dataset           = "transactions"
  query             = "event.type:transaction transaction.op:pageload"
  aggregate         = "p75(measurements.lcp)"
  time_window       = 60
  threshold_type    = 0
  resolve_threshold = 2000

  trigger {
    label           = "critical"
    alert_threshold = 4000
    resolve_threshold = 2500

    action {
      type              = "slack"
      target_type       = "specific"
      target_identifier = "#alerts-performance"
      integration_id    = var.sentry_slack_integration_id
    }
  }

  trigger {
    label           = "warning"
    alert_threshold = 2500
    resolve_threshold = 2000

    action {
      type              = "slack"
      target_type       = "specific"
      target_identifier = "#alerts-performance"
      integration_id    = var.sentry_slack_integration_id
    }
  }
}

# ─── Metric Alert: Error Rate by Tab ────────────────────────────────
# Backed by TabErrorBoundary's `tab` scope tag.
resource "sentry_metric_alert" "error_rate" {
  organization      = var.sentry_org
  project           = sentry_project.calculation_detail.id
  name              = "Error Rate by Tab > 1%"
  dataset           = "events"
  query             = "event.type:error tags.tab:*"
  aggregate         = "percentage(sessions_crashed, sessions)"
  time_window       = 60
  threshold_type    = 0
  resolve_threshold = 0.5

  trigger {
    label           = "critical"
    alert_threshold = 5
    resolve_threshold = 1

    action {
      type              = "pagerduty"
      target_type       = "specific"
      target_identifier = var.pagerduty_service_id
      integration_id    = var.sentry_pagerduty_integration_id
    }
  }

  trigger {
    label           = "warning"
    alert_threshold = 1
    resolve_threshold = 0.5

    action {
      type              = "slack"
      target_type       = "specific"
      target_identifier = "#alerts-errors"
      integration_id    = var.sentry_slack_integration_id
    }
  }
}

# ─── Metric Alert: API Response Time ────────────────────────────────
# Requires backend transaction tracing (transaction.op:http.server).
resource "sentry_metric_alert" "api_latency" {
  organization      = var.sentry_org
  project           = sentry_project.calculation_detail.id
  name              = "API Response Time > 2s (p95)"
  dataset           = "transactions"
  query             = "event.type:transaction transaction.op:http.server"
  aggregate         = "p95(transaction.duration)"
  time_window       = 15
  threshold_type    = 0
  resolve_threshold = 1500

  trigger {
    label           = "warning"
    alert_threshold = 2000
    resolve_threshold = 1500

    action {
      type              = "slack"
      target_type       = "specific"
      target_identifier = "#alerts-backend"
      integration_id    = var.sentry_slack_integration_id
    }
  }
}

# ─── Variables ──────────────────────────────────────────────────────
variable "sentry_auth_token" {
  type        = string
  description = "Sentry auth token with org:read, project:read, project:write, alerts:write"
  sensitive   = true
}

variable "sentry_org" {
  type    = string
  default = "your-org"
}

variable "sentry_team" {
  type    = string
  default = "frontend-team"
}

variable "sentry_slack_integration_id" {
  type    = string
  default = "12345"
}

variable "sentry_pagerduty_integration_id" {
  type    = string
  default = "67890"
}

variable "pagerduty_service_id" {
  type    = string
  default = "pagerduty-service-id"
}
