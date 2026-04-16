# Contributing to Engramia

Thank you for your interest in Engramia. This document explains how you can
help and what to expect when you interact with this project.

## Code contributions

**Engramia does not accept external code contributions at this time.**

The project is source-available under the
[Business Source License 1.1](LICENSE.txt). To maintain legal clarity over
the codebase — and full control over product direction — all code is written
and owned exclusively by the Engramia team. This makes it possible to
relicense, dual-license, or transfer the project in the future without
requiring consent from every past contributor.

Pull requests from external contributors will be closed without review.
This is not a reflection of the quality of the submission.

## How you *can* help

The most valuable contributions right now are non-code:

- **Bug reports** — open a [GitHub Issue](https://github.com/engramia/engramia/issues)
  with a minimal reproduction. Please search existing issues before filing.
- **Feature requests** — describe your use case in an Issue. Explain what you
  are trying to achieve, not just what you want added.
- **Documentation feedback** — if something in the docs is wrong, unclear, or
  missing, open an Issue. Please reference the specific page or section.
- **Spread the word** — write about how you use Engramia, share benchmarks,
  mention it in your projects. This directly supports continued development.

## Documentation structure

Documentation is built from Markdown files with [MkDocs Material](https://squidfunnel.com/mkdocs-material/)
and published at [engramia.readthedocs.io](https://engramia.readthedocs.io).

When reporting documentation issues, it helps to know where files live:

| Location | Contents |
|----------|----------|
| `docs/` | All public documentation (guides, API reference, legal) |
| `docs/integrations/` | Agent framework integration guides |
| `docs/legal/` | Terms of Service, Privacy Policy, and other legal documents |
| `mkdocs.yml` | Site navigation and build configuration |

The entry point is `docs/index.md`. When referencing a problem, please include
the file path or the URL of the published page.

## Reporting security vulnerabilities

**Do not open a public Issue for security vulnerabilities.**

Report them privately to [support@engramia.dev](mailto:support@engramia.dev).
Include a description of the issue, steps to reproduce, and potential impact.
You will receive an acknowledgement within 48 hours.

See [SECURITY.md](SECURITY.md) for the full security policy and disclosure process.

## Licensing questions

See [docs/legal/licensing.html](docs/legal/licensing.html) or email
[support@engramia.dev](mailto:support@engramia.dev).
