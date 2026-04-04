# Engramia Website Draft

Public marketing website draft for `engramia.dev`, built as a separate Next.js app using the same visual language as the dashboard.

## Included pages

- `/` landing page
- `/pricing`
- `/licensing`
- `/blog`
- `/legal`
- `/legal/[slug]`

## Notes

- `Licensing` is based on the supplied `licensing.html` content and translated into the dashboard design system.
- Legal detail pages render the Markdown files from `src/content/legal`.
- This app is intentionally separate from `dashboard/`, which currently uses `/dashboard` basePath and an auth-first structure.
