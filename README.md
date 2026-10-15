# TraceTrust: Laptop Anti-Counterfeit Trust Fabric
A miniproject/prototype built specifically under the Problem Statement- "Build a provenance network where products/lots receive identities and every authorized transfer or
scan becomes a verifiable event. Detect duplicate identities, impossible travel and suspicious
handovers".
A provenance prototype that links physical laptops, tamper-evident seals and boxes to a signed, hash-chained, blockchain-anchored record, then flags impossible or inconsistent histories with explainable evidence scores.

> **Scope note:** this is a hackathon prototype. It makes cloning, tampering and bad handovers visible and explainable. It does not prove that a physical laptop is genuine, and the UI never says "genuine".

## The problem

A QR code alone proves nothing: a counterfeiter can copy the identifier of a real laptop. A genuine box can also be opened and its contents swapped. TraceTrust connects physical observations (scans, seal and box checks, location), ownership transfers and trusted records, and detects impossible histories: duplicate identities, impossible travel, mismatched boxes or seals, and suspicious handovers.

## Features

- **Product identity:** each laptop gets a unique product ID, a random 128-bit QR token (only its hash is stored), a box serial and a seal ID.
- **Signed event history:** every registration, transfer, receipt and sale is a canonical-JSON event, hashed with SHA-256, signed with the organization key and linked to the previous event of the same product.
- **Blockchain anchoring:** a Solidity contract enforces roles, custody, legal transfer routes, single-use operation IDs and event heads. The database never becomes the only source of truth.
- **Two-party transfers:** the sender initiates, the named recipient inspects (box ID, seal ID, condition) and accepts. A mismatch returns `422 HANDOVER_MISMATCH` and moves nothing.
- **Sealed sale:** the retailer records a sale of the sealed, unopened product.
- **Public verifier:** anyone can verify a record without signing in. Results are shown as three separate parts: record integrity, physical checks and restriction flags.
- **Evidence-fusion anomaly scoring:** deterministic, explainable scores per suspected cause (see below). No machine-learning model is used.
- **Tamper demo:** edit a copy of the database and watch the verifier detect it at the right layer.
- **IoT simulator:** registered, signed devices at fixed locations produce normal traffic, clones and other scenarios.

## How it works

```
 React web app (Vite)  ──►  FastAPI backend  ──►  SQLite
 verifier, transfers,         auth, events,         records, operations,
 sale, provenance map         fusion engine         alerts, incidents
                                  │
                                  ▼
                        Web3 adapter ──► Solidity contract
                        (submit, confirm,   (Hardhat local node, or the
                         reconcile)          built-in stand-in chain)
```

Every blockchain write follows a crash-safe flow: save the signed event and a PENDING operation, submit the transaction and record its hash, wait for the receipt outside any DB transaction, then confirm and update projections. A timeout never marks an operation FAILED, only a definitive revert does. `reconcile_pending()` runs at API startup. If the chain is unreachable or reset, records show `UNVERIFIABLE`, not "tampered".

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | React, Vite, Leaflet, browser geolocation, QR generation and scanning |
| Backend | Python 3.11+, FastAPI, Uvicorn, Pydantic |
| Auth | scrypt password hashing, short-lived JWT (fixed algorithm, iss/aud/exp), per-request role and organization check |
| Database | SQLite with additive migrations |
| Cryptography | Canonical JSON, SHA-256, secp256k1 signatures via `eth-account` |
| Blockchain | Solidity, Hardhat, `web3.py` |
| Testing | pytest, httpx, Hardhat tests |


## Setup

Requirements: Python 3.11 or newer, and Node.js for the web app.

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS or Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` is the API and test set: FastAPI, Uvicorn, Pydantic, PyJWT, eth-account, hexbytes, web3, python-dotenv, pytest and httpx. Passwords use the standard-library scrypt hasher, so bcrypt is not installed.

### Configuration

Copy `.env.example` to `.env` and set:

| Variable | Purpose |
| --- | --- |
| `JWT_SECRET` | Long random secret for signing tokens |
| Three demo account passwords | Passwords for the manufacturer, distributor and retailer demo users (names in `.env.example`) |
| `SMTP_HOST` and related | Optional mail settings. If `SMTP_HOST` is empty, mail is written to `mail_outbox/`. Gmail needs a 16-letter app password in `SMTP_PASSWORD`, not a normal login password |

Keep organization private keys out of the database. They come from the environment or a keystore file. Never commit `.env` or key files.

## Run

From the project root, start the API:

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal, start the web app:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies API calls to port 8000. Restart the API after Python changes. Frontend changes reload on their own.

SQLite is stored in `laptop_anti_counterfeit.db`.

### Blockchain (optional)

If nothing is listening on `http://127.0.0.1:8545`, the API keeps running with a local stand-in chain. To use a real local chain, start a Hardhat node on that port, run the deploy script in `backend/chain/`, then restart the API. The deploy script records the contract address and the organizations' public addresses only.

## Demo accounts and roles

Only three accounts can sign in: `demo_manufacturer`, `demo_distributor` and `demo_retailer`. Other roles (admin, regulator, auditor, logistics) are disabled and can never log in through the API.

Custody moves only **manufacturer → distributor → retailer**. A visitor can verify a record and does not sign in.

