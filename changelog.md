# Changelog

All notable changes to Vodum will be documented in this file.

---

# VERSION=26.05.20


### general improvements
* Fixed referral cleanup migration issue on older databases by upgrading the user_referrals status constraint and improving migration safety
* UI fix
* translations
* Automatically force expiration_date_override for Plex owners and Jellyfin admins during media syncs
* Prevent admin/owner accounts from losing expiration override even without manual user save
* Improved consistency between provider roles (Plex/Jellyfin) and Vodum subscription logic
* Owner/admin accounts are now permanently protected from automatic expiration handling
* Fixed Jellyfin multi-server identity handling to prevent automatic merges based only on username.
* Jellyfin users are now uniquely identified per server using their provider identity instead of shared usernames.
* Same usernames across different Jellyfin servers are now treated as separate users unless manually merged by the admin.
* Prevented unintended password/actions conflicts caused by duplicate Jellyfin usernames across servers.

### added
* Added per-user expiration override option with automatic 1-year renewal when reaching the warning period.
* Added Jellyfin password management directly from the user page
* New “Change password” modal with multi-server Jellyfin support
* Automatic detection of Jellyfin servers linked to the user
* Added secure password update requests directly to Jellyfin API
* Added optional local password storage support per Jellyfin server
* Improved CSRF handling for AJAX modal actions
* Fixed modal/form conflicts caused by nested forms in user detail page
* Improved Jellyfin API authentication compatibility using X-Emby-Token headers
* Added detailed backend error handling and JSON responses for password operations
* Improved browser password manager handling for Jellyfin password fields
* Added automatic expiration override lock for Plex owners and Jellyfin admins
* Owner/admin accounts now automatically force expiration override and disable manual editing
* Updated action buttons styling for better UI consistency with primary Save button style
* Improved overall user management modal stability and frontend behavior

