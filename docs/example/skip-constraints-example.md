# Example: Building Collections with Conflicting Versions

This example demonstrates how to use the `--skip-constraints` option to build wheel collections containing conflicting package versions.

## Use Case

Suppose you need to build a package index that contains multiple versions of the same package for different downstream consumers. For example, you might want to include both Django 3.2 and Django 4.0 in your collection.

## Requirements Files

Create a requirements file with conflicting versions:

### requirements-conflicting.txt

```text
django==3.2.0
django==4.0.0
requests==2.28.0  
```

Normally, this would fail with a conflict error because both Django versions cannot be installed together.

## Running with --skip-constraints

```bash
fromager bootstrap --skip-constraints \
  --sdists-repo ./sdists-repo \
  --wheels-repo ./wheels-repo \
  --work-dir ./work-dir \
  -r requirements-conflicting.txt
```

## Expected Behavior

1. **Success**: Both Django versions will be built successfully
2. **Output Files**:
   - `build-order.json` - Contains build order for all packages
   - `graph.json` - Contains dependency resolution graph  
   - No `constraints.txt` file is generated
3. **Wheel Repository**: Contains wheels for both Django versions and their respective dependencies

## Verification

Check that both versions were built:

```bash
find wheels-repo/downloads/ -name "Django-*.whl"
# Expected output:
# wheels-repo/downloads/Django-3.2.0-py3-none-any.whl  
# wheels-repo/downloads/Django-4.0.0-py3-none-any.whl
```

Verify no constraints file was created:

```bash
ls work-dir/constraints.txt
# Expected: file does not exist
```
