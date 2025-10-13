# list_models() — Dataflow

## A) Names & IDs (`service=23, method=8`)

1. **Tsunagi** → `list_models()`

2. **Python** → `anki/pylib/anki/models.py :: ModelManager.all()`

   - **(a)** `ModelManager.all_names_and_ids()`
   - **(b)** **Python backend shim** → `anki/pylib/anki/_generated_backend.py :: get_notetype_names()`
   - **(c)** **Python bridge** → `anki/pylib/anki/_backend.py :: _run_command(23, 8, bytes)`
   - **(d)** **Rust bridge** → `pylib/rsbridge/lib.rs :: Backend::command(23, 8, input)`
   - **(e)** **Rust bridge (dispatcher)** → `Backend::run_service_method(23, 8, input)`
   - **(f)** **Generated dispatcher** → `target/**/build/*/out/backend.rs :: run_backend_notetypes_service_method(8, input)`
   - **(g)** **Generated wrapper** → `Backend::get_notetype_names(self)`
   - **(h)** **Generated wrapper** → `with_col(|col| NotetypesService::get_notetype_names(col))`
   - **(i)** **Rust service** → `rslib/src/notetype/service.rs :: NotetypesService::get_notetype_names(col)`
   - **(j)** **Rust storage** → `rslib/src/storage/notetype/mod.rs :: SqliteStorage::get_all_notetype_names()`
   - **(k)** **SQL** → `rslib/src/storage/notetype/get_notetype_names.sql :: SELECT id, name FROM notetypes`
   - **(l)** **Back to service** → map `(NotetypeId, String)` → `anki_proto::notetypes::NotetypeNames { entries }`
   - **(m)** **Generated wrapper** → encode protobuf `NotetypeNames` → `Vec<u8>` → return to Python
   - **(n)** **Python backend shim** → decode protobuf → `NotetypeNames(entries)` → `ModelManager.all_names_and_ids()` → `[(name, id), …]`

## B) Per-ID materialization used by `all()`

3. **Python** → `anki/pylib/anki/models.py :: ModelManager.get(id)`

   - **(a)** **Cache hit** → return cached `Notetype`
   - **(b)** **Cache miss → legacy fetch:**
     1. **Python backend shim** → `_generated_backend.py :: get_notetype_legacy(id)` (`service=23, method=7`)
     2. **Generated dispatcher** → `run_backend_notetypes_service_method(7, input)`
     3. **Generated wrapper** → `Backend::get_notetype_legacy(self, id)` → `with_col(|col| NotetypesService::get_notetype_legacy(col, id))`
     4. **Rust service/storage fan-out:**
        - `SqliteStorage::get_notetype(id)` (core) → **SQL** `get_notetype.sql`
        - `SqliteStorage::get_notetype_fields(id)` → **SQL** `get_fields.sql`
        - `SqliteStorage::get_notetype_templates(id)` → **SQL** `get_templates.sql`
     5. **Return** → encode protobuf `Notetype` → Python decodes → `ModelManager.get(id)` returns `Notetype`

## C) Assemble & return

4. **Python** → `ModelManager.all()` → list of `Notetype`s (mix of cached and fetched)

5. **Tsunagi** → `list_models()` returns model list

6. **Tsunagi** → paginate / project → **HTTP 200 JSON**


```mermaid
%%{init:{
  "sequence": { "showSequenceNumbers": true, "actorMargin": 60 },
  "themeVariables": { "fontFamily": "Inter, Segoe UI, Arial", "fontSize": "12px" }
}}%%
sequenceDiagram
  title list_models() — ModelManager.all() path

  box rgb(156, 151, 131) TSUNAGI 
    participant TS as Tsunagi (/v1/models)
  end

  box rgb(156, 151, 131) ANKI PYTHON 
    participant PY as ModelManager (pylib)
  end

  box rgb(184,81,240) Python ⇄ Rust bridge
    participant PB as Bridge
  end

  box rgb(211,69,22) RUST CORE 
    participant RC as Rust Core
  end

  box rgb(121, 153, 131) SQL 
    participant DB as SQLite
  end

  TS->>PY: list_models()
  PY->>PY: all()
  PY->>PY: all_names_and_ids()
  PY->>PB: _run_command(23, 8) • get_notetype_names
  PB->>RC: get_notetype_names
  RC->>DB: SELECT id, name FROM notetypes
  DB->>RC: rows (id, name)
  RC->>PB: encode NotetypeName[]
  PB->>PY: decode NotetypeName[]

  loop for each id in [(name, id)]
    PY->>PY: get(id)
    alt
      note over PY,DB: CACHE HIT
      rect rgba(0,0,0,0.45)
        PY-->>PY: use cached Notetype
      end
    else
      note over PY,DB: CACHE MISS
      rect rgba(0,0,0,0.45)
        PY->>PB: _run_command(23, 7) • get_notetype_legacy(id)
        PB->>RC: get_notetype_legacy(id)
        RC->>DB: get_notetype.sql / get_fields.sql / get_templates.sql
        DB->>RC: core row, fields, templates
        RC->>PB: encode Notetype
        PB->>PY: decode Notetype
      end
    end
  end

  PY-->>TS: list of Notetypes
  TS-->>TS: paginate / project
  TS-->>TS: HTTP 200 (JSON)

```