#!/bin/bash

set -e

# Set namespace
NAMESPACE="${NAMESPACE:-packamal}"

# Get database pod name
DB_POD_NAME=$(kubectl get pods -n "$NAMESPACE" -l app=database -o jsonpath='{.items[0].metadata.name}')

if [ -z "$DB_POD_NAME" ]; then
    echo "Error: Database pod not found in namespace '$NAMESPACE'"
    exit 1
fi

echo "Connecting to database pod: $DB_POD_NAME"
echo ""

# Get database credentials from configmap and secret
POSTGRES_DB=$(kubectl get configmap packamal-config -n "$NAMESPACE" -o jsonpath='{.data.POSTGRES_DB}')
POSTGRES_USER=$(kubectl get configmap packamal-config -n "$NAMESPACE" -o jsonpath='{.data.POSTGRES_USER}')
POSTGRES_PASSWORD=$(kubectl get secret packamal-secrets -n "$NAMESPACE" -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)

if [ -z "$POSTGRES_DB" ] || [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_PASSWORD" ]; then
    echo "Error: Could not retrieve database credentials"
    exit 1
fi

echo "Database: $POSTGRES_DB"
echo "User: $POSTGRES_USER"
echo ""
echo "Type '\q' to exit, '\dt' to list tables, '\d table_name' to describe a table"
echo "Example queries:"
echo "  SELECT * FROM package_analysis_analysistask LIMIT 10;"
echo "  SELECT id, report_id FROM package_analysis_analysistask WHERE report_id IS NOT NULL;"
echo "  DELETE FROM package_analysis_analysistask WHERE id = <id>;"
echo ""

# Export password and connect to psql
export PGPASSWORD="$POSTGRES_PASSWORD"
kubectl exec -it -n "$NAMESPACE" "$DB_POD_NAME" -- psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

