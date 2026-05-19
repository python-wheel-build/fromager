Analyze a fromager build graph and recommend how to eliminate wasted wheel builds before the next bootstrap.

## Step 1: Run the check

Parse $ARGUMENTS for a graph.json path and any flags (`--json`, `--constraints`). If no path is found, ask the user.

```bash
fromager graph check [flags] <graph.json>
```

## Step 2: Respond based on the outcome

### All checks pass

One line. Offer to compare against another graph if relevant.

### Structural failures (dangling edges or cycles)

These block everything — don't analyze conflicts. Report what failed:

- **Dangling edges**: which packages are missing from the graph
- **Cycles**: which packages form the cycle

Self-loops are warnings (exit 0). Mention briefly, don't treat as blockers.

### Version conflicts found

Present build efficiency first, then conflicts grouped by leverage.

**At scale (5+ conflicts):** Group by binding parent. One parent that binds 4 packages is one line, not four. Show the top binding parents ranked by how many packages they'd free, then summarize the rest.

**Per conflict**, present problem and fix together:

> **`<package>`** — \<collapsible|required>, bound by `<parent>` (`<specifier>`)
> → <recommendation>

**Collapsible** recommendations:

- Internal binding parent → "relax the specifier in `<parent>`"
- Exact `==` pin → "upgrade `<parent>` (can't relax an exact pin)"
- Quick workaround → "add `<package>==<pin>` to constraints.txt"

**Required** → blocker. `write_constraints_file` will likely fail. The binding parent must change before rebuilding.

## Step 3: Offer artifacts and next steps

After presenting findings, proactively offer:

- **Constraints block**: Run `fromager graph check --constraints <graph.json>` and present the output as a ready-to-paste block for constraints.txt.
- **Binding parent detail**: "Want me to check the specifiers on `<parent>`?" when a binding parent drives multiple conflicts.
- **Comparison**: If the user has another graph (previous build, different accelerator), offer to diff: "Want to compare against `<other-graph>`?"

## What to trust

- **Collapsible is a guarantee.** The check is conservative relative to `write_constraints_file`. Don't hedge — recommend with confidence.
- **Required is conservative.** The resolver may cascade-resolve some. Say "will likely fail" not "will fail."

## Don't

- Don't restate the raw output — interpret it
- Don't explain how the tool works
- Don't list every conflict individually when grouping by parent is clearer
- Don't suggest fixes for required conflicts beyond "update the binding parent"

## Example response

For a graph with 419 wheels, 3 collapsible conflicts, and 1 required:

> **419 wheels built, 3 extra.** 1 required conflict blocks the next build.
>
> **Blocker:**
>
> - **`tokenizers`** — required, bound by `transformers==4.40.0` (`tokenizers<0.20,>=0.19`). No pin satisfies all consumers. Update transformers before rebuilding.
>
> **Eliminate 3 extra builds:**
>
> - **`datasets`** and **`huggingface-hub`** — both bound by `unsloth-zoo==0.1.0`. Relaxing unsloth-zoo's specifiers frees both. Pin: `datasets==2.20.0`, `huggingface-hub==0.23.0`
> - **`fsspec`** — bound by `datasets==2.19.0` (`fsspec>=2023.1.0,<2024.6.0`). Pin: `fsspec==2024.5.0`
>
> Ready-to-paste constraints:
>
> ```
> datasets==2.20.0
> huggingface-hub==0.23.0
> fsspec==2024.5.0
> ```
>
> Want me to check unsloth-zoo's specifiers, or compare against a previous build?

$ARGUMENTS
