// Exact-time dispatcher for the GitHub Actions workflows that care about the
// clock. GitHub's own cron has been landing this repo's schedules 3-6 hours
// late (the "8:30am ET" morning post was going out at noon-2pm), so Cloudflare
// fires workflow_dispatch at the minute instead. The GitHub schedules stay on
// as a fallback: every workflow dispatched here is idempotent (refresh commits
// only on change, the morning post has a ledger dedupe gate, the reply bot and
// outreach are capped per day from their logs), so a late GitHub run after
// ours is a no-op.
//
// This is its own tiny Worker (dispatcher/wrangler.jsonc), deliberately
// separate from the site's config so it can't touch how the site deploys.
//
// Secret: GITHUB_TOKEN, a fine-grained PAT for repo ndaly111/Hormuz with
// "Actions: read and write".
//   npx wrangler secret put GITHUB_TOKEN -c dispatcher/wrangler.jsonc
// Without it every dispatch fails with 401 and the GitHub schedules carry on.

const REPO = "ndaly111/Hormuz";

// cron (UTC) -> workflow file. Keep in sync with triggers.crons in wrangler.jsonc.
const SCHEDULE = {
  "0 6 * * *":   "daily-refresh.yml",   // PortWatch fetch; must land before the post
  "30 12 * * *": "daily-post.yml",      // 8:30am ET morning post
  "0 14 * * *":  "reply-scout.yml",     // 10:00am ET reply bot
  "30 15 * * *": "pack-outreach.yml",   // starter-pack outreach
};

async function dispatch(env, file) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${file}/dispatches`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "hormuz-traffic-dispatcher",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  if (r.status !== 204) {
    throw new Error(`${file}: HTTP ${r.status} ${await r.text()}`);
  }
  console.log(`dispatched ${file}`);
}

export default {
  async fetch() {
    return new Response("hormuz-traffic dispatcher: cron only", { status: 404 });
  },

  async scheduled(event, env, ctx) {
    const file = SCHEDULE[event.cron];
    if (!file) {
      console.log(`no workflow mapped to cron "${event.cron}"`);
      return;
    }
    ctx.waitUntil(dispatch(env, file));
  },
};
