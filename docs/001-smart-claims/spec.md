# Feature Specification: Smart Claims — End-to-End Insurance Lakehouse

**Feature Branch**: `001-smart-claims`

**Created**: 2026-09-09

**Status**: Draft

**Input**: Reproduce the end-to-end Databricks project described in `docs/transcript.txt` as a reproducible, bundle-deployed implementation, adapted to run entirely inside a Databricks Free Edition workspace with no external cloud services.

## Context

A car insurance company processes claims manually: when a customer submits a claim for a car
crash, a human reviews the policy, the claimed amount, the accident circumstances and a photo of
the damage. This is slow, inconsistent, and does not use the telematics data the company already
collects from its vehicles.

The company wants two outcomes:

1. **A single source of truth.** Customer, policy, claim, telematics and accident-image data
   currently live in three disconnected systems. Unify them so the business can run analytics and
   make decisions on complete data.
2. **Automated claims triage.** Replace the manual first-pass review with automated checks:
   was the driver speeding, is the policy valid, is the claimed amount within coverage, and does
   the damage visible in the photo actually match the severity the customer reported? Claims that
   pass every check are approved for payout; claims that fail any check are routed to a human.

The delivery target is a Databricks Free Edition workspace, which imposes hard constraints
(serverless compute only, no GPU, no external object storage, no classic-compute ingestion
gateways). The architecture is preserved; the external data sources are simulated inside the
workspace. See **Assumptions** for the full substitution list and its rationale.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Governed Data Foundation (Priority: P1)

A data engineer sets up the governed workspace structure that everything else depends on: one
catalog with clearly separated zones for raw landing, untransformed ingested data, cleaned data
and business-ready data. They seed the operational source data (customers, policies, claims) and
load a labelled set of car-damage photographs that the classifier will later learn from.

**Why this priority**: Every other story reads from or writes to this structure. Nothing can be
built or demonstrated until the catalog, schemas, volumes and seed data exist. It is also the
only story that must succeed before the workspace's actual capabilities are known.

**Independent Test**: Run the foundation setup, then confirm the catalog contains four
populated schemas, that source tables hold plausible referentially-consistent records, and that
the training-image volume contains labelled images organised so their severity label is
recoverable.

**Acceptance Scenarios**:

1. **Given** an empty workspace, **When** the foundation setup runs, **Then** a catalog exists
   containing a source zone, a landing zone, and bronze, silver and gold zones.
2. **Given** the foundation setup has run, **When** the source customer, policy and claim tables
   are queried, **Then** each holds at least 1,000 records and every claim references an existing
   policy and every policy references an existing customer.
3. **Given** the foundation setup has run, **When** the training-image volume is listed, **Then**
   it contains images spanning at least three distinct damage-severity classes, each label
   represented by at least 20 images.
4. **Given** the environment cannot reach the public image source, **When** the foundation setup
   runs, **Then** it reports the failure clearly and falls back to a documented alternative rather
   than leaving the volume silently empty.

---

### User Story 2 - Telematics Event Ingestion (Priority: P2)

Vehicles continuously emit telematics readings — chassis identifier, speed, position and event
time. A data engineer ingests this event feed into the lakehouse so that speed at the time of an
accident becomes available to claims triage. The raw feed arrives as an opaque encoded payload and
must be decoded into queryable typed columns.

**Why this priority**: Telematics powers the speeding check, which is one of the four triage
rules. It is also the first ingestion path, establishing the incremental-ingestion pattern the
other sources reuse.

**Independent Test**: Emit a known batch of telematics events, run the ingestion, and confirm the
bronze telematics table holds exactly those events with correct typed values. Then emit more
events, re-run, and confirm only the new events are added.

**Acceptance Scenarios**:

1. **Given** telematics events have been emitted to the landing zone, **When** ingestion runs,
   **Then** the bronze telematics table contains one row per event with chassis number, speed,
   latitude, longitude and event timestamp as distinct typed columns, not an opaque blob.
2. **Given** ingestion has already processed a set of events, **When** new events arrive and
   ingestion runs again, **Then** only the new events are written and previously processed events
   are not duplicated.
