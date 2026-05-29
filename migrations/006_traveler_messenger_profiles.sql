CREATE TABLE IF NOT EXISTS traveler_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    headline TEXT,
    bio TEXT,
    avatar_url TEXT,
    home_country_iso CHAR(2) REFERENCES geo_countries(iso_alpha2),
    home_city_id UUID REFERENCES geo_cities(id),
    languages TEXT[] NOT NULL DEFAULT '{}',
    interests TEXT[] NOT NULL DEFAULT '{}',
    connection_availability TEXT NOT NULL DEFAULT 'open',
    visibility TEXT NOT NULL DEFAULT 'discoverable',
    onboarding_step TEXT,
    profile_completed_at TIMESTAMPTZ,
    last_active_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT traveler_profiles_availability_check CHECK (
        connection_availability IN ('open', 'limited', 'unavailable')
    ),
    CONSTRAINT traveler_profiles_visibility_check CHECK (
        visibility IN ('discoverable', 'connections_only', 'hidden')
    )
);

CREATE INDEX IF NOT EXISTS idx_traveler_profiles_discoverable
    ON traveler_profiles(visibility, connection_availability)
    WHERE visibility = 'discoverable';

CREATE INDEX IF NOT EXISTS idx_traveler_profiles_home_country
    ON traveler_profiles(home_country_iso);

DROP TRIGGER IF EXISTS trg_traveler_profiles_set_updated_at ON traveler_profiles;
CREATE TRIGGER trg_traveler_profiles_set_updated_at
BEFORE UPDATE ON traveler_profiles
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS messenger_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    home_country_iso CHAR(2) REFERENCES geo_countries(iso_alpha2),
    home_city_id UUID REFERENCES geo_cities(id),
    preferred_destination_countries CHAR(2)[] NOT NULL DEFAULT '{}',
    bio TEXT,
    last_search_country_iso CHAR(2) REFERENCES geo_countries(iso_alpha2),
    last_search_city_id UUID REFERENCES geo_cities(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_messenger_profiles_set_updated_at ON messenger_profiles;
CREATE TRIGGER trg_messenger_profiles_set_updated_at
BEFORE UPDATE ON messenger_profiles
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS user_privacy_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    allow_connection_requests BOOLEAN NOT NULL DEFAULT true,
    allow_search_discovery BOOLEAN NOT NULL DEFAULT true,
    show_current_location BOOLEAN NOT NULL DEFAULT true,
    show_trip_dates BOOLEAN NOT NULL DEFAULT true,
    show_online_status BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS trg_user_privacy_settings_set_updated_at ON user_privacy_settings;
CREATE TRIGGER trg_user_privacy_settings_set_updated_at
BEFORE UPDATE ON user_privacy_settings
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();
