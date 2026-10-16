"""Catalog entries first sent by Easydict (https://github.com/tisfeng/Easydict at af5b654):
its requests that no other entry covers (tests/clients/easydict/client.py)."""


from clients.support import case, named, note

ENTRIES = named("Easydict", [
    # notePayload() in AnkiConnectClient.swift: Back mapped to {Phonetic}, which this lookup lacks.
    case("addNote empty mapped field", "addNote", {"note": {
        **note(fields={"Front": "猫", "Back": ""}, tags=["easydict"]), "options": {"allowDuplicate": False}}},
        effects=True),
])