3. **Given** ingestion is configured for continuous operation, **When** events are emitted while
   it is running, **Then** the bronze table reflects them without a manual re-run.
4. **Given** ingestion is configured for triggered operation, **When** it is invoked, **Then** it
   processes all pending events and stops.

---

### User Story 3 - Operational Database Change Capture (Priority: P3)

Customer, policy and claim records are maintained in the company's operational system, where they
are created, corrected and deleted throughout the day. A data engineer replicates those changes
into the lakehouse incrementally, so the analytical copy reflects the operational truth without
re-copying the whole database.

**Why this priority**: Claims triage needs current policy and customer state — a stale copy would
approve claims against expired policies. Change capture must work before the silver layer can be
trusted.

**Independent Test**: Ingest an initial snapshot, then perform one insert, one update and one
delete against the source, re-run ingestion, and confirm each change is reflected correctly in
the corresponding bronze table.

**Acceptance Scenarios**:

1. **Given** the source system holds customer, policy and claim records, **When** ingestion runs
   for the first time, **Then** bronze tables contain a complete copy of each source table.
2. **Given** a new policy is created in the source, **When** ingestion runs, **Then** that policy
   appears in the bronze policy table.
3. **Given** an existing claim's severity is changed in the source, **When** ingestion runs,
   **Then** the bronze claim table shows the new value and does not retain a duplicate row with
   the old value.
4. **Given** a customer is deleted in the source, **When** ingestion runs, **Then** that customer
   is absent from the bronze customer table.

---

### User Story 4 - Accident Image and Metadata Ingestion (Priority: P4)

Customers upload accident photographs, and an accompanying metadata feed describes which claim
each photograph belongs to. A data engineer ingests both incrementally. The metadata feed's shape
changes over time as upstream teams add fields, and processed photographs must be moved out of
the active area so storage is not paid for twice.

**Why this priority**: The accident images are the input to the damage classifier, and the
metadata links each image to its claim. Without both, the severity check cannot run. Schema drift
and archiving are secondary concerns but are explicit learning objectives of this story.

**Independent Test**: Ingest an initial batch, then add a file carrying an unexpected extra
field, re-run, and confirm the ingestion handles the drift according to the configured policy.
Separately, confirm processed image files are relocated to the archive area.

**Acceptance Scenarios**:

1. **Given** training images exist in the landing zone, **When** ingestion runs, **Then** a bronze
   table contains one row per image with its file path, binary content and file metadata.
2. **Given** metadata ingestion is configured to absorb new fields, **When** a file arrives with
   an additional column, **Then** that column is added to the target table and existing rows show
   no value for it.
3. **Given** metadata ingestion is configured to quarantine unexpected fields, **When** a file
   arrives with an additional column, **Then** the target table's columns are unchanged and the
   unexpected field's value is captured in a dedicated quarantine column.
4. **Given** accident images have been ingested and the archive retention period has elapsed,
   **When** ingestion runs again, **Then** the processed image files are present in the archive
   area and absent from the active area.

---

### User Story 5 - Cleansing, Business Views and Scheduled Orchestration (Priority: P5)

A data engineer turns raw ingested data into trustworthy, business-ready datasets: enforcing data
quality rules that reject bad records, correcting inconsistent formats, and joining the separate
entities into the combined views that analysts and applications consume. The whole flow then runs
on a schedule without human intervention.

**Why this priority**: This is where raw data becomes usable. The combined customer-claim-policy-
telematics view is the single input to both the rules engine and the application. Orchestration
makes the platform operational rather than a set of manual steps.

**Independent Test**: Introduce deliberately invalid records into bronze, run the transformation,
and confirm they are excluded from silver and reported as quality violations. Then confirm the
gold views join correctly and the scheduled job runs the full graph in dependency order.

**Acceptance Scenarios**:

1. **Given** a bronze claim record with a missing claim number, **When** transformation runs,
   **Then** that record is excluded from the silver claim table and counted as a quality
   violation.
2. **Given** a bronze claim record with an incident hour outside 0–23, **When** transformation
   runs, **Then** that record is excluded from the silver claim table and counted as a quality
   violation.
