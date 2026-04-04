# Dependency License Inventory — Engramia

Generated: 2026-04-03  |  Engramia version: 0.6.4

## Summary

| | Count |
|---|---|
| Python packages (transitive) | 103 |
| Frontend packages (direct only) | 13 |
| 🔴 HIGH — must resolve before release | 0 |
| 🟡 MEDIUM — review required | 1 |
| 🟠 LOW — safe, note only | 3 |
| ✅ OK | 99 |

**Result: no blocking issues. All flagged packages are safe for commercial use (see notes).**

## Flagged packages

Packages that require a note. All have been reviewed and cleared.

| Risk | Package | Version | License | Assessment |
|---|---|---|---|---|
| 🟡 MEDIUM | psycopg2-binary | 2.9.11 | GNU Library or Lesser General Public License (LGPL) | LGPL-2.1 — used as dynamic library; Python import model does not trigger copyleft propagation. Standard commercial use is safe. Widely used in commercial products (Django, SQLAlchemy ecosystem). |
| 🟠 LOW | certifi | 2026.2.25 | Mozilla Public License 2.0 (MPL 2.0) | MPL-2.0 — file-level copyleft only. Unmodified use in commercial product is safe; only modified MPL files must be shared. |
| 🟠 LOW | pathspec | 1.0.4 | Mozilla Public License 2.0 (MPL 2.0) | MPL-2.0 — file-level copyleft only. Unmodified use in commercial product is safe; only modified MPL files must be shared. |
| 🟠 LOW | tqdm | 4.67.3 | MPL-2.0 AND MIT | MPL-2.0 — file-level copyleft only. Unmodified use in commercial product is safe; only modified MPL files must be shared. |

## Python — full list

Transitive dependencies as installed in the production environment.

