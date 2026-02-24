-- Which points the BACnet scraper should poll. Default true so existing points keep being polled.
ALTER TABLE points ADD COLUMN IF NOT EXISTS polling boolean DEFAULT true;
CREATE INDEX IF NOT EXISTS idx_points_polling ON points (polling) WHERE polling IS NOT TRUE;
