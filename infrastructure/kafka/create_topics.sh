#!/bin/bash
# ============================================================
# CDS — Kafka Topic Initialization Script
# Usage: ./create_topics.sh [broker_host:port]
# Example: ./create_topics.sh localhost:29092
# ============================================================
set -e

BROKER="${1:-localhost:29092}"
REPLICATION_FACTOR=3

echo "Creating CDS Kafka topics on broker: $BROKER"

create_topic() {
    local TOPIC=$1
    local PARTITIONS=$2
    local RETENTION_MS=$3
    echo "  + $TOPIC (partitions=$PARTITIONS)"
    kafka-topics.sh --bootstrap-server "$BROKER" --create --if-not-exists \
        --topic "$TOPIC" \
        --partitions "$PARTITIONS" \
        --replication-factor "$REPLICATION_FACTOR" \
        --config "retention.ms=$RETENTION_MS" \
        --config "cleanup.policy=delete" \
        --config "compression.type=lz4" || true
}

SEVEN_DAYS=$((7 * 24 * 60 * 60 * 1000))
THIRTY_DAYS=$((30 * 24 * 60 * 60 * 1000))
NINETY_DAYS=$((90 * 24 * 60 * 60 * 1000))

echo "--- Audit (immutable, 90-day retention) ---"
create_topic "audit.events" 3 "$NINETY_DAYS"

echo "--- Raw ingestion ---"
create_topic "raw.water_dept_api.meter_reading" 3 "$SEVEN_DAYS"
create_topic "raw.water_dept_api.sensor_data" 3 "$SEVEN_DAYS"
create_topic "raw.transport_dept_api.vehicle" 3 "$SEVEN_DAYS"
create_topic "raw.iot.sensor_generic" 6 "$SEVEN_DAYS"

echo "--- Validated ---"
create_topic "validated.water_dept_api.meter_reading" 3 "$THIRTY_DAYS"
create_topic "validated.water_dept_api.sensor_data" 3 "$THIRTY_DAYS"
create_topic "validated.transport_dept_api.vehicle" 3 "$THIRTY_DAYS"
create_topic "validated.iot.sensor_generic" 6 "$THIRTY_DAYS"

echo "--- Processed (canonical) ---"
create_topic "processed.water_dept_api.meter_reading" 3 "$THIRTY_DAYS"
create_topic "processed.water_dept_api.sensor_data" 3 "$THIRTY_DAYS"
create_topic "processed.transport_dept_api.vehicle" 3 "$THIRTY_DAYS"
create_topic "processed.iot.sensor_generic" 6 "$THIRTY_DAYS"

echo "--- KPI computed ---"
create_topic "kpi.computed.water.daily_consumption" 3 "$THIRTY_DAYS"
create_topic "kpi.computed.water.network_efficiency" 3 "$THIRTY_DAYS"
create_topic "kpi.computed.transport.avg_response_time" 3 "$THIRTY_DAYS"
create_topic "kpi.computed.transport.fleet_utilization" 3 "$THIRTY_DAYS"
create_topic "kpi.computed.city.service_satisfaction" 3 "$THIRTY_DAYS"

echo "--- System events ---"
create_topic "monitoring.threshold_breach" 3 "$THIRTY_DAYS"
create_topic "governance.freshness_breach" 1 "$THIRTY_DAYS"
create_topic "notification.send" 3 "$SEVEN_DAYS"

echo "--- Dead letter queues ---"
create_topic "dlq.raw.water_dept_api.meter_reading" 1 "$THIRTY_DAYS"
create_topic "dlq.raw.water_dept_api.sensor_data" 1 "$THIRTY_DAYS"
create_topic "dlq.raw.iot.sensor_generic" 1 "$THIRTY_DAYS"

echo "--- AI recommendations ---"
create_topic "ai.recommendations.WATER" 3 "$SEVEN_DAYS"
create_topic "ai.recommendations.TRANSPORT" 3 "$SEVEN_DAYS"

echo ""
echo "All CDS Kafka topics created."
kafka-topics.sh --bootstrap-server "$BROKER" --list | sort
