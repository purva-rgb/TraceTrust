# TraceTrust Laptop System Architecture

### Implementation specification and database review

Revision 3 | 12 October 2026 | Prepared for Ojas Chhajed and team KNML

TraceTrust tracks laptops from manufacturer through distributor to retailer. It binds a laptop identity to a box and tamper-evident seal, records signed handovers, checks digital history against blockchain commitments, and groups related alerts into explainable incident candidates. Investigators retain control of counterfeit decisions.

This specification replaces the medicine-oriented architecture. It defines the target behavior for the working prototype, including failure recovery, API contracts, database changes, physical inspection, security boundaries and acceptance tests. It is a build specification, not a claim that the application or contract has already been implemented.

The supplied database is a useful demonstration foundation, but it is not ready to serve as a cryptographically verified system. Its structural integrity checks pass; its credentials, signatures, hashes and historical fixtures need correction. The detailed assessment and migration sequence appear in sections 15 through 17.

#### Decisions locked for this revision

- Product domain: laptops. Pharmacy becomes retailer; dispensing becomes sale. Medicine expiry and mandatory cold-chain rules are removed.

- Physical checks: QR identity, box ID, seal ID and condition, followed by laptop serial comparison when opening is authorized.

- Analytics: remove IsolationForest entirely. Use deterministic anomaly rules, bounded graph clustering, weighted cause hypotheses and evidence graphs.

- Transfer policy: manufacturer to distributor to retailer only. Normal transfers are all-or-nothing; no silent partial acceptance.

- Consistency: persist an operation before chain submission, confirm the chain result, then update the local projection. Reconcile interrupted operations automatically.

- Truth boundary: seals and serial labels reduce substitution risk but remain copyable. Device signatures authenticate a device statement, not the physical truth of its location.

#### Reading map

Sections 1-4 cover architecture, responsibilities and states. Sections 5-9 specify physical workflows, transfers, cryptography and blockchain recovery. Sections 10-14 define scans, fusion, incidents and APIs. Sections 15-17 review the actual database and migration. Sections 18-21 cover security, testing, delivery and source references.

## 1 System boundaries and guarantees

#### What the product establishes

TraceTrust establishes which registered organization made a claim, whether the claim followed the permitted workflow, and whether the recorded history still agrees with its independent commitment. Physical inspection provides additional evidence that the observed box and laptop correspond to those claims.

The public result must say "Digital record verified" rather than "Guaranteed genuine". An intact seal is an observation; a matching printed serial is a comparison. Neither is equivalent to manufacturer-backed hardware attestation. A browser cannot silently retrieve a laptop's BIOS serial or prove that its motherboard is genuine.

#### Threats addressed and remaining limits

- Copied QR: detect conflicting observations, unusual repeated use and inconsistent receipt evidence. A single convincing clone with no conflicting observation may remain undetected.

- Swapped laptop or box: compare registered box, seal and visible laptop identifiers at designated checkpoints. Counterfeit labels or dishonest inspectors can defeat these checks.

- Unauthorized transfer: reject wrong senders, wrong recipients, illegal role transitions, expired requests and reused transfer IDs in both API and contract.

- Database rewrite: compare canonical signed events, sequence continuity, terminal state and chain anchors. An attacker controlling both the database and local blockchain can defeat the demo trust boundary.

- Lost or delayed transaction: retain durable intent, deterministic operation identity and recovery state; never present unconfirmed custody as final.

- Alert abuse: public scans carry low trust and cannot automatically freeze a laptop or establish a counterfeit verdict.

#### Explicit exclusions

No manufacturer warranty lookup, OEM partnership, NFC authenticity, TPM attestation or real sensor deployment is assumed. Supported brands in the fixture are fictional demo records, not endorsed manufacturer integrations. A laptop's warranty expiry does not make the laptop counterfeit or prohibit supply-chain transfer by itself.

The core prototype has no payment processing, customer account, automated return to sale, arbitrary reverse custody or learned probability model. A return enters a restricted review workflow. Resale and service-center custody require a later, separately authorized extension.

#### Evidence wording

Use three independent labels: record integrity, physical inspection coverage and operational restriction. Show simulated observations prominently. A missing check must display NOT_CHECKED or UNAVAILABLE, never a green pass inferred from another field.

## 2 Components and responsibilities

#### Deployment model

Use one FastAPI application with internal modules, one SQLite database on a persistent local volume, one recovery worker and one local Ethereum-compatible node. The worker may be a separate process using the same service code. React serves role-specific screens and the public verifier. No Docker is required for local development.

| Component | Technology and responsibility |
| --- | --- |
| Presentation | React with Vite; QR rendering; camera scan when available; paste/manual fallback; optional Leaflet map |
| API | FastAPI and Pydantic; authentication, resource authorization, validation and workflow orchestration |
| Persistence | SQLite; foreign keys enabled on every connection, WAL, bounded busy timeout and short write transactions |
| Crypto | SHA-256 event commitments; secp256k1 organization/device keys; EIP-712 typed signatures using established libraries |
| Blockchain | Solidity and Hardhat; web3.py adapter; role graph, custody, restrictions, operation dedupe and event commitments |
| Recovery | Durable outbox, serialized account nonces, receipt polling and chain-to-database reconciliation |
| Analytics | Python deterministic rules, graph components, hypothesis scoring, evidence graph and versioned configuration |
| Evidence | Private local files for demo images, immutable content digests and access-controlled downloads |

#### Module ownership

api/ handles schemas and HTTP responses. auth/ loads users and organization permissions. products/ owns registration, package binding and sale. transfers/ owns manifests, receipt validation and reservations. crypto/ owns canonicalization and signature checks. chain/ owns submission and reconciliation. scans/ owns intake and event-time ordering. rules/ emits deterministic alert records. fusion/ creates versioned incident candidates. investigations/ owns human decisions. simulator/ emits labeled test scenarios.

#### Authority model

The contract is authoritative for confirmed custody, legal transitions and transfer-blocking flags. Signed records are authoritative evidence for their contents. SQLite custody is a projection used by the application; compare it with chain state before critical operations. Neither current_owner_organization_id nor retail_inventory independently determines custody.

Scans, inspection observations, incidents and detailed product metadata remain off-chain. A compact signed inspection digest is committed when it supports a trust-critical operation. Public scans do not each generate a blockchain transaction.

#### Connectivity and scale

