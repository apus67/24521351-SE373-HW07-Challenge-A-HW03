"""BTVN#3 - Flight booking agent with a simple harness (LangChain).

    Agent = Model + Harness

The MODEL decides what to do. The HARNESS (plain Python) decides whether
a call is allowed, and whether the job is really done.

The user can choose HOW the model works (the agent pattern):
    1. ReAct             think -> act -> observe, one step at a time (adaptive)
    2. Plan-then-Execute make a full plan first, then run it step by step (predictable)
    3. Hybrid            plan first; if a step fails, fall back to ReAct to recover

Harness ideas (the SAME harness protects all 3 patterns):
    1. Constraints are DATA     -> the Constraints class
    2. Permission check         -> check_permission(), runs BEFORE every tool call
    3. Done is checked by CODE  -> is_done(), reads the booking back
    4. Handoff to a human       -> handoff(), when the agent fails
    5. Plan is DATA too         -> validate_plan(), checks a plan BEFORE running it
    6. User approves the plan   -> confirm_plan(), NO step runs without a "yes"

Challenge A: Persistent Memory
    - Lưu ở đâu : JSON file (memory.json) — đơn giản, dễ đọc
    - Ai ghi    : Harness ghi sau mỗi pay thành công; lưu conventions khi start
    - Khi nào nạp: Session start, inject vào system prompt
    - Khi quy ước đổi: So sánh Constraints; old sessions marked stale
    - Kiểm chứng: In ra memory context trước khi agent chạy

Run:  python flight_agent_memory.py   then choose a pattern and a case:
    1. success   a valid flight exists -> booked and paid -> DONE
    2. fail      no valid flight -> harness blocks the booking -> FAILED + handoff
"""
import json
import os
from dataclasses import dataclass
from datetime import datetime

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, wrap_tool_call
from langchain_core.messages import ToolMessage


# =====================================================================
# 1. CONSTRAINTS ARE DATA
#    The user's request is stored as data. The prompt is built FROM it,
#    and the harness CHECKS it in code. The model cannot "forget" it.
# =====================================================================
@dataclass
class Constraints:
    origin: str = "SGN"
    destination: str = "DAD"
    date: str = "2026-10-07"
    depart_before: str = "12:00"      # morning flight
    max_price: int = 2_000_000        # VND

    def to_prompt(self) -> str:
        return (f"Book one ticket {self.origin} -> {self.destination} on {self.date}, "
                f"departing before {self.depart_before}, price at most {self.max_price:,} VND.")

    def is_ok(self, flight: dict) -> bool:
        """Does this flight satisfy ALL constraints?"""
        return (flight["depart"].startswith(self.date)
                and flight["depart"][11:16] < self.depart_before
                and flight["price"] <= self.max_price)


CONSTRAINTS = Constraints()


# =====================================================================
# MOCKUP TOOLS - fake data, no network
# =====================================================================
FLIGHTS = {
    "success": [
        {"flight": "VN122", "depart": "2026-10-07T08:10", "price": 1_850_000},
        {"flight": "QH118", "depart": "2026-10-07T15:40", "price": 1_640_000},
    ],
    "fail": [   # no flight is BOTH in the morning AND under 2 million
        {"flight": "VJ604", "depart": "2026-10-07T08:10", "price": 2_480_000},
        {"flight": "QH118", "depart": "2026-10-07T15:40", "price": 1_640_000},
    ],
}
CASE = "success"      # which data set the tools use (chosen by the user in main)
BOOKINGS = {}         # our fake booking database


def search_flights(origin: str, destination: str, date: str) -> dict:
    """Search flights by route and date (YYYY-MM-DD)."""
    return {"status": "ok", "flights": FLIGHTS[CASE]}


def book_seat(flight: str) -> dict:
    """Hold a seat on a flight. Returns a booking code. No money is charged yet."""
    info = next(f for f in FLIGHTS[CASE] if f["flight"] == flight)
    code = f"{flight}-12A"
    BOOKINGS[code] = {"code": code, "paid": False, **info}
    return {"status": "ok", **BOOKINGS[code]}


def pay(code: str) -> dict:
    """Pay for a held booking. This spends money and cannot be undone."""
    if code not in BOOKINGS:
        return {"status": "not_found", "code": code}
    BOOKINGS[code]["paid"] = True
    return {"status": "ok", **BOOKINGS[code]}


def get_booking(code: str) -> dict:
    """Read a booking back from the system."""
    return {"status": "ok", **BOOKINGS[code]} if code in BOOKINGS else {"status": "not_found"}


