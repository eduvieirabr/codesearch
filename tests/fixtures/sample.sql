CREATE OR REPLACE FUNCTION get_monthly_revenue(month INT)
RETURNS DECIMAL AS $$
BEGIN
  RETURN 0;
END;
$$ LANGUAGE plpgsql;

CREATE VIEW v_sales_summary AS
SELECT date, SUM(amount) FROM orders GROUP BY date;

CREATE TABLE raw_transactions (
    id SERIAL PRIMARY KEY,
    amount DECIMAL NOT NULL
);

CREATE TABLE IF NOT EXISTS bronze.events (
    id SERIAL PRIMARY KEY
);
