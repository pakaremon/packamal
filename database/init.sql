-- Note: Database and user are created automatically by PostgreSQL container
-- from POSTGRES_DB and POSTGRES_USER environment variables
-- This script runs after the database is created and is already connected to it

-- Create user if it doesn't exist (idempotent)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'packamal_db') THEN
    CREATE USER packamal_db WITH PASSWORD 'rock-beryl-say-devices';
  END IF;
END
$$;

-- Configure user settings
ALTER ROLE packamal_db SET client_encoding TO 'utf8';
ALTER ROLE packamal_db SET default_transaction_isolation TO 'read committed';
ALTER ROLE packamal_db SET timezone TO 'UTC';

-- Grant ONLY necessary privileges (not superuser)
GRANT CONNECT ON DATABASE packamal TO packamal_db;
GRANT USAGE ON SCHEMA public TO packamal_db;

-- Grant privileges on existing tables
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO packamal_db;

-- Grant privileges on sequences (for auto-increment fields)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO packamal_db;

-- Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO packamal_db;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO packamal_db;

-- Full privileges ==> Caution
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO packamal_db;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO packamal_db;

-- Revoke public schema access from public role
REVOKE ALL ON SCHEMA public FROM public;