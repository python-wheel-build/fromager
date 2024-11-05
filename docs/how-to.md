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