3. **Given** bronze records carry dates in several inconsistent text formats, **When**
   transformation runs, **Then** the corresponding silver columns hold true date values.
4. **Given** a bronze customer record holds a single combined name field, **When** transformation
   runs, **Then** the silver customer record exposes separate first-name and last-name values.
5. **Given** a bronze policy record holds a negative premium, **When** transformation runs,
   **Then** the silver policy record holds the positive equivalent.
6. **Given** silver tables are populated, **When** the gold layer is built, **Then** a combined
   view exists joining each claim to its policy, its customer and that vehicle's aggregated
   telematics.
7. **Given** the orchestration job is scheduled, **When** it runs, **Then** ingestion completes
   before transformation begins, and a failure in ingestion prevents transformation from running.

---

### User Story 6 - Damage Classification and Automated Triage (Priority: P6)

A data scientist trains a model that judges the severity of car damage from a photograph, tracks
the experiment so the result is reproducible, and publishes the model under governance. A claims
analyst then defines the business rules that decide each claim's fate, and the platform applies
every rule to every claim, recording each check's outcome alongside an overall decision.

**Why this priority**: This is the core business value — the automation that replaces manual
review. It depends on every preceding story for its inputs.

**Independent Test**: Train on a held-out split and confirm the model's accuracy is reported with
a per-class breakdown. Separately, construct claims that each violate exactly one rule and
confirm each is flagged for the correct reason while a fully compliant claim is approved.

**Acceptance Scenarios**:

1. **Given** labelled training images are available, **When** training runs, **Then** the run's
   parameters, metrics and resulting model are recorded under a named experiment and can be
   inspected after the fact.
2. **Given** a trained model, **When** it is published, **Then** it is governed in the catalog
   under a stable name with an alias identifying the production version.
3. **Given** a published model and a set of accident images, **When** scoring runs, **Then** every
   image has a predicted severity recorded alongside it, and a per-class breakdown of predicted
   against actual severity is produced.
4. **Given** a claim whose claimed amount exceeds its policy coverage, **When** triage runs,
   **Then** that claim is flagged for investigation and the coverage check is recorded as failed.
5. **Given** a claim whose customer-reported severity disagrees with the predicted severity,
   **When** triage runs, **Then** that claim is flagged for investigation and the severity check
   is recorded as failed.
6. **Given** a claim whose accident occurred outside the policy's valid date range, **When**
   triage runs, **Then** that claim is flagged for investigation and the policy-validity check is
   recorded as failed.
7. **Given** a claim whose telematics show speed above the permitted threshold, **When** triage
   runs, **Then** that claim is flagged for investigation and the speed check is recorded as
   failed.
8. **Given** a claim that passes all four checks, **When** triage runs, **Then** it is marked for
   fund release.
9. **Given** an existing set of triaged claims, **When** a new rule is added, **Then** the rule can
   be applied to re-evaluate all existing claims without changing the triage logic itself.

---

### User Story 7 - Business Consumption Surfaces (Priority: P7)

Three audiences consume the results. A business analyst opens a dashboard summarising claim
volumes and severity mix. A business user without SQL asks questions of the data in plain
language. A customer submits a claim through a portal and receives an immediate decision, while
an internal reviewer uses the same portal's admin view to investigate the flagged claims.

**Why this priority**: This is the visible payoff. It depends on everything upstream and is the
only story an end user interacts with directly.

**Independent Test**: Open the dashboard and confirm the figures reconcile against direct queries.
Ask the natural-language interface a question with a known answer. Submit a claim through the
portal end to end and confirm the decision matches what the rules engine would produce.

**Acceptance Scenarios**:

1. **Given** triaged claims exist, **When** the dashboard is opened, **Then** it shows total claim
   volume and a breakdown by severity, and its figures match direct queries of the same data.
2. **Given** the dashboard has a date-range filter, **When** the range is narrowed, **Then** every
   visual updates to reflect only claims in that range.
3. **Given** the natural-language interface is connected to the business-ready data, **When** a
   user asks how many claims fall into each severity category, **Then** it returns correct counts
   and exposes the query it ran.
