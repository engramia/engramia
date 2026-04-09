#!/bin/bash
# /opt/engramia/scripts/env-manager.sh
# Engramia Environment Manager — CX33
#
# Usage: ./scripts/env-manager.sh <action> [environment]
#   start   <staging|test>  — start environment with health check
#   stop    <staging|test>  — stop and clean up
#   status  <staging|test>  — show container status + resource usage
#   status-all              — show all environments
#   logs    <staging|test>  — follow logs
#   seed    <staging|test>  — seed staging DB or reset test DB
#   help                    — show this help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

ACTION=${1:-help}
ENV=${2:-}

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_resources() {
    local available_mb
    available_mb=$(awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo)
    echo -e "Available RAM: ${available_mb} MB"
    if [ "$available_mb" -lt 500 ]; then
        echo -e "${RED}WARNING: Less than 500 MB available RAM!${NC}"
        echo "Consider stopping other environments first."
        return 1
    fi
    return 0
}

require_env() {
    if [ -z "${ENV}" ]; then
        echo -e "${RED}Error: environment required (staging|test)${NC}"
        exit 1
    fi
    if [[ "$ENV" != "staging" && "$ENV" != "test" ]]; then
        echo -e "${RED}Error: unknown environment '${ENV}' — use staging or test${NC}"
        exit 1
    fi
}

compose_file() {
    echo "${PROJECT_DIR}/docker-compose.${ENV}.yml"
}

env_file() {
    echo "${PROJECT_DIR}/.env.${ENV}"
}

health_port() {
    [ "$ENV" = "staging" ] && echo "8100" || echo "8200"
}

cd "$PROJECT_DIR"

case "$ACTION" in
  start)
    require_env

    local_env_file="$(env_file)"
    if [ ! -f "$local_env_file" ]; then
        echo -e "${RED}Error: ${local_env_file} not found.${NC}"
        echo "Copy .env.${ENV}.example to .env.${ENV} and fill in the values."
        exit 1
    fi

    echo -e "${YELLOW}Starting $ENV environment...${NC}"
    check_resources || echo "Proceeding anyway (swap available)..."

    docker compose -f "$(compose_file)" --env-file "$local_env_file" pull --quiet
    docker compose -f "$(compose_file)" --env-file "$local_env_file" up -d

    echo "Waiting for API health check (port $(health_port))..."
    port="$(health_port)"
    for i in $(seq 1 30); do
        if curl -sf "http://localhost:${port}/v1/health" > /dev/null 2>&1; then
            echo -e "${GREEN}${ENV} API healthy${NC}"
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo -e "${RED}Health check failed after 60s — check logs:${NC}"
            docker compose -f "$(compose_file)" logs --tail=30
            exit 1
        fi
        sleep 2
    done

    echo ""
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" \
        | grep -E "(NAME|engramia)" || true
    ;;

  stop)
    require_env
    echo -e "${YELLOW}Stopping $ENV environment...${NC}"

    if [ "$ENV" = "test" ]; then
        docker compose -f "$(compose_file)" down -v
        echo "Test volumes removed."
    else
        docker compose -f "$(compose_file)" down
    fi

    docker system prune -f --filter "label!=keep" > /dev/null 2>&1 || true
    echo -e "${GREEN}${ENV} stopped.${NC}"
    ;;

  status)
    require_env
    echo -e "${YELLOW}=== $ENV environment ===${NC}"
    docker compose -f "$(compose_file)" ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null \
        || echo "Not running."
    echo ""
    echo -e "${YELLOW}=== Resource usage ===${NC}"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" \
        | grep -E "(NAME|${ENV})" 2>/dev/null || echo "No containers running."
    ;;

  status-all)
    echo -e "${YELLOW}=== All environments ===${NC}"
    echo ""
    echo "--- Production ---"
    docker compose -f "${PROJECT_DIR}/docker-compose.prod.yml" ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null \
        || echo "Not running."
    echo ""
    echo "--- Staging ---"
    docker compose -f "${PROJECT_DIR}/docker-compose.staging.yml" ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null \
        || echo "Not running."
    echo ""
    echo "--- Test ---"
    docker compose -f "${PROJECT_DIR}/docker-compose.test.yml" ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null \
        || echo "Not running."
    echo ""
    echo -e "${YELLOW}=== System resources ===${NC}"
    free -h
    echo ""
    df -h / | tail -1
    echo ""
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" \
        | grep -E "(NAME|engramia)" || true
    ;;

  logs)
    require_env
    docker compose -f "$(compose_file)" logs -f --tail=100
    ;;

  seed)
    require_env
    if [ "$ENV" = "staging" ]; then
        echo "Seeding staging DB..."
        "${SCRIPT_DIR}/seed-staging.sh"
    elif [ "$ENV" = "test" ]; then
        echo "Resetting test DB..."
        "${SCRIPT_DIR}/reset-test-db.sh"
    fi
    ;;

  help|*)
    echo "Engramia Environment Manager (CX33)"
    echo ""
    echo "Usage: $0 <action> [environment]"
    echo ""
    echo "Actions:"
    echo "  start <env>      Start environment, wait for health check"
    echo "  stop <env>       Stop environment and clean up"
    echo "  status <env>     Show container status + resource usage"
    echo "  status-all       Show all environments + system resources"
    echo "  logs <env>       Follow environment logs"
    echo "  seed <env>       Seed staging DB or reset test DB"
    echo "  help             Show this help"
    echo ""
    echo "Environments: staging, test"
    ;;
esac
