Version-Specific Prebuilt Settings
===================================

When working with multiple collections that share the same variant but need
different versions of a package, you may want some versions to use prebuilt
wheels while others are built from source.

Version-specific prebuilt settings allow you to configure ``pre_built`` and
``wheel_server_url`` on a per-version basis within a variant, providing
fine-grained control over which package versions use prebuilt wheels.

Configuration
-------------

Add version-specific settings under the ``versions`` key within a variant:

.. code-block:: yaml

   # overrides/settings/torchvision.yaml
   variants:
     tpu-ubi9:
       # Default behavior for unlisted versions
       pre_built: false
       
       # Version-specific overrides  
       versions:
         # Use prebuilt wheel for this version
         "0.24.0.dev20250730":
           pre_built: true
           wheel_server_url: https://gitlab.com/api/v4/projects/12345/packages/pypi/simple
           
         # Build from source for this version
         "0.23.0":
           pre_built: false

Available Settings
------------------

Within each version-specific block, you can configure:

``pre_built``
  Boolean indicating whether to use prebuilt wheels for this version.
  
``wheel_server_url``
  URL to download prebuilt wheels from for this version.
  
``env``
  Environment variables specific to this version.

``annotations``
  Version-specific annotations.

Precedence Rules
----------------

Version-specific settings override variant-wide settings. If both are defined,
environment variables are merged with version-specific values taking precedence
for conflicting keys.

Example Use Case
----------------

Consider two TPU collections using different ``torchvision`` versions:

**Global Collection** (``collections/accelerated/tpu-ubi9/requirements.txt``):

.. code-block:: text

   torchvision==0.24.0.dev20250730

**Torch-2.8.0 Collection** (``collections/torch-2.8.0/tpu-ubi9/requirements.txt``):

.. code-block:: text

   torchvision==0.23.0

With the configuration above:

- Global collection downloads prebuilt ``torchvision==0.24.0.dev20250730`` wheels
- Torch-2.8.0 collection builds ``torchvision==0.23.0`` from source
- Both use the same variant (``tpu-ubi9``) with different build methods
