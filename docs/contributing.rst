Contributing to Plutus
=======================

We welcome contributions to Plutus! This guide will help you get started.

Getting Started
---------------

1. Fork the repository on GitHub
2. Clone your fork locally
3. Create a virtual environment
4. Install development dependencies

.. code-block:: bash

   git clone https://github.com/your-username/plutus.git
   cd plutus
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[dev]"

Development Setup
-----------------

Environment Variables
~~~~~~~~~~~~~~~~~~~~~

Set up your environment:

.. code-block:: bash

   export PYTHONPATH=/path/to/plutus/src
   export HERMES_DATA_ROOT=/path/to/dataset

Running Tests
~~~~~~~~~~~~~

Run the full test suite:

.. code-block:: bash

   pytest

Run specific tests:

.. code-block:: bash

   pytest tests/test_evaluation/
   pytest tests/datahub/
   pytest tests/test_mcp/

Code Style
----------

We follow PEP 8 with some modifications:

* Maximum line length: 100 characters
* Use 4 spaces for indentation
* Use type hints where appropriate

Coding Standards
~~~~~~~~~~~~~~~~

1. **Docstrings**: Use Google-style docstrings

   .. code-block:: python

      def my_function(param1: str, param2: int) -> bool:
          """Short description.

          Longer description if needed.

          Args:
              param1: Description of param1
              param2: Description of param2

          Returns:
              Description of return value

          Example:
              >>> my_function("test", 42)
              True
          """

2. **Type Hints**: Use type hints for function signatures

3. **Decimal for Finance**: Use Decimal for all financial calculations

4. **Tests**: Write tests for new features

Contributing Guidelines
-----------------------

1. **Create a branch** for your changes:

   .. code-block:: bash

      git checkout -b feature/my-new-feature

2. **Make your changes** and commit:

   .. code-block:: bash

      git add .
      git commit -m "Add my new feature"

3. **Run tests** to ensure nothing breaks:

   .. code-block:: bash

      pytest

4. **Push to your fork**:

   .. code-block:: bash

      git push origin feature/my-new-feature

5. **Create a Pull Request** on GitHub

Pull Request Process
--------------------

1. Update documentation if needed
2. Add tests for new features
3. Ensure all tests pass
4. Update CHANGELOG.md
5. Request review from maintainers

Areas for Contribution
----------------------

We especially welcome contributions in these areas:

* **Performance optimizations**
* **Additional metrics** for performance evaluation
* **More MCP tools** for LLM integration
* **Documentation improvements**
* **Bug fixes**
* **Test coverage improvements**

Questions?
----------

If you have questions, please:

* Open an issue on GitHub
* Contact: dan@algotrade.vn

Thank you for contributing to Plutus!
