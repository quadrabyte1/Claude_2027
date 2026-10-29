# Connecting the Claude CLI to the Desktop app, and getting usage/task dashboards (Pax, 2026-10-29)

Context: Thomas works only in the CLI (v2.1.312, macOS). Claude.app 4.29.0 is installed in /Applications (verified locally). No settings were changed.

Evidence tags: **[docs]** verified in official docs (code.claude.com/docs) | **[local]** verified via local `--help`/commands | **[unverified]** inferred or not stated.

## Bottom line
1. There is **no automatic live mirror** of CLI terminal sessions inside the Desktop app. [docs: Desktop keeps "its own session list"; Desktop's cross-session view "doesn't see sessions you started from the terminal CLI"]
2. Three real bridges exist: **handoff** (`/desktop`), **resume** (`/resume` in Desktop after closing the CLI session), and **Remote Control** (`/remote-control`, makes the live local session visible at claude.ai/code and in Claude apps signed into the same account).
3. For "what are my agents doing / how many tokens", the CLI has its own good tools: **`claude agents`** (agent view), **`/usage`**, **statusline**. The Desktop "tasks pane" and "usage ring" only cover Desktop sessions.

## Q1. Can a running CLI session be viewed/controlled from the Desktop app?

### Option A - Hand the session off to Desktop (moves it) [docs + local]
- In the CLI session: `/desktop` (macOS; needs claude.ai subscription login; not API key/Bedrock/Vertex/Foundry). Saves the session, opens it in Desktop, **exits the CLI**. [docs]
- From a shell: `claude --desktop` (opens Desktop on cwd), `claude --desktop --continue` (most recent in cwd) or `claude --desktop --resume <session-id>` (ID from `/status`; names do not work). Needs v2.1.285+. [docs; flag present in local `claude --help`]
- Will not move a session open in another terminal or running in background. If Desktop isn't installed it prints a download link. [docs]

### Option B - Resume in Desktop [docs]
1. Close the session in the terminal.
2. In a Desktop local session's prompt box type `/resume`; it lists CLI-started sessions on this computer; pick one. Same session continues (not a copy), so `claude --resume` still finds it.
- Not available in SSH/WSL/cloud sessions.

### Option C - Remote Control (keeps CLI running, adds a second window) [docs + local]
- Per session: type `/remote-control` (alias `/rc`; optional name: `/remote-control My Project`) inside the running CLI session. Carries over conversation history. First time a confirm dialog appears ("Enable Remote Control").
- Or start with it: `claude --remote-control "Name"` (alias `--rc`), or server mode `claude remote-control` (multi-session; `--spawn worktree`, `--capacity N`, `--name`). [local help confirms all flags]
- Terminal shows `/rc active`; run `/remote-control` again for URL + QR + disconnect panel.
- View/steer from: **claude.ai/code** (session list, computer icon with green dot), **Claude mobile app** (Code tab). Messages sync both ways; subagent/workflow progress is mirrored and can be stopped from the remote device. [docs]
- Auto-connect every session: `/config` -> "Enable Remote Control for all sessions" or `remoteControlAtStartup: true` in `~/.claude/settings.json` (user scope only). [docs] (not set by us)
- **Does the Desktop app list these sessions?** Docs say connected sessions appear "in the session list at claude.ai/code and in the Claude apps on devices signed in to your claude.ai account" and the Trusted Devices / troubleshooting text mentions viewing Remote Control sessions in "Claude Desktop". Reasonable inference: yes, but no page gives explicit "Desktop sidebar shows terminal Remote Control sessions" steps. **[unverified for Desktop specifically; verified for claude.ai/code and mobile]** Safest first test: use claude.ai/code in a browser.
- Remote Control also works the other way: in a Desktop Code-tab local session, `/remote-control` exposes that session to claude.ai/code. [docs]

## Q2. Can Desktop and CLI sessions message each other / see each other?

### Cross-session (peer) messaging [docs + local]
- Needs v2.1.224+ on macOS; "on with nothing to enable". Claude uses `ListAgents`/`SendMessage` itself; you ask in plain words, e.g. `Ask the session running in my other terminal whether the migration finished`, or mention with `@name` (v2.1.232+). To see reachable sessions: `/list-agents` (alias `/peers`). `/status` shows `Peer address` (a `uds:` socket path). [docs]
- Local sessions: delivered over a per-session Unix socket, never via Anthropic servers. A session appears only if it binds an inbox socket. Background sessions (agent view) are listed. [docs]
- Other machines/cloud: only listed while the current session is **connected to Remote Control** (needs claude.ai login, not API key). Messages route via Anthropic servers. Matches what this session's ListAgents said. [docs + local observation]
- Desktop sessions: docs imply Desktop local sessions take part (they note Desktop/VS Code "can't show the approval dialog" for held messages), but **no page states that a CLI `/list-agents` lists Desktop-app sessions or vice versa**. Docs do state Desktop's own cross-session surface does *not* see terminal CLI sessions. **[unverified for CLI<->Desktop direct; test with `/list-agents` while a Desktop session is open]**
- Safety defaults: message cannot approve permissions or change config; commands in it don't run. Inbound control `crossSessionInbound`: accept/hold/refuse (`/config` row "Messages from your other sessions"). With bypass-permissions receivers, default is HOLD for approval. NOTE: our CLAUDE.md-era setup uses bypass permissions, so incoming messages may be held with an approval dialog. [docs]
- Cost: delivered messages count as a prompt and can wake idle sessions (token use). [docs]

### Agent view (`claude agents`) [docs + local]
- `claude agents` opens a single screen of **background** sessions: states Working / Needs input / Idle / Completed / Failed / Stopped. Type a prompt + Enter to dispatch a new background session; Space = peek/reply; Enter or Right = attach; Left on empty prompt = detach; Ctrl+X stop (twice = delete); Ctrl+T pin. [docs]
- Get a running session into it: `/background` (or `/bg`) inside it, or Left arrow on empty prompt. `/fork` copies a session. Shell: `claude --bg "<prompt>"` (+`--name`, `--resume <id>`). Subcommands: `claude attach|logs|stop|respawn|rm`, `claude daemon status|logs|stop`. [docs; all present in local help]
- `claude agents --json [--all] [--cwd path]` for scripts. Local test showed it lists live interactive sessions with pid/cwd/kind (so interactive CLI sessions appear too). [local]
- Runs on your machine only; Desktop app does not show agent view. Idle unpinned sessions stop after ~1 hour but resume on attach. Dispatched sessions get their own git worktree under `.claude/worktrees/` (setting `worktree.bgIsolation`). [docs]
- `defaultToAgentsView` in `/config` makes plain `claude` open it (not set by us). [docs]
- Local state now: `claude daemon status` = not running (starts on demand). [local]

## Q3. Token-usage and running-task dashboards for a CLI-only user

| Need | Tool | How | Tag |
|---|---|---|---|
| Plan limits (5h/7d bars), activity, who burns tokens (skills/subagents/plugins/MCP %), recommendations | `/usage` | Interactive; `d`/`w` toggles 24h/7d; `f` applies fixes (v2.1.305+). Computed from local history on this machine only (no claude.ai/other devices) | docs |
| This session's tokens/cost by model, cache hit stats | `/usage` Session block | Dollar figure is list-price estimate; irrelevant for Max/Pro billing | docs |
| Running agents/sessions | `claude agents`, `/list-agents` | see Q2 | docs/local |
| Always-on numbers in the prompt | Statusline | `/statusline show model, context % and 5h/7d usage` writes `~/.claude/statusline.sh` + `statusLine` setting. JSON fields: `cost.total_cost_usd`, `context_window.used_percentage`, `rate_limits.five_hour.used_percentage`, `rate_limits.seven_day.used_percentage` (+ resets_at) | docs |
| Context window breakdown | `/context` | per-category | docs |
| Usage patterns report | `/insights` | writes HTML `~/.claude/usage-data/report.html` | docs |
| Extra-usage credits | `/usage-credits` | opens claude.ai Settings > Usage in browser | docs |
| `/cost`, `/status` | `/status` shows version, auth, `Peer address`. `/cost` is not described in current cost docs (superseded by `/usage` Session block) | docs (unverified whether `/cost` still exists as alias) |
| Desktop-only views | Usage ring next to model picker (plan usage, "shared across all your Claude Code surfaces"); Context card in session details; **Background tasks** pane (title bar menu) for subagents/shell/workflows inside the *current Desktop session* | docs |
| Web | claude.ai **Settings > Usage** (plan/credit usage); claude.ai/code session list (Remote Control and cloud sessions) | docs |
| Org/API dashboards | Team/Enterprise analytics, Console usage page, OpenTelemetry | Not applicable to a personal plan (unverified which plan Thomas has) | docs |

Important: the Desktop "dashboard of running tasks/agents" Thomas saw is the per-session tasks pane plus sidebar; the CLI equivalent is **agent view**. There is no documented single web dashboard of per-subagent token usage; the nearest is `/usage` attribution.

## Q4. Caveats
- **Plan/auth**: Remote Control and `/desktop` need claude.ai subscription login (Pro/Max/Team/Enterprise). API key, Bedrock/Vertex/Foundry, custom `ANTHROPIC_BASE_URL`, or env `ANTHROPIC_API_KEY` set -> blocked. Team/Enterprise: Owner must enable the toggle. [docs]
- **Desktop install**: needed for `/desktop`, `--desktop`, Desktop `/resume`. Not needed for Remote Control (claude.ai/code in a browser works). Installed here: Claude.app 4.29.0. [local]
- **Same account**: remote views show sessions only for the same claude.ai account; auto-connect sessions appear only in your own account. [docs]
- **Privacy**: Remote Control makes only outbound HTTPS to Anthropic API (no inbound ports); execution and files stay local, **but the session transcript (messages, responses, tool activity) is stored on Anthropic servers** while connected, under the Data usage policy. Not allowed with ZDR/HIPAA orgs. Disable entirely: `"disableRemoteControl": true`. Local peer messaging stays on-machine (Unix socket); cross-machine/cloud messaging goes via Anthropic. [docs]
- **Machine must stay awake** and the `claude` process running; sessions reconnect after sleep; `claude remote-control --continue` restores within ~4h. [docs]
- **Some commands are local-only** from remote devices (`/plugin`, `/resume`). [docs]
- **Env vars**: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` or `DISABLE_GROWTHBOOK` make Remote Control unavailable; `DISABLE_TELEMETRY`/`DO_NOT_TRACK` ok on v2.1.283+. Worth a check of Thomas's env (not done). [docs]
- **Trusted Devices**: if required, each browser/app must enroll after fresh sign-in. [docs]
- **Repo on /Volumes/GIT**: no doc mentions external volumes. Remote Control is outbound-HTTPS only, so the volume itself is not a documented problem. Local inbox sockets live in `/tmp/cc-socks-<uid>` (docs say a private per-user dir) and the agent-view daemon socket in `/tmp/cc-daemon-501` (observed), not on the repo volume. Known project memory: launchd cannot exec scripts on /Volumes/GIT (nosuid); this affects launchd-run scripts, not Claude's daemon, but **whether `claude daemon`/background sessions work with worktrees created under /Volumes/GIT is untested** [unverified]. Dispatched background sessions create git worktrees in `.claude/worktrees/` inside the repo (docs), which would land on the external volume; this repo is a git repo so it should work; disk-eject risk applies.
- **Our setup**: Larry-spawned subagents run inside one session and show in that session's task list / Desktop tasks pane / Remote Control mirror (progress of subagents is mirrored, docs). They are not separate rows in agent view. Agents spawned with `run_in_background` are tracked inside the session, not as `claude agents` entries (unverified inference).

## Suggested minimal trial (no config changes needed to try)
1. In the running CLI: `/remote-control` -> open the shown URL at claude.ai/code, and check whether Claude.app's Code tab also lists it.
2. `/list-agents` (or `/peers`) to see what is reachable; open a Desktop Code-tab session and re-run to test unverified Q2.
3. In a second terminal: `claude agents` to see the live board; `/background` a session to move it there.
4. `/usage`; optionally `/statusline show model, context percent and 5-hour/7-day usage`.
5. `/desktop` only when ready to move the session (it exits the CLI).

## Confidence
High on commands, flags, plan requirements, privacy and messaging semantics (primary docs + local help). Medium-low on (a) Desktop sidebar showing terminal Remote Control sessions and (b) CLI<->Desktop direct peer messaging, and /Volumes/GIT specifics (unverified). `/cost` status unverified.

## Sources
- https://code.claude.com/docs/en/remote-control
- https://code.claude.com/docs/en/desktop (Coming from the CLI; Control which sessions appear on other devices; Background tasks pane)
- https://code.claude.com/docs/en/agent-view
- https://code.claude.com/docs/en/cross-session-messaging
- https://code.claude.com/docs/en/costs
- https://code.claude.com/docs/en/statusline
- Local: `claude --help`, `claude agents --help`, `claude remote-control --help`, `claude agents --json`, `claude daemon status`, /Applications/Claude.app
- Prior report: owner_inbox/claude_2_0_release_research.md
