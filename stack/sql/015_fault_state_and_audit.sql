-- Fault state: current active fault per (site, equipment, fault_id) for HA binary_sensors
CREATE TABLE IF NOT EXISTS fault_state (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id text NOT NULL,
    equipment_id text NOT NULL,
    fault_id text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    last_changed_ts timestamptz NOT NULL DEFAULT now(),
    last_evaluated_ts timestamptz,
    context jsonb,
    UNIQUE(site_id, equipment_id, fault_id)
);

CREATE INDEX IF NOT EXISTS idx_fault_state_site ON fault_state(site_id);
CREATE INDEX IF NOT EXISTS idx_fault_state_equipment ON fault_state(site_id, equipment_id);
CREATE INDEX IF NOT EXISTS idx_fault_state_active ON fault_state(active) WHERE active = true;

-- BACnet write audit (HA/Node-RED write via Open-FDD only)
CREATE TABLE IF NOT EXISTS bacnet_write_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    point_id uuid NOT NULL REFERENCES points(id) ON DELETE CASCADE,
    value double precision NOT NULL,
    source text,
    ts timestamptz NOT NULL DEFAULT now(),
    success boolean NOT NULL,
    reason text
);

CREATE INDEX IF NOT EXISTS idx_bacnet_write_audit_point ON bacnet_write_audit(point_id);
CREATE INDEX IF NOT EXISTS idx_bacnet_write_audit_ts ON bacnet_write_audit(ts);