TOOLS = [search_flights, book_seat, pay, get_booking]
TOOL_MAP = {t.__name__: t for t in TOOLS}


# =====================================================================
# PERSISTENT MEMORY (Challenge A)
# Lưu ở đâu: JSON file (memory.json)
# Ai ghi   : the harness writes after successful pay/book_seat
# Khi nào nạp: session start, injected into system prompt
# Khi quy ước đổi: constraints hash is compared; old entries marked stale
# Kiểm chứng: printed at session start
# =====================================================================

MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.json")


def load_memory() -> dict:
    """Load memory from JSON file. Returns empty structure if not found."""
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"conventions": {}, "sessions": []}


def save_memory(mem: dict) -> None:
    """Persist memory to JSON file."""
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, indent=2, ensure_ascii=False)


def memory_to_context(mem: dict) -> str:
    """Convert memory to a string that will be injected into the system prompt."""
    parts = []
    if mem.get("conventions"):
        c = mem["conventions"]
        parts.append(
            f"[MEMORY - Project conventions (saved {c.get('saved_at','?')})]\n"
            f"  Route: {c.get('origin')} -> {c.get('destination')}\n"
            f"  Date: {c.get('date')}\n"
            f"  Depart before: {c.get('depart_before')}\n"
            f"  Max price: {c.get('max_price'):,} VND"
        )
    sessions = mem.get("sessions", [])
    if sessions:
        last = sessions[-1]
        bookings_str = ", ".join(
            f"{b['code']} (paid={b['paid']})" for b in last.get("bookings", [])
        )
        parts.append(
            f"[MEMORY - Last session ({last.get('session_id')}, {last.get('started_at')})]\n"
            f"  Pattern: {last.get('pattern')} | Case: {last.get('case')}\n"
            f"  Bookings: {bookings_str or 'none'}\n"
            f"  Result: {last.get('result', 'unknown')}"
        )
    return "\n\n".join(parts) if parts else "[MEMORY - empty]"


