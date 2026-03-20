CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    age INT NOT NULL
);

INSERT INTO users (name, email, age)
SELECT 'user_' || i, 'user_' || i || '@test.com', 20 + (i % 50)
FROM generate_series(1, 1000) AS i
ON CONFLICT DO NOTHING;