Cap normal prototype manifests at 20 laptops and reject larger requests until contract gas and runtime limits are measured. Keep one backend host for SQLite. Multiple writers are serialized; use PostgreSQL and explicit job leases before scaling across hosts.

## 3 Roles and legal movement

#### Identity and authorization

A user belongs to one organization. Load the current user status, organization status and permissions from the database for every protected action. Signed JWT claims identify the session, but do not override current suspension. Reject conflicting user role and organization type.

| Actor | Permitted work |
| --- | --- |
| Manufacturer | Register its own models, batches, laptops and initial packages; initiate handovers of its confirmed inventory |
| Distributor | Accept from manufacturers; inspect and initiate transfers of its confirmed inventory to retailers |
| Retailer | Accept from distributors; inspect, perform supervised opening and record sale |
| Regulator | Review all evidence; freeze, unfreeze, recall and adjudicate incidents with reasons |
| Auditor | Read authorized audit evidence; no mutation, transfer, freeze or verdict |
| Administrator | Provision approved organizations/users/devices and deployment configuration; cannot manufacture or adjudicate merely because it is an admin |
| Logistics organization | Transport and scan delegated shipments; no beneficial ownership or custody transfer in the core prototype |
| Public visitor | Read a reduced verifier response and submit rate-limited low-trust observations |

#### Legal graph

Normal custody follows MANUFACTURER -> DISTRIBUTOR -> RETAILER. Reject manufacturer-to-retailer, distributor-to-manufacturer, retailer-to-distributor and same-organization commercial transfers. Internal warehouse relocation is a separate signed action that retains the custodian and validates both warehouses belong to it. It is optional for the first demo.

A logistics scan must reference an active transport assignment and transfer. Without that delegation it is an observation, not an authorized handover. A distributor scanning an expected incoming shipment must not receive a custodian-mismatch alert solely because acceptance has not yet occurred.

#### Organization suspension

Maintain active status on-chain as well as in the API. Suspension is a durable chain operation; while confirmation is pending the API denies new actions. The contract denies suspended parties independently after confirmation. Historical signatures remain verifiable using the key and authorization history valid at the event's time.

Organization provisioning is restricted to a separate deployment/governance authority. Do not give this account routine transfer keys. A production deployment requires independent governance and key control; one demo backend retaining every key cannot provide separation from that backend.

## 4 Product and operation states

#### Separate state dimensions

A single product_status field cannot accurately represent a sold laptop that is also recalled. Introduce separate lifecycle, restriction and verdict fields and retain product_status only as a legacy display projection.

| Dimension | Values and meaning |
| --- | --- |
| lifecycle_state | REGISTERED, IN_SUPPLY_CHAIN, SOLD, RETURN_REVIEW, RETIRED |
| hold_active | Investigator hold; blocks transfer and sale until an authorized unfreeze |
| recall_active | Recall restriction; permanent in this prototype |
| stolen_active | Reported theft restriction; investigator may clear with documented evidence |
| identity_revoked | Permanently retired identity; never reused |
| authenticity_verdict | UNDETERMINED, COUNTERFEIT; counterfeit requires human decision |
| package lifecycle | Existing ACTIVE, REPLACED, RETIRED; add OPENED for controlled opening |
| operation state | PENDING, SUBMITTED, CONFIRMED, FAILED, RECONCILIATION_REQUIRED |

A transfer or sale is permitted only for confirmed, eligible lifecycle state, no blocking flags, an active organization, no competing reservation and matching chain custody. Reject COUNTERFEIT and REVOKED identities. SUSPICIOUS is a computed verification outcome, not an automatic ownership mutation.

#### Business state versus chain state

Keep transfers.transfer_status as INITIATED, ACCEPTED, REJECTED, EXPIRED or CANCELLED. chain_status records whether the corresponding operation has committed to the blockchain. ACCEPTED is written only after confirmed acceptance. While acceptance is submitted, display "Acceptance pending" using operation state and retain the reservation.

A timed-out RPC request is not a failed transaction. FAILED means a definitive rejection/revert or a locally rejected pre-submission operation. An unknown result remains SUBMITTED or RECONCILIATION_REQUIRED until reconciled.

#### Package binding

At most one sealed ACTIVE package belongs to a laptop. The active association binds product_uid, manufacturer serial, package_uid, box serial, seal ID and package version. A package replacement creates a new record and retires the old one; never overwrite its historical seal identifier.

An opening retires the sealed-box claim without deleting the box record. Ordinary resale as factory-sealed is prohibited. Returning or repackaging an opened laptop requires visible disclosure and an investigator-approved workflow, not a reset of its original registration.

## 5 Registration and physical identity

#### Registration sequence

1. Authenticate the manufacturer and validate its ownership of the batch. Enforce batch/product brand, model and manufacturer agreement. Validate dates without treating warranty as proof of origin.

2. Allocate an opaque product_uid independent of SQLite integer IDs, a random 128-bit-or-stronger QR token, a distinct package_uid and box identifier. Normalize serials conservatively; preserve raw observed values for evidence.

3. Register the OEM serial, expected box serial and seal ID. Require nonempty seals for newly registered sealed units. Record who applied the seal, when, and its package version.

4. Create a canonical registration payload and evidence digest. Persist the pending operation and product staging record in one short transaction. Do not yet expose confirmed inventory.

5. Submit a manufacturer-authorized registration operation. The contract rejects duplicate product IDs and establishes the initial custodian and initial event head.

6. On confirmed receipt, activate custody and metadata projections. Generate printable box QR labels only for confirmed products, with a clear pending state before that point.

#### Sealed receipt policy

At manufacturer packing, verify the actual laptop's chassis serial and, when feasible, manually observed firmware serial before sealing. Record the inspection method. This establishes an initial association, not immutable hardware proof.

At normal sealed handovers, scan the box QR, box ID and seal ID, inspect whether the seal is intact, and compare the external serial label if present. Report laptop_internal_serial_check=NOT_CHECKED. Do not instruct receivers to break every seal merely to satisfy an internal serial requirement.

At final supervised opening, record authorization and the intact/broken state before opening, mark the package OPENED, then compare the laptop chassis serial against the registered serial. An operator may also record a BIOS/service-tag observation. Distinguish typed, camera-read and hardware-reported evidence; none is automatically an OEM attestation.

#### Failed physical check

