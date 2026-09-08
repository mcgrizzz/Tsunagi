"""AnkiConnect argument names, isolated from native request validation.

Snapshot: de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e.
The differential suite checks this against the pinned upstream methods.
Only argument binding belongs here; action handlers own value semantics.
"""

SIGNATURES = {'addNote': [['note'], [], False, []],
 'addNotes': [['notes'], [], False, []],
 'addTags': [['notes', 'tags'], ['add'], False, []],
 'answerCards': [['answers'], [], False, []],
 'apiReflect': [[], ['scopes', 'actions'], False, []],
 'areDue': [['cards'], [], False, []],
 'areSuspended': [['cards'], [], False, []],
 'canAddNote': [['note'], [], False, []],
 'canAddNoteWithErrorDetail': [['note'], [], False, []],
 'canAddNotes': [['notes'], [], False, []],
 'canAddNotesWithErrorDetail': [['notes'], [], False, []],
 'cardReviews': [['deck', 'startID'], [], False, []],
 'cardsInfo': [['cards'], [], False, []],
 'cardsModTime': [['cards'], [], False, []],
 'cardsToNotes': [['cards'], [], False, []],
 'changeDeck': [['cards', 'deck'], [], False, []],
 'clearUnusedTags': [[], [], False, []],
 'cloneDeckConfigId': [['name'], ['cloneFrom'], False, []],
 'createDeck': [['deck'], [], False, []],
 'createModel': [['modelName', 'inOrderFields', 'cardTemplates'], ['css', 'isCloze'], False, []],
 'deckNameFromId': [['deckId'], [], False, []],
 'deckNames': [[], [], False, []],
 'deckNamesAndIds': [[], [], False, []],
 'deleteDecks': [['decks'], ['cardsToo'], False, []],
 'deleteMediaFile': [['filename'], [], False, []],
 'deleteNotes': [['notes'], [], False, []],
 'exportPackage': [['deck', 'path'], ['includeSched'], False, []],
 'findAndReplaceInModels': [['modelName', 'findText', 'replaceText'],
                            ['front', 'back', 'css'],
                            False,
                            []],
 'findCards': [[], ['query'], False, []],
 'findModelsById': [['modelIds'], [], False, []],
 'findModelsByName': [['modelNames'], [], False, []],
 'findNotes': [[], ['query'], False, []],
 'forgetCards': [['cards'], [], False, []],
 'getActiveProfile': [[], [], False, []],
 'getCollectionStatsHTML': [[], ['wholeCollection'], False, []],
 'getDeckConfig': [['deck'], [], False, []],
 'getDeckStats': [['decks'], [], False, []],
 'getDecks': [['cards'], [], False, []],
 'getEaseFactors': [['cards'], [], False, []],
 'getIntervals': [['cards'], ['complete'], False, []],
 'getLatestReviewID': [['deck'], [], False, []],
 'getMediaDirPath': [[], [], False, []],
 'getMediaFilesNames': [[], ['pattern'], False, []],
 'getNoteTags': [['note'], [], False, []],
 'getNumCardsReviewedByDay': [[], [], False, []],
 'getNumCardsReviewedToday': [[], [], False, []],
 'getProfiles': [[], [], False, []],
 'getReviewsOfCards': [['cards'], [], False, []],
 'getTags': [[], [], False, []],
 'guiAddCards': [[], ['note'], False, []],
 'guiAddNoteSetData': [['note'], ['append'], False, []],
 'guiAnswerCard': [['ease'], [], False, []],
 'guiBrowse': [[], ['query', 'reorderCards'], False, []],
 'guiCheckDatabase': [[], [], False, []],
 'guiCurrentCard': [[], [], False, []],
 'guiDeckBrowser': [[], [], False, []],
 'guiDeckOverview': [['name'], [], False, []],
 'guiDeckReview': [['name'], [], False, []],
 'guiEditNote': [['note'], [], False, []],
 'guiExitAnki': [[], [], False, []],
 'guiImportFile': [[], ['path'], False, []],
 'guiPlayAudio': [[], [], False, []],
 'guiReviewActive': [[], [], False, []],
 'guiSelectCard': [['card'], [], False, []],
 'guiSelectNote': [['note'], [], False, []],
 'guiSelectedNotes': [[], [], False, []],
 'guiShowAnswer': [[], [], False, []],
 'guiShowQuestion': [[], [], False, []],
 'guiStartCardTimer': [[], [], False, []],
 'guiUndo': [[], [], False, []],
 'importPackage': [['path'], [], False, []],
 'insertReviews': [['reviews'], [], False, []],
 'loadProfile': [['name'], [], False, []],
 'modelFieldAdd': [['modelName', 'fieldName'], ['index'], False, []],
 'modelFieldDescriptions': [['modelName'], [], False, []],
 'modelFieldFonts': [['modelName'], [], False, []],
 'modelFieldNames': [['modelName'], [], False, []],
 'modelFieldRemove': [['modelName', 'fieldName'], [], False, []],
 'modelFieldRename': [['modelName', 'oldFieldName', 'newFieldName'], [], False, []],
 'modelFieldReposition': [['modelName', 'fieldName', 'index'], [], False, []],
 'modelFieldSetDescription': [['modelName', 'fieldName', 'description'], [], False, []],
 'modelFieldSetFont': [['modelName', 'fieldName', 'font'], [], False, []],
 'modelFieldSetFontSize': [['modelName', 'fieldName', 'fontSize'], [], False, []],
 'modelFieldsOnTemplates': [['modelName'], [], False, []],
 'modelNameFromId': [['modelId'], [], False, []],
 'modelNames': [[], [], False, []],
 'modelNamesAndIds': [[], [], False, []],
 'modelStyling': [['modelName'], [], False, []],
 'modelTemplateAdd': [['modelName', 'template'], [], False, []],
 'modelTemplateRemove': [['modelName', 'templateName'], [], False, []],
 'modelTemplateRename': [['modelName', 'oldTemplateName', 'newTemplateName'], [], False, []],
 'modelTemplateReposition': [['modelName', 'templateName', 'index'], [], False, []],
 'modelTemplates': [['modelName'], [], False, []],
 'multi': [['actions'], [], False, []],
 'notesInfo': [[], ['notes', 'query'], False, []],
 'notesModTime': [['notes'], [], False, []],
 'relearnCards': [['cards'], [], False, []],
 'reloadCollection': [[], [], False, []],
 'removeDeckConfigId': [['configId'], [], False, []],
 'removeEmptyNotes': [[], [], False, []],
 'removeTags': [['notes', 'tags'], [], False, []],
 'replaceTags': [['notes', 'tag_to_replace', 'replace_with_tag'], [], False, []],
 'replaceTagsInAllNotes': [['tag_to_replace', 'replace_with_tag'], [], False, []],
 'requestPermission': [['origin', 'allowed'], [], False, []],
 'retrieveMediaFile': [['filename'], [], False, []],
 'saveDeckConfig': [['config'], [], False, []],
 'setDeckConfigId': [['decks', 'configId'], [], False, []],
 'setDueDate': [['cards', 'days'], [], False, []],
 'setEaseFactors': [['cards', 'easeFactors'], [], False, []],
 'setSpecificValueOfCard': [['card', 'keys', 'newValues'], ['warning_check'], False, []],
 'storeMediaFile': [['filename'], ['data', 'path', 'url', 'skipHash', 'deleteExisting'], False, []],
 'suspend': [['cards'], ['suspend'], False, []],
 'suspended': [['card'], [], False, []],
 'sync': [[], [], False, []],
 'unsuspend': [['cards'], [], False, []],
 'updateModelStyling': [['model'], [], False, []],
 'updateModelTemplates': [['model'], [], False, []],
 'updateNote': [['note'], [], False, []],
 'updateNoteFields': [['note'], [], False, []],
 'updateNoteModel': [['note'], [], False, []],
 'updateNoteTags': [['note', 'tags'], [], False, []],
 'version': [[], [], False, []]}

def validate_arguments(action: str, params: dict) -> None:
    """Reject extra/missing keyword arguments before any action side effects."""
    signature = SIGNATURES.get(action)
    if signature is None:
        return
    required, optional, variadic, aliases = signature
    # The pinned reference has no aliases or variadic public signatures.
    # Snapshot verification requires an explicit update if upstream adds them.
    allowed = required + optional
    for name in params:
        if name not in allowed:
            raise ValueError(
                f"AnkiConnect.{action}() got an unexpected keyword argument '{name}'"
            )
    missing = [repr(name) for name in required if name not in params]
    if not missing:
        return
    if len(missing) == 1:
        names = missing[0]
    elif len(missing) == 2:
        names = " and ".join(missing)
    else:
        names = ", ".join(missing[:-1]) + ", and " + missing[-1]
    plural = "s" if len(missing) != 1 else ""
    raise ValueError(
        f"AnkiConnect.{action}() missing {len(missing)} required positional argument{plural}: {names}"
    )
