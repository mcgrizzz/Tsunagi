# Security model

What Tsunagi protects, from whom, how, and where the gaps are. Findings are
marked **verified** (checked against the code or with real requests) or
**unconfirmed**. Last reviewed 2026-09-26 against Tsunagi `main` and Anki 26.09.

## What is at stake

- **The collection:** notes, cards, review history and scheduling. Every write
  goes through Anki's undo, but a client can make many writes quickly.
- **Files on the computer:** with `gates.media_allow_local_path` on, a client
  can have Anki read any file the user can read, store it as media and fetch it
  back.
- **The local network:** media `url` uploads make Anki fetch a URL and store the
  response, which a client can read back through media retrieval.
- **Anki's UI:** GUI actions open dialogs, switch profiles and answer cards.

## Who can reach the server

| Caller | Default access | Why |
| --- | --- | --- |
| Program on this computer (script, curl, desktop tool) | Full | Sends no `Origin`. It already runs as the user, so it could read the files and collection directly. |
| Browser extension | Full | The default allowlist entry `http://localhost` also allows every extension origin, matching AnkiConnect, so Yomitan works with no setup. |
| Web page served from `127.0.0.1` on any port | Full | Same allowlist rule: `http://127.0.0.1:<any port>` is trusted. Includes local dev servers and other apps' web UIs. |
| Anki's own pages (reviewer, previewer, add-on pages) | None unless `gates.anki_page_scripts` is on | Card templates run JavaScript there. See below. |
| Web page on another site | None, except `requestPermission` | Rejected before anything runs. |
| Another device on the network | Only if `host` is not loopback | Default `host` is `127.0.0.1`. See gap 1. |

## What stops a hostile web page (verified)

Checked by sending each request shape to the real app with default settings (no
API key, allowlist `http://localhost`). Every rejection happened before the
action ran; a note count before and after confirmed nothing was created.

| Request | Result |
| --- | --- |
| JSON `POST /v1/notes` from `https://evil.example` | 403, not run |
| Simple `POST /` with `Content-Type: text/plain` (no preflight), `addNote` | 403, not run |
| `POST /` with `multi` wrapping `addNote` | 403, not run |
| Form-style `text/plain` `POST /v1/notes` | 403, not run |
| Preflight `OPTIONS /v1/notes` | 403 |
| `Origin: null` (sandboxed iframe, `file://` page) | 403, not run |
| DNS rebinding: `Host: evil.example:7777`, with or without `Origin` | 403, not run |
| Page on `http://localhost:3000` (a port other than the exact entry) | 403, not run |
| Cross-site `GET` (image tag, navigation; browsers send no `Origin`) | Runs, but every `GET` route is read-only and the page cannot read the response without CORS headers |

How it works:

1. **Host check** (`DynamicCORSMiddleware`): the `Host` header must be
   a loopback name or the configured bind address, before anything else. This
   defeats DNS rebinding, where an attacker's domain resolves to `127.0.0.1`.
2. **Origin check:** `/v1/*` rejects unknown origins in the middleware, so the
   request never reaches a route. The AnkiConnect root `/` lets every origin
   through the middleware (so `requestPermission` works, as in AnkiConnect) and
   rejects in the endpoint before parsing the action further. Only a
   well-formed `requestPermission` passes.
3. **API key** (optional, empty by default): `X-Api-Key` or `Authorization:
   Bearer` on `/v1/*`, the `key` field on `/`, checked per `multi` child. Browser
   `EventSource` may pass it as `?api_key=` on `/v1/events` only.
4. **Gates:** off-by-default switches for risky features. File-path media and
   FSRS memory-state writes additionally stay off when `host` is not loopback
   and there is no API key.
5. **Anki's own pages:** Anki serves the reviewer, previewer and add-on pages
   from `http://127.0.0.1:<its media port>` with CSP `frame-ancestors 'none'`
   only, so card-template JavaScript runs and can make network requests. In a
   real Anki 26.09 reviewer, a template's `fetch` to another localhost port
   arrived with `Origin: http://127.0.0.1:<media port>`. That origin would match
   the `127.0.0.1` rule, so Tsunagi learns the media port at startup and
   rejects it, even with `*` in the allowlist, unless
   `gates.anki_page_scripts` is on. `requestPermission` from it is denied
   without a dialog, so a card cannot talk the user into approving it; the
   port also changes every launch, so an allowlist entry would not last.
   AnkiConnect has no such exception: any card template can use it.

