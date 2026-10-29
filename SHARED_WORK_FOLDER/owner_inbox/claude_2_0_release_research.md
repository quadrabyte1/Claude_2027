# "Claude 2.0" release research (Pax, 2026-10-29)

## What actually shipped (top line)
**There is no product called "Claude 2.0" / "Claude Code 2.0".** Claude Code is at 2.1.312 and its changelog has no 2.0 release entry. The only "2.0" items from the last ~3 weeks are **API SDK major versions released 2026-10-21** (primary source: platform release notes):
- Python SDK **2.0.0**, Go SDK **2.0.0**, Ruby SDK **2.0.0**, `ant` CLI **2.0.0** (also TS 1.0.0, PHP 1.0.0, Java 3.0.0, C# 13.0.0), plus **API version `2026-10-21`**. Breaking changes; license moved MIT -> Apache 2.0. Claude Code 2.1.307 added `/claude-api api-version` to migrate code to that API version.
- Most likely explanation: Thomas heard about the SDK 2.0 release, or conflated it with **Claude Duet** (same day, 10/21). Unverified guess.

### Other things that did ship (last ~3 weeks)
| Date | Item | Source quality |
|---|---|---|
| Oct 7 | **Claude Haiku 5.5** (`claude-haiku-5-5`, $0.10/$0.50 per MTok, 1M ctx, adjustable effort); Sonnet 5.5 cache reads halved to $0.10 | Primary (anthropic.com/news, release notes) |
| Oct 7 | Max/Team plans get monthly API credits ($100 Max5x, $200 Max20x) | Primary |
| Oct 8 | Claude Docs, Slides, Design leave beta (all plans); Dashboards and Motion enter beta | Secondary (orcarouter blog) |
| Oct 9 | Managed Agents "dynamic workflows" beta | Primary |
| Oct 15 | Code Review GA (Team/Enterprise); Opus 5.5 fast mode out of preview | Primary (fast mode) / secondary (Code Review) |
| Oct 20-23 | User profiles, org webhooks, web-fetch admin controls, Claude Tag API beta | Primary |
| Oct 21 | **Claude Duet** research preview (proactive background agent, US Pro/Max waitlist, built on Opus 5.5); **Claude Security** public beta (Enterprise) | Secondary only (VKTR, foreign-language press, blog); I could not reach Anthropic's own page |
| Oct 22 | Agent Skills donated to Linux Foundation's Agentic AI Foundation | Secondary |
| Claude Code 2.1.301-2.1.312 | `/auto-mode-setup`, idle compaction setting, `CLAUDE_CODE_AUTO_MODE_MODEL`, Monitor on Bedrock/Vertex, `claude ultrareview` needs workspace trust, mod hooks | Primary (CHANGELOG; dates not shown) |
Not Anthropic-announced in Oct: Opus 5.5 / Sonnet 5.5 (earlier), Fable 5.1 (Sept 1, Claude Code wk 36).

## Our setup (grounding)
- Larry orchestrator spawns persona-file subagents (18 members, all Sonnet 5.5 as of 10/22); SQLite dashboard; project hook = one Stop hook (`check_app_version_bump.sh`); user hooks = Stop + SubagentStop notifications; voice enabled; Artifacts used.
- **Finding:** `~/.claude/settings.json` pins `"model": "claude-sonnet-4-6"` - stale vs. the team standard Sonnet 5.5. Worth a look (not changed).

## Recommended adoptions (ranked)
1. **Fix stale default model in ~/.claude/settings.json** - S. Currently Sonnet 4.6 while the team is on 5.5. Consider `fallbackModel` and `modelPicker` too. Risk: none beyond cost/behaviour change.
2. **Haiku 5.5 for mechanical subagents** - S. $0.10/$0.50, adjustable effort; fits narrow roles (Reed bulk SQL, link checks, Zane-style lookups). Caveat: memory says "all team on Sonnet 5.5, no haiku override" - Thomas's explicit choice, so only propose, don't apply. Risk: weaker on complex coding.
3. **`/auto-mode-setup` + auto mode (default since Aug 14)** - S. Fewer permission prompts for background agents; fits your `skipDangerousModePermissionPrompt` habit with a safer classifier. Risk: classifier false blocks; review hard-deny rules.
4. **Agent view (`claude agents`) + cross-session messaging + `/fork`** - S/M. Overlaps your hand-rolled dashboard for "what is running/blocked"; keep SQLite for history. Risk: two sources of truth.
5. **Hooks upgrades** (conditional `if` hooks, `$CLAUDE_EFFORT`) - S. Could enforce "open Larry task row" or version-bump checks more precisely. Risk: low.
6. **`/skill-doctor`, `/usage` per-subagent breakdown** - S. Shows what persona/skill context costs; useful with 18 personas. Risk: none.
7. **Idle compaction (/config)** - S. Long Larry sessions benefit; risk: minor summary loss.
8. **Python/TS SDK 2.0 migration** - M, only if any Flask app calls the Anthropic SDK (grep first). Breaking changes; use `/claude-api api-version`. Otherwise defer.
9. **`claude plugin eval` / Routines** - M. Possible later for periodic maintenance jobs (e.g., link-check app); no urgent need.

## Skip (and why)
- **Claude Duet** - US waitlist, consumer personal-assistant, overlaps Herman/Sprite (our own local-first design); no API, not available yet.
- **Claude Security, Code Review GA, Tag API, Compliance API, user profiles, org webhooks** - Team/Enterprise or API-platform admin features; not our plan.
- **Managed Agents / dynamic workflows (API beta)** - server-hosted; our workflow is local Claude Code.
- **Dashboards / Motion beta, Claude Models on Google Cloud, Azure fast mode** - no fit.
- **Agent Skills foundation donation** - news only, no action.

## Confidence
High that no "Claude 2.0" product exists and that SDK/CLI 2.0.0 shipped 10/21 (primary). Medium on Duet/Code Review GA/Docs-Design GA details (secondary only). Changelog dates were not visible; the Claude Code version-to-date mapping is unknown.

## Sources
- https://platform.claude.com/docs/en/release-notes/overview
- https://www.anthropic.com/news (and /news/claude-haiku-5-5)
- https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
- https://code.claude.com/docs/en/whats-new
- Secondary: https://www.orcarouter.ai/blog/claude-news-what-anthropic-shipped-in-october-2026 ; https://www.vktr.com/ai-platforms/claude-duet-anthropic-previews-an-ai-agent-that-messages-you-first/ ; manifold.markets (prediction markets, rumor-grade)
