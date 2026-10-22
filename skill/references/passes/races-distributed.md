# Pass: races-distributed (step 1, always this pass)

You look for race conditions and distributed-systems flaws: what goes wrong when two things happen at once, when the
system runs as more than one process or replica, when a dependency is slow or down, and when work outlives the request
that started it. No external worker covers this, and it is where inherited systems hide their worst surprises. You
find, cite and design the deterministic test; the proof pass builds and runs it.

`<skill-dir>` is two folders above this file (the folder that holds `SKILL.md` and `ia.py`).

## Scope

The scope your prompt names (usually the whole backend, split by module), covering at least these topics:

1. **Locks and transactions inventory.** Every lock (database row locks, advisory locks, mutexes, distributed locks)
   and every transaction: what it protects, and what it should protect but does not.
2. **Check-then-act without a transaction or lock.** Count, then delete; read, then write; "if not exists, insert";
   "if stock is left, reserve it". Two concurrent requests both pass the check and both act.
3. **Idempotency of handlers and retries.** HTTP handlers, queue consumers and webhooks that run twice (client retry,
   queue redelivery, at-least-once delivery) and repeat a side effect: double charge, duplicate row, duplicate
   external call. Retry wrappers that retry non-idempotent work. A wrapper whose `catch` re-runs the handler it was
   meant to protect, so a failing handler executes twice.
4. **In-memory state with more than one replica.** Caches, maps, sets, counters, rate limiters, circuit breakers,
   session or cancellation flags kept in process memory, while the system runs (or will run) several replicas or a
   separate worker process. State that one process sets and another never sees.
5. **Queues and workers.** Who enqueues, who consumes, and **who starts the worker**: a consumer that no command, image
   or deployment starts. Enqueue calls whose errors are swallowed, so the job silently never exists while the caller
   reports success. Job ids or payloads the queue library rejects. Ordering assumptions a queue does not guarantee.
6. **Work without durability.** Fire-and-forget work started inside the request process (respond `202`, keep working
   in the same process): a deploy, a crash or a scale-down loses it with no retry and no record.
7. **Boot and startup.** Schema changes (DDL), migrations and seeds run at startup by more than one path or by every
   replica at once; startup that assumes it is the only instance; work that runs before the server is ready.
8. **Timeouts and dependencies that are down.** Every outbound call (database, cache, queue broker, HTTP API, LLM): is
   there a timeout, and what does the caller do while the dependency is down or slow? A request that hangs for minutes
   because a client library retries a broken connection inside the request. A fallback that hides the outage.
9. **Cancellation across processes.** A cancel that only reaches the process that received it, not the worker doing
   the work or the other replicas. A cancel flag scoped to a conversation, a user or a resource instead of to one
   request, so it cuts the next, unrelated request. A cancel that leaves state half written.
10. **Time.** Expiry and scheduling that use local clocks across machines, timers kept in memory, TTLs that outlive
    the thing they guard.

## Out of scope

- General functional bugs (`correctness-general.md`), security (`security.md`), supply chain and containers.
- Performance tuning that changes no outcome.
- Writing or running tests in the repos, editing files, making commits. This pass is read-only: you design the test, the
  proof pass builds it in its own worktree.

## Inputs

- The run dir and your scope.
- `manifest.json`: `repos[]` (`alias`, `path`, `subdir`, `sha`), `lang`, `sections.correctness`.
- The baseline-inventory hand-back if the orchestrator passes it (processes, workers and who starts them, data stores,
  schema paths, external dependencies). If not, rebuild the parts you need.
- `python3 <skill-dir>/ia.py finding list --run <run-dir> --report correctness` to avoid duplicates.

## Method

1. Read the code at the pinned SHA (`git -C <path> show <sha>:<file>` or the worktree you were given).
2. Build the process model first: which processes exist (API, workers, schedulers, frontend server), how many of each
   can run, what each starts at boot, and what state each keeps in memory. Search for module-level and singleton state
   (`new Map`, `new Set`, module variables, class statics, `lru_cache`, global dicts).
3. Walk the ten topics above against that model, **module by module**: for each module in your scope, run every
   topic's starting search (below) on it, read what the search returns, and note the result in its cell of the
   topic × module table before moving to the next module. For every write path, ask: what if this runs twice at once,
   twice in a row, in another process, or after the dependency died halfway? A search that returns nothing is a
   result too, but read the module's write paths anyway: the searches are where you start, not where you stop.
