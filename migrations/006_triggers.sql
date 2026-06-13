-- updated_at triggers for mutable tables.
DROP TRIGGER IF EXISTS trg_users_set_updated_at ON users;
CREATE TRIGGER trg_users_set_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tinode_user_mappings_set_updated_at ON tinode_user_mappings;
CREATE TRIGGER trg_tinode_user_mappings_set_updated_at
BEFORE UPDATE ON tinode_user_mappings
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_auth_sessions_set_updated_at ON auth_sessions;
CREATE TRIGGER trg_auth_sessions_set_updated_at
BEFORE UPDATE ON auth_sessions
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_auth_device_fingerprints_set_updated_at ON auth_device_fingerprints;
CREATE TRIGGER trg_auth_device_fingerprints_set_updated_at
BEFORE UPDATE ON auth_device_fingerprints
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_explorer_profiles_set_updated_at ON explorer_profiles;
CREATE TRIGGER trg_explorer_profiles_set_updated_at
BEFORE UPDATE ON explorer_profiles
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_connector_profiles_set_updated_at ON connector_profiles;
CREATE TRIGGER trg_connector_profiles_set_updated_at
BEFORE UPDATE ON connector_profiles
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_user_privacy_settings_set_updated_at ON user_privacy_settings;
CREATE TRIGGER trg_user_privacy_settings_set_updated_at
BEFORE UPDATE ON user_privacy_settings
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_travel_plans_set_updated_at ON travel_plans;
CREATE TRIGGER trg_travel_plans_set_updated_at
BEFORE UPDATE ON travel_plans
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_connection_requests_set_updated_at ON connection_requests;
CREATE TRIGGER trg_connection_requests_set_updated_at
BEFORE UPDATE ON connection_requests
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tinode_conversation_mappings_set_updated_at ON tinode_conversation_mappings;
CREATE TRIGGER trg_tinode_conversation_mappings_set_updated_at
BEFORE UPDATE ON tinode_conversation_mappings
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();
