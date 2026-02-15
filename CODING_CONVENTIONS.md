````markdown
# Coding Conventions

This document describes the coding conventions for this project.  
It is intended for both human developers and AI agents contributing to the codebase.

---

## 1. General Style

- Follow **[PEP 8 – Style Guide for Python Code](https://peps.python.org/pep-0008/)** unless explicitly overridden below.
- Use **4 spaces** per indentation level.
- Maximum line length: **120 characters** (PEP 8 default is 79, but we allow up to 120).
- Use UTF-8 encoding for all source files.
- One public class or function per file, if possible.
- Always use **.venv** for Python virtual environments.
- Always increase the version number in `README.md` and `index.html` files when making changes.

---

## 2. Imports

- Use **absolute imports** (preferred) over relative imports.
- Place imports at the beginning of the file.
- Import order:
  1. Standard library
  2. Third-party packages
  3. Local application imports
- Separate each group with a blank line.
- Example:
  ```python
  import os
  import sys

  import pandas as pd

  from src.util.helpers import my_helper
  ```

### 2.1 Path Setup for Project Root

- When setting up the project root for imports, use **pathlib** for cleaner, more readable code.

❌ **Do NOT** use complex `os.path` chains:
```python
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))
```

✅ **Do** use `pathlib.Path` with `.resolve().parents[n]`:
```python
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(PROJECT_ROOT))
```

**Benefits:**
- More readable and maintainable
- Clear indication of how many parent directories to traverse
- Cross-platform compatibility
- Type-safe path operations

---

### 2.2 __init__.py files

Try to keep all __init__.py files empty for all packages unless it is absolutely necessary to import functions from the subpackages.

### 2.3 Date operations are UTC-aware
Instead of:
datetime.now(datetime.UTC)
Use:
datetime.now(timezone.utc)

Try to keep all __init__.py files empty for all packages unless it is absolutely necessary to import functions from the subpackages.

## 3. Logging

### 3.1 Logger Initialization

* All modules should initialize the logger as:

  ```python
  from src.notification.logger import setup_logger
  _logger = setup_logger(__name__)
  ```

### 3.2 Logging Style

* **Always use lazy formatting** to avoid unnecessary string interpolation when logging is disabled.
* ❌ **Do NOT**:

  ```python
  _logger.info(f"Processing item {item_id}")
  ```
* ✅ **Do**:

  ```python
  _logger.info("Processing item %s", item_id)
  ```

### 3.3 Logging Levels

* Use levels appropriately:

  * `_logger.debug()` – Detailed information for debugging.
  * `_logger.info()` – High-level runtime events.
  * `_logger.warning()` – Unexpected events that are non-fatal.
  * `_logger.error()` – Serious problems that need attention.
  * `_logger.exception()` – Like `error()`, but includes stack trace (use inside `except`).

---

## 4. Naming Conventions

* **Modules & packages**: `lowercase_with_underscores`
* **Classes**: `CamelCase`
* **Functions & variables**: `lowercase_with_underscores`
* **Constants**: `UPPERCASE_WITH_UNDERSCORES`
* Private members: prefix with `_`

---

## 5. Docstrings

* Follow **[PEP 257 – Docstring Conventions](https://peps.python.org/pep-0257/)**.
* Use triple double quotes `"""` for all docstrings.
* First line: short summary.
* Leave a blank line before detailed description.
* Example:

  ```python
  def add(a: int, b: int) -> int:
      """
      Add two integers.

      Args:
          a: First integer.
          b: Second integer.

      Returns:
          The sum of `a` and `b`.
      """
      return a + b
  ```

---

## 6. Type Hints

* Use **type hints** for all function arguments and return values.
* Use `Optional[...]` for nullable values.
* Example:

  ```python
  from typing import Optional

  def greet(name: Optional[str] = None) -> str:
      if name:
          return f"Hello, {name}!"
      return "Hello!"
  ```

---

## 7. Error Handling

* **Do not** use bare `except:`.
* Catch specific exceptions.
* When logging exceptions, use:

  ```python
  _logger.exception("An error occurred while processing item %s", item_id)
  ```
* Raise meaningful errors when input validation fails.

---

## 8. Code Structure

* Keep functions short and focused.
* Avoid deeply nested conditionals (prefer early returns).
* Use helper functions to avoid duplication.

---

## 9. Tests

* All new code must include unit tests.
* Test naming:

  * Function names: `test_<functionality>`
  * Example: `test_add_two_numbers`

---

## 10. Submodule Structure in `src/`

Each module (subfolder) in the `src/` directory is considered a **submodule** and must include:

* `tests/` subdirectory for module-specific tests
  Example: `src/data/tests/`
* `README.md` – Overview of the submodule’s purpose, usage, and examples
* `Requirements.md` – Dependencies specific to this submodule
* `Design.md` – Architecture, design decisions, and diagrams (if any)
* `Tasks.md` – Pending tasks, TODOs, and development notes

Example layout for a submodule:

```
src/
  data/
    __init__.py
    loader.py
    processor.py
    tests/
      test_loader.py
      test_processor.py
    README.md
    Requirements.md
    Design.md
    Tasks.md
```

---

## 11. Git & Commit Messages

* Commit messages should be in imperative mood:

  * ✅ `"Add user authentication"`
  * ❌ `"Added user authentication"`
* Reference related issues where applicable: `"Fix #123 – Handle null values in parser"`

---

## 12. AI Agent Guidelines

These rules are binding for any AI agent generating code for this project:

1. **Always** read and follow this `CODING_CONVENTION.md` before generating or modifying code.
2. Apply **PEP 8** plus all custom conventions listed here.
3. Use the provided **logger initialization** and **lazy logging** format.
4. **CRITICAL**: Ensure that each new or modified `src/` module contains:
   - `README.md` - Module overview and usage examples
   - `docs/` subfolder containing:
     - `Requirements.md` - Technical requirements and dependencies
     - `Design.md` - Architecture and design decisions
     - `Tasks.md` - Implementation tasks and roadmap
   - `tests/` subfolder with module-specific tests
5. When creating functions, **always include** type hints and docstrings in the specified format.
6. Prefer clear, maintainable code over clever one-liners.
7. Write unit tests for any new functionality and place them in the corresponding `tests/` folder.
8. Ensure commit messages follow the Git rules in section 11.
9. **Document cross-module dependencies** in `Requirements.md` when modules interact.
10. **Use absolute imports** from the project root (e.g., `from src.data import ...`).

---

## 13. Templates for Submodule Files

### 13.1 README.md Template

```markdown
# <Module Name>

## Overview
Short description of the module's purpose and responsibilities within the e-trading platform.

## Features
- Key feature 1
- Key feature 2
- Key feature 3

## Quick Start
Example code showing how to use this module:

```python
from src.<module_name> import some_function

result = some_function()
print(result)
```

## Integration
This module integrates with:
- `src.data` - For data retrieval
- `src.notification` - For user notifications
- Other relevant modules

## Configuration
Basic configuration instructions and environment variables.

## Related Documentation
- [Requirements](docs/Requirements.md) - Technical requirements
- [Design](docs/Design.md) - Architecture and design
- [Tasks](docs/Tasks.md) - Implementation roadmap
```

---

### 13.2 Requirements.md Template
```markdown
# Requirements

## Python Dependencies
- `package_name` >= version
- `another_package` >= version

## External Dependencies
- `src.data` - For market data retrieval
- `src.notification` - For user notifications
- `src.common` - For shared utilities

## External Services
- API service name and requirements
- Database requirements
- Authentication services

## System Requirements
- Memory requirements
- CPU requirements
- Storage requirements

## Security Requirements
- API key management
- Data encryption
- Access control

## Performance Requirements
- Response time targets
- Throughput requirements
- Scalability considerations
````

---

### 13.3 Design.md Template

```markdown
# Design

## Purpose
Describe why this module exists and its role in the e-trading platform.

## Architecture
Explain the structure of the module and how it interacts with the rest of the system.

### High-Level Architecture
- Component diagram
- Module interactions
- Data flow patterns

### Component Design
- Individual components and their responsibilities
- Interfaces between components
- Error handling strategies

## Data Flow
- Input/output data structures
- Processing pipelines
- Integration points with other modules

## Design Decisions
List important choices made during development and why:
- Technology choices
- Architecture patterns
- Performance considerations
- Security decisions

## Integration Patterns
- How this module integrates with other modules
- API design principles
- Error handling and recovery
```

---

### 13.4 Tasks.md Template

```markdown
# Tasks

## Implementation Status

### ✅ COMPLETED FEATURES
- [x] Feature 1 - Description
- [x] Feature 2 - Description

### 🔄 IN PROGRESS
- [ ] Feature 3 - Description
- [ ] Feature 4 - Description

### 🚀 PLANNED ENHANCEMENTS
- [ ] Enhancement 1 - Description
- [ ] Enhancement 2 - Description

## Technical Debt
- [ ] Refactor component X
- [ ] Improve error handling
- [ ] Add missing tests

## Known Issues
- Issue 1 - Description and impact
- Issue 2 - Description and impact

## Testing Requirements
- [ ] Unit tests for component X
- [ ] Integration tests for feature Y
- [ ] Performance testing

## Documentation Updates
- [ ] Update API documentation
- [ ] Add usage examples
- [ ] Create troubleshooting guide
```

---

## 14. Project Structure Reference

### 14.1 Module Organization Principles

1. **Each module in `src/` is self-contained** with its own documentation and tests
2. **Cross-module dependencies are explicitly documented** in `Requirements.md`
3. **Consistent structure** across all modules for maintainability
4. **Clear separation of concerns** between modules

### 14.2 Module Categories

#### Core Modules
- `src/data/` - Data providers and market data
- `src/common/` - Shared utilities and fundamentals
- `src/model/` - Data models and schemas
- `src/config/` - Configuration management

#### Feature Modules
- `src/strategy/` - Trading strategies
- `src/backtester/` - Backtesting framework
- `src/trading/` - Trading execution
- `src/analytics/` - Advanced analytics

#### Interface Modules
- `src/frontend/` - User interfaces (Telegram, Web)
- `src/notification/` - Notification system
- `src/management/` - Admin tools

#### Infrastructure Modules
- `src/error_handling/` - Error handling
- `src/ml/` - Machine learning
- `src/util/` - Utility scripts

### 14.3 Documentation Hierarchy

```
Module Level:
├── README.md (User-facing overview)
└── docs/
    ├── Requirements.md (Technical requirements)
    ├── Design.md (Architecture and design)
    └── Tasks.md (Implementation tracking)
```

### 14.4 Import Guidelines

- **Use absolute imports** from project root: `from src.data import ...`
- **Document dependencies** in `Requirements.md`
- **Avoid circular dependencies** between modules
- **Create clear interfaces** for cross-module communication

---

*Last updated: 2025-01-27*

```

