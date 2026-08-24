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

## Upgrading to 4.6.8 — findings that changed the manifest

Verified by inspecting the `netboxcommunity/netbox:v4.6.8` image directly, not
assumed from documentation:

- **`SUPERUSER_NAME` / `_EMAIL` / `_PASSWORD` still work.** The entrypoint pipes
  `/opt/netbox/super_user.py` into `manage.py shell` unless `SKIP_SUPERUSER=true`.
- **API token creation changed.** `super_user.py` issues a token only when
  `SUPERUSER_API_TOKEN` *and* `SUPERUSER_API_KEY` are both set *and*
  `API_TOKEN_PEPPERS` is populated — which the docker config derives from
  `API_TOKEN_PEPPER_1`. The 3.2.8 manifest set only `SUPERUSER_API_TOKEN`, so
  carrying it forward unchanged would create the user with no token and only a
  warning in the log. All three are now set.
- **Token format changed.** v2 tokens (the default) authenticate as
  `Authorization: Bearer nbt_<key>.<token>`, not `Authorization: Token <token>`.
  Constants: prefix `nbt_`, key length 12, token length 40, charset
  `[A-Za-z0-9]`.
- **v1 tokens still work** (`TokenVersionChoices.V1`) and still use the
  `Token <value>` header. AWX's NetBox credential injects `NETBOX_TOKEN` as a
  bare string, which `nb_inventory` sends as `Token %s` — so **AWX needs a v1
  token**. The plugin does support v2 via the dict form
  (`token: {type: Bearer, value: ...}`), but that cannot be fed from the AWX
  credential's env injection.
- Probes were relaxed and a `startupProbe` added, because the first boot runs
  the full initial migration set and exceeded the old 30s readiness delay.

## Rebuild procedure

The 3.2.8 database (`netbox`) is left intact throughout; 4.6.8 uses a new,
empty database (`netbox4`) on the same postgres:16 instance, so rollback is a
manifest revert.

```bash
# 1. new empty database (already done)
kubectl -n netbox exec deploy/postgresql -- psql -U netbox -d netbox \
  -c "CREATE DATABASE netbox4 OWNER netbox;"

# 2. add the secrets 4.6.8 needs (values generated locally, never committed)
kubectl -n netbox patch secret netbox-secrets --type merge --patch-file <file>
#    keys: API_TOKEN_PEPPER_1, SUPERUSER_API_KEY, SUPERUSER_API_TOKEN_V4, SECRET_KEY_V4

# 3. deploy
kubectl -n netbox apply -f netbox/manifests/deploy-netbox.yaml
kubectl -n netbox rollout status deploy/netbox

# 4. confirm the version and that the upgrade actually bought what it was for
curl -s localhost:30080/api/status/ | python3 -m json.tool | grep netbox-version
#    then check Customization -> Custom Field Choice Sets -> Add shows "Choice Colors"
```

Rollback: `git revert` the manifest change and re-apply; the `netbox` database
is untouched.

## Verified outcome

4.6.8 came up cleanly, superuser and API token created. Confirmed on the running
instance:

- `GET /api/status/` (authenticated) reports `netbox-version: 4.6.8`,
  Django 6.0.8, Python 3.14.4. Note `/api/status/` now requires authentication;
  unauthenticated it returns nulls rather than an error.
- `OPTIONS /api/extras/custom-field-choice-sets/` exposes **`choice_colors`**, a
  mapping of choice value to a named colour. Available colours: `blue`, `indigo`,
  `purple`, `pink`, `red`, `orange`, `yellow`, `green`, `teal`, `cyan`, `gray`,
  `black`, `white`. Colours are **named, not hex** — the 3.2.8-era plan referred
  to hex values, which do not apply here.
- Custom field types now include `decimal` and `datetime` alongside the previous
  set.
- Databases side by side: `netbox` (3.2.8, 19 MB, untouched) and `netbox4`
  (4.6.8, 25 MB, live).

## Compliance labels — UI steps

**Customization -> Custom Field Choice Sets -> Add**, name `Compliance Status`:

| Value | Label | Colour |
| --- | --- | --- |
| `compliant` | Compliant | green |
| `partial` | Partial | yellow |
| `non-compliant` | Non-Compliant | red |
| `unknown` | Unknown | gray |

**Customization -> Custom Fields -> Add**, object type **DCIM > Device**:

| Name | Type | Notes |
| --- | --- | --- |
| `compliance_status` | Selection | the choice set above; default `unknown` |
| `compliance_notes` | Long text | failed controls, human readable |
| `compliance_score` | Integer | the 0-100 score |
| `compliance_checked` | Date | makes a stale reading visible |

The objects themselves (region, sites, manufacturer, device type, role,
platform, device, interfaces, IP) must be recreated too - the exact values are
in `snapshot/`. The platform slug must be **`ios`**: `group_vars/platforms_ios.yml`
is keyed on it and `site-device-target.yml` asserts every target resolves an
`ansible_network_os`.

## Still outstanding

- AWX credential 8 (`Netbox-API`) still holds the 3.2.8 token and will fail
  against 4.6.8. It needs a **v1** token, because AWX injects `NETBOX_TOKEN` as
  a bare string which `nb_inventory` sends as `Token <value>`; the auto-created
  superuser token is v2 (`Bearer nbt_<key>.<token>`) and will not authenticate
  that way.
