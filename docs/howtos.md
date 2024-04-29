# Using these tools

### Running Pipelines

The project uses gitlab pipelines for building. As a convenience,
there is a command line program available for users who have access to
a GitLab token with permission to trigger pipelines in the
`GITLAB_TOKEN` environment variable.

To run the bootstrap job for `setuptools` version `69.5.1`, use:

```
$ tox -e job -- bootstrap setuptools 69.5.1
```

To run the job to build the wheel for the same package:

```
$ tox -e job -- build-wheel setuptools 69.5.1
```

To get help, use

```
$ tox -e job -- -h
```
