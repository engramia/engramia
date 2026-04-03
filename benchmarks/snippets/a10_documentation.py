# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""A10 — Documentation snippets (good / medium / bad).

Domain: OpenAPI specs, developer guides, architecture docs, runbooks.
"""

GOOD: dict = {
    "eval_score": 8.7,
    "output": "Generated OpenAPI spec with authentication docs, request/response examples, and error catalog for the billing API.",
    "code": '''\
"""Billing API — OpenAPI specification generator.

Produces a complete OpenAPI 3.1 spec with:
- Authentication flow documentation (API key + JWT)
- Request/response examples for every endpoint
- Error response catalog with problem+json format
- Rate limiting headers documented
"""
from typing import Any


def generate_billing_api_spec(
    version: str = "1.0.0",
    base_url: str = "https://api.example.com/v1",
) -> dict[str, Any]:
    """Generate OpenAPI 3.1 specification for the billing API.

    Args:
        version: API version string.
        base_url: Production base URL.

    Returns:
        Complete OpenAPI spec as a dict (serialize with json/yaml).
    """
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Billing API",
            "version": version,
            "description": (
                "RESTful API for subscription management, invoicing, and payment processing.\\n\\n"
                "## Authentication\\n"
                "All requests require an `Authorization: Bearer <token>` header.\\n"
                "Obtain tokens via `POST /auth/token` with your API key.\\n\\n"
                "## Rate Limiting\\n"
                "- 100 requests/minute per API key\\n"
                "- Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`"
            ),
        },
        "servers": [{"url": base_url, "description": "Production"}],
        "security": [{"bearerAuth": []}],
        "paths": {
            "/subscriptions": {
                "get": {
                    "summary": "List subscriptions",
                    "operationId": "listSubscriptions",
                    "parameters": [
                        {"name": "status", "in": "query", "schema": {"type": "string", "enum": ["active", "canceled", "past_due"]}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20, "maximum": 100}},
                    ],
                    "responses": {
                        "200": {
                            "description": "Paginated list of subscriptions",
                            "content": {"application/json": {"example": {
                                "data": [{"id": "sub_123", "status": "active", "plan": "pro", "current_period_end": "2026-04-15T00:00:00Z"}],
                                "has_more": False,
                            }}},
                        },
                        "401": {"$ref": "#/components/responses/Unauthorized"},
                    },
                },
                "post": {
                    "summary": "Create subscription",
                    "operationId": "createSubscription",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateSubscription"}}},
                    },
                    "responses": {
                        "201": {"description": "Subscription created"},
                        "400": {"$ref": "#/components/responses/ValidationError"},
                        "409": {"description": "Customer already has an active subscription"},
                    },
                },
            },
            "/invoices/{invoice_id}": {
                "get": {
                    "summary": "Get invoice details",
                    "operationId": "getInvoice",
                    "parameters": [{"name": "invoice_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Invoice details"},
                        "404": {"$ref": "#/components/responses/NotFound"},
                    },
                },
            },
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
            },
            "schemas": {
                "CreateSubscription": {
                    "type": "object",
                    "required": ["customer_id", "plan_id"],
                    "properties": {
                        "customer_id": {"type": "string", "example": "cus_abc123"},
                        "plan_id": {"type": "string", "example": "plan_pro_monthly"},
                        "trial_days": {"type": "integer", "default": 0},
                    },
                },
            },
            "responses": {
                "Unauthorized": {"description": "Missing or invalid authentication token"},
                "NotFound": {"description": "Resource not found"},
                "ValidationError": {"description": "Request body failed validation"},
            },
        },
    }
''',
}

MEDIUM: dict = {
    "eval_score": 5.8,
    "output": "OpenAPI spec for billing endpoints.",
    "code": '''\
def get_openapi_spec():
    return {
        "openapi": "3.0.0",
        "info": {"title": "Billing API", "version": "1.0"},
        "paths": {
            "/subscriptions": {
                "get": {"summary": "List subs", "responses": {"200": {"description": "OK"}}},
                "post": {"summary": "Create sub", "responses": {"201": {"description": "Created"}}},
            },
            "/invoices": {
                "get": {"summary": "List invoices", "responses": {"200": {"description": "OK"}}},
            },
        },
    }
''',
}

BAD: dict = {
    "eval_score": 2.5,
    "output": "spec draft",
    "code": '''\
# billing API docs
# endpoints:
# GET /subscriptions - list subs
# POST /subscriptions - create sub
# GET /invoices - list invoices
# TODO: write actual OpenAPI yaml
''',
}
