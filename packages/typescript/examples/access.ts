// docs/capabilities.md's example, compiled by `npm test` (test/readme.test.mjs keeps them the same).
import { Tsunagi, type AccessSnapshot } from "../src/index.js";

declare const anki: Tsunagi;
declare function showSuspendButton(access: AccessSnapshot): void;

const access = await anki.access();
if (!access.can(anki.cards.suspend)) console.log(access.check(anki.cards.suspend).reason);
await anki.onAccessChange(showSuspendButton); // a role, key or setting changed
