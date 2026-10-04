# Tsunagi documentation

To install Tsunagi and connect your tools, start with the
[project README](../README.md#install).

## Use AnkiConnect tools with Tsunagi

- [Switch from AnkiConnect](../README.md#replace-ankiconnect): take over its
  port, key and allowed websites, and keep your tools as they are.
- [AnkiConnect compatibility](ankiconnect_parity.md): every AnkiConnect action,
  and what works differently.
- [Settings reference](../config.md): every page of the settings window,
  including app keys, roles and Recent requests.
- [Security model](security.md): who can reach Anki through Tsunagi, what
  stops them, and known gaps.

## Build an integration

- [Build your first integration](getting_started.md): check the connection,
  add a note, read it back, undo it, use an app key.
- [API reference](https://mcgrizzz.github.io/Tsunagi/): every operation, for
  the latest release. [In Anki](playground.md), the same reference sends real
  requests.
- [Create notes and upload media](creating_notes.md): save several notes,
  check duplicates, and identify rejected inputs.
- [Events](events.md): keep your app's data current, or react to reviewer
  answers.
- [API discovery](capabilities.md): what your app may use, and what to change
  in the settings when it can't.
- [Yomitan case study](api_recipes.md): a real AnkiConnect integration, request
  by request, and what the Tsunagi API changes.
- [TypeScript client](../packages/typescript/README.md): typed queries, writes
  and watching, built from this repository.
- [Add-on providers](addon_providers.md): offer your add-on's actions to apps
  through Tsunagi.

## How it performs

- [API benchmarks](benchmarks.md): Tsunagi and AnkiConnect on the Anki desktop
  with real client workloads, including where Tsunagi is slower, and how to
  reproduce them.

## Work on Tsunagi

- [Development](development.md): build, test, sync and package the add-on.
- [Request dataflow](dataflow/README.md): how routes reach the planner and Anki.
- [Performance notes](performance_notes.md): harness profiling, where Tsunagi
  API time goes, and what optimizations measured.
- [Manual release checks](manual_testing.md): checks that need a real desktop UI.

## Historical records

The [archive](archive/README.md) keeps the initial audits, coverage snapshots and
old manual test log. These explain past decisions; use the pages above for current
setup and API behavior.