def update_conventions(mem: dict, constraints) -> bool:
    """Update conventions in memory if they changed. Returns True if updated."""
    new_conv = {
        "origin": constraints.origin,
        "destination": constraints.destination,
        "date": constraints.date,
        "depart_before": constraints.depart_before,
        "max_price": constraints.max_price,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    old_conv = mem.get("conventions", {})
    changed_fields = {k for k in new_conv if k != "saved_at" and old_conv.get(k) != new_conv[k]}
    if changed_fields:
        # Mark old sessions stale if conventions changed
        for sess in mem.get("sessions", []):
            sess["stale"] = True
        print(f"\n[MEMORY] Conventions changed: {changed_fields}. Old sessions marked stale.")
    mem["conventions"] = new_conv
    save_memory(mem)
    return bool(changed_fields)


def start_session(mem: dict, pattern: str, case: str) -> dict:
    """Create a new session entry. Returns the session dict."""
    session_id = f"sess-{len(mem['sessions'])+1:03d}"
    session = {
        "session_id": session_id,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "pattern": pattern,
        "case": case,
        "bookings": [],
        "result": "pending",
    }
    mem["sessions"].append(session)
    save_memory(mem)
    return session


def record_booking(mem: dict, current_session: dict, booking: dict) -> None:
    """Harness calls this after a successful pay. Booking is stored in memory."""
    for sess in mem["sessions"]:
        if sess["session_id"] == current_session["session_id"]:
            # avoid duplicates
            existing_codes = {b["code"] for b in sess.get("bookings", [])}
            if booking.get("code") not in existing_codes:
                sess.setdefault("bookings", []).append(booking)
            break
    save_memory(mem)


def close_session(mem: dict, current_session: dict, result: str) -> None:
    """Mark the session done."""
    for sess in mem["sessions"]:
        if sess["session_id"] == current_session["session_id"]:
            sess["result"] = result
            break
    save_memory(mem)


# =====================================================================
# THE HARNESS (shared by all 3 patterns)
# =====================================================================
PLAN_REJECTED = False   # True if the user said "no" to the plan
LOG = []        # every tool call: (phase, tool name, args, result)
PHASE = ""      # which part of the run we are in: "react" / "plan" / "fallback"

# Memory globals (populated in __main__)
MEMORY: dict = {"conventions": {}, "sessions": []}
CURRENT_SESSION: dict | None = None


# ---- 2. PERMISSION CHECK: runs BEFORE the tool, using the constraint DATA
def check_permission(tool: str, args: dict) -> str | None:
    """Return None if allowed, or a reason if the call must be blocked."""
    if tool == "book_seat":
        flight = next((f for f in FLIGHTS[CASE] if f["flight"] == args.get("flight")), None)
        if flight is None or not CONSTRAINTS.is_ok(flight):
            return f"{args.get('flight')} breaks the constraints: {CONSTRAINTS.to_prompt()}"
    return None


def guarded_call(name: str, args: dict) -> dict:
    """The ONLY door to the tools: check permission, run, log.
    Both the ReAct middleware and the plan executor go through here."""
    reason = check_permission(name, args)
    if reason:                                         # blocked: the tool does NOT run
        result = {"status": "denied", "reason": reason}
    else:                                              # allowed: run the real tool
        try:
            result = TOOL_MAP[name](**args)
        except Exception as e:                         # bad args, unknown tool, ...
            result = {"status": "error", "reason": str(e)}
    LOG.append((PHASE, name, args, result))

    # MEMORY: harness auto-records successful payments
    if name == "pay" and result.get("status") == "ok" and CURRENT_SESSION:
        record_booking(MEMORY, CURRENT_SESSION, result)

    return result


@wrap_tool_call
def harness(request, handler):
    """LangChain middleware: every tool call of a ReAct agent goes through the harness."""
    call = request.tool_call
    result = guarded_call(call["name"], call["args"])
    return ToolMessage(content=json.dumps(result), tool_call_id=call["id"])


# ---- 5. PLAN IS DATA TOO: check the whole plan BEFORE running any step
ALLOWED_PLAN_TOOLS = {"search_flights", "book_seat", "pay"}
MAX_PLAN_STEPS = 6


def validate_plan(plan: list) -> str | None:
    """Return None if the plan is acceptable, or a reason to reject it."""
    if not isinstance(plan, list) or not plan or len(plan) > MAX_PLAN_STEPS:
        return f"plan must have 1-{MAX_PLAN_STEPS} steps"
    tools = [s.get("tool") for s in plan]
    for t in tools:
        if t not in ALLOWED_PLAN_TOOLS:
            return f"tool '{t}' is not allowed in a plan"
    if "pay" in tools and ("book_seat" not in tools or tools.index("pay") < tools.index("book_seat")):
        return "'pay' must come after 'book_seat'"
    return None


# ---- 6. USER APPROVAL: a plan may spend money, so the human must say yes first
def confirm_plan(plan: list) -> bool:
    """Show the plan and wait for the user. Nothing runs unless the answer is yes."""
    print("\nThis plan will run on your behalf (the step 'pay' spends real money).")
    answer = ""
    while answer not in ("y", "n"):
        answer = input("Approve this plan? (y/n): ").strip().lower()
    return answer == "y"


# ---- 3. DONE IS CHECKED BY CODE: never trust the model saying "I'm done"
def is_done() -> bool:
    """Done = a booking exists, is paid, and satisfies the constraints."""
    for code in BOOKINGS:
        b = get_booking(code)                  # read back from the system
        if b["paid"] and CONSTRAINTS.is_ok(b):
            return True
    return False


# ---- 4. HANDOFF: when the agent fails, give a human 3 things
def handoff() -> dict:
    return {
        "done_so_far": [f"{c}: paid={b['paid']}" for c, b in BOOKINGS.items()] or ["Nothing booked, nothing paid"],
        "tried": [f"[{phase}] {tool}({args}) -> {result['status']}" for phase, tool, args, result in LOG],
        "question": ("You rejected the plan. What would you like to change in it?"
                     if PLAN_REJECTED else
                     "No flight meets all constraints. Which one can we relax: "
                     "departure time or maximum price?"),
    }


# =====================================================================
# THE MODELS
# In a real project these are LLM calls. Here they are SCRIPTED so the
# demo runs without an API key. (Optional reading.)
# =====================================================================
SYSTEM_PROMPT = ("You are a flight booking agent. Use the tools: search_flights, "
                 "book_seat, pay. Only book a flight that meets ALL constraints. "
                 "If no flight meets them, stop and say so.")

SEARCH = ("search_flights", {"origin": "SGN", "destination": "DAD", "date": "2026-10-07"})

# --- ReAct: the model decides ONE tool call at a time, after seeing the last result.
#     In "fail" the model "forgets" the price limit and tries VJ604.
REACT_SCRIPT = {
    "success": [SEARCH,
                ("book_seat", {"flight": "VN122"}),
                ("pay", {"code": "VN122-12A"}),
                ("say", "Booked VN122, seat 12A, paid 1,850,000 VND.")],
    "fail":    [SEARCH,
                ("book_seat", {"flight": "VJ604"}),                  # denied by the harness
                ("say", "I could not book a flight that meets the constraints.")],
}

# --- Hybrid fallback: ReAct continues AFTER the plan failed (it sees the history).
FALLBACK_SCRIPT = {
    "success": [("say", "Nothing more to do.")],
    "fail":    [("say", "No flight meets all constraints, I stop here.")],
}


def scripted_model(script: list):
    """A fake chat model that replays the tool calls a real LLM would make."""
    from langchain_core.language_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    messages = []
    for i, (name, args) in enumerate(script):
        if name == "say":
            messages.append(AIMessage(content=args))
        else:
            messages.append(AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"{name}-{i}"}]))

    class ScriptedModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    return ScriptedModel(messages=iter(messages))