| Package | Version | License | Risk |
|---|---|---|---|
| psycopg2-binary | 2.9.11 | GNU Library or Lesser General Public License (LGPL) | 🟡 |
| certifi | 2026.2.25 | Mozilla Public License 2.0 (MPL 2.0) | 🟠 |
| pathspec | 1.0.4 | Mozilla Public License 2.0 (MPL 2.0) | 🟠 |
| tqdm | 4.67.3 | MPL-2.0 AND MIT | 🟠 |
| annotated-doc | 0.0.4 | MIT | ✅ |
| annotated-types | 0.7.0 | MIT License | ✅ |
| anyio | 4.12.1 | MIT | ✅ |
| babel | 2.18.0 | BSD License | ✅ |
| backrefs | 6.2 | MIT | ✅ |
| charset-normalizer | 3.4.6 | MIT | ✅ |
| click | 8.3.1 | BSD-3-Clause | ✅ |
| colorama | 0.4.6 | BSD License | ✅ |
| coverage | 7.13.5 | Apache-2.0 | ✅ |
| distro | 1.9.0 | Apache Software License | ✅ |
| dnspython | 2.8.0 | ISC License (ISCL) | ✅ |
| docker | 7.1.0 | Apache-2.0 | ✅ |
| email-validator | 2.3.0 | The Unlicense (Unlicense) | ✅ |
| fastapi | 0.135.1 | MIT | ✅ |
| fastapi-cli | 0.0.24 | MIT | ✅ |
| fastapi-cloud-cli | 0.15.0 | MIT License | ✅ |
| fastar | 0.9.0 | MIT | ✅ |
| filelock | 3.25.2 | MIT | ✅ |
| fsspec | 2026.3.0 | BSD-3-Clause | ✅ |
| ghp-import | 2.1.0 | Apache Software License | ✅ |
| greenlet | 3.3.2 | MIT AND PSF-2.0 | ✅ |
| h11 | 0.16.0 | MIT License | ✅ |
| hf-xet | 1.4.2 | Apache-2.0 | ✅ |
| httpcore | 1.0.9 | BSD-3-Clause | ✅ |
| httptools | 0.7.1 | MIT | ✅ |
| httpx | 0.28.1 | BSD License | ✅ |
| huggingface_hub | 1.8.0 | Apache Software License | ✅ |
| idna | 3.11 | BSD-3-Clause | ✅ |
| iniconfig | 2.3.0 | MIT | ✅ |
| Jinja2 | 3.1.6 | BSD License | ✅ |
| jiter | 0.13.0 | MIT License | ✅ |
| joblib | 1.5.3 | BSD-3-Clause | ✅ |
| librt | 0.8.1 | MIT License | ✅ |
| Markdown | 3.10.2 | BSD-3-Clause | ✅ |
| markdown-it-py | 4.0.0 | MIT License | ✅ |
| MarkupSafe | 3.0.3 | BSD-3-Clause | ✅ |
| mdurl | 0.1.2 | MIT License | ✅ |
| mergedeep | 1.3.4 | MIT License | ✅ |
| mkdocs | 1.6.1 | BSD-2-Clause | ✅ |
| mkdocs-get-deps | 0.2.2 | MIT | ✅ |
| mkdocs-material | 9.7.6 | MIT | ✅ |
| mkdocs-material-extensions | 1.3.1 | MIT | ✅ |
| mpmath | 1.3.0 | BSD License | ✅ |
| mypy | 1.19.1 | MIT License | ✅ |
| mypy_extensions | 1.1.0 | MIT | ✅ |
| networkx | 3.6.1 | BSD-3-Clause | ✅ |
| numpy | 2.4.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | ✅ |
| openai | 2.26.0 | Apache Software License | ✅ |
| packaging | 26.0 | Apache-2.0 OR BSD-2-Clause | ✅ |
| paginate | 0.5.7 | MIT License | ✅ |
| pgvector | 0.4.2 | MIT | ✅ |
| platformdirs | 4.9.4 | MIT | ✅ |
| pluggy | 1.6.0 | MIT License | ✅ |
| pydantic | 2.12.5 | MIT | ✅ |
| pydantic-extra-types | 2.11.1 | MIT | ✅ |
| pydantic-settings | 2.13.1 | MIT | ✅ |
| pydantic_core | 2.41.5 | MIT | ✅ |
| Pygments | 2.19.2 | BSD License | ✅ |
| pymdown-extensions | 10.21 | MIT | ✅ |
| pytest | 9.0.2 | MIT | ✅ |
| pytest-asyncio | 1.3.0 | Apache-2.0 | ✅ |
| pytest-cov | 7.1.0 | MIT | ✅ |
| python-dateutil | 2.9.0.post0 | Apache Software License; BSD License | ✅ |
| python-dotenv | 1.2.2 | BSD-3-Clause | ✅ |
| python-multipart | 0.0.22 | Apache-2.0 | ✅ |
| pywin32 | 311 | Python Software Foundation License | ✅ |
| PyYAML | 6.0.3 | MIT License | ✅ |
| pyyaml_env_tag | 1.1 | MIT | ✅ |
| regex | 2026.2.28 | Apache-2.0 AND CNRI-Python | ✅ |
| requests | 2.33.0 | Apache Software License | ✅ |
| rich | 14.3.3 | MIT License | ✅ |
| rich-toolkit | 0.19.7 | MIT | ✅ |
| rignore | 0.7.6 | MIT | ✅ |
| ruff | 0.15.7 | MIT | ✅ |
| safetensors | 0.7.0 | Apache Software License | ✅ |
| scikit-learn | 1.8.0 | BSD-3-Clause | ✅ |
| scipy | 1.17.1 | BSD License | ✅ |
| sentence-transformers | 5.3.0 | Apache Software License | ✅ |
| sentry-sdk | 2.55.0 | BSD License | ✅ |
| shellingham | 1.5.4 | ISC License (ISCL) | ✅ |
| six | 1.17.0 | MIT License | ✅ |
| sniffio | 1.3.1 | Apache Software License; MIT License | ✅ |
| SQLAlchemy | 2.0.48 | MIT | ✅ |
| starlette | 0.52.1 | BSD-3-Clause | ✅ |
| sympy | 1.14.0 | BSD License | ✅ |
| testcontainers | 4.14.2 | Apache-2.0 | ✅ |
| threadpoolctl | 3.6.0 | BSD License | ✅ |
| tokenizers | 0.22.2 | Apache Software License | ✅ |
| torch | 2.11.0 | BSD-3-Clause | ✅ |
| transformers | 5.4.0 | Apache 2.0 License | ✅ |
| typer | 0.24.1 | MIT | ✅ |
| typing-inspection | 0.4.2 | MIT | ✅ |
| typing_extensions | 4.15.0 | PSF-2.0 | ✅ |
| urllib3 | 2.6.3 | MIT | ✅ |
| uvicorn | 0.42.0 | BSD-3-Clause | ✅ |
| watchdog | 6.0.0 | Apache Software License | ✅ |
| watchfiles | 1.1.1 | MIT License | ✅ |
| websockets | 16.0 | BSD-3-Clause | ✅ |
| wrapt | 2.1.2 | BSD-2-Clause | ✅ |

## Frontend — direct dependencies

Transitive frontend audit skipped — license-checker incompatible with Node.js v24. Direct dependencies manually verified. Re-run when Node 24 support is added to license-checker.

| Package | Version | License | Risk | Notes |
|---|---|---|---|---|
| next | ^15.3.0 | MIT | ✅ |  |
| react | ^19.1.0 | MIT | ✅ |  |
| react-dom | ^19.1.0 | MIT | ✅ |  |
| @tanstack/react-query | ^5.74.4 | MIT | ✅ |  |
| recharts | ^2.15.3 | MIT | ✅ |  |
| lucide-react | ^0.484.0 | ISC | ✅ |  |
| clsx | ^2.1.1 | MIT | ✅ |  |
| tailwind-merge | ^3.2.0 | MIT | ✅ |  |
| tailwindcss | ^4.1.4 | MIT | ✅ |  |
| typescript | ^5.8.3 | Apache-2.0 | ✅ | devDependency |
| postcss | ^8.5.3 | MIT | ✅ | devDependency |
| @types/react | ^19.1.2 | MIT | ✅ | devDependency |
| @types/node | ^22.14.1 | MIT | ✅ | devDependency |

## Update process

Re-run this audit on every release:



CI integration is a planned Phase 6 item. The JSON snapshot format above is the target input for the CI check.

---

*This file is auto-generated. Do not edit manually — re-run the audit script instead.*