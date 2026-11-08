# Claude Desktop and terminal-runner login

Historical report. Current requirements and boundaries are in the [specification](../specification.md), and decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state at the time of the experiment.

06.11.2026, following the user's request to investigate Claude while Desktop was working.

## Findings

The computer has `/Applications/Claude.app`, version **4.23118.0**.
The terminal command `/Users/demets/.local/bin/claude` points to stable
Claude Code **2.1.317**. No other `claude` commands were found in `/opt/homebrew/bin`
or `/usr/local/bin`. `CLAUDE_CONFIG_DIR` and API/billing overrides were not set
in the verification environment.

Official `claude auth status --json` returned **exit code 1**, `loggedIn=false`,
`authMethod=none`, `apiProvider=firstParty`. The same result was obtained outside
the sandbox; the current sandbox restriction does not explain that status.
A working Desktop alone does not establish that this CLI is signed in.

According to the [official Desktop/CLI comparison](https://code.claude.com/docs/en/desktop#cli-flag-equivalents),
Desktop does not provide `--print`/`--output-format`; the background runner
therefore still uses terminal Claude Code. The CLI itself handles login according
to [Anthropic's instructions](https://code.claude.com/docs/en/authentication).

## brofessor fixes

The [CLI reference](https://code.claude.com/docs/en/cli-reference#cli-commands)
at the time named `authMethod=claude.ai`. The adapter accepted `oauth_token` and
`claude_ai`; it now also accepts `claude.ai`. All cases require
`loggedIn=true` and `apiProvider=firstParty`. API keys, helpers, and third-party
providers are still rejected, and generation does not start before verification.

Exit code 1 from the status command is now parsed as ordinary signed-out JSON,
rather than a general process error. Real `brofessor.executors.doctor('claude')`
reports `available=false` and the explicit `claude auth login` command.
Other commands continue to require exit code 0 by default.

## Checks and current boundary

**147 offline checks** of adapters, Pydantic navigation, collections, pipeline,
and worker passed. The existing Claude-restrictions test now covers three
subscription-status variants. Separate negative cases check rejection before
text is sent. A real synthetic CLI with exit code 1 checks clear doctor/generate
diagnostics and absence of inference. Ruff check/format passed for both modified
Python files.

The user completed official `claude auth login --claudeai` through ordinary
Terminal. The first run in the service terminal was stopped: the user received
a one-time code and needed to paste it directly into the CLI.
Opening the CLI-provided `https://claude.com/cai/oauth/authorize` address directly
and using the user's accessible Terminal completed login. The documentation link
in the earlier response was not a login page; that unnecessary step was corrected.
The agent did not read or copy passwords, one-time codes, or tokens.
The subscription and payment method were unchanged.

After login, official status returned **exit code 0**, `loggedIn=true`,
`authMethod=claude.ai`, `apiProvider=firstParty`. Thus the new method value
was confirmed by the installed CLI, not only documentation.
`brofessor.executors.doctor('claude')` returned `available=true`,
`auth_mode=claude_subscription` for version 2.1.317.

## Real navigation and content verification

The existing `tools/probe_collection_navigation.py` was run with `--provider claude`
and model alias `sonnet`, through the ordinary worker, Pydantic Agent, and bounded
CLI runner. The exact server-side model revision was not established. Sources were
eight synthetic notes; the personal vault and user files were not used.

Job **`88e54976525c4a18`** completed in **23,586 s**, with four real calls:
three `NavigationStep` and one `Answer`. Navigation searched for River,
listed directories, and read four originals: Главная (Home), River, North,
and South. The answer cited three substantive documents and seven exact quotes.

The entire answer and every quote were checked against originals: the current
**12 ms** timeout is separated from historical **35 ms**; **48 requests on one node**,
absence of a cluster guarantee, and untested power loss are retained. Reasons for
differences between runs were not invented. All seven quotes occur in original
fragments without word substitutions, and all source files remained unchanged.
Navigation has `complete`, with no report problems. This is a short functional
and content check, not a quality assessment for large materials.

Artifacts outside the repository: `/private/tmp/brofessor-claude-auth-2026-11-06/` —
`calls.json`, `result-ask.json`, `audit.json`, returned answers, and the workspace
with sources/checkpoints. No new audio generation or changes to the user's model
selection were performed. The temporary ordinary-Terminal launcher was
`/private/tmp/brofessor-claude-login/Claude Code Login.command`, containing only
the official CLI command, without credentials.

The ordinary path after CLI installation is to run `claude auth login --claudeai`
once in your own terminal, sign in through the browser, and paste a code directly
into the CLI if needed; then run `brofessor doctor --provider claude`. This path
was added to README. The open real-Claude-navigation item was closed in the plan.
