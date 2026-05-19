# Changelog

All notable changes to Vodum will be documented in this file.

---

# VERSION=26.05.18

### Security & logs improvements

- Improved log anonymization system to better protect sensitive data in exported logs.
- Added stronger detection and masking for:
  - Bearer tokens
  - Plex/API query tokens
  - public/local IP addresses
- Unified log sanitization logic to avoid inconsistencies between runtime logs and downloaded logs.
- Fixed potential security leaks where some tokens or authorization headers could still appear in downloaded logs.
- Improved startup/bootstrap logging safety by removing raw exception details from early migration prints.
- Reduced risk of exposing sensitive environment, SQL or API information in exported logs.
- Improved consistency between internal logger paths and downloadable log files.



