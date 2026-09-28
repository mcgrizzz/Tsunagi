# Offer your add-on's actions through Tsunagi

Tsunagi can run an add-on's actions for apps and phones that talk to it:
the things your menu items and dialogs do, with parameters in place of the
dialogs. Your add-on offers them by registering as a **provider**. It needs
no Tsunagi import and does nothing when Tsunagi is not installed.

## Register

Add a hook when your add-on loads:

```python
from anki.hooks import addHook

from .schedule import rebuild_decks


def provide(registry):
    registry.provide(
        "my_addon",                      # provider id: a-z, 0-9, _
        "My Add-on",                     # shown to users
        actions=[{
            "name": "rebuild",
            "title": "Rebuild filtered decks",
            "description": "Empty and rebuild every filtered deck.",
            "level": "normal",
            "params": {"deck": {"type": "integer", "description": "Only this deck"}},
            "run": rebuild_decks,
        }],
    )


addHook("tsunagi.register", provide)
```

Tsunagi calls every `tsunagi.register` hook when its server starts, on
`profile_did_open`. Anki imports every add-on before it opens a profile, so
load order does not matter, as long as you call `addHook` **at import time**
(top level of your add-on, as above). A hook added later, for example inside
your own `profile_did_open` or `main_window_did_init` handler, can miss that
moment and is only seen after the next profile switch. If Tsunagi is not
installed, the hook is never called. `registry.version` is `1`; check it if
you depend on something added later.

The provider id is how apps and permissions name your actions
(`POST /v1/addons/my_addon/actions/rebuild:run`,
permission `addon:my_addon/rebuild`). It must be the same on every install
and not already used by another add-on. A second provider with the same id
is refused, and the error is printed in Anki's console. Your add-on name in
snake_case is a good choice.

## Actions

| Key | Required | Meaning |
| --- | --- | --- |
| `name` | yes | a-z, 0-9, _; unique within your provider |
| `title` | no | the menu text; defaults to `name` |
| `description` | no | one or two sentences for users deciding whether to enable it |
| `level` | yes | `read`, `normal` or `destructive` (below) |
| `run` | yes | the function to call |
| `params` | no | `{name: param}`; see below |
| `shows_ui` | no | `true` if it shows a progress window or message on the computer |

**Levels.**

- `read` returns data (what a screen of yours shows). It is always enabled;
  only the app's role decides.
- `normal` changes something. It is disabled until the user enables it in
  Tsunagi's settings.
- `destructive` is hard to undo (deleting data, clearing history). The user
  must enable it and give a role access to it, and Tsunagi makes an Anki
  backup before each run.

If an update of your add-on changes an action's level, it is disabled until
the user enables it again. Nothing is widened silently.

**`run`** is called on Anki's main thread with the validated parameters as
keyword arguments. Parameters the app left out that have a `default` are
filled in; others are not passed, so give them Python defaults. It can:

- return a JSON-serialisable result;
- return a `concurrent.futures.Future` that resolves with the result when the
  work is finished, for work you run in the background (for example with
  `mw.taskman.run_in_background`). Resolve it only once everything is done,
  including follow-up work, so the app's job ends at the right time;
- raise an exception to refuse or fail. Its message is what the app sees
  (`"FSRS is off; turn it on in deck options"`). Check preconditions before
  starting work, and do not show a warning dialog instead: nobody may be at
  the computer.

A read runs while the app waits. Any other action runs as a job: the app gets
a job id at once and polls it, so long work is fine.

**Parameters.**

| Key | Meaning |
| --- | --- |
| `type` | `integer`, `boolean`, `string`, or `dates` (a list of `YYYY-MM-DD`, sorted and de-duplicated) |
| `description` | shown to app developers |
| `required` | `true` if the app must send it |
| `default` | used when the app leaves it out |
| `min`, `max` | bounds for integers |

Unknown parameters and wrong types are refused before `run` is called. Use
the same defaults and bounds as your dialogs.

## Optional hooks

`registry.provide` also takes:

- `available`: a function returning `None`, or a short reason your actions
  cannot run now (`"FSRS is off"`). Apps see the reason in Tsunagi's
  capabilities report and the actions list, and runs are refused.
- `addon`: your add-on's folder name. Tsunagi works it out from the module
  that defines the first action's `run`, so you rarely need it.

## What users and apps see

- `GET /v1/addons` shows `"provider": "my_addon"` on your add-on.
- `GET /v1/addons/my_addon/actions` lists your actions with their parameters
  and, for the calling app, whether it may run each one.
- `POST /v1/addons/my_addon/actions/{name}:run` runs one (body: the
  parameters).
- Apps cannot abort an action once it runs.

See [Configuration](../config.md) for enabling actions and roles, and
[Security model](security.md) for how actions are limited.
