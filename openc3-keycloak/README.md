## Keycloak for WarpLink role based access control

Keycloak is the identity provider: it authenticates people and says which roles
they hold. What a role *grants* is defined in COSMOS itself (`RoleModel`), not
here, so permissions can be tuned from the Admin tool without touching Keycloak.

Keycloak is self-hosted open source software. There is no account to create with
any vendor - the container in `compose.yaml` runs entirely on your own
infrastructure.

### Two realms, and why logins get confused

Keycloak always has a `master` realm holding its own administrators, and this
setup adds an `openc3` realm holding WarpLink users. They are separate user
stores.

| | Realm | Who lives there | Credentials from |
|---|---|---|---|
| Admin console at `:8080` | `master` | Keycloak administrators | `OPENC3_KEYCLOAK_ADMIN_*` in `.env` |
| WarpLink login at `:2900` | `openc3` | Operators | Set per user, see below |

The admin console password does **not** work for logging into WarpLink. When
working in the console, check the realm selector in the top left says `openc3`
before creating users or assigning roles.

### Adding a user

1. Open `http://localhost:8080`, sign in with the credentials from `.env`.
2. Switch the realm selector (top left) to **openc3**.
3. **Users** -> **Add user**. Fill in the username, then **Create**.
4. **Credentials** tab -> **Set password**. Turn **Temporary** off unless you
   want them forced to change it on first login.
5. **Role mapping** tab -> **Assign role**. Change the filter dropdown from
   *Filter by clients* to **Filter by realm roles**, otherwise you only see
   `realm-management` entries and none of the WarpLink roles.
6. Pick `admin`, `operator`, or `viewer`.

Or from the command line:

```bash
KC="docker exec cosmos-openc3-keycloak-1 /opt/keycloak/bin/kcadm.sh"
$KC config credentials --server http://localhost:8080/auth \
   --realm master --user admin --password admin

$KC create users -r openc3 -s username=jdoe -s enabled=true -s 'requiredActions=[]'
$KC set-password -r openc3 --username jdoe --new-password 'CHANGE_ME_12+' --temporary=false
$KC add-roles -r openc3 --uusername jdoe --rolename operator
```

#### When a login is rejected

Check these in order - all three present as "invalid username or password":

- **No password set.** Creating a user does not create a credential. The
  Credentials tab will be empty. This is the most common cause.
- **Locked out.** The realm locks an account after 10 failed attempts. Clear it
  with `$KC delete attack-detection/brute-force/users/<id> -r openc3`.
- **Wrong realm.** Using the admin console password against the WarpLink login.

The realm enforces a password policy: at least 12 characters, not equal to the
username, and no reuse of the last 3. A password that violates it is rejected
when you set it, not when you log in. Adjust `passwordPolicy` in
`realm-openc3.json` if that does not suit you.

### Branding the login page

`themes/warplink/` is a Keycloak login theme carrying the WarpLink logo and
wording. It sets `parent=keycloak.v2` and overrides only three things, so
Keycloak upgrades bring their own markup and styling without the theme needing
to keep up:

| File | Overrides |
| --- | --- |
| `resources/img/warp-logo.png` | The logo image |
| `resources/css/warplink.css` | Points `div.kc-logo-text` at that image |
| `messages/messages_en.properties` | `loginAccountTitle`, the heading above the form |

Two separate settings control the wording, which is easy to trip over:

- The **browser tab** reads the realm's `displayName` ("WarpLink").
- The **heading on the page** is the `loginAccountTitle` message. It ignores the
  display name entirely, which is why it stays "Sign in to your account" until
  the theme overrides it.

The theme is applied by `loginTheme` on the realm. It is in
`realm-openc3.json` for fresh installs; on a realm that already exists, set it
under **Realm settings** -> **Themes**, or:

```bash
$KC update realms/openc3 -s loginTheme=warplink
```

The directory is bind mounted into the container, so editing CSS or messages
only needs a Keycloak restart, not a rebuild. Note that Keycloak caches theme
resources aggressively in production mode; under `start-dev` it does not.

### The roles

| Role | Grants |
|---|---|
| `admin` | Everything, including simulation control and role administration |
| `operator` | Commands and scripts on every target except `SIM`; no Sim Control tool |
| `viewer` | Read-only telemetry and scripts; no `SIM`, no Sim Control tool |

