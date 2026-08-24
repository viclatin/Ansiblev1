# NetBox deployment

The NetBox instance backing the AWX dynamic inventory runs in the `netbox`
namespace of the local k3s cluster, reachable on NodePort **30080**.

## manifests/

Recovered from the running cluster via each resource's
`kubectl.kubernetes.io/last-applied-configuration` annotation — the originals
existed nowhere on disk. Committed so the deployment is reproducible.

## snapshot/

A dump of every NetBox object taken before the 4.x rebuild, as a safety net.
Sixteen objects in total: 1 region, 5 sites, 1 manufacturer, 1 device type,
1 device role, 1 platform, 1 device, 4 interfaces, 1 IP address.