4. For each candidate, write the interleaving as numbered steps (request A reads 1 unit in stock; request B reads 1
   unit in stock; A reserves it; B reserves it; 2 orders hold the same unit).
5. **Rate it by impact when it fires**, with `references/rubric.md`: a lost write or a broken invariant corrupts data
   (high) even if it needs a narrow window. How often it fires is an inference and goes in the prose as such.
6. **Design a deterministic test** for each candidate; never rely on sleeps or on running something many times hoping
   it collides:
   - barriers or latches (a promise, an event, a `threading.Barrier`) that hold both actors right after the check and
     release them together;
   - two database connections with explicit transactions, each paused at the right statement;
   - fake clocks or injected timers for expiry, TTL and timeout logic;
   - two instances of the service or two worker objects in one test to stand for two replicas or two processes;
   - a dependency stub that never answers (or refuses connections) plus a test-level deadline, to prove a hang.
   **Never mock the suspect library.** When the flaw goes through a library (queue, HTTP client, ORM, database driver,
   cache client), the design uses the real library at the locked version with the input the code really builds (the
   job id, payload, key or query the code assembles), and fakes only what lies beyond it: an in-memory server, a
   closed port, a stub endpoint. A double that replaces the library's call never runs the library's own validation,
   so it hides the cause and proves a different, weaker flaw.
   Write the test design in your hand-back, keyed by finding id: file to put it in, setup, the interleaving, and the
   assertion that fails at the base.
7. If no deterministic test can express it, say why. That candidate stays `confidence: unverified` and is not shown in
   the reports; the person is told about it.

### Starting searches

Run each one per module (`rg -n` from the module folder at the pinned SHA, adjusting the extensions to the stack),
then read every hit in context. They are generic on purpose: widen them when the stack names things differently.

- **Topic 1** (locks, transactions): `rg -n 'transaction\(|BEGIN|FOR UPDATE|advisory|[Mm]utex|[Ll]ock\('`; for each
  hit, list what it protects, then list the write paths that have none.
- **Topic 2** (check-then-act): `rg -n 'count\(|COUNT\(|exists\(|findFirst|findOne'`, then read the next write in the
  same function (`delete`, `update`, `insert`, `create`): a count or read followed by a write with no `transaction` or
  lock around both is the candidate.
- **Topic 3** (idempotency, retries): catch-then-rerun wrappers, including the decorator form whose `catch` calls
  `originalMethod.apply(this, args)`,
  `rg -n -U 'catch\s*(\([^)]*\))?\s*\{[\s\S]{0,400}?\b(fn|handler|callback|next|original|wrapped|method|descriptor)\w*(\.(apply|call))?\('`
  (the bounded `[\s\S]{0,400}?` also reaches calls inside nested braces of the catch body). Then a second, simpler
  search that does not depend on the body's shape: the files that contain both `catch` and `descriptor.value`, or a
  wrapper that returns a function calling the wrapped one (`rg -l 'descriptor\.value' . | while read -r f; do rg -l 'catch' "$f"; done`, and
  `rg -l -U 'return (async )?(function|\()[\s\S]{0,200}?catch'`); read every `catch` in those files. Plus
  `rg -n -i 'retr(y|ies)|attempts|redeliver'`; read whether the re-run work is idempotent.
- **Topic 4** (in-memory state): `rg -n 'new (Map|Set|CircuitBreaker|LRU)'` inside constructors and at module level,
  then count how many times each owning class is built (`rg -c 'new <Service>\('` across the repo), or, with a
  dependency-injection framework, each module or provider that registers it, and its scope: every instance holds its
  own copy, and every replica holds another.
- **Topic 5** (queues, workers): `rg -n '\.add\(|enqueue|jobId|new Worker\(|\.process\('`; then open the queue library
  at the version in the lockfile (its source or its docs for that version) and check what it validates about the
  `jobId` and the payload the code builds (characters, length, uniqueness); and find who starts each consumer.
- **Topic 6** (durability): `rg -n 'status\(202\)|code\(202\)|void [A-Za-z_.]+\(|setImmediate|nextTick|create_task'`:
  work that continues after the response in the same process.
- **Topic 7** (boot, startup): `rg -n -i 'CREATE TABLE|ALTER TABLE|seed' -g '!**/migration*/**'`: DDL and seeds
  outside the migration folders, and every path that runs them at boot. Exclude the repo's own migration folder
  (often `migration*`, `drizzle/`, `alembic/`, `prisma/migrations`) with one `-g '!<folder>/**'` each.
