# PROPOSAL — h1: street-address capture at booking (awaiting-human)

Produced by appointment-requirements-iterate iteration 2 (lane H). This packet
measures the decision inputs and states the options; it decides nothing.

## Question

Should the booking flow capture a street address, or is zip-level dispatch
acceptable for this take-home?

## Measured inputs (2026-07-10)

- **Spec text**: Tier 2 asks for matching "given the caller's zip code and
  appliance type" and confirmation of "the scheduled appointment details" — a
  street address is never mentioned anywhere in the assignment PDF.
- **Schema truth**: no address field exists anywhere. `app/contracts.py::Customer`
  is `{name, zip, email}`; `customers` (rev 0001) has name/phone/email;
  `appointments` (rev 0002) links slot/technician/customer/session with no
  location beyond the technician's `service_areas.zip_code`.
- **Conversation contract**: `SCHEDULING_CONTRACT` collects zip (mandatory) +
  name/email (booking policy); the read-back covers technician + date + time.
- **Eval surface**: no booking-bench scenario, structural assertion, or rubric
  references an address; the never-re-ask fact list (`appliance, brand, model,
  symptom, name, zip, email`) would grow by one re-askable fact.

## Option A — keep zip-level dispatch (status quo)

- **Cost**: zero.
- **Fit**: matches the spec's letter (zip + appliance is the stated matching key;
  "appointment details" is read consistently with tech + date + time everywhere
  else in the repo).
- **Risk**: a grader reading "appointments: booked sessions linking customers to
  technicians" through a real-dispatch lens may notice a technician could not
  actually find the home. Mitigation: one README sentence recording the
  deliberate scope cut.

## Option B — add a service address

- **Surface**: Alembic rev (nullable `appointments.service_address` text — on the
  appointment, not the customer, so per-booking addresses stay correct);
  `Customer`/CaseFile field + `update_case_file` arg; one `SCHEDULING_CONTRACT`
  sentence (collect + read back at booking); never-re-ask list entry; fixture and
  scenario updates; ~1 iteration of lane-F work once the tree is clean.
- **Cost**: one more voice-turn of friction per booking (address + confirmation
  spelling); tool-schema budget grows; all booking fixtures need the new turn.
- **Risk**: scope creep beyond the spec for a demo phone flow.

## Decision requested

Pick A (record the scope cut in README) or B (schedule as lane-F fix f4 with the
surface above). Record the decision in the loop ledger under "Human decisions";
either choice closes h1.