# --- Plan-then-Execute: the PLANNER writes the whole plan once (as JSON text).
def fake_planner(goal: str) -> str:
    """A real planner is one LLM call: goal in, JSON plan out."""
    c = CONSTRAINTS
    return json.dumps([
        {"tool": "search_flights", "goal": "Find flights for the route and date",
         "args": {"origin": c.origin, "destination": c.destination, "date": c.date}},
        {"tool": "book_seat", "goal": "Hold a seat on the best flight"},
        {"tool": "pay", "goal": "Pay for the held booking"},
    ])


def fake_worker(step: dict, memory: dict) -> dict:
    """The WORKER fills in the arguments of ONE step, using results of earlier steps.
    A real worker is a small LLM call. This fake one is naive on purpose:
    it picks the EARLIEST flight and ignores the price (so the harness has work to do)."""
    if step["tool"] == "book_seat":
        flights = memory["search_flights"]["flights"]
        return {"flight": min(flights, key=lambda f: f["depart"])["flight"]}
    if step["tool"] == "pay":
        return {"code": memory["book_seat"]["code"]}
    return {}


# =====================================================================
# THE 3 PATTERNS
# =====================================================================
def run_react(prompt: str, script: list, phase: str = "react", system_prompt: str = None) -> None:
    """Pattern 1: ReAct loop, built by LangChain. The model picks the next tool each turn."""
    global PHASE
    PHASE = phase
    sp = system_prompt or SYSTEM_PROMPT
    agent = create_agent(
        model=scripted_model(script),
        tools=TOOLS,
        system_prompt=sp,
        middleware=[harness,                                   # our harness
                    ModelCallLimitMiddleware(run_limit=10)],   # budget: max 10 model calls
    )
    agent.invoke({"messages": [{"role": "user", "content": prompt}]})


def run_plan_execute(system_prompt: str = None) -> str:
    """Pattern 2: plan once, get the user's approval, then execute step by step.
    NO re-planning. Returns "ok" (every step ran; not the same as DONE!),
    "failed" (a step or the plan was blocked) or "rejected" (the user said no)."""
    global PHASE, PLAN_REJECTED
    PHASE = "plan"

    plan = json.loads(fake_planner(CONSTRAINTS.to_prompt()))      # (a) PLAN
    print("Plan:")
    for i, s in enumerate(plan, 1):
        print(f"  {i}. {s['tool']:<15} {s['goal']}")

    problem = validate_plan(plan)                                 # (b) harness checks the plan
    if problem:
        print(f"Plan REJECTED by harness: {problem}")
        LOG.append((PHASE, "validate_plan", {}, {"status": "denied", "reason": problem}))
        return "failed"

    if not confirm_plan(plan):                                    # (c) USER APPROVAL
        print("Plan REJECTED by user. Nothing was executed.")
        LOG.append((PHASE, "confirm_plan", {}, {"status": "denied", "reason": "rejected by user"}))
        PLAN_REJECTED = True
        return "rejected"
    LOG.append((PHASE, "confirm_plan", {}, {"status": "ok"}))

    memory = {}                                                   # (d) EXECUTE
    for i, step in enumerate(plan, 1):
        args = step.get("args") or fake_worker(step, memory)
        result = guarded_call(step["tool"], args)
        print(f"  -> step {i}: {step['tool']}({args}) = {result['status']}")
        if result["status"] != "ok":
            print(f"  step {i} failed: {result.get('reason', result['status'])}")
            return "failed"                                       # plan broke: stop here
        memory[step["tool"]] = result
    return "ok"