4. **Given** a customer on the portal, **When** they upload an accident photograph, **Then** they
   are shown the severity the model predicts from it before they submit.
5. **Given** a customer has supplied a photograph, policy number, accident location, claimed
   amount, accident date, self-assessed severity, collision type and vehicle count, **When** they
   submit, **Then** they receive an approve-or-investigate decision together with the individual
   result of each of the four checks.
6. **Given** a reviewer in admin mode, **When** they open the overview, **Then** they see total
   claims and a severity breakdown, and can filter the claim list by severity.
7. **Given** a reviewer selects a claim in admin mode, **When** the analysis view opens, **Then**
   it shows every check's result, the claim details, the customer details and the uploaded image.
8. **Given** a reviewer opens a claim's details, **When** the data loads, **Then** it appears
   without the delay characteristic of an analytical query engine.

---

### Edge Cases

- **Claim references a missing policy or customer.** Triage cannot evaluate coverage or validity.
  The claim must be flagged for investigation with the check recorded as indeterminate, never
  silently approved.
- **Claim has no accident image, or the image fails to classify.** The severity check must be
  recorded as indeterminate and the claim flagged, not defaulted to pass.
- **Vehicle has no telematics readings for the accident window.** The speed check must be recorded
  as indeterminate and the claim flagged.
- **Telematics payload is malformed or unparseable.** The row must be quarantined or dropped with
  a recorded quality violation; a single bad payload must not fail the whole ingestion.
- **Two accidents for the same vehicle on the same day.** Telematics aggregation must not
  attribute one accident's speed to the other.
- **Duplicate claim submission.** The same claim submitted twice must not produce two payout
  decisions.
- **Archive retention has not yet elapsed when ingestion runs.** Files remain in the active area
  and are archived on a later run; this must not be reported as a failure.
- **Ingestion runs with no new data.** It must complete successfully having written nothing.
- **A source column is removed upstream.** Downstream transformation must fail loudly rather than
  silently producing null-filled records.
- **Claimed amount is zero or negative.** Must be rejected as a data-quality violation before
  reaching triage.
- **Customer uploads a file that is not an image.** The portal must reject it with a clear message
  rather than submitting an unclassifiable claim.

## Requirements *(mandatory)*

### Functional Requirements

#### Data foundation

- **FR-001**: System MUST provide a single governed catalog containing five separated zones: a
  simulated operational source, a raw landing area, and bronze, silver and gold data layers.
- **FR-002**: System MUST seed the operational source with mutually consistent customer, policy
  and claim records sufficient in volume to exercise every downstream check.
- **FR-003**: System MUST make labelled damage photographs available in the landing area, with
  each image's severity label recoverable from its storage location.
- **FR-004**: System MUST verify external network reachability before attempting to fetch the
  image dataset, and MUST fail with an actionable message and documented fallback if unreachable.

#### Telematics ingestion

- **FR-005**: System MUST emit telematics events — chassis number, speed, latitude, longitude and
  event timestamp — into the landing area as discrete records.
- **FR-006**: System MUST decode telematics events from their transported encoded form into
  individually typed and queryable columns in the bronze layer.
- **FR-007**: System MUST ingest telematics incrementally, processing each event exactly once
  across repeated runs without external bookkeeping by the operator.
- **FR-008**: System MUST support both triggered and continuous telematics ingestion, selectable
  by configuration rather than by rewriting the ingestion logic.

#### Change capture

- **FR-009**: System MUST replicate customer, policy and claim records from the operational source
  into the bronze layer.
- **FR-010**: System MUST apply inserts, updates and deletes from the operational source such that
  each bronze table converges on the source's current state, with updates replacing rather than
  duplicating rows and deletes removing them.
- **FR-011**: System MUST provide a repeatable verification procedure that performs one insert,
  one update and one delete at the source and demonstrates each propagating correctly.

#### File ingestion

- **FR-012**: System MUST ingest image files incrementally into the bronze layer, retaining each
  file's path, binary content and file metadata.
