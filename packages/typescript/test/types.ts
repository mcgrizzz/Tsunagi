import { Tsunagi } from "../src/index.js";

const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:12345" });

// Compiled, never executed. Check guidance at the call site.
async function contract() {
  const cards = await anki.cards.select("id", "question", "queue").take(20);
  const id: number | undefined = cards[0]?.id;
  const question: string | undefined = cards[0]?.question;
  const queue: "new" | "learning" | "review" | "dayLearning" | "preview" | "suspended" | "siblingBuried" | "manuallyBuried" | undefined = cards[0]?.queue;
  void [id, question, queue];
  // @ts-expect-error Unselected fields are not present.
  cards[0]?.interval;
  // @ts-expect-error Reject typos, rather than accepting arbitrary select strings.
  anki.cards.select("questoin");
  // @ts-expect-error Rows use the client's names, not the wire's.
  anki.cards.select("note_id");
  // @ts-expect-error Numeric filters do not accept strings.
  anki.cards.where("interval", "gte", "30");
  // @ts-expect-error Numeric fields cannot use text operators.
  anki.cards.where("interval", "contains", 30);
  // @ts-expect-error Named values are compared by name.
  anki.cards.where("queue", "eq", -1);
  // @ts-expect-error Named values have no order.
  anki.cards.where("flag", "gt", "red");
  // @ts-expect-error A misspelled value is a compile error.
  anki.cards.where("flag", "eq", "grene");
  // @ts-expect-error in takes a list.
  anki.cards.where("queue", "in", "new");
  anki.cards.where("queue", "in", ["siblingBuried", "manuallyBuried"]).where("deckName", "startsWith", "Japanese::");
  anki.reviews.where("rating", "eq", null).where("type", "notIn", ["manual", "rescheduled"]);
  // @ts-expect-error null only where the field can be null.
  anki.cards.where("interval", "eq", null);
  anki.cards.where("originalPosition", "eq", null);
  // @ts-expect-error Use a supported sort, not an arbitrary row field.
  anki.cards.orderBy("question");
  anki.cards.orderBy("easeFactor", "desc");
  const ids: number[] = await anki.cards.values("id").take(10);
  const flags: ("none" | "red" | "orange" | "green" | "blue" | "pink" | "turquoise" | "purple")[] = await anki.cards.values("flag").take(10);
  // @ts-expect-error Array-valued fields are not single values.
  anki.notes.values("tags");
  void [ids, flags];
  const page = await anki.notes.select("id", "fields").page({ total: true });
  const field: string | undefined = page.items[0]?.fields[0]?.value;
  const index: number | undefined = page.items[0]?.fields[0]?.index;
  const total: number | null = page.total;
  void [field, index, total];
  const count: number = await anki.reviews.where("cardId", "eq", 1).count();
  const latest = await anki.reviews.distinctOn("cardId").orderBy("id", "desc").select("cardId", "rating", "interval").take(10);
  const rating: "again" | "hard" | "good" | "easy" | null | undefined = latest[0]?.rating;
  void [count, rating];
  const memory = await anki.cards.select("memoryState").take(1);
  const stability: number | undefined = memory[0]?.memoryState?.stability;
  void stability;
  const types = await anki.noteTypes.select("name", "fields", "templates").take(10);
  const fieldName: string | undefined = types[0]?.fields[0]?.name;
  const front: string | undefined = types[0]?.templates[0]?.qfmt;
  void [fieldName, front];

  const report = await anki.notes.createMany([], { onError: "collect" });
  for (const item of report.items) {
    if (item.ok) { const id: number = item.value.id; void id; }
    else { const message: string = item.error.message; void message; }
  }
  const created = await anki.notes.create({
    deck: "Japanese", noteType: { id: 1 }, fields: { Front: "犬" },
    audio: [{ url: "https://example.com/inu.mp3", filename: "inu.mp3", fields: ["Front"] }],
    picture: [{ data: new Uint8Array([1, 2]), filename: "inu.png" }],
    duplicates: { scope: "deck", includeSubdecks: true },
  }, { cards: true });
  const cardIds: number[] | null = created.cards;
  void cardIds;
  // @ts-expect-error A file is bytes, a URL or a path, not two of them.
  anki.notes.create({ deck: "D", noteType: "B", fields: {}, audio: [{ url: "u", path: "p" }] });
  const failed = await anki.notes.createMany([], { onError: "collect" });
  for (const item of failed.items) {
    if (!item.ok) {
      const code: "duplicate" | "invalidNote" | "invalidAttachment" | "ankiError" = item.error.code;
      void code;
      // @ts-expect-error Answers are read-only.
      item.error.code = "duplicate";
    }
  }
  const checks = await anki.notes.check([{ deck: "D", noteType: "B", fields: { Front: "x" } }]);
  const state: "normal" | "empty" | "duplicate" | "missingCloze" | "invalid" | "unknown" | undefined = checks[0]?.state;
  void state;
  const upserted = await anki.notes.upsert({ deck: "D", noteType: "B", fields: { Front: "x" }, fieldRules: { "*": "append" } });
  if (upserted.action === "updated") { const changed: string[] = upserted.fieldsChanged; void changed; }
  await anki.notes.delete([1, 2]);
  await anki.cards.setFlag([1], "green");
  // @ts-expect-error Flags are named.
  await anki.cards.setFlag([1], 3);
  await anki.cards.answer([{ cardId: 1, rating: "good" }]);
  const stored = await anki.media.upload({ filename: "a.mp3", data: new Uint8Array() });
  const renamed: boolean = stored.renamed;
  void renamed;

  const watching = await anki.notes.search("deck:Mining").select("fields", "tags").watch({
    added: (rows, change) => { const id: number | undefined = rows[0]?.id; const tags: string[] | undefined = rows[0]?.tags; const first: boolean = change.initial; void [id, tags, first]; },
    updated: rows => { const by: unknown = rows; void by; },
    removed: (ids, change) => { const gone: number[] = ids; const app: string | null = change.app; void [gone, app]; },
  }, { signal: AbortSignal.timeout(1_000) });
  watching.stop();
  await watching.done;
  await anki.tags.watch({ removed: names => { const gone: string[] = names; void gone; } });
  // @ts-expect-error An unselected field isn't on a watched row.
  await anki.notes.select("tags").watch({ added: rows => rows[0]?.fields });
  // @ts-expect-error Handlers are named: a misspelled one is refused.
  await anki.notes.watch({ add: () => {} });
  // @ts-expect-error An ordered query can't be watched.
  await anki.notes.orderBy("created").watch({});
  // @ts-expect-error Nor one with distinctOn.
  await anki.reviews.distinctOn("cardId").watch({});
  // @ts-expect-error Nor bare values.
  await anki.cards.values("id").watch({});
  // @ts-expect-error Tsunagi sends no events for media.
  await anki.media.watch({ added: () => {} });
  const changes = await anki.notes.onChange(async () => { await anki.notes.take(20); });
  changes.stop();
  // @ts-expect-error onChange is on the resource, not on a query: it doesn't follow a search.
  anki.notes.search("deck:Mining").onChange(() => {});
  // @ts-expect-error No events for deck presets.
  anki.deckPresets.onChange(() => {});
  await anki.cards.onAnswered(answer => {
    const rating: "again" | "hard" | "good" | "easy" = answer.rating;
    const stability: number | undefined = answer.memoryState?.stability;
    const by: "ui" | "api" | null = answer.by;
    void [rating, stability, by];
  });
  await anki.collection.onSync({ finished: () => {} });
  // @ts-expect-error Handlers are named.
  await anki.collection.onSync({ done: () => {} });
  await anki.decks.onCounts(counts => { const due: number | undefined = counts[0]?.reviewCount; void due; });
  // @ts-expect-error Counts are a decks thing.
  anki.cards.onCounts(() => {});
  const accessChanges = await anki.onAccessChange(access => { const role: string = access.caller.role; void role; });
  await accessChanges.done;
  const raw = await anki.raw.request("GET", "/v1/capabilities");
  // @ts-expect-error Raw JSON requires checking/decoding.
  raw.data.operations;
  await anki.collection.sync({ idempotencyKey: "sync-operation" });
  const keyedWrite = { idempotencyKey: "note-operation", timeoutMs: 1_000 };
  await anki.collection.startSync(keyedWrite);
  const health = await anki.health();
  const state2: "ready" | "syncing" | "closed" | "busy" = health.collection.state;
  void state2;
  const access = await anki.access();
  const role: string = access.caller.role;
  const thisComputer: boolean = access.caller.thisComputer;
  const permitted: boolean = access.can(anki.notes.create);
  const decision = access.check(anki.notes.update);
  if (!decision.allowed) {
    const explanation: string = decision.reason;
    void explanation;
  }
  void [role, thisComputer, permitted];
  // @ts-expect-error Access checks take a method or a query, not a name.
  access.can("notes.create");
  // @ts-expect-error Reports are immutable snapshots.
  access.caller.role = "Everything";
  const due = anki.cards.search("is:due").select("id");
  const queryDecision = await due.checkAccess();
  const batch = access.checkMany({ due, create: anki.notes.create, sync: anki.collection.sync, suspend: anki.cards.suspend });
  const allowed: boolean = batch.checks.create.allowed;
  void [queryDecision, allowed];
  // @ts-expect-error Named results retain the requested keys.
  batch.checks.missing;
  // @ts-expect-error Arbitrary functions are not operation references.
  access.check(async () => {});
  // @ts-expect-error Promises are already executing, rather than checkable targets.
  access.check(Promise.resolve([]));
  // @ts-expect-error Bulk checks accept query/method references, not scope strings.
  access.checkMany({ create: "notes.create" });
}
void contract;
