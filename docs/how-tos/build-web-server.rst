Using an External Build Web Server
==================================

By default, fromager runs its own internal web server to provide
wheels as build requirements for packages that it builds. It maintains
the content for the server by building or downloading wheels as it
bootstraps or builds packages.

For very large sets of dependencies, the internal web server may not
perform well and will either result in errors in the logs, or
potentially failed builds. In these cases it is straightforward to
tell fromager that another web server is hosting the content that it
is managing, and that it does not need to run an internal server by
using the ``--build-wheel-server-url`` option.

.. code-block:: console

   $ fromager --build-wheel-server-url http://localhost:8080/simple/ bootstrap my-package