- **FR-013**: System MUST ingest image metadata files incrementally and MUST support two
  configurable responses to an unexpected new field: absorbing it as a new column, or capturing it
  in a dedicated quarantine column while leaving the table's columns unchanged.
- **FR-014**: System MUST relocate processed accident-image files to an archive area after a
  configurable retention period, and MUST NOT re-ingest archived files.

#### Cleansing and business views

- **FR-015**: System MUST reject records failing declared quality rules — claim number present,
  incident hour within 0–23, claimed amount strictly greater than zero, policy number present,
  customer identifier present — excluding them from the silver layer.
- **FR-016**: System MUST report, per quality rule, how many records passed and how many were
  rejected on each run.
- **FR-017**: System MUST convert date-bearing text columns into true date values, correctly
  handling each of the differing formats present in the source data.
- **FR-018**: System MUST split the combined customer name field into separate first-name and
  last-name values, and normalise the customer address field.
- **FR-019**: System MUST normalise policy premium values to their absolute magnitude.
- **FR-020**: System MUST exclude ingestion-time quarantine columns from the silver layer.
- **FR-021**: System MUST produce a gold view aggregating telematics **per vehicle per day**,
  including maximum and average speed and mean position. Aggregating per vehicle alone is
  insufficient: a vehicle with two accidents on different dates would otherwise carry a single
  speed figure, attributing one accident's speed to the other.
- **FR-022**: System MUST produce a gold view joining each claim to its policy and its customer,
  and a further view adding that vehicle's aggregated telematics **for the date of the incident**.
  The join MUST NOT increase or decrease the claim count.
- **FR-023**: Gold views MUST refresh incrementally in response to upstream changes rather than
  recomputing in full.
- **FR-024**: System MUST orchestrate ingestion and transformation as a single scheduled unit in
  which transformation runs only after ingestion succeeds.

#### Classification and triage

- **FR-025**: System MUST normalise training images to the input dimensions the classifier
  requires before training.
- **FR-026**: System MUST train a damage-severity image classifier and record the run's
  parameters, metrics and artifacts under a named, inspectable experiment.
- **FR-027**: System MUST publish the trained classifier into the governed catalog under a stable
  name carrying an alias that identifies the production version.
- **FR-028**: System MUST score accident images in bulk using the published classifier, writing
  each predicted severity alongside its image.
- **FR-029**: System MUST produce a per-class comparison of predicted against actual severity for
  the held-out data.
- **FR-030**: System MUST store triage rules as data — each with an identifier, a description and
  an evaluable definition — so rules can be added or amended without changing triage logic.
- **FR-031**: System MUST evaluate, for every claim: claimed amount against policy coverage,
  predicted severity against customer-reported severity, accident date against policy validity,
  and telematics speed against the permitted threshold.
- **FR-032**: System MUST record each check's individual outcome per claim, plus an overall
  outcome of either release-funds or requires-investigation.
- **FR-033**: A claim MUST be marked release-funds only when at least one check ran and every
  check passed; any failed or indeterminate check, or the absence of any checks at all, MUST
  mark it requires-investigation.
- **FR-034**: System MUST support re-evaluating all existing claims after a rule is added or
  amended.

#### Consumption

- **FR-035**: System MUST provide a dashboard reporting claim volume and severity mix, filterable
  by a user-supplied date range.
- **FR-036**: System MUST provide a natural-language interface over the business-ready data that
  answers questions and exposes the query it generated.
- **FR-037**: System MUST provide a low-latency serving copy of the combined claim view suitable
  for interactive application reads.
- **FR-038**: Customers MUST be able to submit a claim providing an accident photograph, policy
  number, accident location, claimed amount, accident date, self-assessed severity, collision type
  and vehicle count.
- **FR-039**: System MUST show the customer the classifier's predicted severity for their uploaded
  photograph before they submit.
- **FR-040**: System MUST return, on submission, an approve-or-investigate decision together with
  each individual check's result.
- **FR-041**: System MUST reject non-image uploads with a clear message before submission.
- **FR-042**: Internal reviewers MUST be able to see total claim volume and severity breakdown,
  filter the claim list by severity, and open any claim to see every check result, the claim
  details, the customer details and the uploaded photograph.

