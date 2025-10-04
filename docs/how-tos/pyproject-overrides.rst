Working with Complex pyproject.toml Requirements
================================================

When using fromager's ``project_override`` feature (documented in the 
:doc:`../customization` guide), there are some advanced scenarios worth
understanding for complex build requirements.

Handling Multiple Requirements for the Same Package
---------------------------------------------------

When applying overrides, requirements are matched by (canonical) name, so updating 
``numpy`` will affect all numpy requirements - all existing ones are replaced by 
the new requirements from the override, whether that's just one or multiple.

Consider a ``pyproject.toml`` with multiple version-specific numpy requirements:

.. code-block:: toml

   [build-system]
   requires = [
       "numpy<2.0; python_version<'3.9'",
       "numpy==2.0.2; python_version>='3.9' and python_version<'3.13'",
       "numpy==2.1.3; python_version=='3.13'",
       "packaging",
       "setuptools==59.2.0; python_version<'3.12'",
       "setuptools<70.0.0; python_version>='3.12'"
   ]

Single Requirement Replacement
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When you apply an override with a single numpy requirement:

.. code-block:: yaml

   project_override:
     update_build_requires:
       - numpy==2.0.0

All existing numpy requirements are replaced by the single new one:

.. code-block:: toml

   [build-system]
   requires = [
       "numpy==2.0.0", 
       "packaging",
       "setuptools==59.2.0; python_version<'3.12'",
       "setuptools<70.0.0; python_version>='3.12'"
   ]

Multiple Requirements Replacement
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When you apply overrides with multiple new numpy requirements:

.. code-block:: yaml

   project_override:
     update_build_requires:
       - setuptools 
       - numpy<3.0.0; python_version=='3.12'
       - numpy==3.0.0; python_version>'3.12'

All existing numpy requirements are replaced by all the new numpy requirements:

.. code-block:: toml

   [build-system]
   requires = [
       "numpy<3.0.0; python_version=='3.12'",
       "numpy==3.0.0; python_version>'3.12'",
       "packaging",
       "setuptools"
   ]