Role *names* live in Keycloak; what they *grant* lives in COSMOS. A role
Keycloak knows about but COSMOS has no definition for grants nothing - unknown
means unprivileged, never privileged.

### Custom roles

Create the role in Keycloak (**Realm roles** -> **Create role**), then define
what it grants in COSMOS. Until COSMOS has a definition for it, holding the role
does nothing.

A COSMOS role definition carries:

- `permissions` - any of `system`, `system_set`, `tlm`, `tlm_set`, `cmd`,
  `cmd_raw`, `cmd_info`, `script_view`, `script_run`, `admin`
- `targets` / `excluded_targets` - `ALL` or an explicit list. Exclusions are how
  "everything except the simulator" is expressed, so new spacecraft need no edit
- `tools` / `excluded_tools` - which tools appear in the nav

Holding several roles is additive: permissions union, and an exclusion only
applies if *every* role the user holds excludes it.

### Enabling and disabling

RBAC is off unless `OPENC3_KEYCLOAK_URL` is set. Without it COSMOS falls back to
the single shared password and none of this applies. To disable, comment the
Keycloak lines in `.env` and restart - user accounts and roles are preserved.

Bring Keycloak up and assign someone the `admin` role **before** enabling, or
nobody can administer the system.

### Hosting Keycloak somewhere other than this machine

Yes, this works, and pointing `.env` at a remote URL is most of it - but not
quite all. Four things need to change together.

**1. The two URLs are not the same URL.** COSMOS deliberately keeps them apart:

```
OPENC3_KEYCLOAK_URL=https://auth.example.com   # backend -> Keycloak, for signing keys
OPENC3_KEYCLOAK_EXTERNAL_URL=https://auth.example.com   # browser -> Keycloak
```

Locally the external one is just `/auth` because traefik proxies Keycloak at the
same origin. With a remote Keycloak both become absolute URLs. The backend URL
must be reachable *from inside the containers*; the external one must be
reachable *from the operator's browser*. They can differ (split horizon DNS, a
private backend address) and often should.

Drop the `/auth` suffix unless the remote instance also sets
`KC_HTTP_RELATIVE_PATH=/auth`. A remote Keycloak usually serves at the root.

**2. The realm has to know your COSMOS URL.** `redirectUris` currently only
lists `localhost`. Keycloak refuses any redirect not on the list, so add your
real address or logins fail with `Invalid parameter: redirect_uri`:

```json
"redirectUris": ["https://cosmos.example.com/*"],
"webOrigins": ["https://cosmos.example.com"]
```

`webOrigins` matters once Keycloak is on a different origin - it drives the CORS
headers, without which the browser silently blocks the token request.

**3. HTTPS stops being optional.** The realm is set to `sslRequired: external`,
so Keycloak refuses non-localhost traffic over plain HTTP. Tokens are bearer
credentials: anyone who captures one holds that person's authority until it
expires.

**4. Stop running the local one.** Remove or comment the `openc3-keycloak`
service in `compose.yaml` and the `/auth` router in
`openc3-traefik/traefik.yaml`, so nothing accidentally authenticates against a
second, empty identity provider.

#### Before this is production rather than a demo

- **`start-dev` is not a production mode.** It runs an embedded H2 database in a
  single Docker volume. Losing that volume loses every account, and
  `./openc3.sh cleanup` would do exactly that. Production wants `start` against
  an external Postgres, with that database in your backup rotation.
- **Change `OPENC3_KEYCLOAK_ADMIN_PASSWORD`.** It defaults to `admin`/`admin`,
  which is tolerable only while bound to localhost. It is a *bootstrap*
  credential, so change it before the volume is first created or you will have
  to reset it through the console.
- **`OPENC3_SERVICE_PASSWORD` bypasses every role check.** Microservices have no
  interactive user, so they authenticate with it and are unrestricted. Under
  RBAC it is the most valuable secret you hold, and it currently sits in plain
  text in `.env`.
- **Tokens are not checked for issuer or audience.** The signature and expiry
  are verified, which is what stops forgery. Adding issuer and audience checks
  matters if the same Keycloak ever serves other applications, since a token
  minted for a different client would otherwise be accepted. Note the issuer in
  a token reflects the *external* URL the browser used, not the internal one, so
  it needs its own setting rather than being derived from `OPENC3_KEYCLOAK_URL`.
