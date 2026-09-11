# Live demo

`index.html` (git-ignored, rendered locally) is the HTML catalog generated from the synthetic specifications in
[`../examples/specs`](../examples/specs). It is regenerated with:

```bash
python scripts/build_examples.py
```

The `Deploy demo to GitHub Pages` workflow builds the same page from `main` and publishes it via
GitHub Pages. The demo uses only synthetic example data.
