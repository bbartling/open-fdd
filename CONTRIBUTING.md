# Contributing to Open-FDD

First off, thanks for taking the time to contribute!

Open-FDD is in **Alpha**. The most valuable contributions right now are **bug reports** and **FDD rules**—especially from mechanical engineers and building professionals who can add and refine fault-detection rules using the [Expression Rule Cookbook](https://bbartling.github.io/open-fdd/expression_rule_cookbook). All types of contributions are encouraged. See the [Table of Contents](#table-of-contents) for different ways to help and how this project handles them. Please read the relevant section before contributing; it helps maintainers and keeps things smooth for everyone.

> If you like the project but don't have time to contribute, that's fine. Other ways to support it:
> - Star the [repository](https://github.com/bbartling/open-fdd)
> - Share it with colleagues or at meetups
> - Refer to Open-FDD in your project's readme or documentation

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [I Have a Question](#i-have-a-question)
- [I Want To Contribute](#i-want-to-contribute)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Enhancements](#suggesting-enhancements)
- [Contributing Rules (Expression Rule Cookbook)](#contributing-rules-expression-rule-cookbook)
- [Your First Code Contribution](#your-first-code-contribution)
- [Improving the Documentation](#improving-the-documentation)
- [Styleguides](#styleguides)
- [Commit Messages](#commit-messages)
- [Join the Project Team](#join-the-project-team)

---

## Code of Conduct

This project expects everyone to be respectful and constructive. By participating, you agree to uphold a positive environment. Please report unacceptable behavior by opening an issue or contacting the repository maintainers.

---

## I Have a Question

Before asking, please check the [documentation](https://bbartling.github.io/open-fdd/) and search [existing issues](https://github.com/bbartling/open-fdd/issues) to see if your question is already answered.

If you still need help:

- Open an [issue](https://github.com/bbartling/open-fdd/issues/new).
- Provide as much context as you can (what you're trying to do, what you ran, what happened).
- Include relevant versions: Python, Docker, OS (e.g. Ubuntu, Linux Mint), and Open-FDD commit or release if known.

We’ll respond as soon as we can.

---

## I Want To Contribute

### Legal notice

When contributing, you agree that you have authored 100% of the content, have the necessary rights to it, and that your contribution may be provided under the project license (MIT).

---

## Reporting Bugs

**Bug testing is a top priority in Alpha.** Good bug reports help us fix issues quickly.

### Before submitting a bug report

- Use the latest version (main branch or latest release).
- Confirm the bug is in Open-FDD and not in your environment (e.g. wrong Python version, missing config). Check the [documentation](https://bbartling.github.io/open-fdd/) and [I Have a Question](#i-have-a-question) first.
- Search [issues](https://github.com/bbartling/open-fdd/issues?q=label%3Abug) to see if the bug is already reported.
- Collect:
  - **Stack trace** (Traceback) if applicable
  - **OS and platform** (e.g. Linux, macOS, Windows; x86, ARM)
  - **Versions**: Python, Docker, Docker Compose, and how you ran Open-FDD (pip, Docker Compose, etc.)
  - **Steps to reproduce** and, if possible, sample input/config
  - Whether you can reproduce it every time and on an older version

### How to submit a good bug report

- **Security issues:** Do **not** report security vulnerabilities in public issues. Email the repository owner or open a private security advisory on GitHub.
- Open a new [issue](https://github.com/bbartling/open-fdd/issues/new). Don’t assume it’s a bug yet—avoid using the word “bug” in the title until it’s confirmed.
- Describe **expected behavior** vs **actual behavior**.
- Provide **reproduction steps** so someone else can recreate the issue. Isolate the problem when possible (e.g. minimal rule YAML, minimal config).
- Paste the information you collected above.

After you file:

- Maintainers will label the issue. If we can’t reproduce it, we may ask for more steps and mark it `needs-repro`. Reproducible issues may be marked `needs-fix` and opened for implementation.

---

## Suggesting Enhancements

Enhancements are tracked as [GitHub issues](https://github.com/bbartling/open-fdd/issues).

### Before submitting

- Use the latest version and read the [documentation](https://bbartling.github.io/open-fdd/) to see if the behavior already exists or can be configured.
- Search [issues](https://github.com/bbartling/open-fdd/issues) to see if the enhancement was already suggested; if so, add to that discussion.
- Consider whether the idea fits Open-FDD’s scope (edge AFDD, rules, API, BACnet, Grafana). Make a clear case for why it would help most users.

### How to submit a good enhancement suggestion

- Use a **clear, descriptive title**.
- Describe the **current behavior** and what you **want instead**, and why.
- Provide **step-by-step detail** where useful; screenshots or example YAML/config can help.
- Explain why this would be useful to the community.

---

## Contributing Rules (Expression Rule Cookbook)

**We especially welcome contributions from mechanical engineers and building professionals** who can add or improve FDD rules.

- **Where rules live:** [Fault rules overview](https://bbartling.github.io/open-fdd/rules/overview) — put project rules in **`analyst/rules/`** (YAML). The FDD loop reloads them every run; no restart needed.
- **How to write rules:** [Expression Rule Cookbook](https://bbartling.github.io/open-fdd/expression_rule_cookbook) — expression-type rules use YAML with BRICK-style inputs, params, and pandas/NumPy expressions. The cookbook includes AHU-style rules (e.g. GL36-inspired) and patterns you can adapt.
- **What to contribute:**
  - **New rule YAMLs** for common faults (AHU, VAV, plant, sensors) that others can reuse.
  - **Improvements to existing cookbook rules** (thresholds, logic, descriptions).
  - **New cookbook sections or examples** (e.g. for a specific equipment type or standard).

To contribute a rule or cookbook change:

1. Add or edit files under `analyst/rules/` for new/updated rules, or under `docs/expression_rule_cookbook.md` (and related docs) for cookbook content.
2. Follow the existing YAML style and BRICK naming used in the cookbook.
3. In a PR, describe the fault the rule targets and any assumptions (e.g. Brick types, units). If it’s from a standard (e.g. ASHRAE), note the reference.

---

## Your First Code Contribution

- Look for issues labeled `good first issue` or `help wanted` (if we’ve added them).
- The codebase is Python 3.11+, with FastAPI (API), pandas/NumPy (rules), and Docker for the platform. See [Getting Started](https://bbartling.github.io/open-fdd/getting_started) and the README for setup.
- For rule or analyst changes, run the test suite and, if possible, the FDD loop locally with sample data before submitting a PR.

---

## Improving the Documentation

Documentation lives in the `docs/` directory and is published at [bbartling.github.io/open-fdd](https://bbartling.github.io/open-fdd/). Improvements are welcome:

- Fix typos, clarify wording, or update steps.
- Add examples or how-tos (e.g. for the [Expression Rule Cookbook](https://bbartling.github.io/open-fdd/expression_rule_cookbook), [Operations](https://bbartling.github.io/open-fdd/howto/operations), or BACnet).
- Keep code blocks and links in sync with the codebase.

Open a PR with your changes; for large edits, an issue first can help align with maintainers.

---

## Styleguides

- **Python:** We use [Black](https://github.com/psf/black) for formatting. Run `black` on changed files before committing.
- **YAML:** Match the style in `analyst/rules/` and the expression rule cookbook (indentation, key order).
- **Markdown:** Use clear headings and lists; link to existing docs where relevant.

---

## Commit Messages

- Use a clear, short summary line. Optionally add a body with details.
- Reference issues/PRs when relevant (e.g. `Fix bounds rule when input is all NaN (#123)`).

---

## Join the Project Team

If you’re interested in ongoing maintenance or a larger role, say so in an issue or reach out to the maintainers. We’re especially interested in folks who can triage bugs, review rule contributions, or improve docs and the cookbook.

---

## Attribution

This contributing guide was inspired by the [contributing.md](https://contributing.md/) project. You don’t need to pay to create or use a CONTRIBUTING file—it’s just a markdown file in your repo that helps contributors and maintainers.