A wrong box, seal, serial or missing inspection blocks acceptance or sale. Store the unsuccessful observation, create the appropriate alert and show the exact mismatches. Keep legal custody unchanged until a valid transfer commits. Physical possession of a rejected shipment is recorded separately from accepted custody.

## 6 Receipt opening sale and replacement

#### Receipt evidence contract

Each received item includes product_uid, observed_box_serial, observed_seal_id, seal_condition, inspection_mode, observed_laptop_serial if available, inspector identity and server receipt time. It also carries inspection IDs, observation payload digests and evidence-file hashes. The server derives user, organization and authorized device from authentication.

A SEALED mode requires box and seal match with condition INTACT; internal serial may be NOT_CHECKED. An OPENED mode requires authorized opening plus a laptop serial match. UNKNOWN seal condition is not acceptable for sealed handover. Unexpected broken seals do not become acceptable by selecting OPENED after the fact.

#### Sale workflow

Only the confirmed retailer custodian may sell an eligible laptop. Validate no active transfer, no restrictions and a successful sale inspection. Record whether the sale is SEALED_UNOPENED or OPENED_AND_MATCHED. A sealed sale may proceed under this declared policy, but the UI must state the laptop serial was not inspected directly.

Create a signed PRODUCT_SOLD event and confirm it on-chain before changing lifecycle_state to SOLD and retail inventory to SOLD. Retain the retailer as the last commercial custodian; do not put customer identity or addresses on-chain. Generate an opaque sale reference. Warranty dates follow the chosen demo policy and are not represented as an OEM warranty confirmation.

#### Post-sale scans and returns

An ordinary buyer checking a sold laptop is normal. Do not turn SCAN_AFTER_SOLD into a hard alert. Flag a sold laptop only when someone attempts another supply-chain handover, re-registration or incompatible resale, or independent observations show an actual identity conflict.

A returned laptop enters RETURN_REVIEW and cannot be sold as new. The core demo records the return and hold; automated reverse custody is out of scope. Retailers cannot erase prior sale or opening history.

#### Package replacement

Require a current-custodian request, documented reason, old and new box/seal IDs and regulator approval. Block replacement during a transfer. Record PACKAGE_REPLACED and old/new binding digests on-chain. Retain all old package and inspection rows. A broken-seal incident remains in history even if an approved replacement is later applied.

Evidence images are optional for the demo; if provided, hash original bytes, enforce type and size limits and serve only through authorized download routes.

## 7 Two party transfer protocol

#### Initiation

The sender selects 1-20 distinct products and a named recipient. Inside BEGIN IMMEDIATE, validate confirmed chain projection, legal role edge, warehouse ownership, restrictions and absence of reservations. Create a random transfer_uid and sorted immutable manifest. Reserve every product using a table whose product_id is unique. Bind current package version and expected box/seal identifiers in each manifest item.

The signed request covers transfer_uid, sender, recipient, sorted product UIDs, manifest_digest, source/destination warehouse IDs, created_at, expires_at, operation nonce and chain deployment domain. Default expiry is 24 hours, configurable in the versioned policy. Store intent before the chain call. INITIATED is usable by the recipient only after its chain operation confirms.

#### Receipt and acceptance

The named recipient records observations for every item. Compare both sets and duplicate counts; do not convert a list to a set before checking duplicates. Reject missing, extra, duplicate or physically mismatched items with HANDOVER_MISMATCH and structured missing/unexpected/mismatched lists. No subset moves in this version.

The recipient signs Acceptance containing transfer_uid, request_digest, receipt_digest, decision, acceptance operation UID and deadline. The receipt digest commits to immutable inspection records and evidence hashes. Verify both organization signatures and recheck expiry, role, restrictions, package versions, reservations and current chain custodian immediately before submission.

Reserve/transition under a short transaction and use a conditional state update so only one acceptance operation is created. Do not hold SQLite locks while waiting for RPC. The contract atomically moves the whole manifest and appends one event commitment per product. Only then update custody, warehouse, owner mirror, retail projection, operation and audit rows in one DB transaction.

#### Rejection cancellation expiry

Only the recipient rejects and only the sender cancels; neither can act after acceptance. On-chain terminalization releases all reservations. After expiry anyone may request an expire operation, but the contract checks its timestamp. The API also checks expiry on every access. A worker finalizes expired transfers so stale reservations do not last indefinitely.

A mismatch can be corrected with new receipt observations if the signed manifest is unchanged and the transfer is still eligible. To ship a subset, cancel the original and create a new signed transfer. Once acceptance is pending, block other terminal actions until its chain result is known.

## 8 Canonical events and signatures

#### Event format version 1

Every finalized product event has event_uid, product_uid, operation_uid, event_type, seq, previous_hash, occurred_at, actor_user_id, signer_key_id, organization_uid, payload and schema_version. Registration uses seq=0 and a 32-byte zero previous hash. Later events increment seq by one per product.

Canonical JSON uses UTF-8, sorted keys, compact separators, explicit nulls and ASCII protocol enums. Use integer epoch milliseconds and integer scaled coordinates rather than JSON floating-point measurements. Sort manifest arrays by product_uid; preserve order for arrays whose order has meaning. Reject duplicate keys, NaN and unsupported fields. Store the exact canonical bytes, not just a reconstructed dictionary.

Compute event_hash = SHA256(canonical_event_bytes). Exclude digital_signature, event_hash, transaction hash, block metadata and operation processing status from those bytes. A SHA-256 commitment is distinct from EIP-712's internal Keccak hashing.

#### Typed signatures

Use EIP-712 with name TraceTrust, version 1, chainId, verifyingContract and deployment salt. EventCommitment signs product UID, sequence, previous hash, event hash and operation UID. TransferRequest and TransferAcceptance have separate typed schemas and bind the request/receipt digests. Freeze, recall and sale use action-specific typed payloads.

EIP-712 does not supply replay protection itself [R1]. Enforce unique operation IDs, used transfer IDs, deadlines, per-product sequence and deployment-domain checks. The contract independently recovers signers and checks current authorization. Publish fixed Python/Solidity test vectors for every message type before parallel implementation diverges.

#### Key model and verification

The demo stores organization keys in a backend-only keystore and device keys in the simulator. Log the initiating user separately; an organization signature does not prove that individual controlled the key. Store public key/address, key version and validity interval in key history. Never serialize private keys into the database or frontend.

Verification rebuilds canonical bytes, recomputes hashes, validates signature and historical authorization, checks every link, compares chain commitments and confirms the terminal head and custody. Checking only existing rows misses a deleted tail; compare sequence counts and terminal heads too. Failed intents are operation records, not finalized product events.

