-- Marks this database as the throwaway local test database (read by the live guard check).
-- Runs once on first start of a fresh container; data is on tmpfs, so it reruns every time.
ALTER DATABASE strativa_test SET app.test_db_marker = 'local-throwaway-v1';
