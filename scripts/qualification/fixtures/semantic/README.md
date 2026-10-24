# Synthetic semantic known answers

`valid.ttl` and `expected.json` are manually authored acceptance inputs. No
production export, building identity or credential is embedded. The names are
deliberately misleading. Ten Client A points include duplicate discharge sensors,
a distinct setpoint, pressure, Bool fan command, percent fan speed, enum, Ref and
a dotted equipment identity. Another site repeats the same human label.

The twelve negative Turtle files are static RDF mutations of that valid model
(created with parsed graph operations): wrong owning namespace; wrong camel case;
dangling reference; pressure unit on a temperature input; wrong kind; stale
equipment/role-decoded series key; false and null values used as markers; a
string pretending to be Bool; conflicting sensor/setpoint functions; empty graph;
and malformed Turtle. `suite.json` names the expected failing assertions.

Changing the expected answer to follow a production defect defeats these tests.
Update a contract only with a documented model/profile decision and independent
review. Never turn a broken control's expected status into PASS or drop a control
because a dependency, parser or query fails.