## 9 Blockchain and recovery protocol

#### Contract interface and invariants

Register organization roles and active status under a restricted governance account. Product state stores custodian, lifecycle, blocking flags, current package-binding digest, last sequence and event head. Maintain operationUID consumption, transfer manifests and active transfer reservations.

registerProduct commits initial identity and event. initiateTransfer validates the full list and legal edge. acceptTransfer verifies both typed signatures, exact request and receipt digests, expiry and product state; it moves all products in one transaction. cancelTransfer, rejectTransfer and expireTransfer release reservations. recordOpening, recordSale, replacePackage, setHold, setRecall, setStolen, revokeIdentity and setOrganizationStatus enforce action-specific roles. Recall and identity revocation cannot be silently reversed.

There is no unrestricted anchor function. Every trust-critical action checks expected previous head, sequence and signer, updates business state and anchors its corresponding event in the same transaction. The contract accepts cryptographic commitments to off-chain detail; it cannot inspect photographs or prove that a seal was physically intact.

#### Durable write sequence

1. In a short DB transaction, validate and persist immutable intent, signed payload, expected heads, idempotency key and reservations. Commit PENDING before any broadcast.

2. The worker takes a lease, serializes nonces for the sending account, signs a chain transaction and persists its raw transaction and deterministic hash before broadcasting. Broadcast outside the database transaction.

3. Track SUBMITTED. Poll receipt and validate contract address, success status, operation UID, emitted product commitments and block hash. A successful RPC call alone is insufficient.

4. In one DB transaction, insert finalized events, update projections, mark CONFIRMED and release applicable reservations. An idempotent projector can repeat this step safely.

#### Crash and failure recovery

Crash before broadcast: submit the stored transaction. Crash after broadcast: look up its hash and contract operation UID before retrying; rebroadcast identical bytes when appropriate. Chain success with DB failure: replay the confirmed operation into the database. Explicit revert: record FAILED, preserve evidence and release only reservations proven safe to release. Unknown status: keep pending and block conflicting writes.

Store chain_id, contract_address, deployment_id, tx_hash, block_number and block_hash. A local Hardhat reset invalidates the previous deployment; show UNVERIFIABLE until intentionally reseeded. For a nonlocal chain use a configurable confirmation depth and reorg reconciliation. Never describe the local node as independently decentralized production infrastructure. Serialize all product event appends, including initiation, opening and holds, against expected event heads; refresh and re-sign a rejected stale-head intent only after revalidating its business conditions.

## 10 Scan ingestion and trust levels

#### Intake and validation

POST /scans accepts staff and device observations; public verification is a separate low-trust route. Validate token length, payload limits, method, identifiers, coordinate ranges and timestamps before persistence. Unknown tokens produce UNKNOWN without inventing a product or a counterfeit verdict. Store a token hash in abuse logs to avoid unnecessarily reproducing QR tokens.

A signed device message contains device_id, key_id, request_uid, monotonic counter, occurred_at, observation fields, nonce and domain. Verify the device is registered and active. Resolve its organization and fixed location from server-controlled configuration; reject a client attempt to override them. Registration ties a device to a location administratively, not physically.

#### Dedupe and event time

Use UNIQUE(device_id, key_id, request_uid) and a canonical payload digest as primary dedupe. A request ID reused with different content is rejected. Keep a signature hash as supplementary evidence, not the only dedupe key. Duplicates return the original result and do not create more rules or incidents.

Store both occurred_at and received_at. Demo policy: reject future timestamps beyond five minutes; accept late device events within 24 hours for automatic recomputation; retain older valid events as LATE_REVIEW without silently changing closed decisions. For public scans use server receive time and treat client time as untrusted. These are explicit prototype defaults, not industry standards.

Order device evidence by occurred_at then stable observation UID. Recompute the predecessor and successor comparisons when a late scan is inserted. Derive custodian-mismatch against the custody interval at observation time, not the latest custodian. If timestamp reliability is disputed, downgrade location rules.

#### Trust weights and response

Initial scoring weights: registered device observation 0.8; authenticated witnessed staff inspection 0.7; ordinary app observation 0.4; anonymous observation 0.1; invalid signature 0 for physical claims. Store separate trust values for identity, location and inspection. Simulation is an independent flag and always visible.

Return record_integrity, physical_checks, restriction_flags, final_status, reasons and operation/anchor freshness. Chain unavailable or registration pending yields PENDING/UNVERIFIABLE rather than a clean VALID result. Use the existing scan status enum: VALID for completed clean checks, SUSPICIOUS for evidence needing review, INVALID for failed digital checks, UNKNOWN for unknown identity and PENDING for incomplete checks. Return UNVERIFIABLE as a record_integrity reason under PENDING. Display the independent human verdict separately. INVALID does not mean the physical laptop is counterfeit.

## 11 Deterministic rules

| Rule | Trigger and guard |
| --- | --- |
| SERIAL_MISMATCH | Observed laptop serial differs from registered identity during an applicable inspection; retain raw values privately |
| BOX_PRODUCT_MISMATCH | Received box belongs to another product or does not match the manifest's package version |
| SEAL_ID_MISMATCH | Observed seal differs from the expected current seal |
| BROKEN_SEAL | Broken or missing seal outside an authorized opening/replacement workflow |
| HANDOVER_MISMATCH | Missing, extra, duplicate or noncompliant receipt items; block acceptance |
| IMPOSSIBLE_TRAVEL | Two sufficiently trusted locations exceed configured plausible speed after uncertainty bounds |
| DUPLICATE_BURST | Multiple independent device observations of one token within a configured window; dedupe and cap correlated contributions |
| CUSTODIAN_MISMATCH | Observing organization conflicts with event-time custody and has no incoming shipment or logistics delegation |
| CHAIN_INVALID | Hash, signature, sequence or historical authorization fails |
| ANCHOR_MISMATCH | Confirmed DB commitment differs from the correct deployment's chain commitment |
| RESTRICTED_ACTION | Attempted transfer/sale violates hold, recall, theft, revocation or verdict restrictions |
| SOLD_REENTRY | Attempt to re-enter ordinary supply-chain flow after sale without approved return workflow |

#### Rule policy

