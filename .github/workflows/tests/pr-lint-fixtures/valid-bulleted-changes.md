==COMMIT_MSG==
This rolls up several closely-related changes that all touch the
same handshake:

- drop the redundant retry on the bar acknowledgement;
- collapse the two-step bar acknowledgement into one round trip;
- log the round-trip latency at debug level for future bisects;
- add a regression test for the collapsed acknowledgement path.

The cbea.ms / kernel-style enumerated-changes form reads better
in `git log` than the run-on prose paragraph that authors fell
back to under the previous blanket no-markdown ban (see #345).

Closes: #11
Signed-off-by: Aidan Nagorcka-Smith <aidanns@gmail.com>
==COMMIT_MSG==
