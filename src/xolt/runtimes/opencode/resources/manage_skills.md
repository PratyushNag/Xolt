---
name: manage-skills
description: Search, install, and reload OpenCode skills from within the agent
---

# Manage Skills

You can search for, install, and immediately use new skills without leaving the chat.

## Step 1 - Search the skills.sh registry

```bash
npx -y skills find <keyword>
```

Always pass a keyword. Do not run `npx skills find` without arguments because it opens an interactive picker.

## Step 2 - Fall back to GitHub when the registry is incomplete

```bash
curl -s "https://api.github.com/search/repositories?q=<keyword>+SKILL.md+in:path&sort=stars&per_page=5" \
  | grep -E '"full_name"|"description"'
```

## Step 3 - Install the skill

```bash
npx -y skills add <source> -a opencode -g -y
```

## Step 4 - Signal a reload

```bash
touch {reload_flag_path}
```

Do not call `instance/dispose` directly. The platform reloads safely between turns.
