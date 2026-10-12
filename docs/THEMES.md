# Local display themes

Camper, Rose and Cyberpunk are CSS themes, remembered in each browser's local storage. Optional personal labels live only in the installed private config. The Rose theme uses a pastel plaid accent, clear plum text and small decorative artwork slots for power, solar and environmental monitoring.

Personalised artwork is deliberately not bundled in the public repository. An optional private theme pack can install `power.webp`, `solar.webp` and `air.webp` under `/etc/camper-zero/theme-assets/`. Keep the directory accessible to the service user's group (750) and files readable by that group (640), with root ownership. The private pack installer handles these permissions. Use only trusted local artwork.

The dashboard discovers available files through its authenticated status endpoint; only the Rose theme assigns their image URLs. Images are lazy-loaded, have fixed display dimensions and do not animate. The authenticated `/theme-assets/` route accepts only the three known filenames; it does not expose configuration files or arbitrary paths. No external asset URLs or fonts are requested. Missing files simply leave the normal interface in place, without repeated failed requests or blocking BLE collection.

After adding/removing files, refresh the dashboard; no service restart is needed. The installer preserves the private assets because they live in `/etc`, separately from the reproducible code. Existing private backups include the directory. Never place personal artwork, real names or reference photographs inside the public checkout.

The illustration is decorative and never claims a successful command or substitutes for current telemetry. AC control, stale-state protection, Recorder and all other behaviour are shared across themes. Generic pastel styling can be used without a private image pack.
