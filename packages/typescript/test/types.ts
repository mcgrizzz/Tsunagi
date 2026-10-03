import { Tsunagi } from "../src/index.js";

const anki = new Tsunagi({ baseUrl: "http://127.0.0.1:12345" });

// Compiled, never executed. Check guidance at the call site.
async function contract() {
  const cards = await anki.cards.select("id", "question").take(20);
  const id: number | undefined = cards[0]?.id;
  const question: string | null | undefined = cards[0]?.question;
  void [id, question];
  // @ts-expect-error Unselected fields are not present.
  cards[0]?.interval;
  // @ts-expect-error Reject typos, rather than accepting arbitrary select strings.
  anki.cards.select("questoin");
  // @ts-expect-error Numeric filters do not accept strings.
  anki.cards.where("interval", "gte", "30");
  // @ts-expect-error Numeric fields cannot use string operators.
  anki.cards.where("interval", "contains", 30);
  // @ts-expect-error Use a supported sort, not an arbitrary row field.
  anki.cards.orderBy("question");
  const ids: number[] = await anki.cards.values("id").take(10);
  // @ts-expect-error Array-valued fields are not scalar queries.
  anki.notes.values("tags");
  void ids;
  const page = await anki.notes.select("id", "fields").page();
  const field: string | undefined = page.items[0]?.fields[0]?.value;
  void field;
  const report = await anki.notes.createMany([], { onError: "collect" });
  for (const item of report.items) {
    if (item.ok) { const id: number = item.value.id; void id; }
    else { const message: string = item.error.message; void message; }
  }
  const raw = await anki.raw.request("GET", "/v1/capabilities");
  // @ts-expect-error Raw JSON requires checking/decoding.
  raw.data.operations;
  await anki.collection.sync({ idempotencyKey: "sync-operation" });
  const keyedWrite = { idempotencyKey: "note-operation", timeoutMs: 1_000 };
  await anki.collection.startSync(keyedWrite);
  const access = await anki.access();
  const role: string = access.caller.role;
  const permitted: boolean = access.can(anki.notes.create);
  const decision = access.check(anki.notes.update);
  if (!decision.allowed) {
    const explanation: string = decision.reason;
    void explanation;
  }
  void [role, permitted];
  // @ts-expect-error Access checks use known actions, not inferred role/grant names.
  access.can("write:notes");
  // @ts-expect-error Reports are immutable snapshots.
  access.caller.role = "Everything";
  const due = anki.cards.search("is:due").select("id");
  const queryDecision = await due.checkAccess();
  const batch = access.checkMany({ due, create: anki.notes.create, sync: anki.collection.sync });
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
