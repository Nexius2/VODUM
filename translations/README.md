# VODUM translations

VODUM separates interface translations from user communication translations.

## UI translations

`translations/ui/*.json` contains the admin interface labels and messages.
The English catalog is the reference catalog for keys and placeholders.

## Communication translations

`translations/communication/*.json` contains user-facing communication text:
email subjects, message bodies, Discord user notifications, and generated policy
texts such as block reasons, expiration messages, upgrade suggestions and limits.

## Legacy `lang/` fallback

The repository no longer keeps UI catalogs in `lang/`. Runtime i18n can still
fall back to a legacy `lang/` folder if one exists in an upgraded installation,
but all new UI translation work belongs in `translations/ui/`.

## Adding a language

1. Add `xx.json` to `translations/ui/`.
2. Add `xx.json` to `translations/communication/`.
3. Keep keys and placeholders aligned with the English reference files.
4. Run the translation validation tools before release.
