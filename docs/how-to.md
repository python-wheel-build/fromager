# How To

## Run parallel jobs, allocate cpu cores per job and allocate memory per job

Fromager provides `cpu_cores_per_job` and `memory_per_job_gb` options which are related to build systems and can be used as a per package setting when multiple cores and significant amount of memory is available on a build system.
On the other hand, the `--jobs` overrides the default calculations based on the other settings. For example, when you pass `--jobs 4` then at most 4 processes will run in parallel when building a given wheel. By default, fromager computes a number of jobs and that value can be influenced based on the per-package settings.
Note that the jobs are all within the context of building a single wheel.

The `--jobs` option of fromager allows to set the maximum number of wheel build jobs to run in parallel. Below is an example which uses the `--jobs` option along with the bootstrap command

`fromager --jobs 4 bootstrap torch`

For this example, the maximum number of jobs fromager will run in parallel is 4.

The `cpu_cores_per_job` is a package setting that allows to scale parallel jobs by available CPU cores. The default value is set to 1 which indicates as many parallel jobs as CPU logical cores.
Example: `cpu_cores_per_job = 2` indicates allocating 2 cores per job
This setting should always have value greater than or equal to 1

The `memory_per_job_gb` is a package setting that allows to scale parallel jobs by available virtual memory without swap. The default value is set to 1.0 which indicates that each parallel job requires 1 GB virtual memory
Example: `memory_per_job_gb = 0.5` indicates that each parallel job requires 512 MB virtual memory
This setting should always have value greater than or equal to 0.1

## Enable Repeatable Builds

There are times we need to ensure that the bootstrap process does not change the packages to the latest versions on its own.
Instead, we want to use the last stable bootstrap as the only source of truth to ensure that the build process is fully
repeatable and predictable. Moreover, we also want to allow upgrading of specific packages to rebuild new RC blockers, do bug fixes, etc.

Fromager supports repeatable builds to ensure the bootstrap process does not pull unnecessary new dependencies when they are not required.
It uses the output files of previous successful bootstrap to avoid these dependency updates.

The bootstrap command of fromager has an option `--previous-bootstrap-file` which can be used to achieve repeatable builds. The user
needs to set the file path for `graph.json` from the latest stable bootstrap for the above option. The example bootstrap command to use
repeatable builds is as follows:

`fromager bootstrap --previous-bootstrap-file=path/to/graph.json -r path/to/requirements.txt`

For the above example, replace `path/to/graph.json` with an actual path to `graph.json` file and `path/to/requirements.txt`
with an actual path to `requirements.txt` file.

## Build Collections with Conflicting Versions

In some cases, you may want to build collections of wheels that contain conflicting versions of the same package. This is useful for scenarios such as:

- Building large collections for broader package indexes
- Testing jobs that need to build multiple conflicting versions  
- Creating wheel collections that don't need to resolve to a single installable set of packages

By default, fromager generates a `constraints.txt` file during the bootstrap process to ensure that all packages resolve to a compatible set of versions that can be installed together. However, this validation step can be bypassed using the `--skip-constraints` option.

### Using --skip-constraints

The `--skip-constraints` option allows you to skip the generation of the `constraints.txt` file, enabling the building of packages with conflicting version requirements:

```bash
fromager bootstrap --skip-constraints package1==1.0.0 package2==2.0.0
```

When this option is used:

- The `constraints.txt` file will **not** be generated in the work directory
- The `build-order.json` and `graph.json` files are still created normally  
- All packages specified will be built, even if they have conflicting dependencies
- A log message "skipping constraints.txt generation as requested" will be recorded

### Example Use Case

Consider building both `django==3.2.0` and `django==4.0.0` in the same collection:

```bash
fromager bootstrap --skip-constraints django==3.2.0 django==4.0.0
```

Without `--skip-constraints`, this would fail because the two versions conflict. With the flag, both versions will be built and stored in the wheels repository.

### Important Considerations

- **No installation validation**: The resulting wheel collection may not be installable as a single coherent set
- **Build sequence preservation**: The dependency resolution and build order logic still applies to each package individually
- **Intended for advanced use cases**: This option is primarily intended for specialized scenarios where version conflicts are acceptable or desired

The graph and build-sequence files can already handle multiple conflicting versions, so this change simply allows bypassing the final constraints validation step that ensures pip-compatibility.
