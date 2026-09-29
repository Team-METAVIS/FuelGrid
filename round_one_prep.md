# FuelGrid — Round One Preparation

Round one is about showing that we understand the problem and can give a sensible, practical answer. This page
explains what we are building, why it is better than the obvious approach, and the questions the judges are likely to
ask. It is written in plain words on purpose.

> Everything below has been built and tested against the organizers' simulator. Numbers come from our own runs; the
> raw results are in `docs/BENCHMARK.md` and `docs/LOAD_TEST.md`.

---

## 1. The problem in plain words

A country has a few fuel depots and many fuel stations. Trucks carry fuel from depots to stations along fixed roads.
Things go wrong: a road closes, a shipment arrives late, a city suddenly needs more fuel, a station shuts down. If
nobody reacts in time, a station runs dry and customers go without fuel.

The people running the operation need a screen that answers five questions:

1. What is the situation right now?
2. Where will fuel run out soon, and how sure are we?
3. What should we send, from where, and how much?
4. What happens if we do that?
5. Is the system itself working properly?

The organizers gave us a practice world (a simulator) with 2 depots, 4 stations, 6 roads and 3 fuels (diesel, petrol,
octane). Time moves in 15-minute steps. We may change only one thing in it: create a shipment.

---

## 2. What we are building

**FuelGrid** is an operations screen plus the "brain" behind it. Every time the simulated clock moves forward:

| Step | What it means in plain words |
|---|---|
| Observe | Read the latest fuel levels, roads, deliveries and demand from the simulator |
| Detect | Spot problems: a closed road, a late delivery, a sudden jump in demand |
| Predict | Estimate how much fuel each station will need over the next 8 hours |
| Decide | Work out the best shipments, respecting every real limit (truck size, depot stock, tank space) |
| Simulate | Before acting, calculate what the shipment would change, so the operator sees the benefit |
| Act | Send the shipment to the simulator, but only after a person approves (or automatic mode is switched on) |
| Monitor | Check the result, keep score, and watch our own system's health |
| Recover | If something breaks, switch to a simpler backup and carry on |

### The screens (light, clean, one job per page)

| Page | What the operator sees |
|---|---|
| **Overview** | A written situation briefing, service level, stations at risk, waiting decisions, incidents, a live "do nothing vs simple rules vs our planner" comparison |
| **Network** | A map of depots, roads and stations, colored by problems, plus every fuel level and shipment |
| **Decisions** | Each recommendation with reasons, rejected alternatives and Approve / Reject; full history below |
| **Forecast and Models** | Expected demand with a "how unsure are we" band, projected fuel level (with and without pending shipments), test results |
| **Scenarios and Chaos** | Buttons to create a crisis or break our own system on purpose, for the live demo |
| **System health** | Database, simulator link, response speed, error rate, what the system does when something breaks |
| **Audit log** | A permanent record of every alert, recovery, fallback and operator action |

All pages update by themselves. Approving or rejecting a recommendation removes it at once.

---

## 3. How we are making it a better system

### a) It writes its own briefing
The top of the Overview says, in plain sentences, what matters right now: which station is closest to running out,
what incidents are active, what is waiting for approval and how much shortage that avoids. It is generated from the live
numbers only, so it can never make something up, and it works with no outside AI service.

### b) It gives reasons, not just answers
Every recommendation shows: how much fuel is there now, how much will be needed, when it will run out, how sure we are,
which other routes we considered (and why they lost), and how much the risk drops if the operator accepts it.

