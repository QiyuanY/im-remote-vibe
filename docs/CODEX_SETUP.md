# Codex Agent Setup

Vibe Remote can route individual Slack channels / Telegram chats to Codex instead of Claude Code. This guide walks through enabling Codex end-to-end.

## 1. Install and authenticate Codex CLI

```bash
brew install codex     # or follow https://github.com/openai/codex
codex --help           # verify installation
codex                  # sign in when prompted
```

Codex CLI must be available on the PATH of the host running Vibe Remote. The bot automatically runs Codex with `--json` and `--dangerously-bypass-approvals-and-sandbox`, so make sure you trust the workspace it operates in.

## 2. Configure environment variables

In `.env` (copied from `.env.example`):

```
CODEX_ENABLED=true        # default; set false only if CLI is unavailable
CODEX_CLI_PATH=codex      # customise if the binary lives elsewhere
CODEX_DEFAULT_MODEL=gpt-5-codex  # optional
CODEX_EXTRA_ARGS=--ask-for-approval never  # optional extra flags
```

No additional flag is required to bypass approvals—the bot always adds `--dangerously-bypass-approvals-and-sandbox`.

## 3. Route channels to Codex

Copy the example routing file and edit it:

```bash
cp agent_routes.example.yaml agent_routes.yaml
```

Example contents:

```yaml
default: claude
slack:
  default: claude
  overrides:
    C01ABCD2EFG: codex          # Slack channel ID
telegram:
  default: claude
  overrides:
    "123456789": codex          # Telegram chat ID
```

Each Slack channel ID (starts with `C`) or Telegram chat ID gets its own agent. Routes fall back to the platform default, then to the global `default`.

`agent_routes.yaml` is gitignored so you can maintain different mappings per environment. Alternatively, point `AGENT_ROUTE_FILE` to a custom path.

## 4. Restart the bot and test

```bash
source venv/bin/activate
./start.sh
```

In a routed Slack channel run `@VibeRemote status` or any question—you should see an acknowledgement like `📨 Codex received, processing...` followed by Codex’s reply. If the CLI is missing, the bot will reply with “Agent `codex` is not configured”.

## 5. Troubleshooting

- **“Agent `codex` is not configured”**: ensure `codex` CLI is installed and on PATH; check `CODEX_ENABLED`.
- **`codex exec` errors**: inspect the Slack/Telegram stderr snippet or tail `logs/vibe_remote.log`.
- **Routing not applied**: confirm the channel ID matches Slack’s `C...` value (copy from channel details) or Telegram’s numeric chat ID, and restart the bot after editing `agent_routes.yaml`.
