CREATE TABLE IF NOT EXISTS travel_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    start_date DATE,
    end_date DATE,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT travel_plans_status_check CHECK (
        status IN ('draft', 'active', 'completed', 'cancelled')
    ),
    CONSTRAINT travel_plans_dates_check CHECK (
        start_date IS NULL OR end_date IS NULL OR start_date <= end_date
    )
);

CREATE INDEX IF NOT EXISTS idx_travel_plans_user_status ON travel_plans(user_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_travel_plans_one_primary_per_user
    ON travel_plans(user_id)
    WHERE is_primary = true AND status = 'active';

DROP TRIGGER IF EXISTS trg_travel_plans_set_updated_at ON travel_plans;
CREATE TRIGGER trg_travel_plans_set_updated_at
BEFORE UPDATE ON travel_plans
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS travel_plan_destinations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    travel_plan_id UUID NOT NULL REFERENCES travel_plans(id) ON DELETE CASCADE,
    country_iso CHAR(2) NOT NULL REFERENCES geo_countries(iso_alpha2),
    city_id UUID REFERENCES geo_cities(id),
    sort_order INT NOT NULL DEFAULT 0,
    arrival_date DATE,
    departure_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT travel_plan_destinations_dates_check CHECK (
        arrival_date IS NULL OR departure_date IS NULL OR arrival_date <= departure_date
    )
);

CREATE INDEX IF NOT EXISTS idx_travel_plan_destinations_plan
    ON travel_plan_destinations(travel_plan_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_travel_plan_destinations_country
    ON travel_plan_destinations(country_iso);

CREATE TABLE IF NOT EXISTS traveler_current_locations (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    country_iso CHAR(2) REFERENCES geo_countries(iso_alpha2),
    city_id UUID REFERENCES geo_cities(id),
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    source TEXT NOT NULL DEFAULT 'manual',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT traveler_current_locations_source_check CHECK (
        source IN ('manual', 'gps', 'inferred')
    )
);

CREATE INDEX IF NOT EXISTS idx_traveler_current_locations_country
    ON traveler_current_locations(country_iso);