### c) It does the math properly instead of guessing
Choosing shipments is a puzzle with many rules at once: each road has a maximum load, each depot has limited fuel and
can only send so much per time step, and each station only has so much empty tank space. We use a proven puzzle-solving
tool (Google's OR-Tools) that finds the best mix of shipments within all those rules. The same input always gives the
same answer, so decisions can be checked and repeated. When fuel is short, it spreads it fairly so one station is not
emptied while another is comfortable.

### d) It learns the demand pattern from the data
We start from the daily pattern the organizers publish (busy mornings and evenings) and adjust it using what actually
happens. If demand doubles in one city, our estimate follows within a few steps. We measure how wrong our estimates
are, show it live, and raise an alert if the error grows too large (the demand pattern may have changed).

### e) It shows the proof, live
Every planning round, FuelGrid also works out what would have happened if we did nothing, and what a simple rule-based
approach would have done, on the same situation. The Overview shows all three side by side. Nobody has to take our word
that the planner helps.

### f) A person stays in charge
Automatic sending is **off** by default. When switched on, it has a size limit per round, it stops when the data looks
old or broken, and it never applies to a recommendation we are unsure about. There is a pause switch. Every action is
written to the audit log.

### g) The list of recommendations is stable
Recommendations keep the same identity from one planning round to the next, so what the operator is looking at does not
shuffle under their mouse. An approved shipment counts immediately, so it is never suggested twice and the same depot
fuel is never spent twice. (We found and fixed a bug in this area during testing; there are tests for it.)

### h) It keeps working when parts break

| What breaks | What FuelGrid does |
|---|---|
| The simulator is slow or down | Tries again with growing waits; after repeated failures it leaves the simulator alone for a short while and keeps showing the last good data, clearly labeled "degraded" |
| The simulator sends nonsense | Rejects it, raises an alert, keeps the last good data |
| The simulator says its data is out of date | Shows a warning and pauses automatic sending |
| The live-update connection drops | Reconnects on its own; regular checking fills the gap; everything is re-read afterwards |
| The smart planner fails | Switches to a simpler rule-based planner and says so |
| The smart planner keeps failing (3 rounds in a row) | Switches over for good, with a banner and a one-click "Restore optimizer" button |
| The demand estimator fails | Switches to a simple average |
| The demand pattern drifts | Raises an incident and an alert |
| Sending a shipment fails midway | Each shipment has a unique ticket number, so retrying can never send it twice |
| Our database is down | Keeps records in memory and saves them when it returns; operations continue |
| The simulator is reset | Notices the clock went backwards and clears old data |
| Too many people hit the system at once | Simultaneous requests share one round of work instead of piling up |

### i) It is careful with the shared simulator
During our load test the organizers' simulator stopped responding, because it can only handle a few requests at a
time and our system was asking too much. We fixed it: FuelGrid now limits how many requests it sends at once and never
repeats the same refresh in parallel. The same test now leaves the simulator healthy. A system that can knock over its
own data source is not reliable, so this matters.

### j) We measure, we do not just claim

**Decision quality.** We reset the simulator, replay the same crisis, and compare three approaches on the exact same
world: **do nothing**, **simple rules**, and **our planner**. Share of fuel demand actually served (higher is better):

| Situation | Do nothing | Simple rules | FuelGrid planner |
|---|---:|---:|---:|
| Normal operation (2 days) | 46% | 100% | 100% |
| Demand jump in one city | 43% | 100% | 100% |
| One main road closed | 46% | 100% | 100% |
| Late deliveries | 46% | 100% | 100% |
| Several problems at once | 43% | 100% | 100% |
| Fuel scarcity (supply cut to a quarter, 3 days) | 21% | 94.1% | 94.6% |
| Severe multi-failure (3 days) | 27% | 98.1% | 98.6% |

Honest reading: doing nothing fails badly, because the starting fuel only lasts about a day. Both smart approaches
recover everything in the easy and medium crises. Our planner's edge appears only in the two hardest cases, where fuel
is short or many things fail at once: it leaves less demand unserved than the simple rules (about 8% less in the
scarcity test and 27% less in the multi-failure test). We say this openly rather than overselling.

**Speed under load.** We simulated a busy control room (50 people at once) for a minute while the simulator ran live:
2,407 requests, **no failures**, half answered in under 8 thousandths of a second, 95 out of 100 in under 40
thousandths, 99 out of 100 in under 70 thousandths. A full "read, predict, decide" round takes about 30 thousandths of
a second. Then a stress test with 250 people at once: 7,258 requests, still **no failures**, about 160 requests a
second (the limit of one processor core), and even the slowest answer took under 2 seconds. Details, including the
problems the test uncovered and how we fixed them, are in `docs/LOAD_TEST.md`.

### k) It can be shipped and watched
- One command runs everything in containers (`docker compose up --build`), with an optional monitoring stack
  (Prometheus and a ready-made Grafana dashboard) and alert rules for the situations that matter.
- Automated checks on every change: style check, 26 tests, front-end build, container build and a start-up health test.
- A metrics page and structured logs for everything: request speed, errors, forecast accuracy, how often backups kicked
  in, how many shortage alerts are open.
- The running version is shown on the health page, so we always know which build is live.

---

## 4. Technology choices, in plain words

| Choice | Why |
|---|---|
| Python + FastAPI for the server | Fast to build, easy to read, good for data work |
| Supabase (PostgreSQL) for storage | Managed database, so we spend time on the product, not on running servers |
| Google OR-Tools | Finds the best shipments under many rules, with repeatable results |
| React + Tailwind + Recharts for the screens | Clean, modern, quick to change |
| Prometheus + Grafana (optional) | Standard tools for watching a running system |
| No AI chat model in the core | The core must work with no outside service. A chat model may later *reword* explanations, never make decisions |
| No heavy extras (message queues, container clusters) | The organizers said extra complexity earns nothing by itself |

---

## 5. Questions judges may ask, with our answers

**Q1. What problem are you actually solving?**
Helping an operations team see trouble early and choose good shipments before a station runs dry, while staying usable
when the tools themselves fail.

**Q2. Why not just use a machine-learning model for everything?**
The demand pattern in this world is regular, so a simple estimate that learns from the data is accurate and easy to
explain. Choosing shipments is a rules-and-limits puzzle, and a puzzle solver is the right tool for that. We used
learning only where it helps: the demand estimate.

**Q3. How accurate is your demand estimate?**
Around 6–11% average error on the next 15-minute step in our runs. It is shown live, and an alert fires if it worsens.

**Q4. How do you know your planner is good?**
Two ways. Offline, we replay the same crisis against "do nothing", "simple rules" and our planner, on identical worlds.
Live, the Overview compares all three on the current situation every planning round. Results and honest caveats are in
the table above.

**Q5. Why should a judge trust a recommendation?**
It shows the reasons, the numbers behind them, the alternatives we rejected, how sure we are, and the expected
improvement. Weak-evidence recommendations are blocked from automatic sending.

**Q6. What if your planner crashes or gives a bad answer?**
It falls back to a simpler planner automatically and the dashboard shows a banner. If it keeps failing, FuelGrid
switches over for good and offers a one-click restore. Each step is logged and counted. We have tests that force these
failures.

**Q7. What happens if the simulator goes down during the demo?**
The dashboard keeps working from the last good data and is clearly labeled degraded. Automatic sending pauses. When the
simulator returns, FuelGrid re-reads everything and logs the recovery. This happened for real during our load testing,
and the system handled it. You can also trigger it live from the Scenarios page.

**Q8. Can it accidentally send the same shipment twice?**
No. Every shipment carries a unique ticket, and the simulator returns the same shipment if we resend the same ticket.
An approved shipment also counts immediately inside FuelGrid, so it is not proposed again.

**Q9. Who is in control, the machine or the person?**
The person. Automatic sending is off by default, capped, blocked when data or confidence is doubtful, and has a pause
switch. Everything is written to the audit log.

**Q10. How do you handle a crisis you have never seen?**
We do not depend on a fixed script. Every round we re-read the real state: which roads are closed, which stations are
out, how full each depot is. The planner only uses options that are valid right now. We tested each crisis type the
organizers listed, and combinations of them, and the Scenarios page lets you create new ones live.

**Q11. What about when there is simply not enough fuel?**
The planner spreads scarce fuel so no single station is starved while another has plenty, and it keeps a small reserve
in each depot unless a station is about to run out. Some unmet demand is unavoidable then; we report it honestly.

**Q12. How do you know the system itself is healthy?**
A health page shows the database, simulator link, live-update link, demand estimator and planner, plus speed and error
rate. There is a metrics page for monitoring tools, ready-made alert rules and a Grafana dashboard, and a permanent
audit log.

**Q13. How did you test performance under load?**
With a standard load-testing tool, against the live system while the simulator ran. Results are in section 3j:
no failures at 50 or 250 simultaneous users; 99 of 100 requests under 70 thousandths of a second at normal load; a
limit of about 160 requests a second on one processor core. The test also found real problems (slow repeated work, a
rare error, and the risk to the simulator), which we fixed and then re-measured.

**Q14. Does the dashboard update live?**
Yes. The server tells the browser whenever data or a decision changes, and the browser also checks every few seconds as a
safety net. Approve and Reject take effect instantly on screen.

**Q15. Is it easy to run on another machine?**
Yes. `docker compose up --build` starts everything, including the organizers' simulator. A short manual route is in the
README. Automated checks run on every change.

**Q16. Are you using real data or secrets?**
No. Everything is simulated. Passwords and keys are read from a private settings file that is never committed.

**Q17. Could your system harm the shared simulator?**
It could have, and we found that out by testing. FuelGrid now limits how many requests it sends at once and never
duplicates a refresh, and there are tests for both.

**Q18. What would you build next with more time?**
A plain-language explanation of each decision reworded by an AI assistant (explaining only, never deciding), memory of
past incidents to suggest what worked before, and automatic promotion of a better planner version after testing.

**Q19. What are the weaknesses?**
Honest answer: the world is small and regular, so results will look better than in a messy real country. Our demand
estimate leans on the organizers' published daily pattern. In easier crises, simple rules are already good enough, so our
advantage shows mainly under heavy stress. And the system runs as one process, which is enough here but would need
copies behind a load balancer at much larger scale.

---

## 6. Two-minute demo story

1. Open Overview: calm network, briefing says all is stable, service level 100%.
2. On Scenarios, apply "Combined crisis": demand jumps, roads close, deliveries are late.
3. Watch the briefing turn red, alerts appear, and recommendations arrive with reasons. Point at the live comparison:
   doing nothing leaves far more demand unserved than our plan. Approve one shipment; it disappears immediately.
4. Break our own system: make the simulator unavailable for 30 seconds. Show the degraded banner and cached data.
5. Clear the fault: show the automatic recovery in the audit log.
6. Close with the benchmark table and the load-test result.