- **Topic 8** (timeouts): `rg -n -i 'fetch\(|axios|request\(|new \w*Client\(|timeout'`; every outbound client with no
  timeout in its options or at the call site is a candidate.
- **Topic 9** (cancellation): `rg -n -i 'abort|cancel|signal'`; check what key the flag is stored under and which
  processes can see it.
- **Topic 10** (time): `rg -n -i 'Date\.now\(|new Date\(|setTimeout|setInterval|ttl|expire'`; timers and expiries kept
  in memory or computed from a local clock across machines.

## Evidence rules

- Cite tight line ranges, not whole files: the check line and the act line (two evidence entries if they are apart),
  the in-memory declaration and the place another process should read it, the call without a timeout. `ALIAS/path`
  is relative to the alias root, lines at the pinned SHA.
- Read every cited line. Library behaviour you state (a queue rejecting an id, a client retrying for N seconds, a
  driver's default isolation level) is checked against the library version locked in the repo, in its source or
  documentation, and the version is named; otherwise it is labelled "inference".
- "Runs as more than one replica" needs evidence (deployment manifests, autoscaling settings, a separate worker
  command) or the label "inference: if more than one replica runs".
- Every candidate starts as `confidence: unverified`. Only a red test turns it into `execution`.

## Output

One `ia.py finding add` per candidate, JSON on stdin, prose fields in the run's `lang`:

```bash
python3 <skill-dir>/ia.py finding add --run <run-dir> - <<'EOF'
{"report": "correctness", "category": "<a category from sections.correctness>", "dimension": "race",
 "title": "<one technical line>", "verdict": "candidate", "severity": "high", "confidence": "unverified",
 "source": "races-distributed",
 "what_happens": "<the interleaving in two to four sentences, what is lost or corrupted, who triggers it; frequency labelled as inference>",
 "evidence": [{"cite": "BACK/src/inventory/reserve.ts", "from": 88, "to": 91, "note": "the check: reads the stock left"},
              {"cite": "BACK/src/inventory/reserve.ts", "from": 95, "to": 97, "note": "the act: decrements outside any transaction"}],
 "fix_summary": "<for example: do the check and the write in one transaction with a row lock>"}
EOF
```

Use `dimension: "race"` for concurrency inside one process or one database, and `"distributed"` for flaws that need
more than one process, replica or dependency (in-memory state across replicas, workers nobody starts, missing
durability, timeouts, cancellation across processes). If you cannot run commands that write (a read-only host mode),
print each finding as a fenced `json` block instead and the orchestrator adds them.

The hand-back lists, per id: severity, the deterministic test design (or why none exists), and the process model you
built, so the proof pass does not rebuild it.

The hand-back also carries the **topic × module table**: one row per topic, one column per module in your scope, and
in each cell the finding ids it produced, `nothing`, or `not checked` with the reason. For example:

| Topic | BACK/src/modules/orders | BACK/src/jobs |
|---|---|---|
| 1 locks, transactions | nothing | nothing |
| 2 check-then-act | C-04 | nothing |
| ... | ... | ... |
| 10 time | nothing | not checked: no timers in this module, read in full |

Then record each module's column, one call per module (the orchestrator does it when you cannot write):

```bash
python3 <skill-dir>/ia.py coverage add --run <run-dir> --pass races-distributed --module BACK/src/modules/orders \
  --result found --topics 1,2,3,4,5,6,7,8,9,10 --note "C-04"
python3 <skill-dir>/ia.py coverage add --run <run-dir> --pass races-distributed --module BACK/src/jobs \
  --result nothing --topics 1,2,3,4,5,6,7,8,9,10 --note "all ten topics walked, nothing found"
```

`--result found|nothing` says whether the module produced findings. When the module has nothing this pass looks at
(presentational components with no I/O, no shared state and no background work), record `--result n/a --note
"<why>"` instead, with no topics; a module with any I/O, store, timer or worker is not `n/a`. `--topics` lists only the topics you really
walked on that module: leave a topic out rather than claim it, and the cell stays open until someone walks it.
A later `coverage add` for the same pass and module replaces the whole cell, so list every topic walked so far,
not only the new ones.

## Done when

- The process model is written down (processes, replicas, boot work, in-memory state, workers and their starters).
- Every one of the ten topics was checked against every module in the scope, the topic × module table is in the
  hand-back, and every module has its `ia.py coverage add` call with the topics walked.
- Every candidate has tight cites, an interleaving, a severity by impact and a deterministic test design, or is marked
  as not reproducible deterministically (it stays `unverified` and out of the reports).
