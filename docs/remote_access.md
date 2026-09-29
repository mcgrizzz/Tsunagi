# Use Tsunagi from your phone

Anki on your computer does things the phone apps can't, such as running
add-ons. Tsunagi can take requests from your phone, so you can sync, apply
FSRS Helper's easy days, or run any other action you enabled, without
sitting at the computer.

The recommended way is **Tailscale Serve**. Tsunagi keeps listening only on
this computer (`127.0.0.1`), and Tailscale forwards HTTPS requests from your
own devices to it. Nothing is opened on your router or the public internet.

## Set it up

1. Install Tailscale on the computer running Anki and on your phone, signed
   in to the same tailnet.
2. In the Tailscale admin console, open **DNS**. Turn on **MagicDNS**, then
   under **HTTPS Certificates** click **Enable HTTPS**. Serve needs both, and
   you must be an admin of the tailnet to change them.
3. On the computer, start Serve in front of Tsunagi's port (7777 unless you
   changed it):

   ```sh
   tailscale serve --bg 7777
   ```

   It prints the address, for example `https://pc.tailnet.ts.net/`.
4. In Tsunagi's settings, go to **Server → Other host names**, enter that
   name without `https://` (`pc.tailnet.ts.net`), and Save. Until then
   Tsunagi refuses requests through Serve with "Disallowed Host header".
5. In **Apps & keys**, click **Add app**, name it after your phone and
   Save. It gets the Default role, which can do everything AnkiConnect can;
   the key is copied when you add the app.
6. To run add-on actions such as FSRS Helper's easy days, enable them on the
   **Add-ons** page and Save.

## Check it

From the phone's browser, with Tailscale connected:

- `https://pc.tailnet.ts.net/v1/health` shows Anki's status.
- `https://pc.tailnet.ts.net/v1/capabilities` says **Invalid or missing API
  key**. Requests through Serve never count as coming from this computer,
  so without a key they get **No access**.

With the key, `GET /v1/capabilities` includes a `caller` block naming your
app, with `this_computer: false`. Send the key as the `X-Api-Key` header.

## Use it

A request from the phone is like any other API request, with the key:

```sh
curl -X POST https://pc.tailnet.ts.net/v1/collection:sync -H "X-Api-Key: <key>"
curl -X POST https://pc.tailnet.ts.net/v1/addons/fsrs_helper/actions/easy_days:run -H "X-Api-Key: <key>"
```

A sync answers with its result, or with 202 and a job if it takes longer
than the operation timeout (15 seconds by default). An add-on action always
answers 202 and a job. Poll `GET /v1/jobs/{id}` until it is done. A sync
answers 409 when Anki needs a full upload or download (click Sync in Anki
once to choose) and 502 when AnkiWeb can't be reached. Android's HTTP Shortcuts and
iOS Shortcuts can send these requests with a header.

Anki must be running with your profile open.

## Turn it off

```sh
tailscale serve --https=443 off
```

You can also remove the name from **Other host names**. To stop the phone's
key from working, untick the app's **On** box, click **New key**, or remove
the app on **Apps & keys**.

## Other ways, and what not to do

- **WireGuard or an SSH tunnel** work like Serve: the tunnel ends on this
  computer and forwards to `127.0.0.1`. Add the name you connect with to
  **Other host names**, and give the phone a key.
- **Binding to your network** (Server → Host `0.0.0.0`) lets devices on your
  Wi-Fi connect over plain HTTP. They need a key, but anyone on that network
  can see the traffic, key included. Prefer a tunnel.
- **Do not forward a router port to Tsunagi, and do not use Tailscale
  Funnel.** Both put an API that controls your Anki on the public internet.