Example defaults: duplicate window 10 minutes with three distinct registered devices; movement threshold 900 km/h with configurable location/time uncertainty. These are demo heuristics to test, not validated guarantees. For same-time distant trusted scans, report a simultaneous-location conflict instead of division by zero. Nearby scans with small timestamp differences should not produce huge speed artifacts.

Anonymous coordinates may create a low-confidence report but never a hard impossible-travel claim. Repeated scans by one scanner are not independent witnesses. An invalid device signature is security evidence, but its claimed location must not support a cloned-QR travel hypothesis.

Every alert includes rule_version, stable evidence IDs, observed time, severity, trust, support/contradiction data and status. Its deterministic fingerprint hashes the rule version and sorted evidence IDs. Unique fingerprints make repeated evaluation idempotent. Preserve superseded revisions when corrected evidence changes an alert; do not silently delete the history.

No medicine expiry or COLD_CHAIN_BREACH rule remains. Optional shipping shock, moisture or extreme-temperature observations can be added only with a real sensor policy and laptop-specific limits; they are not needed for this build.

## 12 Alert clustering and probable causes

#### Clustering algorithm

Replace IsolationForest training, feature files and score endpoints with fusion.py. First normalize deduplicated eligible alerts. Partition primarily by product and a configurable 24-hour event-time horizon. Link alerts for the same product, or across products in the same transfer with a shared relevant failure. Shared batch/device/org alone is insufficient to merge all alerts in a warehouse.

For cross-product links require a second relationship, such as the same shipment plus box/seal mismatch, within the horizon. Build edges in a stable sorted order and compute connected components. Cap component span at 24 hours and size at 100 alerts in the prototype; split oversized groups by sorted (event_time, alert_fingerprint), starting a new group when adding an alert would exceed either bound, and expose overflow. Recompute this partition over the complete eligible window when late evidence arrives. This prevents transitive chains from creating a permanent warehouse-wide incident.

Persist component membership and a fingerprint based on sorted alert fingerprints, fusion version and episode boundaries. Repeated runs over the same evidence produce the same active components and scores. Late evidence may change membership and fingerprints; use incident revisions and aliases for merges/splits, retaining earlier references and investigator decisions.

#### Cause vocabulary and evidence weights

| Hypothesis | Positive support weights summing to one |
| --- | --- |
| CLONED_QR | Trusted movement conflict .50; independent duplicate burst .30; concurrent incompatible receipt observations .20 |
| DEVICE_OR_PACKAGE_SUBSTITUTION | Laptop serial mismatch .45; box mismatch .25; unexpected seal failure .20; seal ID mismatch .10 |
| DIVERSION_OR_GRAY_MARKET | Event-time custody mismatch .45; handover mismatch .35; prohibited route/sold reentry .20 |
| RECORD_TAMPERING | Confirmed anchor mismatch .60; invalid signature/hash/sequence .40 |

For each evidence class f, take its strongest independent supported value: x_f = max(trust_f * strength_f), with both factors in [0,1]. Repeated copies do not accumulate. For cause c, S_c = clamp(sum(w_cf * x_f) - sum(v_cj * contradiction_j), 0, 1). Version all weights. A documented authorized opening removes that opening's broken-seal contribution; an independently validated correction can subtract .25 from the relevant hypothesis. Missing checks contribute no support and are not contradictions.

Display top two hypotheses and supporting/contradicting evidence. If maximum S is below .35, show INSUFFICIENT_EVIDENCE. If the top-two gap is below .10, show AMBIGUOUS. Several causes may coexist; scores need not sum to one. These are heuristic support/confidence scores, not calibrated probabilities or a trained ML classifier. For compatibility set risk_score=100*max(S_c), labeled evidence support; restrictions and severity remain separate. Deterministic verified cryptographic failures have trust 1, independent of scanner trust.

## 13 Fusion explanations and incident governance

#### Worked scoring example

A laptop appears at two registered fixed scanners with a verified movement conflict and an independent duplicate burst. Both evidence classes have trust .8 and strength 1. CLONED_QR support is (.50 x .8) + (.30 x .8) = .64. No third evidence class is present. Display "Cloned QR: 64/100 heuristic support" with the runner-up and missing evidence, rather than an invented 82% probability.

If the same claims are anonymous, their weights are at most .1 and they cannot produce a hard trusted-location alert. A high-volume public scan campaign must not push a product into a frozen or counterfeit state.

#### Explanation response

GET /incidents/{id}/explanation returns incident_id, revision, fusion_version, config_hash, evaluated_at, evidence_cutoff, component_fingerprint, hypotheses, uncertainty, missing_checks, nodes and edges. Each hypothesis contains cause, support_score, supporting_alert_ids, contradicting_evidence_ids and short human-readable reasons.

Graph nodes have stable IDs and types PRODUCT, PACKAGE, OBSERVATION, INSPECTION, ALERT, DEVICE, ORGANIZATION, TRANSFER and HYPOTHESIS. Edges use OBSERVED_AT, BELONGS_TO, GENERATED, SUPPORTS and CONTRADICTS and include source references and trust. Limit UI graph size with expandable evidence groups. Public responses do not expose private organization/device relationships.

#### Human workflow

Fusion creates an auto-created OPEN candidate, not a confirmed accusation. Investigator review moves it to UNDER_REVIEW. A documented decision may CONFIRM the incident, DISMISS it or CLOSE it after resolution. A confirmed incident is not automatically a counterfeit finding: the investigator explicitly chooses a verdict and cites evidence.

A hold request is a signed chain action. Counterfeit confirmation also applies a blocking flag so transfer cannot proceed. Unfreezing removes only the hold; it does not clear recall, theft or counterfeit restrictions. Audit every decision, reason, actor and superseded revision.

#### Late and disappearing signals

Recompute evidence without overwriting human notes or decisions. A new material signal attached to a closed incident creates a linked review revision or new candidate. Silence of a device is data-coverage uncertainty, not exonerating evidence. If optional freshness decay is added, display it separately from evidence support and never remove a confirmed incident because a scanner stopped reporting.

The AI/ML convergence is explainable correlation and inference. If an official requirement separately mandates trained learning, this deterministic module alone does not meet that requirement; a supervised model would require labeled data and evaluation.

## 14 API and frontend contract

