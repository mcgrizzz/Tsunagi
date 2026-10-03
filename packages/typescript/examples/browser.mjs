import { Tsunagi, HttpError } from "../dist/index.js";

const form = document.querySelector("#connection");
const read = document.querySelector("#read");
const cancel = document.querySelector("#cancel");
const status = document.querySelector("#status");
const results = document.querySelector("#results");
let controller;

cancel.addEventListener("click", () => controller?.abort());
form.addEventListener("submit", async event => {
  event.preventDefault();
  controller = new AbortController();
  read.disabled = true;
  cancel.disabled = false;
  results.textContent = "";
  status.textContent = "Reading…";
  try {
    const anki = new Tsunagi({
      baseUrl: document.querySelector("#url").value,
      apiKey: document.querySelector("#key").value,
    });
    const cards = await anki.cards.search("is:due")
      .select("id", "question").take(20, { signal: controller.signal });
    results.textContent = JSON.stringify(cards, null, 2);
    status.textContent = `Read ${cards.length} cards.`;
  } catch (error) {
    status.textContent = controller.signal.aborted ? "Read cancelled."
      : error instanceof HttpError ? `Anki returned HTTP ${error.status}. Check the app's access settings.`
      : `${error.message}. Check the URL, connection, and allowed browser origins.`;
  } finally {
    read.disabled = false;
    cancel.disabled = true;
  }
});
