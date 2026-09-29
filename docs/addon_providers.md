# Offer your add-on's actions through Tsunagi

Let apps run what your add-on's menu items do, with parameters in place of
dialogs. Your add-on registers as a **provider**. It doesn't import Tsunagi,
and nothing happens if Tsunagi isn't installed.

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
            "impact": "undoable",
            "params": {"deck": {"type": "integer", "description": "Only this deck"}},
            "run": rebuild_decks,
        }],
    )


addHook("tsunagi.register", provide)
```

An app then runs it with
`POST /v1/addons/my_addon/actions/rebuild:run` and `{"deck": 1}`.

- **Call `addHook` at import time** (top level, as above). Tsunagi calls the
  hook when its server starts, after Anki has imported every add-on, so load
  order doesn't matter. A hook added later, such as in your own
  `profile_did_open` handler, is only seen after the next profile switch.
- **The provider id** names your actions in URLs and permissions
  (`addon:my_addon/rebuild`). Keep it the same on every install; your add-on's
  name in snake_case works well. An id another add-on already uses is refused,
  and the error goes to Tsunagi's log.
- `registry.version` is `1`. Check it if you rely on something added later.

## Actions

| Key | Required | Meaning |
| --- | --- | --- |
| `name` | yes | a-z, 0-9, _; unique within your provider |
| `title` | no | the menu text; defaults to `name` |
| `description` | no | one or two sentences for users deciding whether to enable it |
| `impact` | yes | `read`, `undoable` or `destructive` (below) |
| `run` | yes | the function to call |
| `params` | no | `{name: param}` (below) |
| `shows_ui` | no | `true` if it shows a progress window or message on the computer |
| `backup` | no | `destructive` only: `true` to have Tsunagi back up the collection before each run (below) |

**`impact`** says how much it would matter if the action ran by mistake. Pick
by one question: *can the user put it back?*

| `impact` | Pick it when | Examples | Before it can run |
| --- | --- | --- | --- |
| `read` | It changes nothing | List easy dates, show statistics | Nothing: always enabled |
| `undoable` | The user can put it back: **Edit → Undo** in Anki, or changing a setting back | Change your add-on's own setting; reschedule cards with an undo step | The user enables it in Tsunagi's settings |
| `destructive` | It can't be put back without a backup | Delete your add-on's saved data or files, change the database directly (outside Anki's undo) | The user enables it and gives an app access |

A large change still counts as `undoable` if one **Edit → Undo** reverts it.
Whether it shows a window on the computer is separate: set `shows_ui`.

**`backup`.** For a `destructive` action that changes the collection outside
Anki's undo, set `"backup": True`: Tsunagi then makes an Anki backup before
each run, and doesn't run the action if the backup fails. Leave it off when
the action touches other things, such as your add-on's files or media: a
collection backup doesn't include them, and each backup takes time on a large
collection.

If an update of your add-on changes an action's `impact`, it's disabled until
the user enables it again, so nothing gains access silently.

### `run`

`run` is called on Anki's main thread with the parameters as keyword
arguments. Parameters the app left out are passed only if they have a
`default`, so give the others Python defaults. It can:

- **return a result** (anything JSON can hold);
- **return a `concurrent.futures.Future`** for work you run in the background
  (for example with `mw.taskman.run_in_background`). Resolve it when
  everything is done, including follow-up work, so the app knows when the
  action has finished;
- **raise an exception** to refuse or fail. The app sees its message, such as
  `"FSRS is off; turn it on in deck options"`. Check before starting work, and
  don't show a warning dialog instead: nobody may be at the computer.

A `read` action answers right away with its data. An action that changes
something runs as a job instead: the app gets a job ID at once and checks it
until the work is done, so long work is fine.

### Parameters

| Key | Meaning |
| --- | --- |
| `type` | `integer`, `number` (fractions allowed), `boolean`, `string`, or `dates` (a list of `YYYY-MM-DD`, sorted, without duplicates) |
| `description` | shown to app developers |
| `required` | `true` if the app must send it |
| `default` | used when the app leaves it out |
| `min`, `max` | bounds for `integer` and `number` |

Unknown parameters and wrong types are refused before `run` is called. Use
the same defaults and bounds as your dialogs.

### Optional arguments

`registry.provide` also takes:

- `available`: a function returning `None`, or a short reason your actions
  can't run now (`"FSRS is off"`). Apps see the reason, and runs are refused.
- `addon`: your add-on's folder name. Tsunagi works it out from the module of
  the first action's `run`, so you rarely need it.

## Examples

Four actions, one of each kind:

```python
import os
from concurrent.futures import Future

