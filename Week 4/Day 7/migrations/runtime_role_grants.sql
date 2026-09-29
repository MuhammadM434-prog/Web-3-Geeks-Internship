-- Run while connected to the application database as the migration/schema owner.
-- Set these psql variables before including the file:
--   \set runtime_role voice_agent_runtime
--   \set migration_role voice_agent_migrator
-- The database owner grants CONNECT separately. This file grants table/sequence
-- access and defaults. Run as migration_role (the owner of migrated objects).
-- The runtime role intentionally receives DML only; it cannot create/alter/drop schema.

GRANT USAGE ON SCHEMA public TO :"runtime_role";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"runtime_role";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"runtime_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_role" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"runtime_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_role" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO :"runtime_role";