#### Reproducibility and quality

- **FR-043**: Every workspace asset — pipelines, jobs, dashboard, application — MUST be defined in
  version-controlled configuration and deployable from a clean checkout, with no manual
  console configuration required.
- **FR-044**: System MUST include automated tests covering telematics payload decoding, customer
  name and address normalisation, date-format coercion, and triage rule evaluation, executable
  without a live workspace connection.
- **FR-045**: Transformation MUST fail loudly when a column it depends on is absent from its
  source, rather than emitting rows with null values in its place.

### Key Entities

- **Customer**: A policyholder. Identifier, name (combined at source, split downstream), date of
  birth, address, contact details. Owns one or more policies.
- **Policy**: An insurance contract. Policy number, owning customer, coverage amount, premium,
  effective and expiry dates, insured vehicle chassis number.
- **Claim**: A customer's request for payout. Claim number, referenced policy, accident date and
  hour, location, claimed amount, customer-reported severity, collision type, vehicle count.
- **Telematics Reading**: A single vehicle sensor observation. Chassis number, speed, latitude,
  longitude, event timestamp. Aggregated per vehicle for analysis.
- **Accident Image**: A photograph submitted with a claim. Storage path, binary content, linked
  claim number, predicted severity once scored.
- **Training Image**: A labelled damage photograph used to fit the classifier. Storage path,
  binary content, ground-truth severity label.
- **Triage Rule**: A named, described, evaluable condition applied to claims. Identifier,
  description, definition, and the check name whose result it produces.
- **Claim Insight**: The triage outcome for one claim. Claim number, each individual check result,
  overall decision, and the joined claim, policy, customer and telematics context.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All five catalog zones are populated end to end from a clean deployment, with no
  manual console steps required beyond supplying credentials.
- **SC-002**: One insert, one update and one delete performed at the operational source are all
  correctly reflected in the lakehouse after a single ingestion run.
- **SC-003**: Re-running any ingestion path with no new data completes successfully and adds zero
  rows.
- **SC-004**: A metadata file carrying an unexpected field is handled correctly under both
  configured drift policies, demonstrated by inspecting the resulting table in each case.
- **SC-005**: Processed accident-image files appear in the archive area and are absent from the
  active area after the retention period elapses.
- **SC-006**: Deliberately invalid records injected into bronze are absent from silver, and the
  quality report attributes each rejection to the specific rule that caught it.
- **SC-007**: The combined gold view returns one row per claim with its policy, customer and
  telematics context, and no claim is lost or duplicated by the joins. A vehicle with accidents on
  two different dates yields a distinct speed figure for each.
- **SC-007a**: A claim with a zero or negative claimed amount is absent from the silver layer and
  attributed to the amount rule in the quality report.
- **SC-007b**: Removing a depended-upon column from a source table causes transformation to fail
  with an error naming the missing column, rather than producing null-filled rows.
- **SC-008**: A registered classifier exists in the catalog carrying a production alias, traceable
  back to the experiment run that produced it.
- **SC-009**: The classifier's per-class accuracy breakdown is produced and recorded, establishing
  a documented baseline for the dataset used.
- **SC-010**: For each of the four checks, a claim constructed to violate only that check is
  flagged for investigation with exactly that check recorded as failed.
- **SC-011**: A claim constructed to satisfy all four checks is marked release-funds.
- **SC-012**: A newly added rule can be applied to re-evaluate all existing claims without
  modifying triage logic.
- **SC-013**: Dashboard figures reconcile exactly against direct queries of the same underlying
  data.
- **SC-014**: A customer can complete a claim submission — upload through to decision — in under
  two minutes, and the returned decision matches what the rules engine independently produces for
  the same inputs.
- **SC-015**: A reviewer opening a claim's detail view sees it populated in under two seconds.
- **SC-016**: The automated test suite passes from a clean checkout without a workspace
  connection.
- **SC-017**: Deploying to an empty workspace from a clean checkout produces a working system with
  no undocumented manual steps.

## Assumptions

### Environment

