CREATE MACRO fdd_try_double(value) AS TRY_CAST(value AS DOUBLE);
CREATE MACRO fdd_is_nan(value) AS CASE WHEN isnan(value) THEN 1 ELSE 0 END;
CREATE MACRO fdd_elapsed_seconds(start_time,end_time) AS EXTRACT(EPOCH FROM (end_time-start_time));
CREATE MACRO fdd_hour_bucket_utc(value) AS date_trunc('hour',value AT TIME ZONE 'UTC');
CREATE MACRO fdd_month_key_utc(value) AS strftime(value AT TIME ZONE 'UTC','%Y-%m');
