-- Runs once, on the first start of an empty volume. Lets the app user create the test database
-- (`manage.py test` makes test_<DB_NAME>). Development only: production users get no such grant.
GRANT ALL PRIVILEGES ON `test\_%`.* TO 'dzen'@'%';
FLUSH PRIVILEGES;
