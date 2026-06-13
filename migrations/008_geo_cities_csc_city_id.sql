-- CSC dataset uses duplicate city names within the same state; upsert on CSC source id instead.

ALTER TABLE geo_cities ADD COLUMN IF NOT EXISTS csc_city_id BIGINT;

DROP INDEX IF EXISTS idx_geo_cities_state_name_unique;

CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_cities_csc_city_id_unique
    ON geo_cities (csc_city_id);

CREATE INDEX IF NOT EXISTS idx_geo_cities_state_name
    ON geo_cities (state_id, name);