- The target is the Databricks Free Edition workspace at
  `https://dbc-b5c9918e-c2d2.cloud.databricks.com`, accessed via the `DEFAULT` CLI profile.
- Only serverless compute is available. No classic clusters, no GPU, no instance pools.
- No external cloud object storage, no external relational database, no managed streaming service,
  and no cloud IAM roles or service credentials are available to this project.
- A single serverless SQL warehouse is available and may be started on demand.
- Costs are zero; runtime and feature availability, not spend, are the binding constraints.

### Source-system substitutions

The transcript's architecture depends on external AWS services. Each is simulated inside the
workspace. The architectural pattern and its learning objective are preserved; only the transport
changes.

| Transcript source | Substitution | Preserved | Lost |
|---|---|---|---|
| Managed streaming service, accessed via a cloud IAM service credential | A producer job writes encoded event records into a landing volume; ingestion reads them incrementally | Payload decoding into typed columns, exactly-once incremental processing, triggered vs continuous modes | Configuring a cloud service credential; true unbounded low-latency transport |
| External relational database with change-data-capture, replicated by a managed ingestion gateway | Seeded source tables plus a change feed, replicated by declarative change-application | Insert/update/delete convergence semantics, incremental replication | The managed gateway itself, which requires classic compute and a reachable external database; source-side CDC enablement |
| External object storage bucket behind an external location | Catalog-managed volumes | Incremental file discovery, schema-drift handling, post-processing archival | External location and storage credential configuration |
| GPU compute for model training | Serverless CPU compute, a compact model architecture, few epochs | Experiment tracking, governed model publication, bulk scoring | Training speed; achievable model accuracy |

### Scope decisions

- **Real-time model serving is out of scope unless proven available.** The workspace exposes only
  foundation-model endpoints today; no custom endpoint exists. The classifier is consumed through
  bulk scoring, and the application reads precomputed predictions. An early investigation
  determines whether a custom endpoint can be created; if it can, adding one is an enhancement,
  not a prerequisite, and no acceptance scenario in this specification depends on it.
- **Low-latency serving depends on availability.** The workspace shows the managed operational
  database plumbing present but zero instances provisioned. An early investigation confirms whether
  an instance can be created. If it cannot, FR-037 is satisfied by the analytical query engine
  instead, SC-015 is relaxed accordingly, and the substitution is recorded.
- **The classifier's accuracy target is deliberately unstated.** With CPU-only training on a small
  public dataset, the objective is a working, tracked, governed and reproducible model — not a
  competitive one. SC-009 requires the accuracy be measured and recorded, not that it exceed a
  threshold.
- **The portal has no authentication or multi-tenancy.** Customer and admin modes are selected by
  a mode switch, as in the transcript's demonstration. This is a learning artifact, not a
  production application, and it must not be exposed to real claimants or loaded with real
  personal data.
- **All data is synthetic.** No real customer, policy, claim or telematics data is used at any
  point.
- **The permitted-speed threshold is a fixed configured value** rather than a per-jurisdiction
  lookup, matching the transcript. It is expressed as a rule definition so it can be changed
  without altering triage logic.
- **Historical claim backfill is out of scope.** The system triages the seeded claim set and any
  claims submitted through the portal.

### Delivery

- Every asset is defined as version-controlled configuration and deployed as a bundle, departing
  from the transcript's console-driven approach. The transcript teaches the concepts through the
  user interface; this specification requires the result be reproducible from the repository.
- Automated tests are required and were declared as such at specification time. They cover the
  pure logic that can be tested without a workspace — payload decoding, name and address
  normalisation, date coercion, and rule evaluation. Data correctness in the pipelines is enforced
  separately by declared quality rules, which are not a substitute for the test suite.
- The workspace already contains unrelated catalogs and one unrelated deployed application. This
  project must not modify or remove them.

### Dependencies

- Reachable public internet from serverless compute, for the labelled image dataset and for
  installing libraries. FR-004 makes this an explicit, checked precondition rather than a silent
  assumption.
- A publicly available labelled car-damage-severity image dataset of at least three classes.
- Command-line access to the workspace with authority to create catalogs, pipelines, jobs,
  dashboards and applications.
