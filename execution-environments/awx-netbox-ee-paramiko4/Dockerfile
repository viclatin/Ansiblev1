# awx-netbox-ee with paramiko pinned below 5.
#
# paramiko 5.0 removed SHA-1 key exchange. IOS 15.2 (including IOSvL2) offers
# only diffie-hellman-group-exchange-sha1, -group14-sha1 and -group1-sha1, so
# network_cli over paramiko 5 fails with "no acceptable kex algorithm" before
# authenticating. paramiko 4.x still offers those alongside the SHA-2 methods
# modern IOS-XE uses. Built on the exact current image so nothing else changes.
FROM 192.168.1.95:5000/awx-netbox-ee@sha256:71affc79f1eb38db3fbcd105a1f3a310b79d7a752d8f762ea3a382de085bbf47
USER root
RUN /usr/bin/python3.12 -m pip install --no-cache-dir "paramiko>=3.5.1,<5"
USER 1000
