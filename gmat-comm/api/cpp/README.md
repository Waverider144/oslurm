# C++ API

Include headers from `core/include` and link `gmat_comm_core`.

```cpp
#include "gmat_comm/communication_payload.hpp"
#include "gmat_comm/routing.hpp"
```

The C++ API is intentionally GMAT-free. Use adapters to translate GMAT state into `ContactWindow` or `CommunicationEnvironmentState` values before calling the core.
