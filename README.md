# Hormuz Traffic Tracker

Daily ship transit data for the Strait of Hormuz, with annotated geopolitical events from 2019 to today.

Live site: [hormuz-traffic.com](https://hormuz-traffic.com)

## Data source

Transit-call counts come from the [IMF PortWatch](https://portwatch.imf.org) project, which derives them from satellite AIS data. The pipeline checks the complete upstream history every day, validates it, replaces the local SQLite cache, and recomputes the site's static JSON. PortWatch publishes observations in batches, so the latest source date can lag the pipeline check.

The headline is the latest seven complete source days compared with a fixed 365-day pre-closure baseline (2025-02-28 through 2026-02-27). Counts cover tanker, container, dry-bulk, general-cargo, and ro-ro transit calls. They can omit ships without sufficient AIS observations and should not be read as a census of every physical crossing.

## How it works

```
GitHub Actions (daily 06:00 UTC)
  -> downloads PortWatch CSV
  -> updates SQLite cache
  -> writes site/data/transits.json
  -> commits only when observations, revisions, or methodology change
  -> Cloudflare Pages auto-deploys
```

## Local development

Pipeline:
```bash
cd pipeline
pip install -r requirements.txt
python fetch_portwatch.py
```

Site (any static server works):
```bash
cd site
python -m http.server 8000
# open http://localhost:8000
```

## Adding new events

Edit `site/data/events.json`. Each entry needs `date`, `label`, and `category`. The chart will automatically render a new annotation on next deploy.

## Support

If this site is useful to you, consider [buying me a coffee](https://buymeacoffee.com/) to help cover the domain.