`requestPermission` from any site shows a dialog in Anki naming the requesting
origin; approving it adds the origin to the allowlist. It exists only as an
AnkiConnect action: the native API has no permission request yet. One is
planned, with an approval dialog that asks for a deliberate choice and warns
what trusting a site grants.

## How Anki protects its own server

Anki's internal media server (`aqt/mediasrv.py`, 26.09), for comparison:

- rejects any `Host` that is not `127.0.0.1`, `localhost` or `[::1]`, and any
  `Origin` that is not one of those on some port;
- requires `Content-Type: application/binary` on API `POST`s, which a web page
  cannot send cross-origin without a preflight the server never approves;
- gives full API access only with a random bearer token created at each launch;
  other pages get a short list of reviewer endpoints.

Anki trusts local origins for its own server, but it does not trust card
content: the editor blocks field scripts with a CSP, and the API needs a token
card scripts never see. Tsunagi trusts all local origins with no token.

## Gaps

Ranked by how likely they are to matter.

1. **Network bind without a key opens everything except two gates.** With `host`
   set to `0.0.0.0` or a LAN address and no key, any device on the network can
   read and write the collection and drive the UI. Only file paths and
   memory-state writes are held back. Nothing warns the user. Possible
   fix: refuse to start, or warn in the dialog, when `host` is not loopback and
   the key is empty.
2. **Media URL downloads reach the local network.** A `url` upload has Anki fetch
   any `http(s)` address, including routers, other local services and cloud
   metadata endpoints, and store the response as media the caller can read
   back. Allowed clients can do this today.
   Possible fix: a gate or refusing private and loopback addresses, weighed
   against Yomitan-style local audio servers that rely on `http://localhost`
   URLs.
3. **Every local page and every extension is trusted.** Any page served from
   `127.0.0.1` on any port, and any installed browser extension, has full
   access by default. This is the AnkiConnect-compatible default that makes
   Yomitan work. Per-application keys with their own permissions are the
   planned way to narrow it.
4. **`requestPermission` is a social-engineering prompt.** Any site can open the
   dialog. Its protection is the user reading the origin before approving.
5. **Key in the URL.** `?api_key=` on `/v1/events` can end up in browser history
   or proxy logs. Headers are preferred wherever the client can set them.

Accepted by design: programs running as the same user have full access (a key
would not stop them from opening the collection directly), and the vendored
FastAPI/Starlette stack carries known advisories, each reviewed and
allowlisted in CI with its reason; none is reachable today.

## AnkiConnect

AnkiConnect's model is the one Tsunagi's compatibility layer copies. From its
source (GitHub mirror at 4064fa1 and upstream at de6e6e1, both 2025) and its
issue history:

- **Defaults:** bound to `127.0.0.1:8765`, `webCorsOriginList` is
  `["http://localhost"]`, `apiKey` is null. `storeMediaFile` opens any `path`
  it is given; there is no setting to turn that off.
- **History:** until late 2019 it answered every origin
  (`Access-Control-Allow-Origin: *`). Issue
  [#130](https://github.com/FooSoft/anki-connect/issues/130) reported that any
  website could control Anki, and PR #131 limited CORS to localhost. The API
  key and origin allowlist followed in early 2020. PR
  [#252](https://github.com/FooSoft/anki-connect/pull/252) (May 2021) fixed
  actions still running for disallowed origins, which had only withheld the
  response; the same PR began trusting `127.0.0.1` origins and every browser
  extension whenever `http://localhost` is allowed. `requestPermission`
  arrived in PR #255 days later.
- **Today:** a disallowed origin gets 403 before the action runs, except
  `requestPermission`. A request with no `Origin` is allowed. It never reads
  the `Host` header, so it has no DNS-rebinding defence; no rebinding report was
  found in its issues.
- **No CVE** is recorded for AnkiConnect in NVD.

Differences in Tsunagi: it checks `Host` (defeating rebinding), answers
disallowed preflights with 403 rather than 200, and gates file paths. It keeps
AnkiConnect's origin rule except for Anki's own pages, so gap 3 applies to
both.

Browsers are adding their own layer: Chrome's Local Network Access asks the
user before a public website may reach loopback or LAN addresses (prompt since
Chrome 142, split into `local-network` and `loopback-network` permissions in
145, per [Chrome's blog](https://developer.chrome.com/blog/local-network-access)
and release notes). It targets public websites; local pages, extensions and
Anki's card pages are not public websites, so it is no help for gap 3
(not tested per browser). Firefox and Safari were not checked.
