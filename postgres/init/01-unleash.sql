SELECT 'CREATE DATABASE unleash OWNER postgres'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'unleash')\gexec