## Demo walkthrough

1. **Register:** as the manufacturer, register a laptop with its box and seal. Wait for CONFIRMED, then save the QR label (the token cannot be shown again).
2. **Transfer:** create a transfer to the distributor. The distributor performs the sealed receipt (box ID, seal ID, condition) and accepts.
3. **Verify:** open the public verifier and check the product. Record integrity is separate from physical checks, and anything not checked stays grey `NOT_CHECKED`.
4. **Attack scenarios:** run the simulator (below) to see a cloned QR, a wrong box and seal, a handover mismatch, and an interrupted dispatch, each with its own evidence card.
5. **Tamper:** run the tamper demo on a copy of the database and verify that the failure is caught at the right layer.

```bash
# Windows
.\.venv\Scripts\python.exe tools\simulator.py

# macOS / Linux
python tools/simulator.py
```

## Anomaly scoring: evidence support, not probability

> **Score = sum of (weight × trust) for each kind of evidence found.**

- **Weight:** how much that evidence matters for the cause. Weights for one cause add up to 1.
- **Trust:** derived on the backend only (never from the client): registered device 0.80, witnessed staff inspection 0.70, ordinary app 0.40, anonymous 0.10, invalid signature 0.00 (for its physical claims), verified cryptographic failure 1.00.
- Repeated copies of the same evidence count once. Missing evidence adds nothing and is listed as a missing check.

| Cause | Evidence → weight |
| --- | --- |
| Cloned QR | movement conflict 0.50, duplicate burst 0.30, concurrent receipt 0.20 |
| Device or package substitution (sealed-only profile) | box mismatch 0.35, seal ID mismatch 0.35, unexpected broken seal 0.30 |
| Diversion or gray market | custody mismatch 0.45, handover mismatch 0.35, prohibited route or sold re-entry 0.20 |
| Record tampering | anchor mismatch 0.60, event integrity 0.40 |
| Process or recording gap | interrupted operation 0.35, independent corroboration 0.40, consistency check 0.25 |

Examples: a clone seen by 3 registered devices scores 0.50×0.8 + 0.30×0.8 = **64/100**; the same scans from anonymous users score **5/100**; a wrong box and wrong seal at staff inspection score **49/100**; a confirmed anchor mismatch plus an invalid signature scores **100/100**.

Rules of the road:

- Below 0.35 is `INSUFFICIENT_EVIDENCE`. If the top two causes are within 0.10 the result is `AMBIGUOUS`.
- Scores are not probabilities and different causes do not sum to 100.
- A normal customer scan after sale, a normal route, and a scan by the named recipient of an open transfer raise no alert.
- A missing handover record raises a documentation gap, which supports only the recording-error explanation, never cloning or diversion.
- Workflow failures stay separate from scores: a wrong box on receipt always returns 422 and moves nothing.
- The substitution weights use a sealed-only profile because the laptop's internal serial is not checked in this prototype (`NOT_CHECKED`). All weights are prototype policy values, not statistically validated.

## Tests

```bash
pytest
```

Run the contract tests with Hardhat from the `contracts/` setup (for example `npx hardhat test`). Key fusion suites: `tests/test_fusion_eval.py`, `tests/test_fusion_tuning.py` and `tests/test_fusion_process_gap.py`.

## Project layout

| Path | Contents |
| --- | --- |
| `backend/auth` | Login, JWT, role and ownership guards |
| `backend/crypto` | Canonical JSON, hashing, signing, event chain |
| `backend/chain` | Deploy script and web3 adapter with reconcile |
| `backend/fusion` | Rules, trust, scoring, incidents (`config.py`, `rules.py`, `score.py`, `engine.py`) |
| `contracts/` | `TraceTrust.sol` and Hardhat tests |
| `frontend/` | React app (verifier, transfers, sale, provenance map, assessment cards) |
| `tools/simulator.py` | Signed device scenarios |
| `tests/` | API, crypto, fusion and transfer tests |
| `PLAN.md`, `ARCHITECTURE.md` | Design documents |

## Limitations

- A copied QR still points to the same digital identity, so cloning is detected through conflicts, not prevented.
- A seal is a physical control. A well-made fake seal with a copied serial can pass a visual check.
- The blockchain cannot verify the truth of data first entered by an organization. It makes later changes detectable.
- GPS is client-reported and never blocks a handover. Alerts are indicators for investigation, not proof.
- Organization keys are custodial in this prototype. Production would use client-side keys or an HSM.
- The laptop's internal serial is not checked (`NOT_CHECKED`).
- Not production-ready without independent security review and physical authentication.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Frontend cannot reach the API | Confirm the API runs on port 8000 and restart it after Python changes |
| Records show `UNVERIFIABLE` | The chain is unreachable or was reset. Start the node or redeploy, then restart the API |
| Camera scanning does not work | Camera access needs HTTPS or `localhost`. Use the paste-token field as a fallback |
| QR codes do not open on a phone | Set the public base URL to a tunnel or reachable address before registering products |
| Emails do not appear | Check `mail_outbox/` when `SMTP_HOST` is empty |

## Security notes

- Secrets and private keys live in `.env` or a keystore, never in the database or Git.
- The QR token is kept in browser memory only and is never written to storage.
- Only the hash of each QR token is stored.
