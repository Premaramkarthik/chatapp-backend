CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS geo_countries (
    iso_alpha2 CHAR(2) PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS geo_cities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    country_iso CHAR(2) NOT NULL REFERENCES geo_countries(iso_alpha2),
    name TEXT NOT NULL,
    admin1_code TEXT,
    latitude NUMERIC(9, 6),
    longitude NUMERIC(9, 6),
    slug TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT geo_cities_country_slug_unique UNIQUE (country_iso, slug)
);

CREATE INDEX IF NOT EXISTS idx_geo_cities_country ON geo_cities(country_iso);
CREATE INDEX IF NOT EXISTS idx_geo_cities_name_trgm ON geo_cities USING gin (name gin_trgm_ops);

INSERT INTO geo_countries (iso_alpha2, name, region) VALUES
    ('US', 'United States', 'Americas'),
    ('GB', 'United Kingdom', 'Europe'),
    ('CA', 'Canada', 'Americas'),
    ('AU', 'Australia', 'Oceania'),
    ('IN', 'India', 'Asia'),
    ('DE', 'Germany', 'Europe'),
    ('FR', 'France', 'Europe'),
    ('SG', 'Singapore', 'Asia'),
    ('AE', 'United Arab Emirates', 'Asia'),
    ('JP', 'Japan', 'Asia')
ON CONFLICT (iso_alpha2) DO NOTHING;

INSERT INTO geo_cities (country_iso, name, admin1_code, latitude, longitude, slug) VALUES
    ('US', 'New York', 'NY', 40.712800, -74.006000, 'new-york-ny-us'),
    ('US', 'San Francisco', 'CA', 37.774900, -122.419400, 'san-francisco-ca-us'),
    ('US', 'Los Angeles', 'CA', 34.052200, -118.243700, 'los-angeles-ca-us'),
    ('GB', 'London', 'ENG', 51.507400, -0.127800, 'london-eng-gb'),
    ('CA', 'Toronto', 'ON', 43.653200, -79.383200, 'toronto-on-ca'),
    ('AU', 'Sydney', 'NSW', -33.868800, 151.209300, 'sydney-nsw-au'),
    ('IN', 'Mumbai', 'MH', 19.076000, 72.877700, 'mumbai-mh-in'),
    ('IN', 'Bengaluru', 'KA', 12.971600, 77.594600, 'bengaluru-ka-in'),
    ('DE', 'Berlin', 'BE', 52.520000, 13.405000, 'berlin-be-de'),
    ('FR', 'Paris', 'IDF', 48.856600, 2.352200, 'paris-idf-fr'),
    ('SG', 'Singapore', NULL, 1.352100, 103.819800, 'singapore-sg'),
    ('AE', 'Dubai', 'DU', 25.204800, 55.270800, 'dubai-du-ae'),
    ('JP', 'Tokyo', '13', 35.676200, 139.650300, 'tokyo-13-jp')
ON CONFLICT (country_iso, slug) DO NOTHING;
