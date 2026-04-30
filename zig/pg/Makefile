F=

.PHONY: t
t:
	TEST_FILTER="${F}" zig build test --summary all -freference-trace

.PHONY: d
d:
	cd tests && docker compose up

.PHONY: ssl
ssl:
	openssl req -days 3650 -new -text -nodes -subj '/C=SG/ST=SG/L=SG/O=Personal/OU=Personal/CN=localhost' -keyout tests/server.key -out tests/server.csr
	openssl req -days 3650 -x509 -text -in tests/server.csr -key tests/server.key -out tests/server.crt
	rm tests/server.csr
	cp tests/server.crt tests/root.crt

	openssl req -days 3650 -new -nodes -subj '/C=SG/ST=SG/L=SG/O=Personal/OU=Personal/CN=localhost/CN=testclient1' -keyout tests/client.key -out tests/client.csr
	openssl x509 -days 3650 -req  -CAcreateserial -in tests/client.csr -CA tests/root.crt -CAkey tests/server.key -out tests/client.crt
	rm tests/client.csr
