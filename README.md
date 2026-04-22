# Hormuz Traffic Tracker

Daily ship transit data for the Strait of Hormuz, with annotated geopolitical events from 2019 to today.

Live site: [hormuz-traffic.com](https://hormuz-traffic.com)

## Data source

Daily transit counts come from the [IMF PortWatch](https://portwatch.imf.org) project, which derives them from satellite AIS data. The pipeline pulls the latest CSV every day and recomputes the site's static JSON.

## How it works

```
GitHub Actions (daily 06:00 UTC)
  -> downloads PortWatch CSV
  -> updates SQLite cache
  -> writes site/data/transits.json
  -> commits to repo
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
