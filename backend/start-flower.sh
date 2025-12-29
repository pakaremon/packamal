#!/bin/bash
# Wait for Redis to be ready
echo "Waiting for Redis..."
sleep 5

# Try to connect to Redis using Python
until python -c "import redis; r = redis.Redis(host='redis', port=6379); r.ping()" > /dev/null 2>&1; do
  echo "Redis not ready yet, waiting..."
  sleep 2
done

echo "Redis is ready! Starting Flower..."
# READ BROKER FROM ENV VARIABLES
BROKER_URL=$(echo $CELERY_BROKER_URL)
celery -A packamal flower --port=5555 --broker=$BROKER_URL
