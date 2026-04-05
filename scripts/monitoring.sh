#!/usr/bin/env bash
# Engramia Monitoring Stack management script
# Usage: ./scripts/monitoring.sh {start|stop|status|logs|restart}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

COMPOSE_FILES="-f ${PROJECT_DIR}/docker-compose.prod.yml -f ${PROJECT_DIR}/docker-compose.monitoring.yml"

# Monitoring-only services (excludes prod services)
MONITORING_SERVICES="prometheus alertmanager loki promtail grafana uptime-kuma"

usage() {
    echo "Usage: $0 {start|stop|status|logs|restart}"
    echo ""
    echo "Commands:"
    echo "  start    Start monitoring stack (requires prod stack running)"
    echo "  stop     Stop monitoring services only"
    echo "  status   Show status of all services"
    echo "  logs     Tail logs from monitoring services"
    echo "  restart  Restart monitoring services"
    echo ""
    echo "Full stack (prod + monitoring):"
    echo "  $0 start-all   Start prod + monitoring together"
    echo "  $0 stop-all    Stop everything"
    exit 1
}

cmd_start() {
    echo "Starting monitoring stack..."
    docker compose ${COMPOSE_FILES} up -d ${MONITORING_SERVICES}
    echo ""
    echo "Monitoring started:"
    echo "  Grafana:      http://localhost:3000"
    echo "  Prometheus:   http://localhost:9090"
    echo "  Alertmanager: http://localhost:9093"
    echo "  Uptime Kuma:  http://localhost:3001"
}

cmd_stop() {
    echo "Stopping monitoring services..."
    docker compose ${COMPOSE_FILES} stop ${MONITORING_SERVICES}
    docker compose ${COMPOSE_FILES} rm -f ${MONITORING_SERVICES}
}

cmd_status() {
    docker compose ${COMPOSE_FILES} ps
}

cmd_logs() {
    docker compose ${COMPOSE_FILES} logs -f --tail=100 ${MONITORING_SERVICES}
}

cmd_restart() {
    cmd_stop
    cmd_start
}

cmd_start_all() {
    echo "Starting prod + monitoring stack..."
    docker compose ${COMPOSE_FILES} up -d
    echo ""
    echo "All services started."
}

cmd_stop_all() {
    echo "Stopping all services..."
    docker compose ${COMPOSE_FILES} down
}

case "${1:-}" in
    start)     cmd_start ;;
    stop)      cmd_stop ;;
    status)    cmd_status ;;
    logs)      cmd_logs ;;
    restart)   cmd_restart ;;
    start-all) cmd_start_all ;;
    stop-all)  cmd_stop_all ;;
    *)         usage ;;
esac