| Endpoint | Authorization and behavior |
| --- | --- |
| POST /auth/login | Issue short-lived bearer token after real password verification; generic failure |
| POST /batches | Manufacturer; validates catalog and organization consistency |
| POST /products | Manufacturer; register laptop/package binding; returns 202 operation reference |
| GET /operations/{uid} | Related participant or investigator; pending, confirmed or reasoned failure |
| POST /transfers | Confirmed custodian; immutable manifest; idempotency key required |
| POST /transfers/{uid}/receipts | Named recipient; creates immutable per-item inspection records |
| POST /transfers/{uid}/accept | Recipient; signs complete receipt; 202 pending confirmation |
| POST /transfers/{uid}/reject or /cancel | Recipient or sender respectively; chain-confirmed terminal action |
| POST /scans | Authenticated staff/device; idempotent intake and deterministic analysis |
| POST /public/verify | Anonymous, rate-limited; reduced record and physical-check status |
| GET /products/{uid}/provenance | Resource-authorized history, signature/anchor checks and custody |
| POST /products/{uid}/open or /sell | Current retailer; applicable inspection and signed operation |
| POST /products/{uid}/package-replacements | Custodian request plus regulator approval |
| GET /alerts and /incidents | Authorized filtered lists, pagination and bounded queries |
| GET /incidents/{id}/explanation | Authorized graph, hypotheses, revisions and reasons |
| POST /incidents/{id}/resolve | Regulator; explicit evidence-backed disposition |
| POST /products/{uid}/hold or /unhold or /recall | Regulator; durable chain operation |

#### Response contract

State-changing operations return operation_uid, chain_status and status_url. A confirmed retry returns the same operation result. Reusing an idempotency key with different content returns 409. Use 401 for unauthenticated, 403 for forbidden, 404 where appropriate, 409 for conflicts, 422 for validation, 413 for size limits, 429 for rate limits and 503 for unavailable dependencies. Responses include request_id and reason codes, never stack traces.

#### User journey

Manufacturer registers and prints labels. Distributor opens incoming transfer, scans each box/seal and accepts. Retailer repeats receipt, performs optional supervised opening and sells. Investigator sees grouped incidents, top causes, uncertainty and evidence, then chooses hold or disposition. Every screen distinguishes pending versus confirmed chain state.

The verifier shows model, masked serial, digital integrity, inspection coverage and restrictions. The control tower combines provenance, a map and incident cards. Use a static map fallback when tiles fail. Demo controls require a local-only demo flag and administrator authorization; they are disabled in any public deployment.

## 15 Audit of the supplied database

#### Actual checks performed

The attached SQLite database contains 18 application tables, 4 organizations, 5 users, 4 batches, 8 products, 8 packages, 8 seal inspections, 9 scans, 2 transfers, 3 transfer items, 4 event rows, 5 alerts and 2 incidents. SQLite's internal sqlite_sequence table is excluded from the application-table count.

PRAGMA integrity_check returned ok. PRAGMA foreign_key_check returned no violations. Current owner/warehouse mirrors agree with custody for all eight products. Custody warehouse organizations match their custodians. Product brand/model/manufacturer values match their batches. The partial unique index for one ACTIVE package per product is already present.

| Finding | Impact and required correction |
| --- | --- |
| All 5 password_hash values are placeholders | Login cannot use these as real password hashes; seed actual hashes and require demo secret configuration |
| Both ACCEPTED transfers lack sender/recipient signatures and transaction hashes | They cannot substantiate signed blockchain handovers |
| All 4 event hashes are DEMO-HASH strings; signatures are null | Cryptographic integrity is unverified; never mark these histories VALID |
| Products 3 through 8 have no PRODUCT_REGISTERED event | Six products lack a registration genesis; product 3 begins with a transfer event |
| All 3 accepted item movements precede products.registered_at | Fixture chronology is inconsistent; rebuild scenarios coherently |
| Retailer custody holds products 3, 7 and 8, but inventory has only product 3 | Two products are omitted from retail inventory; use a custody-derived view |
| No triggers are defined | Append-only event protection described in the prior architecture is absent |
| No device/key registry or chain metadata tables | Device identity, key history and reconciliation cannot be implemented from current columns alone |

#### Verdict

Keep the domain structure and identifiers as a migration input. Treat the existing rows as UI/scenario fixtures, not verified provenance. The current schema is a good start for laptops, but the database is not a final operational backend and does not prove signatures or chain integration.

A structural integrity pass only establishes that SQLite can read its structures and declared foreign keys are consistent. It does not establish business chronology, authenticity, password validity or event-chain correctness. The attachment itself is preserved; this revision specifies changes and an implementation plan rather than silently rewriting demo history.

## 16 Target schema additions

#### Existing tables to extend or rebuild

| Table | Required target fields or constraints |
| --- | --- |
| organizations | organization_uid UNIQUE, chain address/key reference, provisioning state; role and active status mirrored on-chain |
| products | product_uid UNIQUE, lifecycle_state, hold_active, recall_active, stolen_active, identity_revoked, authenticity_verdict, registration operation; owner fields become projections |
| packages | package_uid UNIQUE, binding_version, predecessor_package_id, binding_digest; add OPENED to status; nonempty seal for newly sealed registrations |
| seal_inspections | inspection_uid, mode, observed_box_serial, observed_laptop_serial, occurred_at/received_at, signature/digest, trust, device/key reference and evidence references |
| authentication_checks | Link inspection/observation; separate result from is_simulated; retain NOT_CHECKED and UNAVAILABLE |
| transfers | transfer_uid UNIQUE, expires_at, request_digest, manifest_digest, receipt_digest, chain_status, operation_uid, deployment reference; complete signature payload references |
| transfer_items | Expected package/version, expected box/seal, validated receipt inspection ID and item outcome; prevent duplicate products |
| scan_history | observation_uid, occurred_at, received_at, source/trust, device_key_id, signed payload, payload_digest, signature_hash, is_simulated, rule_version, lateness state |
| event_ledger | event_uid, product_uid, seq, canonical_payload, signer_key_id, operation_uid, schema_version; UNIQUE(product_id,seq); immutable finalized contents |
| verification_alerts | rule_code with extensible registry, fingerprint UNIQUE, rule_version, trust, event time, evidence JSON and revision/supersession link |
| incidents | auto_created, probable_cause, support_score, hypotheses_json, component_fingerprint, fusion_version, revision and uncertainty; preserve human lifecycle |

#### New supporting tables

keys holds organization/device public addresses with validity intervals. devices binds an active device to an organization and registered location. chain_deployments identifies chain ID, contract, deployment salt and start block. operations stores immutable signed intents, idempotency keys, request hashes, status and retry diagnostics. chain_submissions stores raw signed transactions and receipt metadata. product_reservations has product_id as primary key and a transfer/operation reference.