def fallback_prompt() -> str:
    """Tell the ReAct agent what the plan already did, so it can continue."""
    history = "\n".join(f"- {tool}({args}) -> {json.dumps(result)}"
                        for _, tool, args, result in LOG)
    return (f"{CONSTRAINTS.to_prompt()}\n\nA plan was already tried and did not finish. "
            f"What happened so far:\n{history}\nContinue and finish the booking.")


def run_hybrid(system_prompt: str = None) -> None:
    """Pattern 3: Plan-then-Execute first (cheap, predictable, user-approved).
    If the plan fails, or the job is not done, ReAct takes over (adaptive)."""
    status = run_plan_execute(system_prompt=system_prompt)
    if status == "rejected":          # the user said no: do NOT sneak in with ReAct
        return
    if status == "ok" and is_done():
        return
    print("\nPlan did not finish the job -> switching to ReAct fallback ...")
    run_react(fallback_prompt(), FALLBACK_SCRIPT[CASE], phase="fallback",
              system_prompt=system_prompt)


# =====================================================================
def ask(title: str, options: list[str]) -> int:
    print(f"\n{title}")
    for i, text in enumerate(options, 1):
        print(f"  {i}. {text}")
    choice = ""
    while choice not in [str(i) for i in range(1, len(options) + 1)]:
        choice = input(f"Your choice (1-{len(options)}): ").strip()
    return int(choice)


if __name__ == "__main__":
    # ---------------------------------------------------------------
    # MEMORY: load at session start
    # ---------------------------------------------------------------
    MEMORY = load_memory()

    pattern_name = ["react", "plan", "hybrid"][ask("Choose a pattern:", [
        "ReAct             - think, act, observe, one step at a time",
        "Plan-then-Execute - plan first, then run the plan",
        "Hybrid            - plan first, ReAct fallback when a step fails",
    ]) - 1]
    CASE = ["success", "fail"][ask("Choose a case:", [
        "success - a valid flight exists",
        "fail    - no valid flight, the harness must hand off",
    ]) - 1]

    print(f"\n=== pattern: {pattern_name} | case: {CASE} ===")
    print("Constraints (data):", CONSTRAINTS)
    print("User's request:", CONSTRAINTS.to_prompt(), "\n")

    # ---------------------------------------------------------------
    # MEMORY: update conventions (detect changes, mark stale if needed)
    # ---------------------------------------------------------------
    update_conventions(MEMORY, CONSTRAINTS)

    # ---------------------------------------------------------------
    # MEMORY: start a new session entry
    # ---------------------------------------------------------------
    CURRENT_SESSION = start_session(MEMORY, pattern=pattern_name, case=CASE)

    # ---------------------------------------------------------------
    # MEMORY: Kiểm chứng — print what will be injected into context
    # ---------------------------------------------------------------
    memory_context = memory_to_context(MEMORY)
    print("\n[KIỂM CHỨNG - Memory injected into context]")
    print(memory_context)
    print()

    # Build the memory-augmented system prompt
    SYSTEM_PROMPT_WITH_MEMORY = SYSTEM_PROMPT + "\n\n" + memory_context

    # ---------------------------------------------------------------
    # Run the chosen pattern with the augmented system prompt
    # ---------------------------------------------------------------
    if pattern_name == "react":
        run_react(CONSTRAINTS.to_prompt(), REACT_SCRIPT[CASE],
                  system_prompt=SYSTEM_PROMPT_WITH_MEMORY)
    elif pattern_name == "plan":
        run_plan_execute(system_prompt=SYSTEM_PROMPT_WITH_MEMORY)
    else:
        run_hybrid(system_prompt=SYSTEM_PROMPT_WITH_MEMORY)

    print("\n--- trace ---")
    for i, (phase, tool, args, result) in enumerate(LOG, 1):
        print(f"[{i}] ({phase}) {tool}({args}) -> {result['status']} {result.get('reason', '')}")

    # The harness decides the result, not the model.
    if is_done():
        final_result = "DONE"
        output = {"result": final_result, "booking": list(BOOKINGS.values())}
    else:
        final_result = "FAILED"
        output = {"result": final_result, "handoff": handoff()}
    print("\n--- result ---")
    print(json.dumps(output, indent=2, ensure_ascii=False))

    # ---------------------------------------------------------------
    # MEMORY: close the session with the final result
    # ---------------------------------------------------------------
    close_session(MEMORY, CURRENT_SESSION, result=final_result)
    print(f"\n[MEMORY] Session {CURRENT_SESSION['session_id']} saved. Result: {final_result}")
    print(f"[MEMORY] Memory file: {MEMORY_FILE}")
