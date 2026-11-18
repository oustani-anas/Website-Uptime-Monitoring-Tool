-- Runs once, on first start with an empty data volume.
-- Creates an isolated database for pytest so tests never touch real data.
CREATE DATABASE uptime_test;
