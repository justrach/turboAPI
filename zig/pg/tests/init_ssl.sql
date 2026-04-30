ALTER SYSTEM SET ssl_ca_file TO '/etc/postgresql/root.crt';
ALTER SYSTEM SET ssl_key_file TO '/etc/postgresql/server.key';
ALTER SYSTEM SET ssl_cert_file TO '/etc/postgresql/server.crt';
ALTER SYSTEM SET ssl TO 'ON';
