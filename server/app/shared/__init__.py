"""Shell-side building blocks shared by the gateway and the workers (errors, clock,
rate limiting, message dispatch). Not the "pure core": these may touch time and I/O."""