incident_alerts links many alerts to an incident revision. incident_products supports multi-product clusters. incident_revisions retains graph and hypothesis snapshots plus merge/split aliases. evidence_objects stores file digests, type, size, uploader and private location. logistics_assignments authorizes shipment observation. schema_migrations records applied schema versions and checksums.

Keep audit_log append-only at application and trigger level. Move blockchain processing metadata to operation/anchor tables so finalized event contents never need updates. Use foreign keys, explicit NOT NULLs and indexes on product/event time, operation status, alert fingerprint and incident membership. Section 17 defines the migration order.

## 17 Migration and data initialization

#### Preserve before changing

Create a SQLite backup and record its SHA-256 digest. Run migration against a separate staging copy first. Record counts and IDs from the input. Never assign real-looking signatures to old DEMO-HASH records or backdate newly generated attestations to make them appear contemporaneous.

Archive legacy demo histories in a clearly labeled import snapshot. For the working demo, regenerate coherent scenarios through the new API and contract from registration onward. A catalog import may retain model names and demonstration serials, but generate random QR tokens and explicitly state it is a new demo deployment.

#### Ordered migration

1. Add schema_migrations and new reference/operation tables. Add nullable new identity fields, populate stable UIDs and create uniqueness indexes only after validating duplicates.

2. Rebuild tables whose CHECK constraints change, including package status and alert codes. Use an explicit create-copy-validate-swap migration with a recoverable backup, not blanket DROP TABLE commands.

3. Map legacy product states into lifecycle, flags and verdict: ACTIVE to IN_SUPPLY_CHAIN; QUARANTINED to hold; RECALLED to recall; REVOKED to identity_revoked; SOLD to SOLD; STOLEN to stolen; COUNTERFEIT to verdict plus hold. Preserve the original status in import metadata. Never infer a human decision that was not recorded.

4. Validate manufacturer role, batch consistency, warehouse ownership and legal transfer graph. Enforce these with service checks and targeted constraints/triggers where practical.

5. Replace retail inventory as an authority with a view over confirmed custody joined to retailer organizations and product lifecycle/restrictions. Keep sale metadata in a sale record; preserve the old table as archived fixture data if needed.

6. Add immutable event and audit triggers after the legacy archive and new schema are in place. Triggers block ordinary updates/deletes; they do not stop an attacker who can replace the database file.

7. Seed real password hashes and dedicated demo keys, deploy the contract, register organizations/devices and create signed product histories through actual services.

8. Recheck integrity, foreign keys, chronology, per-product genesis/sequence, signatures, anchor equality, custody, package uniqueness and inventory coverage. Commit the schema version only when the migration succeeds.

#### Connection and rollback discipline

Enable foreign_keys on every connection before transactions; changing that PRAGMA during a transaction does not enable it [R3]. Any controlled table-rebuild procedure must restore enforcement and run foreign_key_check before release. Keep chain calls out of migrations. If migration fails, use the untouched backup; if seeding a new chain fails, resume operation recovery or reset the explicitly disposable demo deployment as a coordinated pair.

## 18 Security and operational controls

#### Authentication and authorization

Use established password-hashing libraries, short-lived JWTs, fixed allowed algorithms and checks for issuer, audience and expiry. Resolve role/resource access at every endpoint. Serve through HTTPS when accessed beyond localhost. OWASP's REST guidance supports endpoint-level authorization, strict token validation and protected transport [R2].

For the browser demo, keep bearer credentials in memory and require login after reload. Explicitly configure CORS origins. If authentication later moves into automatically attached cookies, add the corresponding CSRF defenses; the mere use of JWT does not remove CSRF risk. Sanitize rendered notes and avoid unsafe HTML in graph explanations.

#### Abuse resistance

Apply separate limits to login, public verification, staff scans, device scans and state-changing operations. Example public baseline: 30 requests/minute/IP with token-level limits and short bursts; tune behind the real proxy. IP alone is not a reliable identity. Public scan floods create abuse telemetry, not high-confidence physical evidence or automatic restriction.

Cap request bodies, manifest sizes, graph sizes, pagination and date ranges. Reject unknown fields. Require idempotency for mutable operations. Prevent insecure direct object access by checking every requested product, transfer, incident and evidence file against the actor's organization and role.

#### Storage and observability

Store secrets outside Git and outside the frontend. Redact passwords, JWTs, private keys, raw QR tokens and sensitive images from logs. Use structured request/operation IDs. Collect pending-operation age, reconciliation failures, invalid signatures, scan rejection rate, fusion revision counts and rule timings.

Back up database, evidence files and chain deployment information together. Validate restoration into a separate environment and compare contract deployment/head values before enabling writes. A changed chain deployment must not silently reuse old confirmation metadata.

#### Availability and trust boundary

If chain access fails, allow clearly labeled historical reads but block final custody/sale confirmation. Show last verified time and stale state. A single local node and one machine are an availability and trust limitation. Custodial keys mean a compromised backend can authorize fraudulent new actions; anchoring detects inconsistent later edits only while the chain and verification reference remain trustworthy.

Production work includes independent key custody, real governance, tested revocation/rotation, managed evidence storage, multi-node chain policy, centralized monitoring and an external security review. No claim of complete security follows from this specification.

## 19 Acceptance and evaluation plan

| Test | Required result |
| --- | --- |
| Wrong manufacturer, custodian or recipient | API and direct contract invocation both reject |
| Illegal role edge or warehouse ownership | Reject without custody mutation |
| Duplicate/concurrent acceptance | Exactly one confirmed operation; repeat returns original or 409 |
| Missing/extra/duplicate receipt item | Block whole manifest; retain mismatch evidence |
| Wrong box/seal/laptop serial | Block applicable receipt or sale; explain actual failed check |
| Sealed receipt with no internal serial | Allowed only in SEALED mode; internal check remains NOT_CHECKED |
| Normal scan after sale | Informational; no counterfeit or hard sold-scan anomaly |
| Hold/recall during pending transfer | Contract serialization determines winner; no transfer after a preceding blocking state |
| Crash before broadcast or after chain success | Resume from durable intent; converge to one confirmed projection |
| RPC timeout and duplicate broadcast | Never assume failure or move custody twice |
| DB edit, deletion or consistent hash rewrite | Detect digest/head mismatch; display correct failing layer |
| Chain reset or unavailable RPC | UNVERIFIABLE/PENDING; no fabricated confirmation |
| Invalid device signature or replay | Reject physical claim; no duplicate evidence contribution |
| Public flood with copied QR | No automatic freeze/counterfeit; low-trust evidence remains capped |
| Shuffled and duplicate observations | Same final active clusters/scores for same evidence within lateness policy |
| Late evidence changing component membership | New revision with aliases; preserve human decisions |
| Product IDs 7 and 8 in fixture retail custody | Both included in custody-derived inventory |

