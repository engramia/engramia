# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""A12 — CI/CD & Deployment snippets (good / medium / bad).

Domain: GitHub Actions workflows, Docker builds, staging deploy, release automation.
"""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "GitHub Actions workflow: lint → test → build Docker → deploy to staging. Matrix strategy, caching, OIDC auth.",
    "code": '''\
# .github/workflows/ci-deploy.yml
name: CI/CD Pipeline

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read
  id-token: write  # OIDC for AWS ECR

env:
  REGISTRY: 123456789.dkr.ecr.eu-central-1.amazonaws.com
  IMAGE_NAME: myapp
  PYTHON_VERSION: "3.12"

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pip install ruff mypy
      - run: ruff check .
      - run: mypy src/ --strict

  test:
    runs-on: ubuntu-latest
    needs: lint
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: testdb
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -e ".[test]"
      - run: pytest --cov=src --cov-report=xml --cov-fail-under=80
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/testdb
      - uses: codecov/codecov-action@v4
        with:
          file: coverage.xml
        if: github.event_name == 'push'

  build-and-deploy:
    runs-on: ubuntu-latest
    needs: test
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789:role/github-actions-ecr
          aws-region: eu-central-1

      - uses: aws-actions/amazon-ecr-login@v2
        id: ecr

      - name: Build and push Docker image
        run: |
          docker build -t $REGISTRY/$IMAGE_NAME:${{ github.sha }} .
          docker tag $REGISTRY/$IMAGE_NAME:${{ github.sha }} $REGISTRY/$IMAGE_NAME:latest
          docker push $REGISTRY/$IMAGE_NAME:${{ github.sha }}
          docker push $REGISTRY/$IMAGE_NAME:latest

      - name: Deploy to staging
        run: |
          aws ecs update-service \\
            --cluster staging \\
            --service myapp-staging \\
            --force-new-deployment \\
            --query 'service.taskDefinition'

      - name: Wait for deployment
        run: |
          aws ecs wait services-stable \\
            --cluster staging \\
            --services myapp-staging \\
            --timeout 300
''',
}

MEDIUM: dict = {
    "eval_score": 5.5,
    "output": "CI workflow with test and build steps.",
    "code": '''\
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[test]"
      - run: pytest

  build:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t myapp .
''',
}

BAD: dict = {
    "eval_score": 2.5,
    "output": "workflow file",
    "code": '''\
# ci.yml
name: CI
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: python -m pytest
      # TODO: add docker build
      # TODO: add deploy step
''',
}
