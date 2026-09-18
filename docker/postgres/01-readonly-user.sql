CREATE ROLE analytics_ro LOGIN PASSWORD 'analytics_ro';

GRANT CONNECT ON DATABASE analytics TO analytics_ro;
GRANT USAGE ON SCHEMA public TO analytics_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE analytics IN SCHEMA public
    GRANT SELECT ON TABLES TO analytics_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE analytics IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO analytics_ro;
