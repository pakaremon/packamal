#!/bin/bash
set -e

echo "===== Pack-A-Mal Backend Starting ====="

echo "Waiting for database..."
while ! pg_isready -h database -p 5432 -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
  echo "  Database not ready yet, waiting..."
  sleep 0.5
done
echo "✓ Database is ready!"

echo "Making migrations..."
python manage.py makemigrations
echo "✓ Migrations made!"

echo "Running migrations..."
python manage.py migrate --noinput
echo "✓ Migrations complete!"

echo "Collecting static files..."
python manage.py collectstatic --noinput --clear
echo "✓ Static files collected!"

echo "===== Starting Django development server ====="
exec "$@"
