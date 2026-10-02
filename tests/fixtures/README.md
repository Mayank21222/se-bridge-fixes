# Test fixtures

Small, trimmed copies of **public** Standard Ebooks catalogue pages, captured
with the project's own polite client settings (one request per second, caching,
descriptive User-Agent). They contain only public bibliographic metadata about
ebooks that are themselves in the public domain; there is no personal data, no
account data and no credentials anywhere in this directory.

Trimming removed `<footer>`, the "more ebooks" carousel, the donation and
history blocks, and the `<picture>` wrappers around cover images. The capture
script asserts that trimming does not change any parsed record, so these files
parse exactly like the live pages.

| File | Source URL | HTTP | Size | Captured (UTC) |
| --- | --- | --- | --- | --- |
| `catalog_page_1.html` | `/ebooks?view=list&per-page=12&page=1` | 200 | 29,077 bytes | 2026-10-02 |
| `catalog_page_2.html` | `/ebooks?view=list&per-page=12&page=2` | 200 | 28,925 bytes | 2026-10-02 |
| `catalog_page_12.html` | `/ebooks?view=list&per-page=12&page=12` | 200 | 29,114 bytes | 2026-10-02 |
| `catalog_subject_drama.html` | `/ebooks?view=list&per-page=12&tags%5B%5D=drama` | 200 | 20,742 bytes | 2026-10-02 |
| `catalog_search_shakespeare.html` | `/ebooks?view=list&per-page=12&page=1&query=shakespeare` | 200 | 17,973 bytes | 2026-10-02 |
| `catalog_search_relevance.html` | `/ebooks?view=list&per-page=12&page=1&query=shakespeare&sort=relevance` | 200 | 17,726 bytes | 2026-10-02 |
| `catalog_page_out_of_range.html` | `/ebooks?view=list&per-page=12&page=9999` | 200 | 18,137 bytes | 2026-10-02 |
| `catalog_search_empty.html` | `/ebooks?view=list&per-page=12&query=zzzqqqxyzzy` | 200 | 6,250 bytes | 2026-10-02 |
| `ebook_oberland.html` | `/ebooks/dorothy-m-richardson/oberland` | 200 | 14,365 bytes | 2026-10-02 |
| `ebook_imitation_of_christ.html` | `/ebooks/thomas-a-kempis/the-imitation-of-christ/william-benham` | 200 | 15,997 bytes | 2026-10-02 |
| `ebook_flatland.html` | `/ebooks/edwin-a-abbott/flatland` | 200 | 14,514 bytes | 2026-10-02 |
| `author_dorothy_m_richardson.html` | `/ebooks/dorothy-m-richardson?view=list&per-page=48` | 200 | 15,922 bytes | 2026-10-02 |
