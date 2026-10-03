import { Tsunagi, AuthenticationError, PermissionError } from "../src/index.js";
import type { CreatedNote, NoteInput } from "../src/index.js";

// Optional UI preflight, followed by handling the actual request's result.
// The application decides when to invoke this function; it can create a note.
export async function createNoteWithAccessGuidance(
  anki: Tsunagi,
  input: NoteInput,
  showMessage: (message: string) => void,
): Promise<CreatedNote | undefined> {
  try {
    const access = await anki.access();
    showMessage(`${access.caller.name}: ${access.caller.role}`);
    const creation = access.check(anki.notes.create);
    if (!creation.allowed) {
      showMessage(creation.reason);
      return;
    }
    return await anki.notes.create(input);
  } catch (error) {
    // Permission changes after discovery still arrive as a normal API error.
    if (error instanceof AuthenticationError) {
      showMessage(error.detail ?? "Check the API key or the applicable No key role in Tsunagi settings.");
      return;
    }
    if (error instanceof PermissionError) {
      showMessage(error.detail ?? "This app cannot perform that request. Check its role in Tsunagi settings.");
      return;
    }
    throw error;
  }
}

// One discovery request for every feature on this screen. No queries or writes run.
export async function checkScreenAccess(anki: Tsunagi, signal?: AbortSignal) {
  const due = anki.cards.search("is:due").select("id", "question");
  const access = await anki.access({ signal });
  const checks = access.checkMany({
    dueCards: due,
    addNote: anki.notes.create,
    sync: anki.collection.sync,
  });
  return { due, checks };
}
