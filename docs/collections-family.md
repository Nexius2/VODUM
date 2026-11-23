# Family

Family is a clickable model under More ways to discover, alongside Kids and IMDb. It uses only the selected Plex/Jellyfin library inventory: local Family/Kids genre labels (including common translated forms) identify candidates. Animation alone does not qualify. It requires neither TMDb nor Arr and rejects acquisition mode. Movie and series libraries can be configured together.

Top sorts by the server audience/community rating (Plex audienceRating, falling back to rating; Jellyfin CommunityRating). Latest releases sorts by original release date. It uses the existing limit, presentation language, priority, activation, visibility, preview and cleanup mechanisms. Selection depends on the server's genre metadata.

Family and Kids expose an optional required audio language, distinct from presentation language and original-language filters. ISO language tags are normalized to their base language, so fr-FR, fr-BE, fr-CA and ISO-639-2 fre/fra all match French. Every existing episode must have the language for a series to qualify. Successful audio checks are cached per inventory generation. Unknown connection/lookup failures preserve existing publication and report a warning/error; confirmed lack of the required language excludes the title.

When Kids requires audio, only verified local versions qualify; absent versions cannot be acquired without verifying their tracks. Its title limit is applied after this verification.