from anki.hooks import addHook
from aqt import mw
from aqt.operations import CollectionOp

ADDON = __name__.split(".")[0]


def count_leeches():
    # read: returns data, changes nothing
    return {"leeches": len(mw.col.find_cards("tag:leech"))}


def set_greeting(text):
    # undoable: your add-on's own setting, which the user can change back
    config = mw.addonManager.getConfig(ADDON)
    config["greeting"] = text
    mw.addonManager.writeConfig(ADDON, config)
    return {"greeting": text}


def suspend_leeches():
    # undoable, run in the background: one Edit -> Undo reverts it.
    # Return a Future and resolve it when the work is done.
    future = Future()
    ids = mw.col.find_cards("tag:leech")
    CollectionOp(mw, lambda col: col.sched.suspend_cards(ids)).success(
        lambda changes: future.set_result({"suspended": len(ids)})
    ).failure(future.set_exception).run_in_background()
    return future


def reset_stats():
    # destructive: deletes a file your add-on keeps; nothing can bring it back.
    # No "backup": a collection backup wouldn't include this file.
    path = os.path.join(mw.addonManager.addonsFolder(ADDON), "user_files", "stats.json")
    if os.path.exists(path):
        os.remove(path)
    return {"reset": True}


def provide(registry):
    registry.provide("leech_tools", "Leech Tools", actions=[
        {"name": "count", "title": "Count leeches", "impact": "read", "run": count_leeches},
        {"name": "greeting", "title": "Set the greeting", "impact": "undoable",
         "run": set_greeting, "params": {"text": {"type": "string", "required": True}}},
        {"name": "suspend", "title": "Suspend leeches", "impact": "undoable",
         "run": suspend_leeches},
        {"name": "reset_stats", "title": "Reset statistics", "impact": "destructive",
         "run": reset_stats},
    ])


addHook("tsunagi.register", provide)
```

`count` is a read, so the app gets its answer right away. The other three
change something, so each runs as a job: the app gets a job ID and checks it
until the job is done.

- `set_greeting` and `reset_stats` do their work before returning, so their
  job is done when they return.
- `suspend_leeches` returns while Anki is still working in the background, so
  it returns a Future. Its job is done when the Future resolves, after Anki
  has saved the change.

**When to return a Future.** `run` is called on Anki's main thread, so while
it runs, Anki's window freezes and other requests wait. Anything that takes
more than about a tenth of a second (a search over the whole collection,
changing many cards, a network call) belongs in the background: start it
there and return a Future, as `suspend_leeches` does. Quick work, like
`set_greeting`, can simply return. The job waits either way; the Future is
what keeps Anki responsive.

## What users see

Your add-on appears on the **Add-ons** page of Tsunagi's settings, with each
action's title and description. Two separate settings decide whether an app
can run an action:

- **Enabled** (Add-ons page) is one on/off switch per action, for every app
  at once. An action that isn't enabled can't run for anyone. `read` actions
  are always enabled.
- **Roles** (Roles page) decide *which* apps may run an enabled action. By
  default, enabled `undoable` actions are in the Default role, and `destructive`
  ones only in Everything.

See [Configuration](../config.md#add-ons).

## What apps get

`GET /v1/addons/my_addon/actions` lists your actions, their parameters, and
a `status` for the app asking:

| Status | Means |
| --- | --- |
| `allowed` | The app can run it. |
| `disabled` | The user hasn't enabled it. |
| `not_permitted` | The app isn't allowed to run it. |
| `unsupported` | Your `available` gave a reason; the list is empty. |

`POST /v1/addons/my_addon/actions/{name}:run` (body: the parameters) answers:

| Answer | When |
| --- | --- |
| 200 with the result | a `read` action |
| 202 with a job | any other action; poll `GET /v1/jobs/{id}` |
| 403 | the action is disabled, or the app isn't allowed to run it |
| 409 | your add-on is unavailable, or another job (a sync, an import, an FSRS optimization, another action) is running |

A finished job's result is `{provider, action, result, settled, backup}`:

- `result` is what `run` returned (or its Future resolved with). If `run`
  raised, the job fails with your message.
- `settled` is `false` if follow-up work didn't finish within two minutes.
- `backup` names the Anki backup made before the run, for actions with
  `"backup": True`; otherwise it's `null`.

Apps can't cancel an action once it runs.
