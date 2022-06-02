# neon-messagebus-mq-connector
Proxy module for establishing communication between MQ Services and the Messagebus.
This module should be run as part of the [Messagebus Service](https://github.com/NeonGeckoCom/neon_messagebus).
MQ requests will be routed through this module with core responses emitted back to a client-specific queue.
