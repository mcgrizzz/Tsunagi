# Security model

[← Documentation](README.md) · [Settings reference](../config.md)

What Tsunagi protects, from whom, how, and where the gaps are. Findings marked
**verified** were checked against the code or with real requests. Last
reviewed 2026-10-03 against Tsunagi 0.5.1 and Anki 26.09.

## In short

- By default Tsunagi listens only on this computer (`127.0.0.1`).
- Public websites are blocked unless you allow them. Browser extensions and
  pages served from this computer are allowed, as in AnkiConnect.
- Other devices are blocked unless you set up access: an app's key, or a role
  for other devices under **Requests without a key**.
- Each app's key and role decide what it may do. Untick an app's **On** box or
  give it a **New key** to stop it.
- A tool you haven't given a role of its own gets the Default role. It allows
  what AnkiConnect allows, except reading files on this computer, and leaves
  out a few other risky things ([what's off by default](#whats-off-by-default)).
- Card templates and other add-ons' pages inside Anki can't use it unless you
  turn that on.

## What is at stake

- **The collection:** notes, cards, review history and scheduling. Most writes
  can be undone in Anki, but a client can make many quickly. Media files and
  add-on actions aren't undone that way.
- **Files on the computer:** an app allowed to read files on this computer can
  have Anki read any file you can, store it as media and fetch it back.
- **The local network:** a media `url` upload makes Anki fetch that address
  and store the answer, which the caller can read back.
- **Anki's windows:** GUI actions open dialogs, switch profiles and answer
  cards.
- **Other add-ons' actions:** apps can run actions that add-ons offer (FSRS
  Helper through a provider bundled with Tsunagi, others by registering), which
  may change many cards outside Anki's operations. See
  [add-on actions](#add-on-actions) below.

## Who can reach the server

| Caller | Default access | Why |
| --- | --- | --- |
| Program on this computer (script, desktop tool) | Default role | It already runs as you and could open the collection directly. **Requests without a key → Programs on this computer** can be set to another role. |
| Browser extension | Default role | The default allowed origin `http://localhost` also allows every extension, as in AnkiConnect, so Yomitan works with no setup. |
| Web page served from `127.0.0.1`, any port | Default role | Same rule. Includes local dev servers and other apps' web pages. |
| Anki's own pages (reviewer, previewer, add-on pages) | None, unless **Allow card templates and add-on pages** is on | Card templates run JavaScript there. See [check 4](#how-the-checks-work). |
| Web page on another site | None, unless you allow it | Refused before anything runs. You allow a site by adding it under **Allowed website origins**, or by approving its `requestPermission` dialog. After that, its requests come from your browser on this computer, so without a key it gets the Default role, like a local page. |
| Another device on the network | Only with an app's key | The default host `127.0.0.1` isn't reachable from it. With another host, keyless requests get the role for other devices under **Requests without a key**: No access unless you change it. Tsunagi serves plain HTTP, so the connection doesn't encrypt the key or your data; someone able to intercept that traffic could read them. |
| Another device through a proxy on this computer (Tailscale Serve) | Only with an app's key | The proxy's name must be under **Other host names**, and forwarded requests always count as other devices. Tailscale encrypts the traffic between devices, so this is the safer way to connect from elsewhere. |

## What's off by default

The Default role is what a tool gets unless you give it another. It allows
what AnkiConnect allows, so AnkiConnect clients keep working, with the
exceptions below: things a tool you never thought about could do real damage
with. Give each one only to a tool that needs it, through its role on the
**Roles** page. Card templates have a switch of their own instead, on
**Websites & Anki pages**.

- **Reading files on this computer.** AnkiConnect lets a client store media by
  naming a file's path: Anki copies the file into its media folder, and the
  client reads it back as media. Any client that can reach the API, including
  a website you allowed, could read any file your account can (SSH keys,
  browser password databases, documents), and media sync could upload it to
  AnkiWeb. Browsers stop websites reading your files; this would get around
  that.
  - Cost: a client that names a path is refused. A screenshot or recording
    tool that has just written a file is the usual one. It can send the
    file's contents (`data`) or a `url` instead.
- **Card templates and add-on pages.** Scripts in Anki's own pages, including
  the card templates of shared decks you downloaded, could read, change or
  delete your collection while you study.
  - Cost: an interactive card template, or an add-on page that uses the API,
    needs **Allow card templates and add-on pages** turned on. Then you have
    to trust every deck you study and every add-on page you open.
    AnkiConnect lets them all in.
- **Rewriting FSRS memory state.** It overwrites what FSRS knows about your
  cards. A faulty tool could quietly damage your scheduling, and you might
  not notice for weeks.
  - Cost: none for AnkiConnect clients; AnkiConnect can't do this.
- **Running add-on actions.** Each action another add-on offers stays off
  until you enable it on the **Add-ons** page, and some are destructive. One
  you enable that can be undone joins the Default role; a destructive one
  joins only Everything ([add-on actions](#add-on-actions)).
  - Cost: none for AnkiConnect clients; these are Tsunagi's own.
- **Each card you answer, live.** The event stream can report every review:
  which card, how you answered and when. Nothing needs it by default: a
  client should get it because it uses it, not because it's there. The
  Default role still gets changes to your collection.
  - Cost: a study tracker, stream overlay or companion app that reacts as you
    review needs a role with it. None for AnkiConnect clients; AnkiConnect
    has no event stream.

## What stops a hostile web page (verified)

Each request shape was sent to the real app with default settings (no key,
allowed origin `http://localhost`). Each got the result below, and the note
count didn't change. In the code, `/v1` requests are refused in the middleware
before any route runs, and AnkiConnect requests (`/`) before the action is
dispatched.

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

**Not refused:** a cross-site `GET` (an image tag or a link; browsers send no
`Origin`) does run. Every `GET` route only reads, and the page can't read the
response without CORS headers.

### How the checks work

1. **Host check** (`DynamicCORSMiddleware`), before anything else. The `Host`
   header must be a loopback name, the configured host, a name under **Other
   host names**, or (with a network host) a plain IP address.
   - This defeats DNS rebinding, where an attacker's domain resolves to
     `127.0.0.1`.
   - Each name you list is one more `Host` that reaches the key check.
   - It doesn't identify the caller: a program on another device can send any
     `Host`, so keys protect network access, not this check.
2. **Origin check.** `/v1/*` refuses unknown origins before any route runs.
   The AnkiConnect endpoint `/` lets every origin reach it, so
   `requestPermission` works as in AnkiConnect, then refuses anything else
   from an unknown origin before running it.
3. **Apps and roles** ([configuration](../config.md#apps--keys)). A key selects
   an app: `X-Api-Key` or `Authorization: Bearer` on `/v1/*`, `"key"` on `/`
   (checked for each action inside `multi`), `?api_key=` on `/v1/events` only.
   - Without a key, the request is "No key, this computer" (from this computer
     and addressed to it) or "No key, other devices".
   - Each has a role. Every route and AnkiConnect action declares the
     permission it needs; a test fails if one is missing.
   - A few permissions are left out of the Default role
     ([what's off by default](#whats-off-by-default)).
4. **Anki's own pages.** Anki serves the reviewer, previewer and add-on pages
   from `http://127.0.0.1:<its media port>`, where card-template JavaScript
   can make network requests.
   - In a real Anki 26.09 reviewer, a template's `fetch` to another local port
     arrived with `Origin: http://127.0.0.1:<media port>`, which the
     `127.0.0.1` rule would allow.
   - So Tsunagi learns the media port at startup and refuses that origin, even
     with `*` allowed, unless **Allow card templates and add-on pages** is on.
   - Its `requestPermission` is refused without a dialog, so a card can't talk
     you into approving it. The port changes every launch, so an allowed-origin
     entry wouldn't last anyway.
   - AnkiConnect has no such exception: any card template can use it.

## Keys and settings

- **Settings have no HTTP endpoint.** The settings window talks to Tsunagi
  through Anki's page bridge, attached only to that window's own web view.
  Card templates, other add-ons' pages and API clients have no route to it
  (from the code; not tested from inside a card).
- **Keys are stored in plain text** in the add-on's `meta.json`, as
  AnkiConnect's are. Anything that can read your Anki folder can read them.
- **To stop a key working,** untick the app's **On** box, click **New key**,
  or remove the app on **Apps & keys**.
- **Recent requests** shows which apps, websites and devices have called
  Tsunagi since Anki started, including refused requests. It's kept in memory
  only, records no keys or request contents, and isn't reachable over HTTP.
- **`requestPermission`** from any site shows a dialog in Anki naming the site;
  approving adds it to the allowed origins. It exists only as an AnkiConnect
  action; the Tsunagi API has no permission request.

### Add-on actions

- An add-on that registers actions is already code running inside Anki, so
  Tsunagi trusts how it labels them.
- Each action is disabled until you enable it on the **Add-ons** page, and runs
  only for apps whose role allows it.
- Enabled undoable actions join the Default role. Destructive ones join only
  Everything. A destructive action that changes the collection outside undo
  can ask for an Anki backup before each run; the add-on decides.
- An add-on update that changes an action's impact disables it again.
- The bundled FSRS Helper provider checks the add-on's functions before
  calling them and reports the add-on as unavailable rather than guessing
  (verified in tests and against FSRS Helper in a throwaway profile).

## How Anki protects its own server

Anki's internal media server (`aqt/mediasrv.py`, 26.09), for comparison:

- refuses any `Host` other than `127.0.0.1`, `localhost` or `[::1]`, and any
  `Origin` that isn't one of those on some port;
- requires `Content-Type: application/binary` on API `POST`s, which a web page
  can't send cross-origin without a preflight the server never approves;
- gives full API access only with a random token created at each launch;
  other pages get a short list of reviewer endpoints.

Anki trusts local origins, but not card content: the editor blocks field
scripts, and its full API needs a token Anki gives only to its own trusted
pages. Tsunagi trusts local origins with no token.

## Known gaps

Most likely to matter first.

1. **Media URL downloads reach the local network (accepted).** A `url` upload
   has Anki fetch any `http(s)` address, including your router and other local
   services, and store the response as media the caller can read back.
   - Only callers already trusted can ask: extensions, local tools, key
     holders.
   - Anki's own editor and AnkiConnect don't restrict addresses either, and
     local audio servers rely on `localhost` URLs, so it stays.
   - Tsunagi adds a size limit and timeout, and redirects must stay on
     `http(s)`.
2. **Every local page and every extension is trusted.** Any page served from
   `127.0.0.1` on any port, and any installed browser extension, gets the
   Default role without a key, so it can read and change your collection.
   It's the AnkiConnect-compatible default that makes Yomitan work. To narrow
   it, give each tool its own key and set **Requests without a key → Programs
   on this computer** to a smaller role or No access.
3. **Proxies and "this computer".** A request counts as local only when it
   comes from this computer, is addressed to a loopback name, and carries no
   proxy header (`Tailscale-User-Login`, `Forwarded`, `X-Forwarded-For`,
   `X-Forwarded-Host`, `X-Real-IP`).
   - Tailscale Serve keeps the phone's `Host` (verified 2026-09-28) and always
     adds `Tailscale-User-Login`, so its requests count as other devices.
   - A local proxy that rewrites `Host` to `localhost` and adds none of those
     headers would make remote requests look local. Configure such a proxy to
     send `X-Forwarded-For`.
4. **`requestPermission` is a social-engineering prompt.** Any site can open
   the dialog. The protection is you reading the site's name before approving.
5. **Keys in plain sight.** Over plain HTTP between devices, keys travel
   unencrypted; use Tailscale Serve (or another encrypting proxy) rather than
   a network host. `?api_key=` on `/v1/events` can also end up in browser
   history or proxy logs; use the header wherever the client can.

Accepted by design:

- Programs running as you have full access: a key wouldn't stop them opening
  the collection directly.
- The bundled Starlette library carries known advisories, each listed with
  its reason under `audit_ignore` in [`pyproject.toml`](../pyproject.toml),
  which CI's audit skips: form parsing (Tsunagi parses no forms), URLs
  rebuilt from the `Host` header (Tsunagi checks `Host` first and routes on
  the path), and `StaticFiles` and `HTTPEndpoint` (not used). The fixes are in Starlette 1.x. Tsunagi bundles FastAPI 0.125.0,
  which requires Starlette below 0.51; later FastAPI releases require
  pydantic 2, which isn't pure Python and can't be bundled.

## Compared with AnkiConnect

Tsunagi's AnkiConnect endpoint copies AnkiConnect's model. From AnkiConnect's
source (GitHub mirror at 4064fa1 and upstream at de6e6e1, both 2025) and its
issue history:

- **Defaults:** `127.0.0.1:8765`, allowed origins `["http://localhost"]`, no
  API key. `storeMediaFile` opens any `path` it's given, with no setting to
  turn that off.
- **History:**
  - Until late 2019 it answered every origin. Issue
    [#130](https://github.com/FooSoft/anki-connect/issues/130) reported that
    any website could control Anki; PR #131 limited it to localhost.
  - The API key and allowed origins followed in early 2020.
  - PR [#252](https://github.com/FooSoft/anki-connect/pull/252) (May 2021)
    stopped actions running for disallowed origins (before, only the answer
    was withheld). The same PR started trusting `127.0.0.1` pages and every
    browser extension when `http://localhost` is allowed.
  - `requestPermission` arrived in PR #255 days later.
- **Today:** a disallowed origin gets 403 before the action runs, except
  `requestPermission`. A request with no `Origin` is allowed. It never checks
  `Host`, so it has no DNS-rebinding defence; no rebinding report was found in
  its issues.
- **No CVE** is recorded for AnkiConnect in NVD.

Where Tsunagi differs:

- It checks `Host`, which defeats DNS rebinding.
- It answers disallowed preflights with 403 rather than 200.
- Reading a file by its path is off by default.
- It refuses Anki's own pages. Otherwise it keeps AnkiConnect's origin rule,
  so gap 2 applies to both.

Browsers are adding their own layer. Since Chrome 142, Local Network Access
asks you before a public website reaches your local network or this computer,
or a local-network website (an intranet page) reaches this computer; Chrome
145 split it into `local-network` and `loopback-network` permissions
([release notes](https://developer.chrome.com/release-notes/142),
[blog](https://developer.chrome.com/blog/local-network-access)). Pages served
from this computer itself and browser extensions aren't covered, so it doesn't
help with gap 2. Not tested per browser; Firefox and Safari weren't checked.
