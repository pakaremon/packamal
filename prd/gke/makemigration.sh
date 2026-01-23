#!usr/bin/bash

# Đường dẫn tới thư mục backend của bạn
BACKEND_PATH="/home/packamal/backend"

# Lấy UID và GID của user hiện tại
HOST_UID=$(id -u)
HOST_GID=$(id -g)

# Tạo thư mục migrations trên host trước và set permissions
mkdir -p "$BACKEND_PATH/package_analysis/migrations"
touch "$BACKEND_PATH/package_analysis/migrations/__init__.py"
chmod -R 777 "$BACKEND_PATH/package_analysis/migrations"

docker run --rm \
  -v "$BACKEND_PATH":/app \
  -w /app \
  -e POSTGRES_HOST="" \
  -e POSTGRES_DB="dummy" \
  -e POSTGRES_USER="dummy" \
  -e POSTGRES_PASSWORD="dummy" \
  python:3.11-slim \
  /bin/bash -c "apt-get update && apt-get install -y git && \
    pip install -r requirements.txt && \
    python manage.py makemigrations package_analysis --verbosity 2"