#### Analytics evaluation

Create labeled synthetic scenarios for normal movement, cloned identity, substitution, diversion, record tampering and benign ambiguity. Separate policy tuning fixtures from held-out scenarios; vary cities, timing, noise, missing observations, device counts and mixed causes. Test cases from the same generated sequence must not appear on both sides of the split.

Measure rule precision/recall, false-positive rate on normal/anonymous traffic, pairwise cluster precision/recall, top-one/top-two cause accuracy, insufficient-evidence rate and explanation evidence completeness. Report per-cause results and dataset sizes. Do not invent performance numbers or describe synthetic results as real-world validation.

Retain a versioned feature vocabulary and config file containing every weight, strength mapping, threshold and contradiction rule. Support scores are uncalibrated. Probability calibration metrics are applicable only after a genuinely probabilistic model and labeled calibration set exist. Track p95 latency and pending-operation recovery time on the actual demo machine, with workload and hardware noted.

## 20 Build order and demonstration

#### Four track implementation plan

The original 12-hour target is aggressive. Protect the confirmed end-to-end path first; extra UI and physical evidence storage follow only after its tests pass. This is a suggested team work allocation, not an assumption that all features will finish within the time box.

| Window | Backend and data | Contract and recovery | Frontend | Rules and fusion |
| --- | --- | --- | --- | --- |
| Hours 0-2 | Schema, auth, IDs, canonical bytes | Contract interfaces, domains, test vectors | Routes, API types, pending states | Fixtures, observation schema, trust policy |
| Hours 2-5 | Registration, receipts, reservations | Register/initiate/accept, durable intents | Registration and transfer screens | Core laptop rules, event-time dedupe |
| Hours 5-7 | Sale, projections, restrictions | Recovery and direct contract tests | Verifier and provenance | Clusters, scores, explanation endpoint |
| Hours 7-9 | Investigator workflow | Crash/replay/anchor checks | Incident evidence cards | Shuffled and held-out scenarios |
| Hours 9-12 | Integrated fixes and data reset | Demo rehearsal and backups | Usability and failure states | Evaluate and rehearse explanations |

#### Feature cuts when time runs short

Cut interactive graph rendering before the explanation API; show an evidence list. Cut map tiles, camera scanning, photographs and automated package replacement. Keep manual box/seal entry. Do not cut transaction recovery, role validation, signature verification, transfer reservations or truthful pending states. Returns may remain review-only. Do not describe cut features as implemented.

#### Local startup order

Install from locked dependency files. Configure environment with DB path, JWT secret, RPC URL, deployment identity and demo-only key references. Start the local chain, deploy and register roles, apply migrations, seed through service operations, start recovery worker, API, then Vite frontend. Health endpoints should separately report database, chain/deployment and worker readiness. Keep RPC bound to localhost.

#### Seven minute demo

Minute 0-1: explain the laptop/box/seal identity and physical-truth boundary. Minute 1-2: register one laptop and show its confirmed signature and commitment. Minute 2-3: transfer manufacturer to distributor with matched receipt. Minute 3-4: show a substituted serial or cloned QR producing a grouped incident. Minute 4-5: replay observations shuffled with duplicates and show identical final inference. Minute 5-6: tamper with a disposable DB copy and show anchor/custody disagreement. Minute 6-7: investigator holds the laptop, blocked transfer is demonstrated, and pending-operation recovery is shown.

## 21 Completion criteria and references

#### Definition of ready to build

The team has agreed on exact canonical bytes, typed signing schemas, API payloads, enums, transfer all-or-nothing policy, chain/DB ownership and physical inspection modes. UI text distinguishes digital integrity, physical checks and restrictions. The database has a versioned migration and coherent API-generated fixtures.

#### Definition of a working prototype

A new product can be registered, handed over twice, inspected and sold with actual valid signatures and confirmed local-chain commitments. Incorrect physical evidence blocks the relevant action. A clone/substitution scenario produces an explainable, versioned incident candidate. An investigator can hold the product, and the contract rejects further transfer. A deliberate database change fails verification. A crash after chain success recovers without duplicate custody movement.

Every demonstrated check has a repeatable test and a visible explanation. The interface does not present simulator data, unverified legacy rows or heuristic support scores as real-world proof. An automated candidate never independently labels a laptop counterfeit.

#### Revision summary

Medicine entities and conditions are replaced by laptop identity, box/seal binding, controlled opening and sale. IsolationForest is removed. Separate incident alerts become bounded clusters with explicit cause hypotheses and evidence graphs. Transfer signatures now bind receipt evidence, legal recipient edges are enforced, and chain consistency uses durable operations and automatic reconciliation. The supplied database has been reviewed at schema and row level, with specific migration requirements identified.

#### Source material

S1. TraceTrust Revised System Architecture(1).pdf, supplied architecture, 18 pages. Used as the baseline for the revised workflows and scope.

S2. Pasted text.txt, supplied review and change request. Used for laptop conversion, incident fusion and implementation-detail requirements.

S3. laptop_anti_counterfeit.db, supplied SQLite database. Inspected read-only on 12 October 2026. Integrity, foreign keys, table counts, signature/hash placeholders, chronology and custody/inventory checks underpin section 15.

#### Primary technical references

R1. Ethereum EIP-712, Typed structured data hashing and signing. Used for typed signature/domain design and the explicit need for application replay protection. https://eips.ethereum.org/EIPS/eip-712

R2. OWASP REST Security Cheat Sheet. Used for transport, token validation and endpoint authorization guidance. https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html

R3. SQLite Foreign Key Support. Used for connection-level enforcement and transaction/migration behavior. https://www.sqlite.org/foreignkeys.html

Technical references checked on 12 October 2026. Thresholds, trust weights, schema proposals and build windows in this document are explicit prototype design choices, not externally validated performance claims.
