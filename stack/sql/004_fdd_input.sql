-- FDD rule input mapping (e.g. sat, mat, oat for AHU rules)
ALTER TABLE points ADD COLUMN IF NOT EXISTS fdd_input text;
